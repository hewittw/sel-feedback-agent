"""Runtime settings from environment variables (optionally loaded from .env)."""
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROUNDS = 6
QUESTION_MAX_TOKENS = 1024     # generous: some models spend tokens on thinking before the text
INTERPRETER_MAX_TOKENS = 1024


@dataclass
class Settings:
    api_key: str | None
    model: str | None
    rounds: int
    prompts_dir: Path = ROOT / "prompts"
    config_dir: Path = ROOT / "config"
    logs_dir: Path = ROOT / "logs"


def load_settings() -> Settings:
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    raw_rounds = os.environ.get("SEL_ROUNDS", str(DEFAULT_ROUNDS))
    try:
        rounds = max(1, int(raw_rounds))
    except ValueError:
        rounds = DEFAULT_ROUNDS
    return Settings(
        api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
        model=os.environ.get("ANTHROPIC_MODEL") or None,
        rounds=rounds,
    )
