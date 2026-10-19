# Hosted free-beta foundation

This API is experimental and is NOT deployed or connected to the desktop app yet. The existing personal translator remains unchanged.

## Setup

Install root dependencies and backend dependencies:

```powershell
py -3.12 -m pip install -r requirements.txt -r server/requirements.txt
```

Provision Supabase Auth with asymmetric signing keys (ES256/RS256) and a Redis instance. In the Supabase SQL editor, run:

```sql
create table if not exists public.entitlements (
  user_id uuid primary key references auth.users(id) on delete cascade,
  plan text not null check (plan in ('free', 'paid', 'grandfathered')),
  active_until timestamptz
);
alter table public.entitlements enable row level security;
```

Do not add client-side policies permitting entitlement writes. Only your trusted server should assign paid or grandfathered access.

Set the following **server-only** environment variables through your host's secret manager (never distribute or commit values):

- `SUPABASE_URL`: your Supabase project's HTTPS URL.
- `SUPABASE_SECRET_KEY`: backend-only privileged key.
- `OPENAI_API_KEY`: backend-only OpenAI API key.
- `REDIS_URL`: Redis connection URL.
- `OPENAI_MODEL`: optional model override.
- `FREE_BETA_ENABLED=true`: allow all authenticated users for the beta.
- `MONTHLY_LIMIT=10000`: optional monthly per-user request ceiling.
- `MINUTE_LIMIT=30`: optional minute rate ceiling.

Run for local development:

```powershell
py -3.12 -m uvicorn server.app:app --host 127.0.0.1 --port 8000
```

`POST /v1/translate` accepts `Authorization: Bearer <Supabase user access JWT>` and JSON `{"text":"привет","target":"English"}`. It returns `{"translation":"hello"}`. User tokens are checked against Supabase's asymmetric JWKS; the server checks entitlement, quotas and calls OpenAI. Nothing is charged automatically for subscriptions.

When `FREE_BETA_ENABLED=false`, only accounts with `paid` or `grandfathered` entitlements can access hosted translation. This allows subscription enforcement without Windows updates **once clients are using this backend**.

## Remaining before any public beta

- Implement Windows sign-in using browser PKCE, token refresh, and protected OS credential storage.
- Connect the desktop translation worker to hosted mode without shipping backend secrets.
- Add Stripe Billing with webhook signature verification; do not trust client-side subscription claims.
- Add real integration tests for JWT verification, quota concurrency, entitlement fail-closed and provider failures.
- Use HTTPS, secret management, observability, spending caps, and deployment hardening.
- Verify incoming other-player Dota messages via GSI. The existing repository has not verified this yet.
- Review commercial distribution, security and applicable game policies.

Do not use the backend as an unrestricted anonymous translation proxy or deploy it publicly without rate limiting and abuse monitoring.
