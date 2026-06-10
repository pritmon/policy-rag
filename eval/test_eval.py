"""
test_eval.py — The pass/fail gate. Checks the exam marks meet the minimum.

run_eval.py gives the app its marks (report.json). This file is the
school rule that says: "you must score at least X to pass."

  faithfulness must be >= 0.7  (no making things up!)
  context_recall must be >= 0.6 (must find the right document parts)

If the app scores below the floor, `make test` FAILS — which stops a
bad version from being released. This is called a "quality gate".

The floors can be changed via environment variables without touching code.
Run it with:  make test   (after `make eval` has produced report.json)
"""
import json
import os

import pytest

# Where run_eval.py wrote the marks
REPORT_PATH = os.path.join(os.path.dirname(__file__), "report.json")
# Minimum acceptable marks (0 to 1). Overridable via env vars.
FAITHFULNESS_FLOOR = float(os.getenv("FAITHFULNESS_FLOOR", "0.7"))
CONTEXT_RECALL_FLOOR = float(os.getenv("CONTEXT_RECALL_FLOOR", "0.6"))


@pytest.fixture(scope="session")
def report():
    """Load the report card — skip the tests politely if it doesn't exist yet."""
    if not os.path.exists(REPORT_PATH):
        pytest.skip("report.json not found — run `make eval` first")
    with open(REPORT_PATH) as f:
        return json.load(f)


def test_faithfulness(report):
    """Fail if the app made things up too often (score below the floor)."""
    score = report["scores"]["faithfulness"]
    assert score >= FAITHFULNESS_FLOOR, f"faithfulness {score:.2f} < floor {FAITHFULNESS_FLOOR}"


def test_context_recall(report):
    """Fail if the app missed the right document sections too often."""
    score = report["scores"]["context_recall"]
    assert score >= CONTEXT_RECALL_FLOOR, (
        f"context_recall {score:.2f} < floor {CONTEXT_RECALL_FLOOR}"
    )
