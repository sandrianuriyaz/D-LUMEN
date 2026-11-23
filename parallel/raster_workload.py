"""CPU/data-heavy VIIRS workload using real GeoTIFF pixels."""
from __future__ import annotations

import os
from pathlib import Path


def analyze_raster(params: dict) -> dict:
    try:
        import numpy as np
        import rasterio
    except ImportError as exc:
        raise RuntimeError("rasterio dan numpy wajib untuk raster_aggregate") from exc
    data_dir = Path(os.getenv("DLUMEN_DATA_DIR", Path(__file__).resolve().parents[1]/"data"/"raw"))
    start = params["start_year"]*100 + params["start_month"]
    end = params["end_year"]*100 + params["end_month"]
    files = []
    for path in sorted(data_dir.glob("VIIRS_Java_*.tif")):
        parts = path.stem.split("_")
        try: period = int(parts[-2])*100 + int(parts[-1])
        except (ValueError, IndexError): continue
        if start <= period <= end: files.append(path)
    if not files:
        raise FileNotFoundError(f"partisi raster {start}-{end} tidak tersedia di {data_dir}")
    pixels, total, low, high = 0, 0.0, None, None
    histogram = np.zeros(64, dtype=np.int64)
    for path in files:
        with rasterio.open(path) as src:
            if src.count < 2: raise ValueError(f"{path.name} tidak memiliki band coverage")
            for _, window in src.block_windows(1):
                radiance = src.read(1, window=window, masked=True).filled(np.nan)
                coverage = src.read(2, window=window, masked=True).filled(np.nan)
                valid = np.isfinite(radiance) & np.isfinite(coverage) & (coverage > 0) & (radiance >= 0)
                values = radiance[valid].astype(np.float64, copy=False)
                if not values.size: continue
                pixels += int(values.size); total += float(values.sum(dtype=np.float64))
                block_low, block_high = float(values.min()), float(values.max())
                low = block_low if low is None else min(low, block_low)
                high = block_high if high is None else max(high, block_high)
                histogram += np.histogram(np.clip(values, 0, 64), bins=64, range=(0, 64))[0]
    return {"months": len(files), "valid_pixels": pixels, "sum_radiance": total,
            "min_radiance": low, "max_radiance": high, "histogram_0_64": histogram.tolist()}
