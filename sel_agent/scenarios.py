"""Load scenarios from config/scenarios.json."""
import json
from dataclasses import dataclass
from pathlib import Path


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    text: str


def load_scenarios(path: Path) -> list[Scenario]:
    if not path.is_file():
        raise ConfigError(f"Scenario file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigError(f"Scenario file is not valid JSON ({path}): {e}") from None
    items = data.get("scenarios") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        raise ConfigError(f"{path} must contain a non-empty \"scenarios\" list.")
    out, seen = [], set()
    for i, s in enumerate(items, 1):
        if not isinstance(s, dict):
            raise ConfigError(f"Scenario #{i} in {path} is not an object.")
        missing = [k for k in ("id", "title", "text") if not isinstance(s.get(k), str) or not s[k].strip()]
        if missing:
            raise ConfigError(f"Scenario #{i} in {path} is missing or has empty: {', '.join(missing)}")
        if s["id"] in seen:
            raise ConfigError(f"Duplicate scenario id {s['id']!r} in {path}")
        seen.add(s["id"])
        out.append(Scenario(s["id"], s["title"].strip(), s["text"].strip()))
    return out
