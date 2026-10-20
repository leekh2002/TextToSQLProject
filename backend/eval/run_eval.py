from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv

from ..process import process
from .grading import classify_failure, grade_case

load_dotenv()  # load workspace .env if present
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)  # load backend/.env

GOLDEN_QUERIES_PATH = Path(__file__).with_name("golden_queries.json")
DEFAULT_REPORTS_DIR = Path(__file__).with_name("reports")


def _ensure_utf8_console() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if not stream or not hasattr(stream, "reconfigure"):
            continue
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def load_cases(path: Path = GOLDEN_QUERIES_PATH) -> list[dict]:
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def v1_pipeline(query, *, exclude_completed_courses=False, student_id=None, value_hints=None):
    # value_hints is ignored: v1 has no hint input. Looks up `process` at call time.
    return process(query, exclude_completed_courses=exclude_completed_courses, student_id=student_id)


PIPELINES: dict[str, Callable] = {"v1": v1_pipeline}


def _case_record(case: dict, ok: bool, reason: str | None, sql=None, error=None,
                 failure_type: str = "ok", latency_ms: int = 0, soft_f1=None) -> dict:
    return {
        "id": case["id"],
        "category": case["category"],
        "query": case["query"],
        "ok": ok,
        "reason": reason,
        "sql": sql,
        "reference_sql": case.get("reference_sql"),
        "error": error,
        "failure_type": failure_type,
        "latency_ms": latency_ms,
        "soft_f1": soft_f1,
        "empty_gold": bool(case.get("empty_gold", False)),
    }


def run_case(case: dict, pipeline: Callable | None = None, decoupled: bool = False) -> dict:
    pipeline = pipeline or PIPELINES["v1"]
    hints = case.get("gold_values") if decoupled else None
    started = time.perf_counter()
    try:
        result = pipeline(
            case["query"],
            exclude_completed_courses=case.get("exclude_completed_courses", False),
            student_id=case.get("student_id"),
            value_hints=hints,
        )
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return _case_record(case, ok=False, reason=f"파이프라인 실행 중 예외 발생: {exc}",
                            failure_type="exception", latency_ms=latency_ms)
    latency_ms = int((time.perf_counter() - started) * 1000)

    warning = result.get("warning") if isinstance(result, dict) else None
    if isinstance(warning, str) and warning.startswith("DATABASE_URL is not set"):
        return _case_record(
            case, ok=False,
            reason=f"DATABASE_URL이 설정되지 않아 SQL-only 모드로 동작했습니다: {warning}",
            sql=result.get("sql"), failure_type="exception", latency_ms=latency_ms,
        )

    try:
        grade = grade_case(case, result)
    except Exception as exc:
        grade = {"ok": False, "reason": f"채점 중 예외 발생: {exc}"}

    return _case_record(
        case,
        ok=grade["ok"],
        reason=grade["reason"],
        sql=result.get("sql"),
        error=result.get("error"),
        failure_type=classify_failure(case, result, grade),
        latency_ms=latency_ms,
        soft_f1=grade.get("soft_f1"),
    )


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(p / 100 * len(ordered)) - 1)
    return ordered[index]


def _accuracy(items: list[dict]) -> dict:
    passed = sum(1 for item in items if item["ok"])
    return {
        "passed": passed,
        "total": len(items),
        "accuracy": round(100 * passed / len(items), 1) if items else 0.0,
    }


def summarize(records: list[dict]) -> dict:
    scored = [record for record in records if not record.get("empty_gold")]
    empty = [record for record in records if record.get("empty_gold")]

    by_category: dict[str, list[dict]] = defaultdict(list)
    for record in scored:
        by_category[record["category"]].append(record)

    failure_types: dict[str, int] = defaultdict(int)
    for record in records:
        failure_types[record.get("failure_type", "ok")] += 1

    latencies = [record["latency_ms"] for record in records if record.get("latency_ms") is not None]
    f1_values = [record["soft_f1"] for record in records if record.get("soft_f1") is not None]

    return {
        "overall": _accuracy(scored),
        "by_category": {category: _accuracy(items) for category, items in sorted(by_category.items())},
        "empty_gold": {"passed": sum(1 for r in empty if r["ok"]), "total": len(empty)},
        "failure_types": dict(sorted(failure_types.items())),
        "latency_ms": {"p50": percentile(latencies, 50), "p95": percentile(latencies, 95)},
        "mean_soft_f1": round(sum(f1_values) / len(f1_values), 4) if f1_values else None,
    }


def collect_config(pipeline_name: str, decoupled: bool) -> dict:
    env = {key: value for key, value in sorted(os.environ.items()) if key.startswith("T2S_")}
    if "OLLAMA_MODEL" in os.environ:
        env["OLLAMA_MODEL"] = os.environ["OLLAMA_MODEL"]
    return {"pipeline": pipeline_name, "decoupled": decoupled, "env": env}


def print_report(summary: dict, records: list[dict]) -> None:
    print("=== 카테고리별 정확도 ===")
    for category, stats in summary["by_category"].items():
        print(f"{category:<28} {stats['passed']:>3}/{stats['total']:<3} ({stats['accuracy']}%)")
    print("-" * 55)
    overall = summary["overall"]
    print(f"{'전체':<28} {overall['passed']:>3}/{overall['total']:<3} ({overall['accuracy']}%)")
    print(f"{'빈 정답(별도)':<28} {summary['empty_gold']['passed']:>3}/{summary['empty_gold']['total']:<3}")
    print(f"실패 유형: {summary['failure_types']}")
    print(f"응답 시간 p50={summary['latency_ms']['p50']}ms p95={summary['latency_ms']['p95']}ms")
    print(f"평균 Soft-F1: {summary['mean_soft_f1']}")

    failures = [record for record in records if not record["ok"]]
    if failures:
        print("\n=== 실패 케이스 ===")
        for record in failures:
            print(f"[{record['id']}] {record['query']}")
            print(f"  reason: {record['reason']}")
            print(f"  sql: {record['sql']}")
            if record.get("reference_sql"):
                print(f"  reference_sql: {record['reference_sql']}")
            if record.get("error"):
                print(f"  error: {record['error']}")


def write_report_file(summary: dict, records: list[dict], report_dir: Path, config: dict | None = None) -> Path:
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = report_dir / f"{timestamp}.json"
    with open(report_path, "w", encoding="utf-8") as file:
        json.dump({"config": config or {}, "summary": summary, "records": records}, file, ensure_ascii=False, indent=2)
    return report_path


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_console()
    parser = argparse.ArgumentParser(description="Text-to-SQL 골든 평가셋 실행기")
    parser.add_argument("--filter", default=None, help="이 문자열을 포함하는 category만 실행")
    parser.add_argument(
        "--min-accuracy",
        type=float,
        default=None,
        help="전체 정확도가 이 값(0-100) 미만이면 종료 코드 1",
    )
    parser.add_argument(
        "--report-dir",
        default=str(DEFAULT_REPORTS_DIR),
        help="JSON 리포트 저장 디렉터리",
    )
    parser.add_argument("--pipeline", default="v1", choices=sorted(PIPELINES), help="평가할 파이프라인")
    parser.add_argument("--decoupled", action="store_true", help="정답 값 힌트(gold_values)를 주입해 생성 단계만 평가")
    args = parser.parse_args(argv)

    cases = load_cases(GOLDEN_QUERIES_PATH)
    if args.filter:
        cases = [case for case in cases if args.filter in case["category"]]

    if not cases:
        print("실행할 케이스가 없습니다.")
        return 1

    records = [run_case(case, PIPELINES[args.pipeline], args.decoupled) for case in cases]
    summary = summarize(records)
    print_report(summary, records)

    report_path = write_report_file(
        summary, records, Path(args.report_dir), config=collect_config(args.pipeline, args.decoupled)
    )
    print(f"\n리포트 저장: {report_path}")

    if args.min_accuracy is not None and summary["overall"]["accuracy"] < args.min_accuracy:
        print(f"\n전체 정확도 {summary['overall']['accuracy']}% < 기준 {args.min_accuracy}% -> FAIL")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
