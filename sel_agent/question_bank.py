"""Deterministic question source (--det): pick pre-written questions instead of generating them.

config/question_bank.json holds, for every scenario, a list of questions per mode.
Each round picks an unused question from the active mode's list, preferring
questions tagged with the current complexity/length preferences.
No API call is made to produce a question.
"""
import json
import random
from dataclasses import dataclass
from pathlib import Path

from .scenarios import ConfigError
from .state import ALLOWED, NEUTRAL, AdaptationState


@dataclass(frozen=True)
class BankQuestion:
    text: str
    complexity: str = NEUTRAL["complexity"]
    length: str = NEUTRAL["length"]

    def to_dict(self) -> dict:
        return {"text": self.text, "complexity": self.complexity, "length": self.length}


class QuestionBank:
    def __init__(self, entries: dict[str, dict[str, list[BankQuestion]]]):
        self.entries = entries   # scenario_id -> mode_id -> questions

    def pick(self, scenario_id: str, mode_id: str, default_mode: str, state: AdaptationState,
             asked: list[str], rng: random.Random) -> tuple[str, dict]:
        """Return (question, details for the log)."""
        by_mode = self.entries[scenario_id]
        unused = lambda qs: [q for q in qs if q.text not in asked]
        pool, source_mode, fallback = unused(by_mode[mode_id]), mode_id, None
        if not pool and mode_id != default_mode:
            pool, source_mode = unused(by_mode[default_mode]), default_mode
            fallback = f"all '{mode_id}' questions used; took from '{default_mode}'"
        if not pool:
            for other, qs in by_mode.items():
                if unused(qs):
                    pool, source_mode = unused(qs), other
                    fallback = f"'{mode_id}' and '{default_mode}' used up; took from '{other}'"
                    break
        if not pool:
            pool, source_mode = list(by_mode[mode_id]), mode_id
            fallback = "every question for this scenario already asked; repeating one"

        def score(q: BankQuestion) -> int:
            # A preference someone asked for (non-neutral) counts double, so "shorter" beats
            # "matches the default complexity" when no question matches both.
            total = 0
            for field in ALLOWED:
                wanted, has = getattr(state, field), getattr(q, field)
                if has == wanted:
                    total += 1 if wanted == NEUTRAL[field] else 2
            return total

        best = max(score(q) for q in pool)
        candidates = [q for q in pool if score(q) == best]
        choice = rng.choice(candidates)
        return choice.text, {
            "picked_from_mode": source_mode,
            "picked_tags": {"complexity": choice.complexity, "length": choice.length},
            "style_score": best,     # higher = closer to the current style preferences
            "candidates": [q.text for q in candidates],
            "fallback": fallback,
        }


def load_question_bank(path: Path, scenario_ids, mode_ids) -> QuestionBank:
    """Load and validate. Every scenario needs at least one question for every mode."""
    if not path.is_file():
        raise ConfigError(f"Question bank not found: {path} (needed for --det)")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigError(f"Question bank is not valid JSON ({path}): {e}") from None
    scen = data.get("scenarios") if isinstance(data, dict) else None
    if not isinstance(scen, dict):
        raise ConfigError(f"{path} must contain a \"scenarios\" object.")
    errors, entries = [], {}
    for sid in scenario_ids:
        if sid not in scen or not isinstance(scen[sid], dict):
            errors.append(f"scenario {sid!r} has no questions")
            continue
        entries[sid] = {}
        for mid in mode_ids:
            raw = scen[sid].get(mid)
            if not isinstance(raw, list) or not raw:
                errors.append(f"{sid}: mode {mid!r} needs a non-empty list of questions")
                continue
            qs = []
            for i, item in enumerate(raw, 1):
                q = _parse_entry(item)
                if isinstance(q, str):
                    errors.append(f"{sid}/{mid} #{i}: {q}")
                else:
                    qs.append(q)
            entries[sid][mid] = qs
        for extra in set(scen[sid]) - set(mode_ids):
            errors.append(f"{sid}: {extra!r} is not a mode in modes.json")
    for extra in set(scen) - set(scenario_ids):
        errors.append(f"{extra!r} is not a scenario in scenarios.json")
    if errors:
        raise ConfigError("Question bank problems:\n  - " + "\n  - ".join(sorted(errors)))
    return QuestionBank(entries)


def _parse_entry(item) -> BankQuestion | str:
    """Return a BankQuestion, or an error message."""
    if isinstance(item, str):
        return BankQuestion(item.strip()) if item.strip() else "empty question"
    if not isinstance(item, dict) or not isinstance(item.get("text"), str) or not item["text"].strip():
        return "must be a string or an object with a non-empty \"text\""
    tags = {}
    for field, allowed in ALLOWED.items():
        if field in item:
            if item[field] not in allowed:
                return f"{field} must be one of {', '.join(allowed)}, got {item[field]!r}"
            tags[field] = item[field]
    unknown = set(item) - {"text", *ALLOWED}
    if unknown:
        return f"unknown field(s): {', '.join(sorted(unknown))}"
    return BankQuestion(item["text"].strip(), **tags)
