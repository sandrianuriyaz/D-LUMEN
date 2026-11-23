from __future__ import annotations

import os
from contextlib import contextmanager


def config() -> dict:
    cfg = {"dbname": os.getenv("DLUMEN_DB_NAME", "dlumen_db"),
           "user": os.getenv("DLUMEN_DB_USER", "postgres"),
           "host": os.getenv("DLUMEN_DB_HOST", "127.0.0.1"),
           "port": os.getenv("DLUMEN_DB_PORT", "5432"), "connect_timeout": 10}
    if os.getenv("DLUMEN_DB_PASSWORD"):
        cfg["password"] = os.environ["DLUMEN_DB_PASSWORD"]
    return cfg


@contextmanager
def connection():
    try:
        import psycopg2
    except ImportError as exc:
        raise RuntimeError("psycopg2 belum terpasang") from exc
    conn = psycopg2.connect(**config())
    try:
        yield conn
    finally:
        conn.close()


def _period_clause(p: dict) -> tuple[str, list]:
    start = p.get("start_year", 1900) * 100 + p.get("start_month", 1)
    end = p.get("end_year", 9999) * 100 + p.get("end_month", 12)
    return "(year * 100 + month) BETWEEN %s AND %s", [start, end]


def execute_operation(operation: str, params: dict) -> dict:
    period_sql, values = _period_clause(params)
    filters = [period_sql]
    if params.get("min_mean") is not None:
        filters.append("mean_radiance >= %s"); values.append(params["min_mean"])
    if params.get("max_mean") is not None:
        filters.append("mean_radiance <= %s"); values.append(params["max_mean"])
    where = " AND ".join(filters)
    with connection() as conn, conn.cursor() as cur:
        if operation == "aggregate":
            cur.execute(f"""SELECT COUNT(*), COALESCE(SUM(valid_pixels),0),
              COALESCE(SUM(sum_radiance),0), MIN(min_radiance), MAX(max_radiance)
              FROM viirs_monthly WHERE {where}""", values)
            count, pixels, total, low, high = cur.fetchone()
            return {"months": count, "valid_pixels": int(pixels), "sum_radiance": float(total),
                    "min_radiance": float(low) if low is not None else None,
                    "max_radiance": float(high) if high is not None else None}
        if operation in ("search", "highest", "lowest"):
            order = "max_radiance DESC" if operation == "highest" else (
                "min_radiance ASC" if operation == "lowest" else "year, month")
            cur.execute(f"""SELECT year,month,filename,valid_pixels,mean_radiance,
              min_radiance,max_radiance,sum_radiance FROM viirs_monthly
              WHERE {where} ORDER BY {order} LIMIT %s""", values + [int(params.get("limit", 100))])
            columns = [d.name for d in cur.description]
            return {"rows": [dict(zip(columns, map(_json_value, row))) for row in cur.fetchall()]}
        if operation in ("annual", "trend"):
            cur.execute(f"""SELECT year, SUM(valid_pixels), SUM(sum_radiance),
              SUM(sum_radiance)/NULLIF(SUM(valid_pixels),0) FROM viirs_monthly
              WHERE {where} GROUP BY year ORDER BY year""", values)
            return {"annual": [{"year": r[0], "valid_pixels": int(r[1]),
                    "sum_radiance": float(r[2]), "mean_radiance": float(r[3])} for r in cur.fetchall()]}
    raise ValueError(f"operation tidak didukung: {operation}")


def _json_value(value):
    return float(value) if value is not None and value.__class__.__module__ == "decimal" else value
