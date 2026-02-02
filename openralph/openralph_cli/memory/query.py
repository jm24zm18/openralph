from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import math, sqlite3, struct
from typing import List

from .embed import ollama_embed

@dataclass(frozen=True)
class MemoryHit:
    path: str
    chunk_index: int
    score: float
    content: str

def _unpack_f32(blob: bytes, dim: int) -> List[float]:
    return list(struct.unpack(f"{dim}f", blob))

def _cosine(a: List[float], b: List[float]) -> float:
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))

def query_memory(db_path: Path, ollama_host: str, embed_model: str, query: str, k: int = 8) -> list[MemoryHit]:
    qvec = ollama_embed(ollama_host, embed_model, query)
    con = sqlite3.connect(db_path)
    rows = con.execute("SELECT path, chunk_index, content, embedding, dim FROM chunks").fetchall()
    con.close()

    hits: list[MemoryHit] = []
    for path, chunk_index, content, blob, dim in rows:
        vec = _unpack_f32(blob, dim)
        score = _cosine(qvec, vec)
        hits.append(MemoryHit(path, int(chunk_index), float(score), content))

    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:k]
