
import pytest
import streamlit as st


@pytest.fixture(autouse=True)
def _real_session_state(monkeypatch):
    monkeypatch.setattr(st, "session_state", {}, raising=False)
