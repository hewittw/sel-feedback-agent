"""Assemble the question-generation prompt and call Claude."""
from .modes import Mode, PromptConfig
from .scenarios import Scenario
from .settings import QUESTION_MAX_TOKENS
from .state import AdaptationState

STYLE_TEXT = {
    "complexity": {
        "simpler": "Use very simple words and a concrete, easy-to-answer idea. Suitable for a young child.",
        "standard": "Use everyday language a school-age child understands.",
        "more_challenging": "You may ask about a deeper or more abstract idea, still in child-friendly words.",
    },
    "length": {
        "shorter": "Keep the question very short: about 12 words or fewer.",
        "standard": "Keep the question to one sentence of about 15-25 words.",
        "longer": "The question may be one fuller sentence (up to about 35 words) with a little context.",
    },
}


def build_question_request(config: PromptConfig, mode: Mode, state: AdaptationState, scenario: Scenario,
                           previous_questions: list[str], last_exchange: tuple[str, str] | None,
                           round_number: int, total_rounds: int) -> tuple[str, str]:
    """Return (system, user). Pure function: easy to inspect and log."""
    system = f"{config.question_base}\n\n--- Question focus ---\n{mode.prompt}"
    parts = [
        f"ROUND: {round_number} of {total_rounds}",
        "STYLE:\n- Complexity: " + STYLE_TEXT["complexity"][state.complexity]
        + "\n- Length: " + STYLE_TEXT["length"][state.length],
        f"SCENARIO ({scenario.title}):\n<scenario>\n{scenario.text}\n</scenario>",
    ]
    if previous_questions:
        parts.append("PREVIOUS QUESTIONS (do not repeat or paraphrase):\n"
                     + "\n".join(f"- {q}" for q in previous_questions))
    if last_exchange:
        q, a = last_exchange
        parts.append(f"MOST RECENT EXCHANGE:\nQuestion: {q}\n<answer>\n{a}\n</answer>")
    parts.append("Write the next question.")
    return system, "\n\n".join(parts)


def clean_question(text: str) -> str:
    q = text.strip().splitlines()[-1].strip() if text.strip() else ""
    return q.strip('"“”').strip()


def generate_question(client, system: str, user: str) -> str:
    return clean_question(client.complete(system, user, QUESTION_MAX_TOKENS))
