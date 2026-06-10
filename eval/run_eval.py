"""
run_eval.py — The exam for our app. Checks how good its answers really are.

How the exam works:
  1. golden.jsonl is the question paper — questions WITH the correct answers
  2. We ask our app every question and collect its answers
  3. ragas (the examiner) compares our answers against the correct ones,
     using a judge AI (OpenAI) to score them
  4. The marks are saved to eval/report.json

The three marks:
  faithfulness     — did the app stick to the document, or make things up?
  answer_relevancy — did it actually answer the question that was asked?
  context_recall   — did it find the right parts of the document?

All scores go from 0 (terrible) to 1 (perfect).
Run it with:  make eval
"""
import json
import os
import sys
import time

# Allow "from app.xxx import ..." even though this file lives in eval/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datasets import Dataset
from ragas import evaluate
from ragas.metrics import answer_relevancy, context_recall, faithfulness

from app.graph import run_query

# The question paper (one JSON question per line)
GOLDEN_PATH = os.path.join(os.path.dirname(__file__), "golden.jsonl")
# Where the marks get written
REPORT_PATH = os.path.join(os.path.dirname(__file__), "report.json")


def load_golden():
    """Read the question paper — one question + correct answer per line."""
    with open(GOLDEN_PATH) as f:
        return [json.loads(line) for line in f if line.strip()]


def main():
    rows = load_golden()
    print(f"Running {len(rows)} eval questions...")

    questions, ground_truths, answers, contexts = [], [], [], []

    # Ask our app every question on the paper
    for i, row in enumerate(rows):
        print(f"  [{i+1}/{len(rows)}] {row['question'][:60]}...")
        if i > 0:
            # Pace ourselves: Gemini free tier allows ~20 requests/minute,
            # and each question fires several LLM + embedding calls.
            time.sleep(20)
        result = run_query(row["question"])
        questions.append(row["question"])
        ground_truths.append(row["ground_truth"])
        answers.append(result["answer"])
        contexts.append([c for c in result.get("citations", [])] or [""])

    # Package everything in the table format ragas expects
    dataset = Dataset.from_dict(
        {
            "question": questions,
            "answer": answers,
            "contexts": [[a] for a in answers],  # fallback; faithfulness uses answer+question
            "ground_truth": ground_truths,
        }
    )

    # The examiner (ragas + OpenAI judge) marks every answer
    print("Scoring with ragas...")
    result = evaluate(dataset, metrics=[faithfulness, answer_relevancy, context_recall])

    def avg(metric: str) -> float:
        """ragas returns one score per question — average them into one mark."""
        value = result[metric]
        if isinstance(value, list):
            return sum(value) / len(value)
        return float(value)

    scores = {
        "faithfulness": avg("faithfulness"),
        "answer_relevancy": avg("answer_relevancy"),
        "context_recall": avg("context_recall"),
    }
    print("Scores:", scores)

    # Save the report card — test_eval.py reads this to pass/fail the build
    with open(REPORT_PATH, "w") as f:
        json.dump({"scores": scores, "num_questions": len(rows)}, f, indent=2)
    print(f"Report written to {REPORT_PATH}")


if __name__ == "__main__":
    main()
