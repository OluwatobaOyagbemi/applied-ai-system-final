"""Retrieval over the local pet-care knowledge base (the "R" in RAG).

Each markdown file in knowledge/ has YAML front matter and a body. The body is
split on "## " headings so retrieval returns focused chunks instead of whole
documents. Ranking is BM25, implemented here in pure Python so the project has
no embedding service or vector database to set up.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge"

_STOPWORDS = set(
    "a an and are as at be by can do for from has have how i if in is it its my "
    "of on or our should so that the their them they this to was what when which "
    "who will with you your about any not no".split()
)


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens with stopwords removed and a light plural strip."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    out = []
    for w in words:
        if w in _STOPWORDS or len(w) < 2:
            continue
        if len(w) > 4 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.append(w)
    return out


@dataclass
class Document:
    """One knowledge file: its metadata and body text."""

    id: str
    title: str
    source: str
    species: list[str]
    topics: list[str]
    body: str
    requires_vet: bool = False
    suggested_tasks: list[dict] = field(default_factory=list)
    path: str = ""


@dataclass
class Chunk:
    """A section of a document. `id` is "<doc id>#<section slug>"."""

    id: str
    doc: Document
    heading: str
    text: str
    score: float = 0.0

    @property
    def citation(self) -> str:
        return f"{self.doc.title} ({self.doc.source})"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "intro"


def load_documents(directory: Path = KNOWLEDGE_DIR) -> list[Document]:
    """Parse every knowledge/*.md file (except SOURCES.md) into a Document."""
    docs = []
    for path in sorted(directory.glob("*.md")):
        if path.name.upper() == "SOURCES.MD":
            continue
        raw = path.read_text(encoding="utf-8")
        parts = raw.split("---", 2)
        if len(parts) < 3:
            log.warning("Skipping %s: no front matter", path.name)
            continue
        try:
            meta = yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError as err:
            log.warning("Skipping %s: bad front matter (%s)", path.name, err)
            continue
        if "id" not in meta:
            log.warning("Skipping %s: front matter has no id", path.name)
            continue
        docs.append(
            Document(
                id=meta["id"],
                title=meta.get("title", meta["id"]),
                source=meta.get("source", "unknown"),
                species=[s.lower() for s in meta.get("species", [])],
                topics=meta.get("topics", []),
                body=parts[2].strip(),
                requires_vet=bool(meta.get("requires_vet", False)),
                suggested_tasks=meta.get("suggested_tasks", []) or [],
                path=str(path),
            )
        )
    log.info("Loaded %d knowledge documents from %s", len(docs), directory)
    return docs


def chunk_document(doc: Document) -> list[Chunk]:
    """Split a document body on "## " headings. Text before the first heading
    becomes an "intro" chunk."""
    chunks = []
    sections = re.split(r"(?m)^## +", doc.body)
    for i, section in enumerate(sections):
        section = section.strip()
        if not section:
            continue
        if i == 0 and not doc.body.lstrip().startswith("## "):
            heading, text = "Overview", section
        else:
            heading, _, text = section.partition("\n")
            heading = heading.strip()
        chunks.append(Chunk(id=f"{doc.id}#{_slug(heading)}", doc=doc, heading=heading, text=text.strip()))
    return chunks


class Retriever:
    """BM25 ranking over knowledge chunks, with an optional species filter."""

    def __init__(self, documents: list[Document] | None = None, k1: float = 1.5, b: float = 0.75):
        self.documents = load_documents() if documents is None else documents
        self.chunks: list[Chunk] = [c for d in self.documents for c in chunk_document(d)]
        self.k1, self.b = k1, b
        # Index title + topics + heading + text so metadata words help matching.
        self._tokens = [
            tokenize(f"{c.doc.title} {' '.join(c.doc.topics)} {c.heading} {c.text}") for c in self.chunks
        ]
        self._tf = [Counter(toks) for toks in self._tokens]
        self._avgdl = sum(len(t) for t in self._tokens) / max(len(self._tokens), 1)
        df: Counter = Counter()
        for toks in self._tokens:
            df.update(set(toks))
        n = len(self._tokens)
        self._idf = {term: math.log(1 + (n - f + 0.5) / (f + 0.5)) for term, f in df.items()}

    @property
    def chunk_ids(self) -> set[str]:
        return {c.id for c in self.chunks}

    def get_document(self, doc_id: str) -> Document | None:
        return next((d for d in self.documents if d.id == doc_id), None)

    def search(self, query: str, species: str | None = None, k: int = 5) -> list[Chunk]:
        """Return the top-k chunks for `query`. If `species` is given, chunks
        from documents that don't cover that species are left out."""
        q_terms = tokenize(query)
        if not q_terms:
            return []
        results = []
        for i, chunk in enumerate(self.chunks):
            if species and chunk.doc.species and species.lower() not in chunk.doc.species:
                continue
            tf, dl = self._tf[i], len(self._tokens[i])
            score = 0.0
            for term in q_terms:
                f = tf.get(term, 0)
                if not f:
                    continue
                score += self._idf.get(term, 0) * f * (self.k1 + 1) / (
                    f + self.k1 * (1 - self.b + self.b * dl / self._avgdl)
                )
            if score > 0:
                results.append(Chunk(chunk.id, chunk.doc, chunk.heading, chunk.text, round(score, 3)))
        results.sort(key=lambda c: c.score, reverse=True)
        return results[:k]
