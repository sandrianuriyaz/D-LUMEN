from pathlib import Path
import rasterio
import numpy as np

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"

files = sorted(DATA_DIR.glob("VIIRS_Java_*.tif"))

print("=" * 50)
print("D-LUMEN - VALIDASI DATASET VIIRS")
print("=" * 50)

if not files:
    raise SystemExit("Tidak ada file VIIRS ditemukan di data/raw!")

print(f"Jumlah file ditemukan: {len(files)}")

for file in files:
    with rasterio.open(file) as src:
        if src.count != 2:
            print(f"[PERINGATAN] {file.name}: bukan 2 band")
            continue

        radiance = src.read(1, masked=True).filled(np.nan)
        coverage = src.read(2, masked=True).filled(np.nan)

        valid = (
            np.isfinite(radiance)
            & np.isfinite(coverage)
            & (coverage > 0)
            & (radiance >= 0)
        )

        values = radiance[valid]

        print(f"\nFile: {file.name}")
        print(f"Ukuran: {src.width} x {src.height}")
        print(f"CRS: {src.crs}")
        print(f"Piksel valid: {values.size:,}")

        if values.size:
            print(f"Rata-rata: {values.mean():.4f}")
            print(f"Minimum: {values.min():.4f}")
            print(f"Maksimum: {values.max():.4f}")
        else:
            print("Tidak ada piksel valid.")