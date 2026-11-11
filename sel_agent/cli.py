"""Terminal interface. All discussion logic lives in session.py."""
import argparse
import sys
import textwrap

from .claude_client import ClaudeClient
from .modes import load_prompt_config
from .question_bank import load_question_bank
from .scenarios import ConfigError, load_scenarios
from .session import DiscussionSession, QuestionError
from .settings import load_settings

EXIT_CMD, QUIT_CMD = "/exit", "/quit"
FEEDBACK_PROMPT = "What feedback would you give the agent about its question? Press Enter to skip."
HELP = f"(Type {EXIT_CMD} to leave this scenario, or {QUIT_CMD} to quit the app.)"


class ExitSession(Exception):
    pass


class QuitApp(Exception):
    pass


def ask(prompt: str) -> str:
    try:
        text = input(prompt)
    except EOFError:
        raise QuitApp from None
    cmd = text.strip().lower()
    if cmd == QUIT_CMD:
        raise QuitApp
    if cmd == EXIT_CMD:
        raise ExitSession
    return text.strip()


def wrap(text: str) -> str:
    return "\n".join(textwrap.fill(p, 78) for p in text.split("\n"))


def choose_scenario(scenarios):
    print("\n=== Choose a scenario ===")
    for i, s in enumerate(scenarios, 1):
        print(f"  {i}. {s.title}")
    print("  q. Quit")
    while True:
        choice = ask("> ").lower()
        if choice in ("q", "quit"):
            raise QuitApp
        if choice.isdigit() and 1 <= int(choice) <= len(scenarios):
            return scenarios[int(choice) - 1]
        print(f"Please enter a number from 1 to {len(scenarios)}, or q to quit.")


def run_session(session: DiscussionSession) -> None:
    s = session.scenario
    print(f"\n--- {s.title} ---\n{wrap(s.text)}\n\n{HELP}")
    completed = False
    try:
        while not session.finished:
            try:
                question = session.next_question()
            except QuestionError as e:
                print(f"\n[Could not generate a question: {e}]")
                choice = ask("Press Enter to retry, or type m to return to the menu: ").lower()
                if choice == "m":
                    raise ExitSession
                continue
            print(f"\nQuestion {session.round} of {session.total_rounds}:\n{wrap(question)}")
            answer = ""
            while not answer:
                answer = ask("\nYour answer: ")
            print(f"\n{session.record_answer(answer)}")
            session.submit_feedback(ask(f"\n{FEEDBACK_PROMPT}\n> "))
        completed = True
        print("\nThat's the end of this scenario. Thank you for taking part!")
    except ExitSession:
        print("\nLeaving this scenario.")
    finally:
        session.end(completed)
        print(f"(Session log: {session.log.path})")


def parse_args(argv):
    p = argparse.ArgumentParser(description="Parent-child SEL discussion agent.")
    p.add_argument("det", nargs="?", choices=["det"],
                   help="deterministic mode: pick questions from config/question_bank.json instead of generating them")
    p.add_argument("--det", dest="det_flag", action="store_true", help="same as 'det'")
    p.add_argument("--seed", type=int, help="seed for question picks in det mode (reproducible sessions)")
    a = p.parse_args(argv)
    a.det = bool(a.det or a.det_flag)
    return a


def main(argv=None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    settings = load_settings()
    bank = None
    try:
        config = load_prompt_config(settings.prompts_dir, settings.config_dir / "modes.json")
        scenarios = load_scenarios(settings.config_dir / "scenarios.json")
        if args.det:
            bank = load_question_bank(settings.config_dir / "question_bank.json",
                                      [s.id for s in scenarios], list(config.modes))
    except ConfigError as e:
        print(f"Startup failed.\n{e}", file=sys.stderr)
        return 2
    missing = [n for n, v in (("ANTHROPIC_API_KEY", settings.api_key), ("ANTHROPIC_MODEL", settings.model)) if not v]
    if missing:
        print(f"Missing environment variable(s): {', '.join(missing)}.\n"
              "Copy .env.example to .env and fill it in, or export them in your shell.", file=sys.stderr)
        return 2
    client = ClaudeClient(settings.api_key, settings.model)
    print("Parent-Child Story Discussion")
    print(f"({settings.rounds} rounds per scenario. In a scenario, {EXIT_CMD} returns here, {QUIT_CMD} quits.)")
    if args.det:
        print("[det mode: questions come from config/question_bank.json]")
    try:
        while True:
            scenario = choose_scenario(scenarios)
            session = DiscussionSession(client, config, scenario, settings.rounds, settings.logs_dir, settings.model,
                                        bank=bank, seed=args.seed)
            run_session(session)   # its finally-block closes the log on /exit, /quit or Ctrl-C
    except (QuitApp, KeyboardInterrupt):
        print("\nGoodbye!")
    return 0
