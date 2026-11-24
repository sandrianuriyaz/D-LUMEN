"""Safely create/upgrade the central master database schema."""
from pathlib import Path
from master.repository import connection


def main() -> None:
    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute(schema); conn.commit()
    print("Schema dlumen_db siap di Master (data lama tidak dihapus).")


if __name__ == "__main__": main()
