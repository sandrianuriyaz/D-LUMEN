"""Create a local .env for one D-LUMEN node without exposing its token."""
from __future__ import annotations

import argparse
import getpass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKERS = ("fawwaz", "kenanga", "alif", "rama", "jamal", "zheka", "shafa", "raden", "ristin")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("name", choices=("sandria", *WORKERS), help="nama pemilik node")
    args = parser.parse_args()
    source = (ROOT / "deployment" / "master-sandria.env.example" if args.name == "sandria"
              else ROOT / "deployment" / "workers" / f"{args.name}.env.example")
    target = ROOT / ".env"
    token = getpass.getpass("Masukkan DLUMEN_TOKEN (tidak ditampilkan): ").strip()
    if not token:
        raise SystemExit("Token tidak boleh kosong")
    if target.exists():
        answer = input(f"{target} sudah ada. Timpa? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            raise SystemExit("Dibatalkan; .env lama tidak berubah")
    content = source.read_text(encoding="utf-8").replace("GANTI_DENGAN_TOKEN_YANG_SAMA", token)
    target.write_text(content, encoding="utf-8")
    role = "Master" if args.name == "sandria" else "Worker"
    print(f"Konfigurasi {role} {args.name} tersimpan di {target}")


if __name__ == "__main__":
    main()
