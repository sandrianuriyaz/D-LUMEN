"""Validate grid aggregates against monthly source-of-truth records."""
from __future__ import annotations

from master.repository import connection


def main() -> None:
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute("""SELECT m.year, m.month, m.valid_pixels, COALESCE(SUM(g.valid_pixels), 0),
            m.sum_radiance, COALESCE(SUM(g.sum_radiance), 0), COUNT(g.id)
            FROM viirs_monthly m JOIN viirs_grid_chunks g
              ON g.year=m.year AND g.month=m.month
            GROUP BY m.year,m.month,m.valid_pixels,m.sum_radiance ORDER BY m.year,m.month""")
        rows = cursor.fetchall()
    failures = []
    for year, month, monthly_pixels, grid_pixels, monthly_sum, grid_sum, chunks in rows:
        if monthly_pixels != grid_pixels or chunks == 0:
            failures.append(f"{year}-{month:02d}: pixels {monthly_pixels}!={grid_pixels}, chunks={chunks}")
        relative = abs(float(monthly_sum)-float(grid_sum)) / max(abs(float(monthly_sum)), 1.0)
        if relative > 1e-5:
            failures.append(f"{year}-{month:02d}: selisih sum {relative:.3e}")
    if failures:
        raise SystemExit("VALIDASI GRID GAGAL\n" + "\n".join(failures))
    grid_months = sum(row[-1] > 0 for row in rows)
    print(f"VALIDASI GRID OK: {grid_months} bulan, count/sum konsisten")


if __name__ == "__main__":
    main()
