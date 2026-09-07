from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from ..process import process
from .grading import grade_case

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


def run_case(case: dict) -> dict:
    result = process(
        case["query"],
        exclude_completed_courses=case.get("exclude_completed_courses", False),
        student_id=case.get("student_id"),
    )
    try:
        grade = grade_case(case, result)
    except Exception as exc:
        grade = {"ok": False, "reason": f"채점 중 예외 발생: {exc}"}

    return {
        "id": case["id"],
        "category": case["category"],
        "query": case["query"],
        "ok": grade["ok"],
        "reason": grade["reason"],
        "sql": result.get("sql"),
        "reference_sql": case.get("reference_sql"),
        "error": result.get("error"),
    }


def summarize(records: list[dict]) -> dict:
    by_category: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        by_category[record["category"]].append(record)

    category_summary = {}
    for category, items in sorted(by_category.items()):
        passed = sum(1 for item in items if item["ok"])
        category_summary[category] = {
            "passed": passed,
            "total": len(items),
            "accuracy": round(100 * passed / len(items), 1) if items else 0.0,
        }

    total_passed = sum(1 for record in records if record["ok"])
    total = len(records)
    overall_accuracy = round(100 * total_passed / total, 1) if total else 0.0

    return {
        "overall": {"passed": total_passed, "total": total, "accuracy": overall_accuracy},
        "by_category": category_summary,
    }


def print_report(summary: dict, records: list[dict]) -> None:
    print("=== 카테고리별 정확도 ===")
    for category, stats in summary["by_category"].items():
        print(f"{category:<28} {stats['passed']:>3}/{stats['total']:<3} ({stats['accuracy']}%)")
    print("-" * 55)
    overall = summary["overall"]
    print(f"{'전체':<28} {overall['passed']:>3}/{overall['total']:<3} ({overall['accuracy']}%)")

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


def write_report_file(summary: dict, records: list[dict], report_dir: Path) -> Path:
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = report_dir / f"{timestamp}.json"
    with open(report_path, "w", encoding="utf-8") as file:
        json.dump({"summary": summary, "records": records}, file, ensure_ascii=False, indent=2)
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
    args = parser.parse_args(argv)

    cases = load_cases(GOLDEN_QUERIES_PATH)
    if args.filter:
        cases = [case for case in cases if args.filter in case["category"]]

    if not cases:
        print("실행할 케이스가 없습니다.")
        return 1

    records = [run_case(case) for case in cases]
    summary = summarize(records)
    print_report(summary, records)

    report_path = write_report_file(summary, records, Path(args.report_dir))
    print(f"\n리포트 저장: {report_path}")

    if args.min_accuracy is not None and summary["overall"]["accuracy"] < args.min_accuracy:
        print(f"\n전체 정확도 {summary['overall']['accuracy']}% < 기준 {args.min_accuracy}% -> FAIL")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
