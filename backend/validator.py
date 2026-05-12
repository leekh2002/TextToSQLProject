def validate_sql(sql):
    s = sql.lower()

    if not s.startswith("select"):
        raise Exception("SELECT only")

    forbidden = ["insert", "delete", "update", "drop"]
    if any(f in s for f in forbidden):
        raise Exception("forbidden query")

    return True


def enforce_limit(sql):
    if "limit" not in sql.lower():
        sql += " LIMIT 50"
    return sql
