"""python -m reviewer.cli <github-url | local-folder> [--provider mock] [--out samples/x.json]"""
import argparse
import sys

from dotenv import load_dotenv

from .pipeline import review_snapshot
from .repo_source import from_github, from_local


def main() -> int:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    ap.add_argument("--provider", default="anthropic", choices=["anthropic", "gemini", "mock"])
    ap.add_argument("--model")
    ap.add_argument("--out")
    a = ap.parse_args()

    snap = from_github(a.target) if a.target.startswith(("http", "github.com")) else from_local(a.target)
    result = review_snapshot(snap, a.provider, a.model)
    text = result.model_dump_json(indent=2)
    if a.out:
        with open(a.out, "w") as f:
            f.write(text)
        print(f"{result.repo}: {result.overall_score}/100 ({result.readiness}) -> {a.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
