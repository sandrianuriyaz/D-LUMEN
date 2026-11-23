# Strategi Pengujian

- Unit/API: `python -m pytest -q`.
- Quick gate: `python scripts/gate.py --quick`.
- Full gate: `python scripts/gate.py --workers 2`.
- E2E lokal: `python scripts/e2e_local.py --workers 2 --processes 2`.
- Readiness node: `python scripts/check_readiness.py --role master|worker`.

E2E menjalankan proses Master dan Worker nyata melalui loopback, memproses raster VIIRS 2020, lalu membandingkan bulan dan jumlah piksel dengan `viirs_summary.json`. E2E bukan bukti node fisik; bukti fisik harus direkam terpisah.

Sebelum demo, full gate harus mencetak `GATE OK`. Setelah deployment, validasi hasil sequential dan distributed mempunyai bulan serta `valid_pixels` identik dan toleransi floating-point yang wajar untuk `sum_radiance`.
