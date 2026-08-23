import json
from dataclasses import dataclass
from pathlib import Path

VERSION_FILE = Path(__file__).resolve().parents[1] / "version.json"


@dataclass(frozen=True)
class RuntimeVersion:
    release_id: str
    api_version: str
    schema_version: str


def load_runtime_version(path: Path = VERSION_FILE) -> RuntimeVersion:
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected = {"release_id", "api_version", "schema_version"}
    if set(payload) != expected or not all(isinstance(payload[key], str) and payload[key] for key in expected):
        raise RuntimeError(f"invalid runtime version manifest: {path}")
    return RuntimeVersion(**payload)
