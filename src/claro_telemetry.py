"""Anonymous usage telemetry for the CLARO Streamlit app.

Records three events per session so that adoption can be described in terms of
completed optimisation runs rather than page views:

    session_started
    optimisation_started
    optimisation_completed

What is sent: a random session id, the event name, the utm parameters the
visitor arrived with, and the app version. Nothing the user typed, no budget
figures, no uploaded data, no IP address, no cookies.

Telemetry never blocks the app and never raises. If Supabase is unreachable or
the secrets are missing, the calls become no-ops and the optimiser carries on.

Setup
-----
1. Run sql/claro_events.sql in the Supabase SQL editor.
2. Add to .streamlit/secrets.toml, or to Secrets in Streamlit Community Cloud:

    [supabase]
    url = "https://xxxxxxxx.supabase.co"
    anon_key = "eyJhbGci..."

The anon key is insert-only under row level security, so it cannot read your
usage data back.
"""

from __future__ import annotations

import threading
import uuid
from typing import Any, Mapping

import requests
import streamlit as st

APP_VERSION = "0.2.1"
_TIMEOUT_SECONDS = 3
_TABLE = "claro_events"

# The vocabulary the website sends. Anything else is recorded as it arrives,
# truncated, so an unexpected value cannot bloat the column.
_MAX_TAG_LENGTH = 40


def _config() -> tuple[str, str] | None:
    """Return (url, anon_key), or None when telemetry is not configured."""
    try:
        section = st.secrets["supabase"]
        url = str(section["url"]).rstrip("/")
        key = str(section["anon_key"])
    except Exception:
        return None
    if not url or not key:
        return None
    return url, key


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    return text[:_MAX_TAG_LENGTH]


def _attribution() -> dict[str, str | None]:
    """Read the utm parameters once and keep them for the whole session."""
    if "claro_attribution" not in st.session_state:
        try:
            params = st.query_params
            source = _clean(params.get("utm_source"))
            medium = _clean(params.get("utm_medium"))
            campaign = _clean(params.get("utm_campaign"))
        except Exception:
            source = medium = campaign = None
        st.session_state.claro_attribution = {
            "utm_source": source or "direct",
            "utm_medium": medium,
            "utm_campaign": campaign,
        }
    return st.session_state.claro_attribution


def _session_id() -> str:
    if "claro_session_id" not in st.session_state:
        st.session_state.claro_session_id = str(uuid.uuid4())
    return st.session_state.claro_session_id


def _post(url: str, key: str, payload: Mapping[str, Any]) -> None:
    """Fire and forget. Runs on a daemon thread and swallows every error."""
    try:
        requests.post(
            f"{url}/rest/v1/{_TABLE}",
            json=payload,
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            timeout=_TIMEOUT_SECONDS,
        )
    except Exception:
        pass


def log_event(event: str, run_id: str | None = None) -> None:
    """Record one event. Safe to call from anywhere, including inside a rerun."""
    config = _config()
    if config is None:
        return

    payload = {
        "session_id": _session_id(),
        "run_id": run_id,
        "event": event,
        "app_version": APP_VERSION,
        **_attribution(),
    }

    threading.Thread(
        target=_post,
        args=(config[0], config[1], payload),
        daemon=True,
    ).start()


def track_session() -> None:
    """Record session_started once per session. Call near the top of the app."""
    if st.session_state.get("claro_session_logged"):
        return
    st.session_state.claro_session_logged = True
    log_event("session_started")


def new_run_id() -> str:
    """Identifier tying an optimisation_started to its optimisation_completed."""
    run_id = str(uuid.uuid4())
    st.session_state.claro_run_id = run_id
    return run_id


def current_run_id() -> str | None:
    return st.session_state.get("claro_run_id")
