# Technical Approach: BitElevate Project Reviewer

> DRAFT SKELETON. Replace every TODO with your real numbers after running `eval/run_eval.py`.

## 1. Architecture
```
GitHub URL -> repo_source (tree + prioritised files, ~45k char budget)
 -> static_checks (deterministic facts)
 -> prompt (rubric + signals + untrusted file contents)
 -> LLM (schema-forced JSON) -> guardrails -> weighted score in code -> route (auto / mentor)
```

## 2. Model choices
| Choice | Why | Trade-off |
|---|---|---|
| Claude Sonnet (default) | Strong code reasoning; tool-use gives schema-valid JSON | Cost per review (TODO measure) |
| Gemini Flash (alt.) | Free tier for demos; cheap at scale | Weaker on subtle code judgement (TODO verify in eval) |
| No fine-tuning | Rubric + few-shot beats it at this data size; no labelled corpus yet | Revisit after ~500 mentor-scored reviews |
| Mock provider | Tests and offline demo only | Not an AI review; labelled as such |

## 3. Data pipeline
1. Fetch via GitHub REST API (tree, then selected contents). Skip binaries, vendored dirs, lockfiles.
2. Prioritise README > manifests > entrypoints > tests (max 2) > source; cap per file and in total.
3. Static signals (tests, CI, license, secrets regex, committed .env, dependency manifest).
4. Output stored as JSON; a mentor override field is the future training/eval data.

## 4. Prompt engineering
- System prompt: role, rubric with 0/3/5 anchors, rules. Temperature 0.
- Structured output via tool-use schema (Anthropic) / JSON mode (Gemini); one automatic repair retry.
- Static signals passed as ground truth so the model doesn't waste effort counting.
- Injection defence: repo content in `<repo_file>` tags, declared untrusted.
- Model returns dimension scores only; totals and readiness bands are computed in code.

## 5. Guardrails and human-in-the-loop
Evidence paths verified against the tree; missing dimensions scored 0 and flagged; secrets, empty repos,
truncation, or any invented path route the review to a mentor.

## 6. Evaluation (TODO: fill with real results)
Method: N repos scored by hand with the same rubric, compared with AI output.
| Metric | Result | Target |
|---|---|---|
| MAE (points) | TODO | <= 12 |
| Spearman | TODO | >= 0.7 |
| Band agreement | TODO | >= 70% |
Include the per-repo table, 2 cases where it was wrong, and why. Small-N caveat stated plainly.

## 7. Cost and latency
TODO: tokens per review x provider price = cost per review; seconds per review.

## 8. Execution plan
- Week 1: pilot on one BitElevate batch; mentors score blind vs AI; tune rubric weights.
- Week 2-3: GitHub login / webhook on submission, mentor dashboard with override, store overrides.
- Week 4+: tracking learner improvement across resubmissions; feed project scores into placement matching.
- Risks: score drift when models update (pin version, re-run eval), gaming, privacy (public repos only at first).
