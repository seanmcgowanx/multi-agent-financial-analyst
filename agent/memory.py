"""Read and save bounded lessons with atomic local file updates."""

import os
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from agent.providers import ticker_symbol
from agent.runtime import check_prose
from agent.schemas import Lesson, MemoryDocument


class MemoryFailure(Exception):
    """Describe a storage problem without exposing file contents."""


class PersistentMemory:
    """Keep the most recent lessons in a small JSON file."""

    def __init__(self, path: Path, lock_timeout: float = 2):
        self.path = Path(path).absolute()
        self.lock_timeout = lock_timeout

    def _read(self) -> MemoryDocument:
        """Preserve a corrupt or oversized file instead of replacing it."""
        try:
            if self.path.is_symlink():
                raise MemoryFailure("The memory file must not be a link.")
            if not self.path.exists():
                return MemoryDocument()
            with self.path.open("rb") as stream:
                data = stream.read(256001)
            if len(data) > 256000:
                raise MemoryFailure("The memory file exceeds the size limit.")
            return MemoryDocument.model_validate_json(data)
        except (OSError, ValueError, ValidationError):
            raise MemoryFailure("The memory file could not be read.") from None

    # REQUIREMENT: Reuse brief lessons across research runs.
    def load_lessons(self, ticker: str, limit: int = 5) -> list[Lesson]:
        """Load recent lessons for the same validated ticker."""
        symbol = ticker_symbol(ticker)
        if type(limit) is not int or not 1 <= limit <= 10:
            raise ValueError("The memory limit must be from one to ten.")
        document = self._read()
        return [item for item in document.lessons if item.ticker == symbol][
            -limit:
        ]

    @contextmanager
    def _lock(self):
        """Prevent concurrent writers from losing each other changes."""
        lock = self.path.with_name(self.path.name + ".lock")
        acquired = False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            deadline = time.monotonic() + self.lock_timeout
            while not acquired:
                try:
                    descriptor = os.open(
                        lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
                    )
                    os.close(descriptor)
                    acquired = True
                except FileExistsError:
                    if time.monotonic() >= deadline:
                        raise MemoryFailure("The memory file is busy.")
                    time.sleep(0.02)
            yield
        except OSError:
            raise MemoryFailure(
                "The memory file could not be updated."
            ) from None
        finally:
            if acquired:
                try:
                    lock.unlink()
                except OSError:
                    pass

    def save_lessons(
        self, ticker: str, texts: list[str], outcome: str, run_id: str
    ) -> list[Lesson]:
        """Save at most three deduplicated lessons and retain 100 total."""
        symbol = ticker_symbol(ticker)
        if not 1 <= len(texts) <= 3:
            raise ValueError("Save one to three lessons at a time.")
        saved = []
        for text in dict.fromkeys(texts):
            check_prose(text)
            saved.append(
                Lesson(
                    id=str(uuid4()),
                    run_id=run_id,
                    ticker=symbol,
                    text=text.strip(),
                    outcome=outcome,
                    created_at=datetime.now(timezone.utc),
                )
            )
        with self._lock():
            document = self._read()
            keys = {(item.ticker, item.text.casefold()) for item in saved}
            retained = [
                item
                for item in document.lessons
                if (item.ticker, item.text.casefold()) not in keys
            ]
            updated = MemoryDocument(lessons=(retained + saved)[-100:])
            encoded = updated.model_dump_json(indent=2)
            if len(encoded.encode("utf-8")) > 256000:
                raise MemoryFailure("The memory file exceeds the size limit.")
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=self.path.parent,
                    prefix=".lessons-",
                    suffix=".tmp",
                    delete=False,
                ) as stream:
                    temporary = Path(stream.name)
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        return saved
