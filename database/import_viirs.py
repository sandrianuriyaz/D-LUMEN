import json
import os
from pathlib import Path

import psycopg2

BASE_DIR = Path(__file__).resolve().parents[1]
JSON_FILE = BASE_DIR / "data" / "processed" / "viirs_summary.json"

DB_HOST = os.getenv("DLUMEN_DB_HOST", "/tmp")
DB_PORT = os.getenv("DLUMEN_DB_PORT", "5432")
DB_NAME = os.getenv("DLUMEN_DB_NAME", "dlumen_db")
DB_USER = os.getenv("DLUMEN_DB_USER", "sandrianuriya")

if not JSON_FILE.exists():
    raise SystemExit(
        f"File tidak ditemukan: {JSON_FILE}\n"
        "Jalankan viirs_processor.py terlebih dahulu."
    )

with open(JSON_FILE, "r", encoding="utf-8") as f:
    records = json.load(f)

if not isinstance(records, list) or not records:
    raise SystemExit("Data JSON kosong atau format tidak sesuai.")

password = os.getenv("DLUMEN_DB_PASSWORD")

conn = psycopg2.connect(
    host=DB_HOST,
    port=DB_PORT,
    dbname=DB_NAME,
    user=DB_USER,
    connect_timeout=10
    , **({"password": password} if password else {})
)

try:
    with conn:
        with conn.cursor() as cur:
            for row in records:
                cur.execute(
                    """
                    INSERT INTO viirs_monthly (
                        year,
                        month,
                        filename,
                        valid_pixels,
                        mean_radiance,
                        min_radiance,
                        max_radiance,
                        sum_radiance
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (year, month)
                    DO UPDATE SET
                        filename = EXCLUDED.filename,
                        valid_pixels = EXCLUDED.valid_pixels,
                        mean_radiance = EXCLUDED.mean_radiance,
                        min_radiance = EXCLUDED.min_radiance,
                        max_radiance = EXCLUDED.max_radiance,
                        sum_radiance = EXCLUDED.sum_radiance
                    """,
                    (
                        row["year"],
                        row["month"],
                        row["filename"],
                        row["valid_pixels"],
                        row["mean_radiance"],
                        row["min_radiance"],
                        row["max_radiance"],
                        row["sum_radiance"]
                    )
                )

    print("=" * 45)
    print("D-LUMEN - IMPORT DATABASE BERHASIL")
    print("=" * 45)
    print("Database :", DB_NAME)
    print("Port     :", DB_PORT)
    print("Data JSON:", len(records))

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM viirs_monthly")
        total = cur.fetchone()[0]

    print("Total baris database:", total)

finally:
    conn.close()
