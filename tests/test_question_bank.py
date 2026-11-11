"""Offline checks for --det mode (questions picked from config/question_bank.json)."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from sel_agent.cli import parse_args
from sel_agent.modes import load_prompt_config
from sel_agent.question_bank import load_question_bank
from sel_agent.scenarios import ConfigError, load_scenarios
from sel_agent.session import DiscussionSession
from tests.test_adaptation import FakeClient, state

ROOT = Path(__file__).resolve().parent.parent


class TestQuestionBank(unittest.TestCase):
    def setUp(self):
        self.config = load_prompt_config(ROOT / "prompts", ROOT / "config" / "modes.json")
        self.scenarios = load_scenarios(ROOT / "config" / "scenarios.json")
        self.bank = load_question_bank(ROOT / "config" / "question_bank.json",
                                       [s.id for s in self.scenarios], list(self.config.modes))
        self.logs = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.logs)

    def session(self, client, scenario=0, rounds=6, seed=1):
        return DiscussionSession(client, self.config, self.scenarios[scenario], rounds, self.logs,
                                 bank=self.bank, seed=seed)

    def play(self, s, feedback):
        q = s.next_question()
        s.record_answer("answer")
        s.submit_feedback(feedback)
        return q

    def test_args(self):
        self.assertTrue(parse_args(["det"]).det)
        self.assertTrue(parse_args(["--det"]).det)
        self.assertFalse(parse_args([]).det)
        self.assertEqual(parse_args(["det", "--seed", "3"]).seed, 3)

    def test_real_bank_covers_every_scenario_and_mode(self):
        for s in self.scenarios:
            self.assertEqual(set(self.bank.entries[s.id]), set(self.config.modes))

    def test_questions_come_from_active_bucket_without_api_calls(self):
        client = FakeClient([state("feelings")])
        s = self.session(client)
        q1 = self.play(s, "Ask about how she feels")
        sid = self.scenarios[0].id
        normal = [q.text for q in self.bank.entries[sid]["normal"]]
        feelings = [q.text for q in self.bank.entries[sid]["feelings"]]
        self.assertIn(q1, normal)
        q2 = s.next_question()
        self.assertIn(q2, feelings)
        self.assertEqual([c[0] for c in client.calls], ["interpret"])   # no question-generation calls
        self.assertEqual(s.log.data["question_source"], "bank")

    def test_style_preference_picks_tagged_question(self):
        s = self.session(FakeClient([state("feelings", "simpler", "shorter")]))
        self.play(s, "simpler and shorter feelings questions")
        q = s.next_question()
        self.assertEqual(s.log.data["rounds"][-1]["question_request"]["style_score"], 4)
        sid = self.scenarios[0].id
        tagged = [x.text for x in self.bank.entries[sid]["feelings"] if x.length == "shorter"]
        self.assertIn(q, tagged)

    def test_requested_preference_beats_default_match(self):
        # only "shorter" requested; the short question is tagged simpler+shorter and must still win
        s = self.session(FakeClient([state("feelings", length="shorter")]))
        self.play(s, "feelings, shorter")
        q = s.next_question()
        sid = self.scenarios[0].id
        self.assertIn(q, [x.text for x in self.bank.entries[sid]["feelings"] if x.length == "shorter"])

    def test_no_repeats_and_fallback_when_bucket_runs_out(self):
        s = self.session(FakeClient([state("feelings")]), rounds=12)
        asked = [self.play(s, "feelings please" if i == 0 else "") for i in range(12)]
        self.assertEqual(len(asked), len(set(asked)))
        self.assertTrue(any(e["type"] == "bank_fallback" for e in s.log.data["events"]))

    def test_same_seed_same_questions(self):
        runs = []
        for _ in range(2):
            s = self.session(FakeClient([state("problem_solving")]), seed=42)
            runs.append([self.play(s, fb) for fb in ["help us solve it", "", ""]])
        self.assertEqual(runs[0], runs[1])

    def test_missing_bucket_reported(self):
        d = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, d)
        data = json.loads((ROOT / "config" / "question_bank.json").read_text())
        del data["scenarios"]["left_out_game"]["feelings"]
        data["scenarios"]["left_out_game"]["normal"].append({"text": "x", "length": "tiny"})
        (d / "bank.json").write_text(json.dumps(data))
        with self.assertRaises(ConfigError) as cm:
            load_question_bank(d / "bank.json", [s.id for s in self.scenarios], list(self.config.modes))
        self.assertIn("feelings", str(cm.exception))
        self.assertIn("tiny", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
