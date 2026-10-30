"""The scoring rubric. Weights live in code so the LLM never computes totals."""

# dimension -> (weight, what a 0 / 3 / 5 looks like)
RUBRIC: dict[str, dict] = {
    "code_quality": {
        "weight": 0.25,
        "anchors": "0: unreadable/duplicated, no structure. 3: works, some naming/function-size issues. "
        "5: clear naming, small cohesive functions, no dead code, idiomatic for the language.",
    },
    "architecture": {
        "weight": 0.20,
        "anchors": "0: everything in one file. 3: some separation but tangled. "
        "5: clear modules/layers, config separated from logic, sensible data flow.",
    },
    "testing": {
        "weight": 0.20,
        "anchors": "0: no tests. 3: some tests, happy path only. "
        "5: meaningful unit/integration tests incl. edge cases; runnable with one command.",
    },
    "documentation": {
        "weight": 0.15,
        "anchors": "0: no README. 3: README with description only. "
        "5: purpose, setup, usage example, architecture notes; a stranger can run it in 5 minutes.",
    },
    "security_hygiene": {
        "weight": 0.10,
        "anchors": "0: committed secrets or obvious injection. 3: no secrets but weak input handling. "
        "5: env-based config, input validation, .gitignore, pinned deps.",
    },
    "engineering_practices": {
        "weight": 0.10,
        "anchors": "0: single giant commit, no tooling. 3: some commits/CI. "
        "5: CI, linting/formatting, dependency manifest, license, meaningful structure.",
    },
}

assert abs(sum(d["weight"] for d in RUBRIC.values()) - 1.0) < 1e-9

READINESS_BANDS = [  # (min_score_out_of_100, label)
    (80, "Placement-ready"),
    (60, "Portfolio-ready"),
    (40, "Developing"),
    (0, "Needs rework"),
]


def readiness(score: float) -> str:
    for minimum, label in READINESS_BANDS:
        if score >= minimum:
            return label
    return "Needs rework"


def overall_score(dim_scores: dict[str, int]) -> float:
    """Weighted 0-100. Missing dimensions count as 0 (and get flagged elsewhere)."""
    total = 0.0
    for name, spec in RUBRIC.items():
        total += spec["weight"] * (dim_scores.get(name, 0) / 5) * 100
    return round(total, 1)


def rubric_text() -> str:
    lines = []
    for name, spec in RUBRIC.items():
        lines.append(f"- {name} (weight {int(spec['weight'] * 100)}%): {spec['anchors']}")
    return "\n".join(lines)
