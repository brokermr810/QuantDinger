"""
Lightweight embedding utilities for local-only deployments.

We intentionally avoid heavyweight ML deps (torch/sentence-transformers) and external services.
This module provides a deterministic "hashed embedding" (similar to feature hashing):
- Tokenize text
- Hash tokens into a fixed-size dense vector
- L2 normalize

It is not as semantically strong as modern transformer embeddings, but it enables:
- Vector storage in SQLite
- Cosine similarity retrieval
- Recency/return weighted ranking
"""

from __future__ import annotations

import math
import os
import re
import struct
import hashlib
from typing import List, Optional


_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+", re.UNICODE)


def _tokenize(text: str) -> List[str]:
    t = (text or "").lower()
    return _TOKEN_RE.findall(t)


class EmbeddingService:
    """Deterministic local embedding service."""

    def __init__(self, dim: Optional[int] = None):
        self.dim = int(dim or os.getenv("AGENT_MEMORY_EMBEDDING_DIM", "256") or 256)
        if self.dim <= 0:
            self.dim = 256

    def embed(self, text: str) -> List[float]:
        """
        Return a dense, L2-normalized embedding vector.
        """
        vec = [0.0] * self.dim
        tokens = _tokenize(text)
        if not tokens:
            return vec

        # Feature hashing with signed counts
        for tok in tokens:
            h = hashlib.blake2b(tok.encode("utf-8"), digest_size=8).digest()
            # Use first 8 bytes as unsigned int
            v = int.from_bytes(h, "little", signed=False)
            idx = v % self.dim
            sign = -1.0 if ((v >> 63) & 1) else 1.0
            vec[idx] += sign

        # L2 normalize
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    def to_bytes(self, vec: List[float]) -> bytes:
        """
        Pack float vector into little-endian float32 bytes for SQLite BLOB storage.
        """
        if not vec:
            return b""
        return struct.pack("<" + "f" * len(vec), *[float(x) for x in vec])

    def from_bytes(self, blob: bytes) -> List[float]:
        if not blob:
            return []
        n = len(blob) // 4
        if n <= 0:
            return []
        return list(struct.unpack("<" + "f" * n, blob[: n * 4]))


def cosine_sim(a: List[float], b: List[float]) -> float:
    """
    Cosine similarity for L2-normalized vectors.
    If vectors are not normalized, this becomes a scaled dot product.
    """
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    return float(sum(a[i] * b[i] for i in range(n)))


