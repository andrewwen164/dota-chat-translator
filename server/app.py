"""Hosted free-beta translation API. Run with uvicorn server.app:app.

Environment: SUPABASE_URL, SUPABASE_SECRET_KEY, OPENAI_API_KEY, REDIS_URL,
FREE_BETA_ENABLED=true|false, OPENAI_MODEL, MONTHLY_LIMIT, MINUTE_LIMIT.

This is a foundation, not production deployment or desktop login.
"""
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import os
import time
from uuid import UUID

import httpx
import jwt
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis
from typing import Literal

from translator.core import OpenAITranslator, ApiFailure, DEFAULT_MODEL, valid_text


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=500)
    target: Literal["English", "Russian", "Spanish", "Chinese"]


class Service:
    def __init__(self, http, redis, translator, url, secret, free_beta=True,
                 monthly_limit=10000, minute_limit=30):
        self.http, self.redis, self.translator = http, redis, translator
        self.url, self.secret, self.free_beta = url.rstrip("/"), secret, free_beta
        self.monthly_limit, self.minute_limit = monthly_limit, minute_limit
        self.jwks, self.jwks_until = None, 0

    async def verify(self, token):
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") not in ("ES256", "RS256") or not header.get("kid"):
                raise ValueError("Unsupported JWT")
            if not self.jwks or time.monotonic() > self.jwks_until:
                r = await self.http.get(self.url + "/auth/v1/.well-known/jwks.json", timeout=4)
                r.raise_for_status()
                self.jwks = r.json()["keys"]
                self.jwks_until = time.monotonic() + 300
            key = next(k for k in self.jwks if k["kid"] == header["kid"])
            pub = jwt.PyJWK.from_dict(key, algorithm=header["alg"]).key
            claims = jwt.decode(token, pub, algorithms=[header["alg"]],
                issuer=self.url + "/auth/v1", audience="authenticated",
                options={"require": ["sub", "exp", "iss", "aud"]})
            if claims.get("role") != "authenticated":
                raise ValueError("Role not allowed")
            return str(UUID(claims["sub"]))
        except (ValueError, TypeError, KeyError, StopIteration, jwt.PyJWTError, httpx.HTTPError):
            raise HTTPException(401, "Sign in again") from None

    async def entitlement(self, user):
        if self.free_beta:
            return
        try:
            response = await self.http.get(self.url + "/rest/v1/entitlements",
                params={"user_id": "eq." + user, "select": "plan,active_until"},
                headers={"apikey": self.secret}, timeout=4)
            response.raise_for_status()
            rows = response.json()
            allowed = len(rows) == 1 and rows[0]["plan"] in ("paid", "grandfathered")
            until = rows[0].get("active_until") if allowed else None
            if until:
                allowed = datetime.fromisoformat(until.replace("Z", "+00:00")) > datetime.now(timezone.utc)
            if not allowed:
                raise HTTPException(402, "Subscription required")
        except HTTPException:
            raise
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            raise HTTPException(503, "Entitlements temporarily unavailable") from None

    async def quota(self, user):
        now = datetime.now(timezone.utc)
        month = now.strftime("%Y%m")
        minute = int(now.timestamp()) // 60
        script = """
        local a = redis.call('INCR', KEYS[1])
        if a == 1 then redis.call('EXPIRE', KEYS[1], 3024000) end
        local b = redis.call('INCR', KEYS[2])
        if b == 1 then redis.call('EXPIRE', KEYS[2], 90) end
        return {a, b}
        """
        try:
            a, b = await self.redis.eval(script, 2,
                f"dota:m:{user}:{month}", f"dota:r:{user}:{minute}")
        except Exception:
            raise HTTPException(503, "Translation temporarily unavailable") from None
        if a > self.monthly_limit or b > self.minute_limit:
            raise HTTPException(429, "Usage limit reached")

    async def translate(self, token, request):
        user = await self.verify(token)
        await self.entitlement(user)
        await self.quota(user)
        try:
            result = await self.translator.translate(request.text, request.target)
            if not valid_text(result):
                raise ValueError("Invalid response")
            return {"translation": result}
        except (ApiFailure, ValueError, TimeoutError):
            raise HTTPException(502, "Translation temporarily unavailable") from None
        except Exception:
            raise HTTPException(503, "Translation temporarily unavailable") from None


def create_app(service=None):
    @asynccontextmanager
    async def lifespan(app):
        if service is not None:
            app.state.service = service
            yield
            return
        names = ["SUPABASE_URL", "SUPABASE_SECRET_KEY", "OPENAI_API_KEY", "REDIS_URL"]
        cfg = {k: os.getenv(k, "") for k in names}
        if any(not cfg[k] for k in names) or not cfg["SUPABASE_URL"].startswith("https://"):
            raise RuntimeError("Missing/invalid server configuration")
        async with httpx.AsyncClient(follow_redirects=False) as http:
            redis = Redis.from_url(cfg["REDIS_URL"])
            provider = OpenAITranslator(cfg["OPENAI_API_KEY"], os.getenv("OPENAI_MODEL", DEFAULT_MODEL))
            try:
                await redis.ping()
                app.state.service = Service(http, redis, provider, cfg["SUPABASE_URL"],
                    cfg["SUPABASE_SECRET_KEY"],
                    os.getenv("FREE_BETA_ENABLED", "true").lower() == "true",
                    int(os.getenv("MONTHLY_LIMIT", "10000")),
                    int(os.getenv("MINUTE_LIMIT", "30")))
                yield
            finally:
                await provider.close()
                await redis.aclose()

    app = FastAPI(title="Dota Chat API", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/v1/translate")
    async def translate(body: Request, authorization: str | None = Header(None)):
        if not authorization or not authorization.startswith("Bearer ") or len(authorization) > 8192:
            raise HTTPException(401, "Sign in required")
        return await app.state.service.translate(authorization[7:], body)

    return app


app = create_app()
