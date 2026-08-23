import argparse
import json
import os
import time
from pathlib import Path
from statistics import mean
from typing import Any

from streamlit_app.client import ResearchApiClient

ROOT = Path(__file__).resolve().parent
MANUAL_METRICS = (
    "claim_accuracy",
    "citation_correctness",
    "contradiction_detection",
    "confidence_tier_quality",
)


def _manual_review_template() -> dict[str, float | None]:
    return dict.fromkeys(MANUAL_METRICS)


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [record for record in records if record.get("status") == "completed"]
    latencies = [float(record["latency_seconds"]) for record in completed]
    source_counts = [
        len({source["domain"] for source in record["report"].get("deduplicated_sources", [])})
        for record in completed
    ]
    cache_hits = [bool(record["report"].get("cache_hit", False)) for record in completed]

    manual: dict[str, dict[str, float | int | None]] = {}
    for metric in MANUAL_METRICS:
        scores = [
            float(record["manual_review"][metric])
            for record in completed
            if record.get("manual_review", {}).get(metric) is not None
        ]
        manual[metric] = {
            "rated_reports": len(scores),
            "average_score": round(mean(scores), 3) if scores else None,
        }

    return {
        "questions_run": len(records),
        "completed": len(completed),
        "average_latency_seconds": round(mean(latencies), 3) if latencies else None,
        "cache_hit_rate": round(mean(cache_hits), 3) if cache_hits else None,
        "average_independent_sources": round(mean(source_counts), 3) if source_counts else None,
        "reports_with_contradictions": sum(
            bool(record["report"].get("contradictions")) for record in completed
        ),
        "manual_metrics": manual,
        "note": (
            "Manual metric averages remain null until a reviewer scores each report from 0 to 1."
        ),
    }


def run(
    api: ResearchApiClient,
    questions: list[dict[str, str]],
    *,
    poll_seconds: float,
    timeout_seconds: float,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in questions:
        started_at = time.monotonic()
        started = api.start_research(item["question"])
        job_id = started["job_id"]
        deadline = started_at + timeout_seconds
        status = api.status(job_id)
        while status["status"] == "running" and time.monotonic() < deadline:
            time.sleep(poll_seconds)
            status = api.status(job_id)

        record: dict[str, Any] = {
            **item,
            "job_id": job_id,
            "status": status["status"],
            "latency_seconds": round(time.monotonic() - started_at, 3),
            "manual_review": _manual_review_template(),
        }
        if status["status"] == "completed":
            record["report"] = api.report(job_id)
        else:
            record["error"] = status.get("error") or "Evaluation polling timed out"
        records.append(record)
    return records


def _write_results(path: Path, records: list[dict[str, Any]]) -> None:
    payload = {"summary": summarize(records), "records": records}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run or summarize the 20-question evaluation set")
    parser.add_argument("--questions", type=Path, default=ROOT / "questions.json")
    parser.add_argument("--output", type=Path, default=ROOT / "results.json")
    parser.add_argument("--api-base", default=os.getenv("API_BASE_URL", "http://localhost:8000"))
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument(
        "--summarize-only",
        type=Path,
        help="Recalculate the summary after manually scoring an existing results file",
    )
    args = parser.parse_args()

    if args.summarize_only:
        existing = json.loads(args.summarize_only.read_text(encoding="utf-8"))
        _write_results(args.summarize_only, existing["records"])
        return

    token = os.getenv("EVALUATION_BEARER_TOKEN")
    if not token:
        parser.error("EVALUATION_BEARER_TOKEN is required to run live evaluation")
    questions = json.loads(args.questions.read_text(encoding="utf-8"))
    records = run(
        ResearchApiClient(args.api_base, token),
        questions,
        poll_seconds=args.poll_seconds,
        timeout_seconds=args.timeout_seconds,
    )
    _write_results(args.output, records)


if __name__ == "__main__":
    main()
