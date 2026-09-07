from __future__ import annotations


def common_columns(rows_a: list[dict], rows_b: list[dict]) -> list[str]:
    if not rows_a or not rows_b:
        return []
    keys_a = set(rows_a[0].keys())
    keys_b = set(rows_b[0].keys())
    return sorted(keys_a & keys_b)


def project_rows(rows: list[dict], columns: list[str]) -> list[tuple]:
    return [tuple(row.get(column) for column in columns) for row in rows]


def compare_execution(
    reference_rows: list[dict],
    generated_rows: list[dict],
    order_sensitive: bool = False,
) -> tuple[bool, str | None]:
    if not reference_rows and not generated_rows:
        return True, None

    columns = common_columns(reference_rows, generated_rows)
    if not columns:
        reference_cols = sorted(reference_rows[0].keys()) if reference_rows else []
        generated_cols = sorted(generated_rows[0].keys()) if generated_rows else []
        return False, (
            f"컬럼이 겹치지 않습니다: reference={reference_cols}, generated={generated_cols}"
        )

    reference_projection = project_rows(reference_rows, columns)
    generated_projection = project_rows(generated_rows, columns)

    if order_sensitive:
        ok = reference_projection == generated_projection
    else:
        ok = set(reference_projection) == set(generated_projection)

    if ok:
        return True, None

    reference_set = set(reference_projection)
    generated_set = set(generated_projection)
    missing = reference_set - generated_set
    extra = generated_set - reference_set
    reason_parts = [f"reference={len(reference_rows)}행 vs generated={len(generated_rows)}행"]
    if missing:
        reason_parts.append(f"누락된 행 {len(missing)}개(예: {next(iter(missing))})")
    if extra:
        reason_parts.append(f"추가된 행 {len(extra)}개(예: {next(iter(extra))})")
    return False, "; ".join(reason_parts)
