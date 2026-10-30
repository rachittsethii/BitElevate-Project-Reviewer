import pytest

from reviewer import pipeline
from reviewer.models import DimensionScore, Fix, LLMReview, RepoSnapshot
from reviewer.repo_source import RepoError, parse_github_url, select_files
from reviewer.rubric import RUBRIC, overall_score, readiness
from reviewer.static_checks import compute_signals, mentor_flags


def snap(paths, files=None):
    return RepoSnapshot(name="t/t", source="x", paths=paths, files=files or {})


def test_parse_url():
    assert parse_github_url("https://github.com/a/b") == ("a", "b")
    assert parse_github_url("https://github.com/a/b.git") == ("a", "b")
    assert parse_github_url("github.com/a/b/tree/main") == ("a", "b")
    with pytest.raises(RepoError):
        parse_github_url("https://gitlab.com/a/b")


def test_select_files_prioritises_readme_and_skips_junk():
    paths = ["node_modules/x/index.js", "logo.png", "src/a.py", "README.md", "tests/test_a.py", "requirements.txt"]
    chosen = select_files(paths)
    assert chosen[0] == "README.md"
    assert "node_modules/x/index.js" not in chosen and "logo.png" not in chosen
    assert "requirements.txt" in chosen


def test_signals_detect_tests_ci_and_secrets():
    s = snap(
        ["README.md", "app.py", "tests/test_app.py", ".github/workflows/ci.yml", ".env", ".gitignore"],
        {"app.py": 'API_KEY = "abcd1234abcd1234abcd1234"', "README.md": "# X\n## Setup\nrun it"},
    )
    sig = compute_signals(s)
    assert sig["has_tests"] and sig["has_ci"] and sig["has_readme"] and sig["readme_has_setup"]
    assert sig["committed_env_files"] == [".env"]
    assert any("app.py" in x for x in sig["possible_secrets"])
    assert mentor_flags(sig)  # secrets always reach a human


def test_score_weights_and_bands():
    assert overall_score({k: 5 for k in RUBRIC}) == 100.0
    assert overall_score({k: 0 for k in RUBRIC}) == 0.0
    assert overall_score({"code_quality": 5}) == 25.0  # missing dims count as 0
    assert readiness(85) == "Placement-ready" and readiness(10) == "Needs rework"


def _fake_llm(evidence, fix_file):
    dims = [DimensionScore(dimension=d, score=5, rationale="ok", evidence=evidence) for d in RUBRIC]
    return LLMReview(summary="s", dimensions=dims, top_fixes=[Fix(priority="high", file=fix_file, action="a")], strengths=[])


def test_guardrails_drop_hallucinated_paths_and_flag(monkeypatch):
    s = snap(["README.md", "a.py", "b.py"], {"README.md": "hi"})
    monkeypatch.setattr(pipeline, "run_review", lambda *a, **k: (_fake_llm(["a.py", "ghost.py"], "nope.py"), "fake"))
    r = pipeline.review_snapshot(s, "anthropic")
    assert "ghost.py" in r.dropped_evidence and "nope.py" in r.dropped_evidence
    assert all(d.evidence == ["a.py"] for d in r.llm.dimensions)
    assert r.llm.top_fixes[0].file is None
    assert r.needs_mentor_review  # hallucinated paths => human check


def test_missing_dimension_scores_zero_and_flags(monkeypatch):
    s = snap(["README.md", "a.py", "b.py"])
    partial = _fake_llm([], None)
    partial.dimensions = partial.dimensions[:3]
    monkeypatch.setattr(pipeline, "run_review", lambda *a, **k: (partial, "fake"))
    r = pipeline.review_snapshot(s, "anthropic")
    assert r.overall_score < 100 and any("omitted" in f for f in r.mentor_flags)


def test_mock_pipeline_end_to_end_on_local_folder(tmp_path):
    from reviewer.repo_source import from_local

    (tmp_path / "README.md").write_text("# Demo\n## Setup\n" + "text " * 200)
    (tmp_path / "app.py").write_text("print('hi')\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("def test_x(): pass\n")
    r = pipeline.review_snapshot(from_local(str(tmp_path)), provider="mock")
    assert 0 <= r.overall_score <= 100
    assert len(r.llm.dimensions) == len(RUBRIC)
