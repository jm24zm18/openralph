from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import math, sqlite3, struct
from typing import List, Sequence, Tuple

from .embed import ollama_embed
from ..logging import get_logger

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

def _apply_path_boost(path: str, score: float, boosts: Sequence[Tuple[str, float]]) -> float:
    boosted = score
    for prefix, factor in boosts:
        if path == prefix or path.startswith(prefix):
            boosted *= factor
    return boosted

def query_memory(
    db_path: Path,
    ollama_host: str,
    embed_model: str,
    query: str,
    k: int = 8,
    path_boosts: Sequence[Tuple[str, float]] | None = None,
) -> list[MemoryHit]:
    log = get_logger("memory.query")
    log.debug("query_memory: db=%s, k=%d, query=%s", db_path, k, query[:100])

    log.debug("Embedding query via %s/%s", ollama_host, embed_model)
    qvec = ollama_embed(ollama_host, embed_model, query)
    log.debug("Query embedded: %d dimensions", len(qvec))

    con = sqlite3.connect(db_path)
    rows = con.execute("SELECT path, chunk_index, content, embedding, dim FROM chunks").fetchall()
    con.close()
    log.debug("Loaded %d chunks from database", len(rows))

    boosts = path_boosts or []
    hits: list[MemoryHit] = []
    for path, chunk_index, content, blob, dim in rows:
        vec = _unpack_f32(blob, dim)
        score = _cosine(qvec, vec)
        score = _apply_path_boost(path, score, boosts)
        hits.append(MemoryHit(path, int(chunk_index), float(score), content))

    hits.sort(key=lambda h: h.score, reverse=True)
    top_hits = hits[:k]
    if top_hits:
        log.debug("Top %d hits: scores range from %.3f to %.3f", len(top_hits), top_hits[0].score, top_hits[-1].score)
    else:
        log.debug("No hits found")
    return top_hits
