"""pytest gate: assert eval scores meet minimum thresholds."""
import json
import os

import pytest

REPORT_PATH = os.path.join(os.path.dirname(__file__), "report.json")
FAITHFULNESS_FLOOR = float(os.getenv("FAITHFULNESS_FLOOR", "0.7"))
CONTEXT_RECALL_FLOOR = float(os.getenv("CONTEXT_RECALL_FLOOR", "0.6"))


@pytest.fixture(scope="session")
def report():
    if not os.path.exists(REPORT_PATH):
        pytest.skip("report.json not found — run `make eval` first")
    with open(REPORT_PATH) as f:
        return json.load(f)


def test_faithfulness(report):
    score = report["scores"]["faithfulness"]
    assert score >= FAITHFULNESS_FLOOR, f"faithfulness {score:.2f} < floor {FAITHFULNESS_FLOOR}"


def test_context_recall(report):
    score = report["scores"]["context_recall"]
    assert score >= CONTEXT_RECALL_FLOOR, (
        f"context_recall {score:.2f} < floor {CONTEXT_RECALL_FLOOR}"
    )
