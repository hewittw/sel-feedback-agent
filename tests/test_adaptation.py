"""Offline checks (no API calls): python -m unittest discover tests"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from sel_agent.claude_client import ClaudeError
from sel_agent.modes import load_prompt_config
from sel_agent.scenarios import ConfigError, load_scenarios
from sel_agent.session import CLOSING_REMARK, DiscussionSession, QuestionError
from sel_agent.state import AdaptationState, InvalidState, initial_state, validate_proposal

ROOT = Path(__file__).resolve().parent.parent


class FakeClient:
    """Stands in for ClaudeClient. Questions are numbered; interpreter replies come from a queue."""
    def __init__(self, interpreter_replies=()):
        self.interpreter_replies = list(interpreter_replies)
        self.calls = []

    def complete(self, system, user, max_tokens):
        is_interp = "CURRENT STATE:" in user
        self.calls.append(("interpret" if is_interp else "question", system, user))
        if is_interp:
            r = self.interpreter_replies.pop(0)
            if isinstance(r, Exception):
                raise r
            return r if isinstance(r, str) else json.dumps(r)
        return f"Question number {sum(1 for c in self.calls if c[0] == 'question')}?"


def state(mode="normal", complexity="standard", length="standard"):
    return {"active_mode": mode, "complexity": complexity, "length": length}


class Base(unittest.TestCase):
    def setUp(self):
        self.config = load_prompt_config(ROOT / "prompts", ROOT / "config" / "modes.json")
        self.scenario = load_scenarios(ROOT / "config" / "scenarios.json")[0]
        self.logs = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.logs)

    def session(self, client, rounds=6):
        return DiscussionSession(client, self.config, self.scenario, rounds, self.logs)

    def play_round(self, s, feedback):
        s.next_question()
        self.assertEqual(s.record_answer("We talked about it."), CLOSING_REMARK)
        s.submit_feedback(feedback)


class TestStateTransitions(Base):
    def test_new_session_starts_in_normal_mode(self):
        s = self.session(FakeClient())
        self.assertEqual(s.state, AdaptationState("normal", "standard", "standard"))

    def test_topic_feedback_selects_bucket(self):
        s = self.session(FakeClient([state("feelings")]))
        self.play_round(s, "Ask more about how the character feels")
        self.assertEqual(s.state.active_mode, "feelings")
        s.next_question()
        self.assertEqual(s.log.data["rounds"][-1]["active_mode"], "feelings")
        self.assertIn("Focus: feelings.", s.log.data["rounds"][-1]["question_request"]["system"])

    def test_style_only_update_preserves_mode(self):
        s = self.session(FakeClient([state("problem_solving"), state("problem_solving", complexity="simpler")]))
        self.play_round(s, "Help us think about what they could do")
        self.play_round(s, "That was too complicated")
        self.assertEqual(s.state, AdaptationState("problem_solving", "simpler", "standard"))

    def test_missing_fields_keep_current_values(self):
        cur = AdaptationState("feelings", "simpler", "standard")
        self.assertEqual(validate_proposal({"length": "shorter"}, cur, self.config.modes),
                         AdaptationState("feelings", "simpler", "shorter"))

    def test_empty_feedback_preserves_state_without_api_call(self):
        client = FakeClient([state("feelings")])
        s = self.session(client)
        self.play_round(s, "Ask about feelings")
        n_calls = len(client.calls)
        s.next_question(); s.record_answer("ok"); s.submit_feedback("   ")
        self.assertEqual(s.state.active_mode, "feelings")
        self.assertEqual(len(client.calls), n_calls + 1)  # only the question call
        self.assertFalse(s.log.data["rounds"][-1]["feedback"]["interpreter_called"])

    def test_invalid_interpretations_preserve_state(self):
        bad = ["not json at all", state("made_up_mode"), state("feelings", length="tiny"), "[1, 2]",
               ClaudeError("Claude API error 500.")]
        s = self.session(FakeClient([state("perspective_taking")] + bad), rounds=7)
        self.play_round(s, "Ask what the other character was thinking")
        good = s.state
        for fb in ["x"] * len(bad):
            self.play_round(s, fb)
            self.assertEqual(s.state, good)
            self.assertIsNotNone(s.log.data["rounds"][-1]["feedback"]["error"])
        self.assertEqual(len(s.log.data["events"]), len(bad))

    def test_preferences_persist_across_rounds(self):
        s = self.session(FakeClient([state(length="shorter"), state("feelings", length="shorter")]))
        self.play_round(s, "Make the questions shorter")
        self.play_round(s, "")
        self.play_round(s, "Ask about how Maya feels")  # mode changes, length stays
        self.assertEqual(s.state, AdaptationState("feelings", "standard", "shorter"))
        for r in s.log.data["rounds"][1:]:
            self.assertEqual(r["state_used"]["length"], "shorter")

    def test_new_session_resets_state(self):
        client = FakeClient([state("feelings", "simpler", "shorter")])
        s1 = self.session(client)
        self.play_round(s1, "simpler feelings questions please")
        self.assertNotEqual(s1.state, initial_state("normal"))
        s2 = self.session(client)
        self.assertEqual(s2.state, initial_state("normal"))
        self.assertEqual(s2.questions, [])

    def test_full_session_and_log(self):
        s = self.session(FakeClient([state("feelings")]), rounds=6)
        feedback = ["Ask more about how the character feels", "", "", "", "", ""]
        for fb in feedback:
            self.play_round(s, fb)
        self.assertTrue(s.finished)
        s.end(completed=True)
        log = json.loads(s.log.path.read_text())
        self.assertEqual(log["status"], "completed")
        self.assertEqual(len(log["rounds"]), 6)
        self.assertEqual(log["rounds"][5]["feedback"]["raw"], "")      # final-round feedback logged
        self.assertEqual([r["active_mode"] for r in log["rounds"]], ["normal"] + ["feelings"] * 5)
        first_user = log["rounds"][0]["question_request"]["user"]
        self.assertNotIn("MOST RECENT EXCHANGE", first_user)
        self.assertIn("MOST RECENT EXCHANGE", log["rounds"][1]["question_request"]["user"])
        self.assertIn("Question number 1?", log["rounds"][2]["question_request"]["user"])

    def test_failed_question_does_not_advance_round(self):
        class Failing(FakeClient):
            def complete(self, system, user, max_tokens):
                raise ClaudeError("Claude API error 529.")
        s = self.session(Failing())
        with self.assertRaises(QuestionError):
            s.next_question()
        self.assertEqual(s.round, 0)
        self.assertEqual(s.log.data["rounds"], [])


class TestConfig(Base):
    def copy_tree(self):
        d = Path(tempfile.mkdtemp())
        shutil.copytree(ROOT / "prompts", d / "prompts")
        shutil.copytree(ROOT / "config", d / "config")
        self.addCleanup(shutil.rmtree, d)
        return d

    def test_real_config_loads(self):
        self.assertEqual(list(self.config.modes),
                         ["normal", "feelings", "perspective_taking", "personal_experience", "problem_solving"])
        self.assertEqual(self.config.default_mode, "normal")

    def test_missing_prompt_file_reported(self):
        d = self.copy_tree()
        (d / "prompts" / "prompt_bins" / "feelings.txt").unlink()
        (d / "prompts" / "question_base.txt").unlink()
        with self.assertRaises(ConfigError) as cm:
            load_prompt_config(d / "prompts", d / "config" / "modes.json")
        self.assertIn("feelings.txt", str(cm.exception))
        self.assertIn("question_base.txt", str(cm.exception))

    def test_invalid_mode_config_reported(self):
        d = self.copy_tree()
        (d / "config" / "modes.json").write_text("{not json")
        with self.assertRaises(ConfigError):
            load_prompt_config(d / "prompts", d / "config" / "modes.json")

    def test_new_bucket_needs_only_file_and_entry(self):
        d = self.copy_tree()
        (d / "prompts" / "prompt_bins" / "gratitude.txt").write_text("Focus: gratitude.")
        cfg = json.loads((d / "config" / "modes.json").read_text())
        cfg["modes"].append({"id": "gratitude", "description": "Appreciation.", "prompt_file": "gratitude.txt"})
        (d / "config" / "modes.json").write_text(json.dumps(cfg))
        config = load_prompt_config(d / "prompts", d / "config" / "modes.json")
        self.assertIn("gratitude", config.modes)
        self.assertEqual(validate_proposal(state("gratitude"), initial_state("normal"), config.modes).active_mode,
                         "gratitude")

    def test_bad_scenarios_reported(self):
        d = self.copy_tree()
        p = d / "config" / "scenarios.json"
        p.write_text(json.dumps({"scenarios": [{"id": "a", "title": "A"}]}))
        with self.assertRaises(ConfigError) as cm:
            load_scenarios(p)
        self.assertIn("text", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
