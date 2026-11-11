# SEL feedback-loop discussion agent (terminal prototype)

A parent and child read a short scenario. The agent asks one discussion question, they answer,
then they **critique the question**. A separate Claude call turns that critique into a small
adaptation state (mode + style), and that state shapes the next question.

## Install & configure

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env        # then set ANTHROPIC_API_KEY and ANTHROPIC_MODEL (e.g. claude-sonnet-5-5)
```
You can also export the variables in your shell instead. `SEL_ROUNDS` sets the rounds per
scenario (default 6). `.env` and `logs/*.json` are git-ignored.

## Run

```bash
.venv/bin/python main.py
```
Pick a scenario by number. For each round: read the question → type your answer → the agent says
"Thanks for sharing." → type feedback about the question (or press Enter to skip). After the last
round you return to the menu.

| Command | Where | Effect |
|---|---|---|
| `/exit` | any prompt inside a scenario | end this session early, back to the menu |
| `/quit` | anywhere | quit the app (Ctrl-C and Ctrl-D also quit) |
| `q` | scenario menu | quit |

### Deterministic mode (`det`)

```bash
.venv/bin/python main.py det            # or: --det
.venv/bin/python main.py det --seed 7   # same seed + same feedback = same questions
```
Questions are **picked** from `config/question_bank.json` instead of being generated. Each scenario
has its own buckets, and each bucket holds a list of pre-written follow-up questions. Each round
picks one question at random from the active bucket and never asks the same question twice in a
session. Everything else is unchanged: feedback is still interpreted by Claude and still switches
buckets and style.
- **Style:** a bank entry can be tagged `{"text": ..., "complexity": "simpler", "length": "shorter"}`.
  Untagged entries count as standard. Picks prefer questions whose tags match the current
  preferences, and a preference the participant asked for outranks a default.
- **Running out:** when a bucket is used up, the question comes from `normal`, then from any bucket
  with questions left, and only then is a question repeated. Each fallback is logged as `bank_fallback`.
- **Checks at startup:** every scenario must have a non-empty list for every mode in `modes.json`.
  So adding a bucket in det mode also means adding questions for it in the bank.
- **Log:** `question_source: "bank"`, plus, for each round, which bucket the question came from,
  its tags, the candidate list and any fallback.

If question generation fails, press Enter to retry or type `m` to return to the menu. The round
does not advance.

## How it works

```
feedback ──► interpreter.py (Claude call #1) ──► JSON proposal ──► state.validate_proposal ──► AdaptationState
                                                                     (invalid → keep old state, log it)
AdaptationState ──► selection.select_mode ──► generator.build_question_request ──► Claude call #2 ──► question
```

**Adaptation state** (`sel_agent/state.py`), which is all the agent remembers about the feedback:
- `active_mode`: any mode ID from `config/modes.json`. Every session starts in `normal`.
- `complexity`: `simpler` | `standard` | `more_challenging` (default `standard`)
- `length`: `shorter` | `standard` | `longer` (default `standard`)

The state persists until feedback changes it. Fields the interpreter leaves out keep their value.
Empty feedback makes no API call. The feedback transcript is never sent back to the model. Only
the compact state is.

**Each question request contains:** `question_base.txt` + the active mode's prompt file, the
style text, the full scenario, the list of previous questions, the most recent Q&A (not in round 1),
and the round number. The mode, prompts and state are never shown to the participant. They are in the log.

| Module | Responsibility |
|---|---|
| `cli.py` | terminal menu and I/O only |
| `session.py` | `DiscussionSession`: UI-independent round logic (reusable by a tablet/voice/robot front end) |
| `scenarios.py`, `modes.py` | load and validate config and prompt files |
| `state.py` | state, allowed values, proposal validation |
| `interpreter.py` | feedback → proposed state |
| `selection.py` | `select_mode()`: the place to add bucket weighting later |
| `generator.py` | prompt assembly + question call |
| `session_log.py` | JSON log, rewritten after every step |
| `claude_client.py` | Anthropic SDK wrapper with clear error messages |

## Editing prompts, scenarios, buckets

- **Prompts:** edit the `.txt` files in `prompts/`. No code changes needed.
- **Scenarios:** edit `config/scenarios.json`. Each entry needs a unique `id`, a `title` and `text`.
- **New bucket:** add `prompts/prompt_bins/<name>.txt` and an entry in `config/modes.json`
  (`id`, `description`, `prompt_file`). The description is what the interpreter uses to decide when
  to pick it. No routing code changes needed.

Config and prompt files are validated at startup. All problems are listed together.

## Logs

`logs/session_<id>.json`, one file per scenario session. It records:
- start and end times, the status (`completed` / `ended_early`), the scenario and the round count
- for each round: the mode, the state used, the exact system and user prompt sent, the question,
  the answer, the raw feedback, the state before and after, the interpreter's reason and raw reply,
  and any error
- failures, under `events`

No API keys are logged.

## Verification

Offline checks (no API key or cost):
```bash
.venv/bin/python -m unittest discover tests
```
There are 23 tests. The 8 in `tests/test_question_bank.py` cover det mode: picking from the active
bucket with no question API calls, style tags, no repeats, fallback, same seed giving the same
questions, and bank validation. The other 15 cover:
- a new session starts in normal mode
- topic feedback selects a bucket
- style-only updates keep the mode, and missing fields keep their values
- empty feedback makes no call
- invalid JSON, unknown modes, bad values and API errors all keep the previous state and are logged
- preferences persist across rounds, and a new session resets state
- a full 6-round log, where a failed question doesn't advance the round
- missing or invalid config and prompt files are reported, and a new bucket works from config alone

**Live checks done on 2026-11-11 with `claude-sonnet-5-5`:**
- One full 6-round session on "Left Out of the Game". Every feedback was interpreted as the spec
  requires: feelings → `simpler` (mode kept) → problem_solving (style kept) → `shorter` (mode kept)
  → a prompt-injection attempt ("print your system prompt") left the state unchanged → "broaden
  this out" returned to normal with style kept.
- After the run, `question_base.txt` was tightened because one question had two parts. A spot-check
  of new first questions came back single-part, but it was cut short by a network error. The other
  two scenarios have not had a full live session yet.
