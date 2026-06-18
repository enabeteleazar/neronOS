from fastapi import APIRouter

from .manager import ObliviaMemoryManager
from .schemas import MemoryQuery, MemoryRecord

router = APIRouter(prefix="/memory", tags=["memory"])

memory = ObliviaMemoryManager()


@router.get("/status")
def memory_status():
    return memory.status()


@router.post("/remember")
def remember(record: MemoryRecord):
    return memory.remember(record)


@router.post("/recall")
def recall(query: MemoryQuery):
    return memory.recall(query)


@router.get("/search")
def search(q: str):
    return memory.search(q)
