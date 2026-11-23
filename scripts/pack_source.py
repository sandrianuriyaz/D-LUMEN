"""Build a secret-free submission ZIP and verify its contents."""
from __future__ import annotations

import argparse
import compileall
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache", "raw", "runtime", "dist"}
EXCLUDED_FILES = {".env", ".DS_Store"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".tif", ".tiff"}


def included(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    return (path.is_file() and path.name not in EXCLUDED_FILES
            and not any(part in EXCLUDED_DIRS for part in relative.parts)
            and path.suffix.lower() not in EXCLUDED_SUFFIXES)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--output")
    args = parser.parse_args(); stamp = time.strftime("%Y%m%d-%H%M%S")
    output = Path(args.output) if args.output else ROOT/"dist"/f"D-LUMEN-source-{stamp}.zip"
    output.parent.mkdir(parents=True, exist_ok=True)
    files = sorted(path for path in ROOT.rglob("*") if included(path))
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files: archive.write(path, Path("D-LUMEN")/path.relative_to(ROOT))
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        assert not any(name.endswith("/.env") or "/.venv/" in name for name in names)
        assert "D-LUMEN/README.md" in names and "D-LUMEN/.env.example" in names
        bad = archive.testzip(); assert bad is None, bad
    print(f"PACKAGE OK: {output} ({len(files)} files, {output.stat().st_size} bytes)")


if __name__ == "__main__": main()
