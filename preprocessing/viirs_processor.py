
from pathlib import Path
import json
import numpy as np
import rasterio

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data" / "raw"
OUTPUT_DIR = BASE_DIR / "data" / "processed"


def process_viirs():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    files = sorted(DATA_DIR.glob("VIIRS_Java_*.tif"))

    if not files:
        raise FileNotFoundError(
            "Tidak ada file VIIRS di data/raw"
        )

    results = []

    for file in files:
        print(f"Memproses: {file.name}")

        with rasterio.open(file) as src:
            if src.count != 2:
                print(f"SKIP: {file.name} bukan 2 band")
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

            if values.size == 0:
                print(f"SKIP: {file.name} tidak ada piksel valid")
                continue

            parts = file.stem.split("_")
            year = int(parts[2])
            month = int(parts[3])

            result = {
                "year": year,
                "month": month,
                "filename": file.name,
                "valid_pixels": int(values.size),
                "mean_radiance": float(np.mean(values)),
                "min_radiance": float(np.min(values)),
                "max_radiance": float(np.max(values)),
                "sum_radiance": float(np.sum(values))
            }

            results.append(result)

            print(
                f"  Rata-rata: {result['mean_radiance']:.4f}"
            )

    output_file = OUTPUT_DIR / "viirs_summary.json"

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print("\n================================")
    print("D-LUMEN PREPROCESSING SELESAI")
    print(f"Total file diproses: {len(results)}")
    print(f"Hasil: {output_file}")
    print("================================")

    return results


if __name__ == "__main__":
    process_viirs()