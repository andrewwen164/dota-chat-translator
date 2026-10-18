from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys

from translator.core import DEFAULT_MODEL
from translator.ingest import Mapping


def app_root():
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent


def data_dir():
    path = app_root() / ".local"
    path.mkdir(exist_ok=True)
    return path


def load_environment():
    from dotenv import load_dotenv
    load_dotenv(app_root() / ".env", override=False)


@dataclass
class Settings:
    model: str = DEFAULT_MODEL
    rpm: int = 20
    font_size: int = 16
    opacity: int = 80
    port: int = 3009
    overlay_geometry: list = field(default_factory=lambda: [100, 100, 650, 260])
    mapping: Mapping = field(default_factory=Mapping)
    outgoing_hotkey: bool = False

    @classmethod
    def load(cls, path):
        result = cls()
        if path.exists():
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("Invalid settings")
            result.model = value.get("model", DEFAULT_MODEL)
            for key, low, high in (("rpm", 1, 120), ("font_size", 10, 40), ("opacity", 15, 100), ("port", 1, 65535)):
                v = value.get(key, getattr(result, key))
                if type(v) is not int or not low <= v <= high:
                    raise ValueError("Invalid setting: " + key)
                setattr(result, key, v)
            if not isinstance(result.model, str) or not result.model.strip() or len(result.model) > 150:
                raise ValueError("Invalid model")
            geometry = value.get("overlay_geometry", result.overlay_geometry)
            if (isinstance(geometry, list) and len(geometry) == 4
                    and all(type(v) is int for v in geometry)
                    and 300 <= geometry[2] <= 4000 and 120 <= geometry[3] <= 2000):
                result.overlay_geometry = geometry
            result.mapping = Mapping.from_dict(value.get("mapping", {}))
            result.outgoing_hotkey = value.get("outgoing_hotkey") is True
        if result.model.startswith("gemini-"):
            result.model = DEFAULT_MODEL  # Preserve all other saved UI/GSI preferences.
        if os.getenv("OPENAI_MODEL", "").strip():
            result.model = os.environ["OPENAI_MODEL"].strip()
        return result

    def save(self, path):
        if path.exists():
            # One bounded backup, made before replacing any existing settings.
            shutil.copy2(path, path.with_suffix(".json.bak"))
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        temporary.replace(path)
