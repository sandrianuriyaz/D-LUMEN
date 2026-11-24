"""PostgreSQL access used exclusively by the master node."""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any


def load_project_env() -> None:
    """Load simple KEY=VALUE settings without requiring python-dotenv."""
    path = Path(__file__).resolve().parents[1] / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_project_env()


def database_config() -> dict[str, Any]:
    config: dict[str, Any] = {
        "dbname": os.getenv("DLUMEN_DB_NAME", "dlumen_db"),
        "user": os.getenv("DLUMEN_DB_USER", "postgres"),
        "host": os.getenv("DLUMEN_DB_HOST", "127.0.0.1"),
        "port": os.getenv("DLUMEN_DB_PORT", "5432"),
        "connect_timeout": 10,
    }
    if os.getenv("DLUMEN_DB_PASSWORD"):
        config["password"] = os.environ["DLUMEN_DB_PASSWORD"]
    return config


@contextmanager
def connection():
    try:
        import psycopg2
    except ImportError as exc:
        raise RuntimeError("psycopg2 wajib dipasang hanya pada Master") from exc
    conn = psycopg2.connect(**database_config())
    try:
        yield conn
    finally:
        conn.close()


class ViirsRepository:
    """Reads JSON-safe monthly or spatial-grid payloads from PostgreSQL."""

    COLUMNS = ("year", "month", "valid_pixels", "mean_radiance", "min_radiance",
               "max_radiance", "sum_radiance")
    GRID_COLUMNS = ("year", "month", "row_off", "col_off", "valid_pixels",
                    "mean_radiance", "min_radiance", "max_radiance", "sum_radiance")

    def payload(self, params: dict[str, Any]) -> dict[str, Any]:
        start = int(params["start_year"]) * 100 + int(params["start_month"])
        end = int(params["end_year"]) * 100 + int(params["end_month"])
        mode = params.get("payload_mode", "grid")
        with connection() as conn, conn.cursor() as cursor:
            rows = []
            if mode == "grid":
                cursor.execute(
                    """SELECT year, month, row_off, col_off, valid_pixels,
                              mean_radiance, min_radiance, max_radiance, sum_radiance
                       FROM viirs_grid_chunks
                       WHERE (year * 100 + month) BETWEEN %s AND %s
                       ORDER BY year, month, row_off, col_off""", (start, end))
                rows = [dict(zip(self.GRID_COLUMNS, row)) for row in cursor.fetchall()]
            if not rows:
                mode = "monthly"
                cursor.execute(
                    """SELECT year, month, valid_pixels, mean_radiance, min_radiance,
                              max_radiance, sum_radiance
                       FROM viirs_monthly
                       WHERE (year * 100 + month) BETWEEN %s AND %s
                       ORDER BY year, month""", (start, end))
                rows = [dict(zip(self.COLUMNS, row)) for row in cursor.fetchall()]
        return {"mode": mode,
                "records": [{k: self._json(v) for k, v in row.items()} for row in rows]}

    @staticmethod
    def _json(value: Any) -> Any:
        return float(value) if value is not None and value.__class__.__module__ == "decimal" else value
