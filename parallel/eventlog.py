from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any


class EventLog:
    """Append-only JSONL audit log safe for concurrent Flask requests."""
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.lock = threading.Lock()

    def emit(self, event: str, **fields: Any) -> dict[str, Any]:
        record = {"timestamp": time.time(), "event": event, **fields}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock, self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, sort_keys=True, default=str) + "\n")
        return record

    def read(self, limit: int = 200) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()[-limit:]
        return [json.loads(line) for line in lines if line.strip()]
