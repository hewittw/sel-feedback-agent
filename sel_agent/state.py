"""The compact adaptation state and its validation."""
from dataclasses import dataclass, asdict, replace

ALLOWED = {
    "complexity": ("simpler", "standard", "more_challenging"),
    "length": ("shorter", "standard", "longer"),
}
NEUTRAL = {"complexity": "standard", "length": "standard"}


@dataclass(frozen=True)
class AdaptationState:
    active_mode: str
    complexity: str = NEUTRAL["complexity"]
    length: str = NEUTRAL["length"]

    def to_dict(self) -> dict:
        return asdict(self)


def initial_state(default_mode: str) -> AdaptationState:
    """Every new scenario session starts here."""
    return AdaptationState(active_mode=default_mode, **NEUTRAL)


class InvalidState(ValueError):
    pass


def validate_proposal(proposal: object, current: AdaptationState, mode_ids) -> AdaptationState:
    """Turn the interpreter's proposed state into a valid AdaptationState or raise InvalidState.

    Missing fields keep their current value (unspecified preferences remain unchanged).
    Unknown modes or values are rejected outright, so the caller keeps the previous state.
    """
    if not isinstance(proposal, dict):
        raise InvalidState(f"expected a JSON object, got {type(proposal).__name__}")
    updates = {}
    if "active_mode" in proposal:
        mode = proposal["active_mode"]
        if mode not in mode_ids:
            raise InvalidState(f"unknown mode {mode!r}")
        updates["active_mode"] = mode
    for field, allowed in ALLOWED.items():
        if field in proposal:
            if proposal[field] not in allowed:
                raise InvalidState(f"invalid {field} {proposal[field]!r} (allowed: {', '.join(allowed)})")
            updates[field] = proposal[field]
    return replace(current, **updates)
