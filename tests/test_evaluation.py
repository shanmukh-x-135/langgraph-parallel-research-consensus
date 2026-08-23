import json
from pathlib import Path

from evaluation.run_evaluation import summarize


def test_evaluation_set_has_twenty_unique_diverse_questions():
    path = Path(__file__).parents[1] / "evaluation" / "questions.json"
    questions = json.loads(path.read_text(encoding="utf-8"))

    assert len(questions) == 20
    assert len({item["id"] for item in questions}) == 20
    assert len({item["question"] for item in questions}) == 20
    assert {item["category"] for item in questions} == {
        "settled",
        "academic",
        "current",
        "contested",
        "source_diversity",
    }


def test_summary_reports_automated_metrics_without_inventing_review_scores():
    records = [
        {
            "status": "completed",
            "latency_seconds": 2.0,
            "report": {
                "cache_hit": True,
                "deduplicated_sources": [{"domain": "one.example"}],
                "contradictions": [],
            },
            "manual_review": {"claim_accuracy": None},
        },
        {
            "status": "completed",
            "latency_seconds": 4.0,
            "report": {
                "cache_hit": False,
                "deduplicated_sources": [
                    {"domain": "one.example"},
                    {"domain": "two.example"},
                ],
                "contradictions": [{"disputed_claim": "A disputed point"}],
            },
            "manual_review": {"claim_accuracy": 0.75},
        },
    ]

    summary = summarize(records)

    assert summary["average_latency_seconds"] == 3.0
    assert summary["cache_hit_rate"] == 0.5
    assert summary["average_independent_sources"] == 1.5
    assert summary["reports_with_contradictions"] == 1
    assert summary["manual_metrics"]["claim_accuracy"] == {
        "rated_reports": 1,
        "average_score": 0.75,
    }
    assert summary["manual_metrics"]["citation_correctness"]["average_score"] is None
