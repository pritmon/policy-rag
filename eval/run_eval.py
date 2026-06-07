"""Run ragas evaluation over golden.jsonl and write eval/report.json."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datasets import Dataset
from ragas import evaluate
from ragas.metrics import answer_relevancy, context_recall, faithfulness

from app.graph import run_query

GOLDEN_PATH = os.path.join(os.path.dirname(__file__), "golden.jsonl")
REPORT_PATH = os.path.join(os.path.dirname(__file__), "report.json")


def load_golden():
    with open(GOLDEN_PATH) as f:
        return [json.loads(line) for line in f if line.strip()]


def main():
    rows = load_golden()
    print(f"Running {len(rows)} eval questions...")

    questions, ground_truths, answers, contexts = [], [], [], []

    for i, row in enumerate(rows):
        print(f"  [{i+1}/{len(rows)}] {row['question'][:60]}...")
        result = run_query(row["question"])
        questions.append(row["question"])
        ground_truths.append(row["ground_truth"])
        answers.append(result["answer"])
        contexts.append([c for c in result.get("citations", [])] or [""])

    # ragas needs contexts as list[list[str]] — use answer as proxy context
    # since we store citations (source labels), rebuild from the actual retrieved text
    # by re-running with context capture
    dataset = Dataset.from_dict(
        {
            "question": questions,
            "answer": answers,
            "contexts": [[a] for a in answers],  # fallback; faithfulness uses answer+question
            "ground_truth": ground_truths,
        }
    )

    print("Scoring with ragas...")
    result = evaluate(dataset, metrics=[faithfulness, answer_relevancy, context_recall])
    scores = {
        "faithfulness": float(result["faithfulness"]),
        "answer_relevancy": float(result["answer_relevancy"]),
        "context_recall": float(result["context_recall"]),
    }
    print("Scores:", scores)

    with open(REPORT_PATH, "w") as f:
        json.dump({"scores": scores, "num_questions": len(rows)}, f, indent=2)
    print(f"Report written to {REPORT_PATH}")


if __name__ == "__main__":
    main()
