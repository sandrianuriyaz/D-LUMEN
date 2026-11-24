"""Bulk-load monthly and spatial-grid VIIRS summaries into PostgreSQL."""
from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import Window

from master.repository import connection

BASE_DIR = Path(__file__).resolve().parents[1]
JSON_FILE = BASE_DIR / "data" / "processed" / "viirs_summary.json"
DATA_DIR = BASE_DIR / "data" / "raw"
MONTHLY_COLUMNS = ("year", "month", "filename", "valid_pixels", "mean_radiance",
                   "min_radiance", "max_radiance", "sum_radiance")
GRID_COLUMNS = ("year", "month", "filename", "row_off", "col_off", "width", "height",
                "valid_pixels", "mean_radiance", "min_radiance", "max_radiance", "sum_radiance")


def csv_buffer(rows, columns) -> io.StringIO:
    buffer = io.StringIO(); writer = csv.writer(buffer, lineterminator="\n")
    writer.writerows([[row[column] for column in columns] for row in rows]); buffer.seek(0)
    return buffer


def grid_rows(path: Path, size: int):
    parts = path.stem.split("_"); year, month = int(parts[-2]), int(parts[-1])
    with rasterio.open(path) as source:
        if source.count < 2:
            raise ValueError(f"{path.name} tidak memiliki band coverage")
        for row_off in range(0, source.height, size):
            for col_off in range(0, source.width, size):
                width, height = min(size, source.width-col_off), min(size, source.height-row_off)
                window = Window(col_off, row_off, width, height)
                radiance = source.read(1, window=window, masked=True).filled(np.nan)
                coverage = source.read(2, window=window, masked=True).filled(np.nan)
                valid = np.isfinite(radiance) & np.isfinite(coverage) & (coverage > 0) & (radiance >= 0)
                values = radiance[valid].astype(np.float64, copy=False)
                if not values.size:
                    continue
                yield {"year": year, "month": month, "filename": path.name,
                    "row_off": row_off, "col_off": col_off, "width": width, "height": height,
                    "valid_pixels": int(values.size), "mean_radiance": float(values.mean()),
                    "min_radiance": float(values.min()), "max_radiance": float(values.max()),
                    "sum_radiance": float(values.sum(dtype=np.float64))}


def import_monthly(cursor) -> int:
    if not JSON_FILE.exists():
        raise SystemExit(f"{JSON_FILE} tidak ditemukan; jalankan preprocessing.viirs_processor")
    records = json.loads(JSON_FILE.read_text(encoding="utf-8"))
    cursor.execute("CREATE TEMP TABLE viirs_import (LIKE viirs_monthly INCLUDING DEFAULTS) ON COMMIT DROP")
    cursor.copy_expert(f"COPY viirs_import ({','.join(MONTHLY_COLUMNS)}) FROM STDIN WITH (FORMAT CSV)",
                       csv_buffer(records, MONTHLY_COLUMNS))
    cursor.execute(f"""INSERT INTO viirs_monthly ({','.join(MONTHLY_COLUMNS)})
        SELECT {','.join(MONTHLY_COLUMNS)} FROM viirs_import
        ON CONFLICT (year, month) DO UPDATE SET filename=EXCLUDED.filename,
          valid_pixels=EXCLUDED.valid_pixels, mean_radiance=EXCLUDED.mean_radiance,
          min_radiance=EXCLUDED.min_radiance, max_radiance=EXCLUDED.max_radiance,
          sum_radiance=EXCLUDED.sum_radiance""")
    return len(records)


def import_grid(cursor, size: int) -> int:
    cursor.execute("CREATE TEMP TABLE viirs_grid_import (LIKE viirs_grid_chunks INCLUDING DEFAULTS) ON COMMIT DROP")
    total = 0
    for path in sorted(DATA_DIR.glob("VIIRS_Java_*.tif")):
        rows = list(grid_rows(path, size)); total += len(rows)
        cursor.copy_expert(f"COPY viirs_grid_import ({','.join(GRID_COLUMNS)}) FROM STDIN WITH (FORMAT CSV)",
                           csv_buffer(rows, GRID_COLUMNS))
        print(f"Grid {path.name}: {len(rows)} chunk")
    cursor.execute(f"""INSERT INTO viirs_grid_chunks ({','.join(GRID_COLUMNS)})
        SELECT {','.join(GRID_COLUMNS)} FROM viirs_grid_import
        ON CONFLICT (year, month, row_off, col_off) DO UPDATE SET
          filename=EXCLUDED.filename, width=EXCLUDED.width, height=EXCLUDED.height,
          valid_pixels=EXCLUDED.valid_pixels, mean_radiance=EXCLUDED.mean_radiance,
          min_radiance=EXCLUDED.min_radiance, max_radiance=EXCLUDED.max_radiance,
          sum_radiance=EXCLUDED.sum_radiance""")
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grid-size", type=int, default=64)
    parser.add_argument("--monthly-only", action="store_true")
    args = parser.parse_args()
    if args.grid_size < 16:
        raise SystemExit("--grid-size minimal 16")
    with connection() as conn, conn.cursor() as cursor:
        monthly = import_monthly(cursor)
        chunks = 0 if args.monthly_only else import_grid(cursor, args.grid_size)
        conn.commit()
    print(f"COPY/upsert selesai: {monthly} bulan, {chunks} grid chunk")


if __name__ == "__main__":
    main()
