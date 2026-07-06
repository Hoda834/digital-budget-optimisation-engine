"""Reproducibility guard for the runnable examples in examples/.

Each example script prints an allocation, classification, and the key
figures a reader is meant to verify. These tests run every script the
same way a reader would (as a subprocess, with PYTHONPATH=src) and pin
the figures that appear in the documentation, so that a future change to
the pipeline that would silently alter a documented example fails CI
instead of being discovered by hand.

The scripts are the source of truth; if an intended change moves a
number here, update the expected value and the corresponding docs in the
same commit.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO_ROOT, "src")
EXAMPLES = os.path.join(REPO_ROOT, "examples")


def _run(script_relpath: str) -> str:
    """Run an example script exactly as documented and return its stdout."""
    env = dict(os.environ)
    env["PYTHONPATH"] = SRC + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, os.path.join(EXAMPLES, script_relpath)],
        cwd=REPO_ROOT, env=env,
        capture_output=True, text=True, timeout=600,
    )
    assert proc.returncode == 0, (
        f"{script_relpath} exited {proc.returncode}\nSTDERR:\n{proc.stderr}")
    return proc.stdout


def _clean(text: str) -> str:
    """Collapse whitespace so figures can be matched regardless of padding."""
    return " ".join(text.split())


def test_case_study_reproduces_three_configurations():
    out = _clean(_run("case_study/run_case_study.py"))
    # Configuration shares and the diagnostic index, all three configs.
    assert "34,000 (50.0%)" in out
    assert "26,000 (38.2%)" in out
    assert "24,000 (35.3%)" in out
    assert "Diagnostic index : 90" in out
    assert "Scenario-sensitive" in out


def test_data_sensitivity_sweep_shape():
    out = _clean(_run("case_study/run_data_sensitivity.py"))
    # The step-function endpoints and the corrected mid-point.
    assert "3,200 | 25.0%" in out
    assert "4,200 | 38.2%" in out
    assert "5,200 | 38.2%" in out
    assert "7,200 | 60.0%" in out


def test_parameter_sensitivity_runs_all_five_subanalyses():
    out = _run("case_study/run_parameter_sensitivity.py")
    for header in ("A. Diversification cap", "B. Diagnostic-index deduction",
                   "C. Classification-threshold", "D. Yield-bracket schedule",
                   "E. Scenario-multiplier"):
        assert header in out, f"missing sub-analysis: {header}"
    cleaned = _clean(out)
    # Diversification cap trade-off is monotonic; endpoints pinned.
    assert "0.60 60.0%" in cleaned
    assert "0.80 76.5%" in cleaned
    # Yield-bracket schedule is the influential parameter: full 25-60 swing.
    assert "25.0%" in cleaned and "60.0%" in cleaned


def test_balanced_example_exact_figures():
    out = _clean(_run("minimal_examples/run_balanced_example.py"))
    assert "12,000 (60%)" in out
    assert "8,000 (40%)" in out
    assert "52,894.74" in out          # expected revenue, to the penny
    assert "Return on spend : 2.64" in out
    assert "Diagnostic index : 82" in out


def test_concentrated_example_exact_figures():
    out = _clean(_run("minimal_examples/run_concentrated_example.py"))
    assert "48,000 (88.9%)" in out     # dominant platform, Plan A
    assert "567,506.25" in out         # corrected expected revenue
    assert "37,800" in out             # Plan B cap
    assert "Redistributed : 10,200" in out
    assert "Trade-off : 2.38%" in out  # corrected trade-off


def test_benchmark_runs_and_scales():
    out = _clean(_run("benchmark/run_benchmark.py"))
    # All five sizes present, largest is 900 LP variables.
    assert "300 900" in out
    assert "Median (ms)" in out
