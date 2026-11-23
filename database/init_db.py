"""Safely create/upgrade the D-LUMEN database schema."""
from pathlib import Path

from parallel.db import connection


def main():
    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(schema)
        conn.commit()
    print("D-LUMEN schema siap (data lama tidak dihapus).")


if __name__ == "__main__":
    main()
