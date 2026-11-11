"""Core discussion logic, independent of any user interface.

A UI (terminal now; tablet, voice or robot later) drives it like this:
    s = DiscussionSession(...)
    while not s.finished:
        q = s.next_question()        # may raise QuestionError -> UI offers retry / menu
        s.record_answer(text)        # returns CLOSING_REMARK
        s.submit_feedback(text)      # "" is fine
    s.end(completed=True)
"""
import uuid
from datetime import datetime

from .claude_client import ClaudeError
from .generator import build_question_request, generate_question
from .interpreter import interpret_feedback
from .modes import PromptConfig
from .scenarios import Scenario
from .selection import select_mode
from .session_log import SessionLog, now
from .state import AdaptationState, initial_state

CLOSING_REMARK = "Thanks for sharing."


class QuestionError(Exception):
    pass


class DiscussionSession:
    def __init__(self, client, config: PromptConfig, scenario: Scenario, rounds: int, logs_dir, model=None):
        self.client = client
        self.config = config
        self.scenario = scenario
        self.total_rounds = rounds
        self.state: AdaptationState = initial_state(config.default_mode)   # fresh every session
        self.questions: list[str] = []
        self.last_exchange: tuple[str, str] | None = None
        self.round = 0              # number of the round in progress (1-based); 0 = not started
        self.phase = "question"     # question -> answer -> feedback -> question ...
        self.session_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        self.log = SessionLog(logs_dir, self.session_id, scenario, rounds, model)
        self._entry: dict | None = None

    @property
    def finished(self) -> bool:
        return self.round >= self.total_rounds and self.phase == "question"

    def next_question(self) -> str:
        assert self.phase == "question" and not self.finished
        round_number = self.round + 1
        mode = select_mode(self.state, self.config)
        system, user = build_question_request(self.config, mode, self.state, self.scenario, self.questions,
                                              self.last_exchange, round_number, self.total_rounds)
        try:
            question = generate_question(self.client, system, user)
        except ClaudeError as e:
            self.log.event("question_generation_failed", round=round_number, error=str(e))
            raise QuestionError(str(e)) from None
        if not question:
            self.log.event("question_generation_failed", round=round_number, error="empty question")
            raise QuestionError("The model returned an empty question.")
        # only now does the round advance
        self.round = round_number
        self.questions.append(question)
        self._entry = self.log.new_round({
            "round": round_number,
            "asked_at": now(),
            "active_mode": mode.id,
            "state_used": self.state.to_dict(),
            "question_request": {"system": system, "user": user},
            "question": question,
            "answer": None,
            "closing_remark": None,
            "feedback": None,
        })
        self.phase = "answer"
        return question

    def record_answer(self, answer: str) -> str:
        assert self.phase == "answer"
        self.last_exchange = (self.questions[-1], answer)
        self._entry["answer"] = answer
        self._entry["closing_remark"] = CLOSING_REMARK
        self.log.save()
        self.phase = "feedback"
        return CLOSING_REMARK

    def submit_feedback(self, feedback: str) -> None:
        assert self.phase == "feedback"
        before = self.state
        result = interpret_feedback(self.client, self.config, before, self.questions[-1], feedback)
        self.state = result.state
        self._entry["feedback"] = {
            "raw": feedback,
            "state_before": before.to_dict(),
            "state_after": self.state.to_dict(),
            "changed": before != self.state,
            "interpreter_called": result.api_called,
            "interpreter_reason": result.reason,
            "interpreter_raw_response": result.raw_response,
            "error": result.error,
        }
        if result.error:
            self.log.event("feedback_interpretation_failed", round=self.round, error=result.error)
        self.log.save()
        self.phase = "question"

    def end(self, completed: bool) -> None:
        self.log.finish("completed" if completed else "ended_early")
