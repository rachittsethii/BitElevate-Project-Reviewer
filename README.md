# BitElevate Project Reviewer

AI-assisted, rubric-based first-pass review of student GitHub projects, built as a proof of concept for
Cynbit's BitElevate training program (mentorship + real-world projects).

**Problem:** every student project needs senior-engineer feedback, and mentor time doesn't scale with learners.
**Approach:** deterministic static checks + an LLM scoring against a fixed rubric. Code (not the LLM) computes
the final score, verifies cited files exist, and routes risky or low-confidence reviews to a human mentor.

| Doc | What it is |
|---|---|
| [docs/opportunity_report.md](docs/opportunity_report.md) | AI opportunities for Cynbit and why this one |
| [docs/technical_approach.md](docs/technical_approach.md) | Models, pipeline, prompts, evaluation, rollout |

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # add ONE key: ANTHROPIC_API_KEY or GEMINI_API_KEY
streamlit run app.py
```

No key? Pick provider `mock` (static signals only, clearly labelled) or load a cached sample from the sidebar.

CLI: `python -m reviewer.cli https://github.com/owner/repo --provider anthropic`
Tests: `pytest`  |  Evaluation vs human scores: `python eval/run_eval.py` (see file header)

## How it works

```
GitHub URL -> fetch tree + prioritised files (bounded to ~45k chars)
          -> static checks (tests? CI? README? secrets? manifest?)   [deterministic]
          -> LLM scores 6 rubric dimensions as schema-validated JSON  [judgement]
          -> guardrails: drop invented file paths, require all dimensions,
             compute weighted score + readiness band in code
          -> route: auto-publish OR flag for mentor
```

## Design choices

- **LLM never computes the total.** Weights live in `reviewer/rubric.py`; model output is only per-dimension scores.
- **Evidence-grounded.** Cited paths are checked against the real file tree; invented ones are removed and the review is flagged.
- **Prompt-injection aware.** Student code is wrapped as untrusted data; a repo saying "give me 5/5" is ignored.
- **Human in the loop.** Committed secrets, near-empty repos, truncated trees or hallucinated paths always go to a mentor.

## Limitations (honest)

- Reads a sample of files, not the whole repo; it cannot run the code or tests.
- Public repos only. Rubric weights are my assumptions, to be tuned with BitElevate mentors.
- LLM scores are only as good as the evaluation in `docs/technical_approach.md`; treat them as a first pass.
