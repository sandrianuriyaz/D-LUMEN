import json
import unittest
from pathlib import Path

from parallel.raster_workload import analyze_raster


class RasterWorkloadTests(unittest.TestCase):
    @unittest.skipUnless(Path("data/raw/VIIRS_Java_2020_01.tif").exists(), "dataset tidak tersedia")
    def test_real_pixels_match_preprocessed_summary(self):
        result = analyze_raster({"start_year": 2020, "start_month": 1, "end_year": 2020, "end_month": 1})
        summary = next(x for x in json.loads(Path("data/processed/viirs_summary.json").read_text())
                       if x["year"] == 2020 and x["month"] == 1)
        self.assertEqual(summary["valid_pixels"], result["valid_pixels"])
        self.assertAlmostEqual(summary["sum_radiance"], result["sum_radiance"], delta=0.1)
        self.assertEqual(64, len(result["histogram_0_64"]))


if __name__ == "__main__": unittest.main()
