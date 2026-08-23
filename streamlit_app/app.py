import secrets

import requests
import streamlit as st

from app.core.config import get_settings
from streamlit_app.client import (
    ResearchApiClient,
    exchange_google_code,
    google_authorization_url,
)

settings = get_settings()
st.set_page_config(page_title="Parallel Research Consensus", page_icon="🔎", layout="wide")


def render_report(report: dict) -> None:
    st.subheader(report["query"])
    st.markdown(report.get("final_answer") or "No synthesized answer was produced.")

    scores = report.get("confidence_scores", {})
    if scores:
        st.markdown("### Confidence")
        for cluster_id, score in scores.items():
            st.write(
                f"**{score['claim_summary']}** — {score['tier'].upper()} "
                f"({score['final_score']:.2f})"
            )
            with st.expander(f"Scoring details · {cluster_id}"):
                st.json(score)

    contradictions = report.get("contested_points", [])
    if contradictions:
        st.markdown("### Contested points")
        for item in contradictions:
            with st.expander(item["disputed_claim"], expanded=True):
                for position in item["positions"]:
                    st.markdown(f"- **{position['statement']}**")
                    st.caption("Supporting agents: " + ", ".join(position["supporting_agents"]))
                    for url in position["source_urls"]:
                        st.markdown(f"  - [{url}]({url})")

    sources = report.get("deduplicated_sources", [])
    if sources:
        st.markdown("### Sources")
        for source in sources:
            agents = ", ".join(source["citing_agents"])
            st.markdown(f"- [{source['domain']}]({source['canonical_url']}) · cited by {agents}")


def finish_google_login() -> None:
    code = st.query_params.get("code")
    returned_state = st.query_params.get("state")
    if not code:
        return
    if not returned_state or returned_state != st.session_state.get("oauth_state"):
        st.error("Google login state validation failed. Please try again.")
        st.query_params.clear()
        st.stop()
    try:
        google_token = exchange_google_code(settings, code)
        auth = ResearchApiClient(settings.api_base_url).login_google(google_token)
    except (requests.RequestException, ValueError) as exc:
        st.error(f"Google login failed: {exc}")
        st.stop()
    st.session_state["access_token"] = auth["access_token"]
    st.session_state["user"] = auth["user"]
    st.query_params.clear()
    st.rerun()


finish_google_login()

if "access_token" not in st.session_state:
    st.title("Parallel Research Consensus")
    st.write("Compare independent web, academic, and recent-news research in one report.")
    oauth_state = st.session_state.setdefault("oauth_state", secrets.token_urlsafe(24))
    try:
        login_url = google_authorization_url(settings, oauth_state)
        st.link_button("Continue with Google", login_url, type="primary")
    except ValueError as exc:
        st.error(str(exc))
    st.stop()

client = ResearchApiClient(settings.api_base_url, st.session_state["access_token"])
user = st.session_state.get("user", {})
st.sidebar.write(f"Signed in as **{user.get('name', user.get('email', 'User'))}**")
if st.sidebar.button("Log out"):
    st.session_state.clear()
    st.rerun()

st.title("Parallel Research Consensus")
research_tab, history_tab = st.tabs(["New research", "My Research"])


@st.fragment(run_every=2)
def poll_active_job() -> None:
    active_job_id = st.session_state.get("active_job_id")
    if not active_job_id:
        return
    try:
        job_status = client.status(active_job_id)
        if job_status["status"] == "running":
            st.info("Research in progress…")
            st.progress(50)
            return
        if job_status["status"] == "failed":
            st.error(job_status.get("error") or "Research failed")
            st.session_state.pop("active_job_id", None)
            return
        st.session_state["active_report"] = client.report(active_job_id)
        st.session_state.pop("active_job_id", None)
        st.rerun()
    except requests.RequestException as exc:
        st.error(f"Could not retrieve research status: {exc}")


with research_tab:
    with st.form("research-form"):
        query = st.text_area(
            "Research question",
            placeholder="Ask one focused question...",
            max_chars=1000,
        )
        submitted = st.form_submit_button("Start research", type="primary")
    if submitted and query.strip():
        try:
            started = client.start_research(query.strip())
            st.session_state["active_job_id"] = started["job_id"]
            st.session_state.pop("active_report", None)
            st.rerun()
        except requests.RequestException as exc:
            st.error(f"Could not start research: {exc}")

    poll_active_job()
    if st.session_state.get("active_report"):
        render_report(st.session_state["active_report"])

with history_tab:
    try:
        history = client.history()
        if not history:
            st.info("No saved research yet.")
        for item in history:
            left, right = st.columns([5, 1])
            left.write(f"**{item['query']}** · {item['status']}")
            if right.button("Open", key=f"open-{item['job_id']}"):
                st.session_state["active_job_id"] = item["job_id"]
                st.session_state.pop("active_report", None)
                st.rerun()
    except requests.RequestException as exc:
        st.error(f"Could not load research history: {exc}")
