# Konfigurasi 10 Node D-LUMEN

Topologi:

| Peran | ID node | Alamat Master |
|---|---|---|
| Master | `sandria` | `192.168.100.92:5050` |
| Worker 1 | `fawwaz` | `http://192.168.100.92:5050` |
| Worker 2 | `kenanga` | `http://192.168.100.92:5050` |
| Worker 3 | `alif` | `http://192.168.100.92:5050` |
| Worker 4 | `rama` | `http://192.168.100.92:5050` |
| Worker 5 | `jamal` | `http://192.168.100.92:5050` |
| Worker 6 | `zheka` | `http://192.168.100.92:5050` |
| Worker 7 | `shafa` | `http://192.168.100.92:5050` |
| Worker 8 | `raden` | `http://192.168.100.92:5050` |
| Worker 9 | `ristin` | `http://192.168.100.92:5050` |

## Master Sandria

Salin `deployment/master-sandria.env.example` menjadi `.env`, lalu ganti
`GANTI_DENGAN_TOKEN_YANG_SAMA` dengan token rahasia.

```bash
cp deployment/master-sandria.env.example .env
source .venv/bin/activate
python -m database.init_db
python -m database.import_viirs
python -m master.master_server
```

## Worker

Setiap pemilik Worker melakukan clone dan setup:

```bash
git clone https://github.com/sandrianuriyaz/D-LUMEN.git
cd D-LUMEN
```

Cara termudah membuat `.env` (token dimasukkan secara tersembunyi):

```bash
python scripts/configure_node.py NAMA
```

Contoh: `python scripts/configure_node.py fawwaz`. Setelah itu gunakan launcher sesuai OS.

### Windows PowerShell

Ganti `NAMA` sesuai pemilik perangkat.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_node.ps1 -Role worker
& ".venv\Scripts\python.exe" scripts/configure_node.py NAMA
powershell -ExecutionPolicy Bypass -File scripts/start_worker.ps1
```

### macOS/Linux

```bash
chmod +x scripts/*.sh
./scripts/setup_node.sh worker
.venv/bin/python scripts/configure_node.py NAMA
./scripts/start_worker.sh
```

Worker tidak menjalankan PostgreSQL dan tidak membutuhkan folder `data/raw`.

## Pemeriksaan dari Master

```bash
curl http://127.0.0.1:5050/health
curl http://127.0.0.1:5050/metrics
```

Semua nama berikut harus terlihat dengan `online: true`: `fawwaz`, `kenanga`,
`alif`, `rama`, `jamal`, `zheka`, `shafa`, `raden`, dan `ristin`.
