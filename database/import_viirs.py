"""Bulk-load preprocessed VIIRS summaries into the master's PostgreSQL."""
from __future__ import annotations
import csv
import io
import json
from pathlib import Path
from master.repository import connection

BASE_DIR = Path(__file__).resolve().parents[1]
JSON_FILE = BASE_DIR / "data" / "processed" / "viirs_summary.json"
COLUMNS = ("year", "month", "filename", "valid_pixels", "mean_radiance",
           "min_radiance", "max_radiance", "sum_radiance")


def main() -> None:
    if not JSON_FILE.exists():
        raise SystemExit(f"{JSON_FILE} tidak ditemukan; jalankan preprocessing.viirs_processor")
    records = json.loads(JSON_FILE.read_text(encoding="utf-8"))
    if not isinstance(records, list) or not records:
        raise SystemExit("Ringkasan VIIRS kosong atau tidak valid")
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerows([[row[column] for column in COLUMNS] for row in records])
    buffer.seek(0)
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute("CREATE TEMP TABLE viirs_import (LIKE viirs_monthly INCLUDING DEFAULTS) ON COMMIT DROP")
        cursor.copy_expert(f"COPY viirs_import ({','.join(COLUMNS)}) FROM STDIN WITH (FORMAT CSV)", buffer)
        cursor.execute(f"""INSERT INTO viirs_monthly ({','.join(COLUMNS)})
            SELECT {','.join(COLUMNS)} FROM viirs_import
            ON CONFLICT (year, month) DO UPDATE SET
              filename=EXCLUDED.filename, valid_pixels=EXCLUDED.valid_pixels,
              mean_radiance=EXCLUDED.mean_radiance, min_radiance=EXCLUDED.min_radiance,
              max_radiance=EXCLUDED.max_radiance, sum_radiance=EXCLUDED.sum_radiance""")
        conn.commit()
    print(f"COPY/upsert selesai: {len(records)} bulan dimuat ke dlumen_db")


if __name__ == "__main__": main()
