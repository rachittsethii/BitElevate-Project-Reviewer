"""Streamlit demo:  streamlit run app.py"""
import json
import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from reviewer.llm import DEFAULT_MODELS, LLMError
from reviewer.models import FinalReview
from reviewer.pipeline import review_snapshot
from reviewer.repo_source import RepoError, from_github
from reviewer.rubric import RUBRIC

load_dotenv()
st.set_page_config(page_title="BitElevate Project Reviewer", page_icon="🧭", layout="wide")
st.title("BitElevate Project Reviewer")
st.caption("Rubric-based first-pass review of a student GitHub project. Mentors review only what the AI flags.")

SAMPLES = sorted(Path("samples").glob("*.json"))

with st.sidebar:
    st.header("Settings")
    provider = st.selectbox("Provider", ["anthropic", "gemini", "mock"], help="mock = no API key, static signals only")
    model = st.text_input("Model", DEFAULT_MODELS[provider])
    st.divider()
    sample = st.selectbox("...or load a cached sample", ["(none)"] + [s.stem for s in SAMPLES])

url = st.text_input("Public GitHub repo URL", placeholder="https://github.com/owner/repo")
go = st.button("Review project", type="primary")

review: FinalReview | None = None
if sample != "(none)":
    review = FinalReview.model_validate_json((Path("samples") / f"{sample}.json").read_text())
elif go and url:
    try:
        with st.spinner("Fetching repo and reviewing..."):
            snap = from_github(url)
            review = review_snapshot(snap, provider=provider, model=model)
    except RepoError as e:
        st.error(str(e))
    except LLMError as e:
        st.error(f"LLM problem: {e}")
    except Exception as e:  # network, missing key, etc.
        st.error(f"{type(e).__name__}: {e}")

if review:
    if review.model == "mock-heuristic":
        st.warning("Mock mode: scores come from static signals only. Use a real provider for a code-level review.")
    c1, c2, c3 = st.columns(3)
    c1.metric("Overall", f"{review.overall_score}/100")
    c2.metric("Readiness", review.readiness)
    c3.metric("Routing", "Mentor review" if review.needs_mentor_review else "Auto-publish OK")
    if review.mentor_flags:
        st.warning("**Flagged for mentor:**\n\n" + "\n".join(f"- {f}" for f in review.mentor_flags))

    st.subheader("Summary")
    st.write(review.llm.summary)

    st.subheader("Rubric scores")
    for d in review.llm.dimensions:
        weight = int(RUBRIC[d.dimension]["weight"] * 100)
        st.progress(d.score / 5, text=f"{d.dimension.replace('_', ' ').title()} ({weight}%): {d.score}/5")
        st.caption(d.rationale + (f"  \n_Evidence:_ {', '.join(d.evidence)}" if d.evidence else ""))

    left, right = st.columns(2)
    with left:
        st.subheader("Fix these first")
        for f in review.llm.top_fixes:
            st.markdown(f"- **{f.priority.upper()}** {f'`{f.file}` ' if f.file else ''}{f.action}")
    with right:
        st.subheader("Strengths")
        for s in review.llm.strengths:
            st.markdown(f"- {s}")

    with st.expander("Static signals (computed by code, not the LLM)"):
        st.json(review.static_signals)
    st.download_button("Download review JSON", review.model_dump_json(indent=2), file_name="review.json")
