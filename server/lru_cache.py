"""
lru_cache.py
------------
A thread-safe LRU (Least Recently Used) cache built on OrderedDict,
used to cache GET responses and static file contents so repeated
requests skip disk reads / handler recomputation.
"""

import threading
from collections import OrderedDict


class LRUCache:
    def __init__(self, capacity: int = 128):
        self.capacity = capacity
        self._store = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key):
        with self._lock:
            if key not in self._store:
                self.misses += 1
                return None
            self._store.move_to_end(key)
            self.hits += 1
            return self._store[key]

    def put(self, key, value):
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            self._store[key] = value
            if len(self._store) > self.capacity:
                self._store.popitem(last=False)  # evict least-recently-used

    def clear(self):
        with self._lock:
            self._store.clear()
            self.hits = 0
            self.misses = 0

    def stats(self):
        with self._lock:
            total = self.hits + self.misses
            hit_rate = round((self.hits / total) * 100, 2) if total else 0.0
            return {
                "capacity": self.capacity,
                "size": len(self._store),
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate_pct": hit_rate,
                "keys": list(self._store.keys()),
            }
