"""Small BM25 retriever over the Markdown maintenance manuals.

No embeddings or external services are used, so retrieval is free, deterministic
and fast. Documents are split at second-level headings ("## 3. Title"), which
allows every hit to be cited as "MNT-101 §3".
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

KNOWLEDGE_DIR = Path(__file__).resolve().parent / "knowledge"
_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "is", "are", "for", "with", "at", "by", "it", "as",
    "be", "this", "that", "from", "if", "then", "than", "not", "no", "can", "may", "so", "do", "does",
}


def _tokens(text: str) -> list[str]:
    out = []
    for tok in re.findall(r"[a-z0-9]+", text.lower()):
        if tok in _STOP or len(tok) < 2:
            continue
        if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss"):
            tok = tok[:-1]
        out.append(tok)
    return out


@dataclass(frozen=True)
class Chunk:
    source: str   # citation id, for example "MNT-101 §3"
    doc_title: str
    heading: str
    text: str
    machines: frozenset = frozenset()  # machines the manual applies to; empty means all machines


def load_chunks(directory: Path = KNOWLEDGE_DIR) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in sorted(directory.glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        title_line = next((ln for ln in raw.splitlines() if ln.startswith("# ")), f"# {path.stem}")
        doc_id = title_line[2:].split()[0]
        doc_title = title_line[2:].strip()
        scope = re.search(r"(?ms)^## 1\. Scope\s*\n(.*?)(?=^## |\Z)", raw)
        machines = frozenset(re.findall(r"\b[A-Z]+-\d{2}\b", scope.group(1))) if scope else frozenset()
        for block in re.split(r"(?m)^## ", raw)[1:]:
            heading, _, body = block.partition("\n")
            number = re.match(r"(\d+)\.", heading)
            section = number.group(1) if number else heading.strip()
            chunks.append(Chunk(f"{doc_id} §{section}", doc_title, heading.strip(), body.strip(), machines))
    return chunks


class Bm25Index:
    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75) -> None:
        self.chunks = chunks
        self.k1, self.b = k1, b
        # Heading and document title are searchable as well
        self._docs = [_tokens(f"{c.doc_title} {c.heading} {c.text}") for c in chunks]
        self._tf = [Counter(d) for d in self._docs]
        self._len = [len(d) for d in self._docs]
        self._avg = sum(self._len) / max(len(self._len), 1)
        df: Counter[str] = Counter()
        for d in self._docs:
            df.update(set(d))
        n = len(self._docs)
        self._idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(self, query: str, top_k: int = 3, machine_id: str | None = None) -> list[tuple[float, Chunk]]:
        q = _tokens(query)
        scored: list[tuple[float, Chunk]] = []
        for i, chunk in enumerate(self.chunks):
            if machine_id and chunk.machines and machine_id not in chunk.machines:
                continue  # Skip manuals scoped to a different machine
            tf, dl = self._tf[i], self._len[i]
            score = 0.0
            for term in q:
                f = tf.get(term, 0)
                if not f:
                    continue
                denom = f + self.k1 * (1 - self.b + self.b * dl / self._avg)
                score += self._idf.get(term, 0.0) * f * (self.k1 + 1) / denom
            if score > 0:
                scored.append((score, chunk))
        scored.sort(key=lambda t: -t[0])
        return scored[:top_k]


_index: Bm25Index | None = None


def get_index() -> Bm25Index:
    global _index
    if _index is None:
        _index = Bm25Index(load_chunks())
    return _index


def search(query: str, top_k: int = 3, max_chars: int = 700, machine_id: str | None = None) -> list[dict]:
    hits = get_index().search(query, top_k=top_k, machine_id=machine_id)
    return [
        {"source": c.source, "title": c.heading, "score": round(s, 2), "text": c.text[:max_chars]}
        for s, c in hits
    ]
