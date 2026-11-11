"""Load question modes (prompt bins) and the shared prompt files.

Adding a bucket = add prompts/prompt_bins/<file>.txt + an entry in config/modes.json.
No code changes needed.
"""
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .scenarios import ConfigError

ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class Mode:
    id: str
    description: str
    prompt: str


@dataclass(frozen=True)
class PromptConfig:
    question_base: str
    feedback_interpreter: str
    modes: dict[str, Mode]       # insertion-ordered
    default_mode: str


def _read_prompt(path: Path) -> str:
    if not path.is_file():
        raise ConfigError(f"Prompt file not found: {path}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ConfigError(f"Prompt file is empty: {path}")
    return text


def load_prompt_config(prompts_dir: Path, modes_path: Path) -> PromptConfig:
    errors: list[str] = []

    def attempt(fn, *a):
        try:
            return fn(*a)
        except ConfigError as e:
            errors.append(str(e))
            return None

    base = attempt(_read_prompt, prompts_dir / "question_base.txt")
    interp = attempt(_read_prompt, prompts_dir / "feedback_interpreter.txt")

    if not modes_path.is_file():
        raise ConfigError("\n".join(errors + [f"Mode config not found: {modes_path}"]))
    try:
        data = json.loads(modes_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigError("\n".join(errors + [f"Mode config is not valid JSON ({modes_path}): {e}"])) from None

    entries = data.get("modes") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not entries:
        errors.append(f"{modes_path} must contain a non-empty \"modes\" list.")
        entries = []
    modes: dict[str, Mode] = {}
    for i, m in enumerate(entries, 1):
        if not isinstance(m, dict):
            errors.append(f"Mode #{i} in {modes_path} is not an object.")
            continue
        mid, desc, fname = m.get("id"), m.get("description"), m.get("prompt_file")
        if not isinstance(mid, str) or not ID_PATTERN.match(mid):
            errors.append(f"Mode #{i}: id must be lowercase letters/digits/underscores, got {mid!r}")
            continue
        if mid in modes:
            errors.append(f"Duplicate mode id {mid!r}")
            continue
        if not isinstance(desc, str) or not desc.strip():
            errors.append(f"Mode {mid!r}: missing description")
            continue
        if not isinstance(fname, str) or not fname.strip() or "/" in fname or "\\" in fname:
            errors.append(f"Mode {mid!r}: prompt_file must be a plain filename inside prompts/prompt_bins/")
            continue
        prompt = attempt(_read_prompt, prompts_dir / "prompt_bins" / fname)
        if prompt is not None:
            modes[mid] = Mode(mid, desc.strip(), prompt)

    default = data.get("default_mode", "normal") if isinstance(data, dict) else "normal"
    if default not in modes and not any(f"Mode {default!r}" in e for e in errors):
        errors.append(f"default_mode {default!r} is not a defined mode.")
    if errors:
        raise ConfigError("Configuration problems:\n  - " + "\n  - ".join(errors))
    return PromptConfig(base, interp, modes, default)
