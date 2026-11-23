import tempfile
import unittest
from pathlib import Path

from parallel.eventlog import EventLog


class EventLogTests(unittest.TestCase):
    def test_append_and_bounded_read(self):
        path = Path(tempfile.mkdtemp()) / "events.jsonl"
        log = EventLog(path)
        log.emit("one", value=1); log.emit("two", value=2)
        self.assertEqual("two", log.read(limit=1)[0]["event"])
        self.assertEqual(2, len(log.read()))


if __name__ == "__main__": unittest.main()
