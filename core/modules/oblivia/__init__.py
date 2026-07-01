"""Compatibility facade for the canonical :mod:`memory.oblivia` package."""

from memory.oblivia import (
    KnowledgeFact,
    ObliviaMemoryManager,
    MemoryRecord,
    MemoryQuery,
    MemorySearchResult,
    MemoryStatus,
    LifecycleKnowledgeFact,
    MemoryReasoner,
    PREDICATES,
    PredicateDefinition,
    TemporalLivesAtFact,
    get_predicate,
)

__all__ = [
    "ObliviaMemoryManager",
    "KnowledgeFact",
    "MemoryRecord",
    "MemoryQuery",
    "MemorySearchResult",
    "MemoryStatus",
    "LifecycleKnowledgeFact",
    "MemoryReasoner",
    "PREDICATES",
    "PredicateDefinition",
    "TemporalLivesAtFact",
    "get_predicate",
]
