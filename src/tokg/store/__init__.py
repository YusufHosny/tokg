# ABOUTME: Persistence backends behind the GraphStore interface.
from tokg.store.base import GraphStore
from tokg.store.memory import MemoryStore

__all__ = ["GraphStore", "MemoryStore"]
