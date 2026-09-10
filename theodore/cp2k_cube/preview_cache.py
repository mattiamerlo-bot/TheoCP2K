"""Memory-bounded cache for downsampled NTO cube previews."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path


class NTOPreviewCache:
    """Keep recently used previews while detecting changed cube files."""

    def __init__(self, max_bytes=256 * 1024 * 1024):
        self.max_bytes = int(max_bytes)
        if self.max_bytes < 1:
            raise ValueError("La dimensione massima della cache deve essere positiva.")
        self._items = OrderedDict()
        self._bytes = 0

    @staticmethod
    def _key(assignment, resolution):
        path = Path(assignment.path).expanduser().resolve()
        stat = path.stat()
        return str(path), int(resolution), int(stat.st_size), int(stat.st_mtime_ns)

    @staticmethod
    def _preview_bytes(preview):
        return int(preview.values.nbytes)

    @property
    def bytes_used(self):
        return self._bytes

    def __len__(self):
        return len(self._items)

    def get(self, assignment, resolution):
        key = self._key(assignment, resolution)
        item = self._items.get(key)
        if item is None:
            return None
        self._items.move_to_end(key)
        return item

    def put(self, assignment, resolution, preview):
        key = self._key(assignment, resolution)
        size = self._preview_bytes(preview)
        previous = self._items.pop(key, None)
        if previous is not None:
            self._bytes -= self._preview_bytes(previous)

        while self._items and self._bytes + size > self.max_bytes:
            _, discarded = self._items.popitem(last=False)
            self._bytes -= self._preview_bytes(discarded)

        if size <= self.max_bytes:
            self._items[key] = preview
            self._bytes += size

    def clear(self):
        self._items.clear()
        self._bytes = 0
