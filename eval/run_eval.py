"""Measure the reviewer against YOUR OWN human scores.

1. Fill eval/repos.csv with 8-10 public repos and a human_score (0-100) you assign by hand,
   using the same rubric (see reviewer/rubric.py). Include weak AND strong repos.
2. python eval/run_eval.py --provider anthropic
3. Paste the printed table + metrics into docs/technical_approach.md.

Metrics: MAE (how far off, in points), Spearman rank correlation (does it order repos correctly?),
and band agreement (same readiness label as human).
"""
import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

from reviewer.pipeline import review_snapshot  # noqa: E402
from reviewer.repo_source import from_github, from_local  # noqa: E402
from reviewer.rubric import readiness  # noqa: E402


def ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):  # average ranks for ties
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def spearman(a, b):
    ra, rb = ranks(a), ranks(b)
    n = len(a)
    ma, mb = sum(ra) / n, sum(rb) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = sum((x - ma) ** 2 for x in ra) ** 0.5
    vb = sum((y - mb) ** 2 for y in rb) ** 0.5
    return cov / (va * vb) if va and vb else float("nan")


def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="anthropic")
    ap.add_argument("--model")
    ap.add_argument("--csv", default="eval/repos.csv")
    ap.add_argument("--out", default="eval/results.csv")
    a = ap.parse_args()

    rows = [r for r in csv.DictReader(open(a.csv)) if r["url"].strip() and r["human_score"].strip()]
    if len(rows) < 3:
        sys.exit("Fill at least 3 rows (url + human_score) in eval/repos.csv first.")

    results = []
    for r in rows:
        try:
            snap = from_github(r["url"]) if r["url"].startswith("http") else from_local(r["url"])
            fr = review_snapshot(snap, a.provider, a.model)
            results.append({**r, "ai_score": fr.overall_score, "ai_band": fr.readiness,
                            "human_band": readiness(float(r["human_score"])), "flagged": fr.needs_mentor_review})
            print(f"{r['url']}: human={r['human_score']} ai={fr.overall_score}")
        except Exception as e:  # keep going; failures are data too
            print(f"{r['url']}: FAILED {type(e).__name__}: {e}")

    if not results:
        sys.exit("No successful reviews.")
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0]))
        w.writeheader()
        w.writerows(results)

    h = [float(x["human_score"]) for x in results]
    m = [float(x["ai_score"]) for x in results]
    mae = sum(abs(x - y) for x, y in zip(h, m)) / len(h)
    agree = sum(x["ai_band"] == x["human_band"] for x in results) / len(results)
    print(f"\nN={len(results)}  MAE={mae:.1f} pts  Spearman={spearman(h, m):.2f}  band agreement={agree:.0%}")
    print(f"Results written to {a.out}")


if __name__ == "__main__":
    main()
