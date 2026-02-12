from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Callable

from filelock import FileLock


class JsonlStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(str(path) + ".lock")
        if not self.path.exists():
            self.path.touch()

    def read_all(self) -> list[dict]:
        with self.lock:
            return self._read_all_unlocked()

    def append(self, record: dict) -> None:
        line = json.dumps(record, ensure_ascii=True)
        with self.lock:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")

    def upsert(self, key: str, value: str, new_record: dict) -> None:
        with self.lock:
            rows = self._read_all_unlocked()
            replaced = False
            for idx, row in enumerate(rows):
                if row.get(key) == value:
                    rows[idx] = new_record
                    replaced = True
                    break
            if not replaced:
                rows.append(new_record)
            self._atomic_rewrite(rows)

    def delete_where(self, predicate: Callable[[dict], bool]) -> int:
        with self.lock:
            rows = self._read_all_unlocked()
            kept = [r for r in rows if not predicate(r)]
            deleted = len(rows) - len(kept)
            if deleted:
                self._atomic_rewrite(kept)
            return deleted

    def find_one(self, key: str, value: str) -> dict | None:
        with self.lock:
            for row in self._read_all_unlocked():
                if row.get(key) == value:
                    return row
        return None

    def filter(self, predicate: Callable[[dict], bool]) -> list[dict]:
        with self.lock:
            return [r for r in self._read_all_unlocked() if predicate(r)]

    def compact(self) -> int:
        with self.lock:
            rows = self._read_all_unlocked()
            before = self.path.stat().st_size if self.path.exists() else 0
            self._atomic_rewrite(rows)
            after = self.path.stat().st_size if self.path.exists() else 0
        return max(before - after, 0)

    def _read_all_unlocked(self) -> list[dict]:
        rows: list[dict] = []
        if not self.path.exists():
            return rows
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
        return rows

    def _atomic_rewrite(self, rows: list[dict]) -> None:
        fd, tmp_name = tempfile.mkstemp(prefix=self.path.name + ".", dir=str(self.path.parent))
        os.close(fd)
        tmp_path = Path(tmp_name)
        try:
            with tmp_path.open("w", encoding="utf-8") as f:
                for row in rows:
                    f.write(json.dumps(row, ensure_ascii=True) + "\n")
            tmp_path.replace(self.path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
