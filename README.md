# jobloop — a verification loop for CVs, application answers and cover letters

> A system I built and use for my own job applications. The point is **verification, not generation**: a single
> submitted sentence that invents experience counts as failure. Every sentence must cite evidence from a profile
> database, drafts are reviewed by models from a different provider than the writer, and nothing is final without
> human approval.
>
> This repository publishes the structure only. My personal profile, application records and lessons ledger are
> private; `profile_db.example.json` and `lessons.example.json` describe a fictional candidate.

Writer (Claude) → judge panel (a different model family, in parallel) → aggregate → revise / pass → human approval.
Built on LangGraph.

**Quick start (no API keys needed)**: `pip install -r requirements.txt` →
`DRY_RUN=1 python main.py --doc-type cv --jd jd.example.txt --profile profile_db.example.json --company "Example Co" --role "Data Analyst"`
→ tests: `python -m unittest discover -s tests`

## File structure

```
config.py               Model names, round limit, thresholds (the only place to change them)
schemas.py              Draft / Claim / JudgeVerdict / LoopState + planning and lessons schemas — every LLM output is forced through these
llms.py                 Model factory + DRY_RUN mock objects
router.py               Document type → judge panel, veto judges
writer.py               Writer node (first draft / revise using only failed judges' fix_instruction)
judges/deterministic.py 5 code judges (known_gaps, claims_integrity, char_limit, jd_keyword_coverage, cv_structure)
judges/prompts.py       9 LLM judge prompts (one judge = one criterion)
judges/run.py           Judge runner — dispatches to code or LLM by name
graph.py                LangGraph assembly (parallel fan-out with Send, human approval with interrupt)
main.py                 CLI + per-round logging
profile_db.json         Single source of truth about the candidate (entries + known_gaps) — private; see profile_db.example.json
jd.example.txt          Example job description
.env.example            Required environment variables (copy to .env; .env is git-ignored)
fetch_posting.py        Job link → applications/<slug>/posting.json (Ashby/Greenhouse/Lever APIs, otherwise HTML or manual paste)
validate_plan.py        Validates an application folder: schemas, brief quotes present in saved sources, evidence ids, limits, lessons review
run_application.py      Runs the loop per document from an approved plan → drafts/ → .docx
lessons.py              Lessons ledger (retrospective → lessons) and matching against a posting; `python lessons.py` → lessons.md
build_docx.py           CV text → one-page .docx (page count checked through Word)
build_answers_docx.py   Application answers → a single .docx with character/word counts
.claude/skills/apply/   /apply skill for Claude Code: company research, posting analysis and planning
tests/                  python -m unittest discover -s tests (fictional data only)
```

## Per-application flow

```
/apply <url> → fetch_posting → company research (brief: each fact with a quoted source) → posting analysis & plan
→ validate_plan → human approves the plan → python run_application.py applications/<slug>
→ per document [writer → judges → aggregate → human_gate] → drafts/ → .docx
```

- Sentences stating employer facts must cite the brief's `co_` ids as claims, checked by `claims_integrity` and
  `fact_grounding`; each `co_` fact's quote must appear verbatim in the saved source text. (Employer sentences backed
  only by the job description itself need no claim.)
- The plan's per-document direction (`lead` / `avoid` evidence, `angle`, `closing_note`) is framing guidance, never a
  source of facts. Citing an `avoid` entry fails `claims_integrity`.
- CV header dates must exactly match the profile's `period` values (`cv_structure`).
- Form questions with no stated limit default to an 800-character cap (not a target), raised to 1,000 only with the
  user's approval.
- `outcome.json` records the result (status, stage reached, feedback, hypotheses) and feeds the retrospective loop.

## Lessons ledger

Lessons from past applications are stored with a **layer** (L1 structure / L2 selection / L3 wording / L4 strategy),
**conditions** on fixed dimensions (`doc_type`, `question_intent`, `role_kind`, `market`, `language`, `company_size`,
`submission` — each a list of values or `any`) and a **status** (hypothesis / confirmed / retired). For every new
application, the lessons whose conditions match must be reviewed in the plan's `lessons_checked` — confirmed lessons
apply by default (not applying requires a reason), hypotheses are decided case by case — or `validate_plan` blocks the
run. Status changes require the user's approval.

## Loop

```
START → writer ──Send×N──▶ judge (parallel) → aggregate
          ▲                                     │ revise (round < MAX_ROUNDS)
          └─────────────────────────────────────┤
                                                ├ pass / escalate → human_gate (interrupt) → END
```

- `verdicts` accumulate across rounds; `aggregate` only looks at the current round.
- Veto judges (`fact_grounding`, `known_gaps`) always send the draft back if they fail.
- On revision the writer receives **only the failed judges' `fix_instruction`** and is told to leave every other
  sentence unchanged.
- When the round limit is reached the draft is `escalate`d to the human with the outstanding failures. The default
  `MAX_ROUNDS` is 4.
- Formatting/tone judges (`tone_length`, `uk_cv_convention`, `bullet_format`) run on `gpt-5-mini`, a separate rate-limit
  bucket from `gpt-5` — accounts on low usage tiers can hit per-model rate limits quickly when the panel fans out in
  parallel, and splitting light checks onto a second model spreads that load.

## Running

```bash
pip install -r requirements.txt

# API keys live in .env (copy .env.example to .env and fill in; .env is git-ignored)
# Writer = Claude (claude-sonnet-5); all judges = OpenAI (gpt-5, gpt-5-mini for light formatting checks)

# 1) Run the whole loop without any API calls
DRY_RUN=1 python main.py --doc-type cv --jd jd.example.txt --profile profile_db.example.json \
    --company "Example Co" --role "Data Analyst"

# 2) Real runs
python main.py --doc-type cv ...
python main.py --doc-type application_answer --question "Describe a time you failed" --word-limit 250 ...
python main.py --doc-type cover_letter --word-limit 400 ...

# 3) A whole application from an approved plan
python run_application.py applications/<slug> [--only q1,q2]
```

On Windows the default cp949 locale breaks UTF-8 file and console output, so the entry points force UTF-8 — new
scripts should also use `open(path, encoding="utf-8")` and `sys.stdout.reconfigure(encoding="utf-8")`.

Every round's verdicts are saved as JSON under `runs/`. After about 20 runs, check which judges fail drafts most often
and which never catch anything, and tune the prompts accordingly.

## profile_db.json rules

- `entries[].id` is the only key the writer may cite. A sentence that cannot cite an entry fails `claims_integrity`.
  The `candidate` block (name/contact details) sits outside `entries`, has no id and is never cited as a claim.
- `known_gaps` lists **phrases that must never appear** in a document. Matching uses word boundaries (so "GAM" does
  not match "game"), which makes short phrases safe, but they should still be phrased the way they would realistically
  be written.
- When a fact changes, edit only this file. Never put candidate facts in prompts or code.
- When adding a failure or conflict story, record only what is confirmed from a real source (a paper, project
  documents) or confirmed in detail by the candidate — strengths are framed through `emphasis` / `angle`, never
  embellished.

## Extending

| To do this | Change this |
|---|---|
| Add a document type (e.g. a portfolio description) | Add a key to `router.PANEL` and one line of guidance to `writer.SYSTEM` |
| Add an LLM judge | Add an entry to `judges/prompts.py`, then its name to `router.PANEL` |
| Add a code judge | Add a function and `REGISTRY` entry in `judges/deterministic.py`, then its name to `router.DETERMINISTIC` |
| Swap models | `WRITER_MODEL` / `JUDGE_MODEL` / `REDTEAM_MODEL` / `JUDGE_MODEL_LIGHT` in `config.py` |
| Run a judge on a cheaper model | Add its name to `config.LIGHT_JUDGES` (it must still be OpenAI — "all judges OpenAI" rule) |
| Approve in a web UI instead of the CLI | Render `human_gate_node`'s interrupt payload and resume with `Command(resume=...)` |
| Several questions at once | Use `run_application.py`, or call `main.py` per question and pass earlier answers via `--prior-answers` |

## Possible next steps

1. Swap `InMemorySaver` for `SqliteSaver` so interrupted runs can resume.
2. Replace the frequency heuristic in `jd_keyword_coverage` with a single LLM keyword-extraction call.
3. A per-judge failure-rate dashboard from the `runs/` logs — to measure which judges actually earn their place.
4. A dedicated judge for the "no self-evaluative summary sentences" rule (currently enforced only in the writer prompt).
