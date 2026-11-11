"""Choose which mode generates the next question.

Kept separate so probabilistic bucket weighting can be added later without
touching the terminal interface or prompt files. For now: the active mode wins.
"""
from .modes import Mode, PromptConfig
from .state import AdaptationState


def select_mode(state: AdaptationState, config: PromptConfig) -> Mode:
    return config.modes.get(state.active_mode) or config.modes[config.default_mode]
