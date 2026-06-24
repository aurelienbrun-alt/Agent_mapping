from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import numpy as np

from .azure_openai_client import AzureOpenAIClient

SUPPORTED_EXTENSIONS = (".txt", ".md", ".pdf", ".docx")


class GuidelineIndex:
    """Semantic index of a regulatory guideline document for RAG enrichment.

    Place the guideline file in data/guidelines/ named:
        guidelines_{framework_name}.pdf   (or .txt / .md / .docx)

    The index (chunks + embeddings) is cached in docs/cache/ and rebuilt
    automatically when the source file changes.
    """

    def __init__(
        self,
        framework_name: str,
        guideline_dir: Path,
        cache_dir: Path,
        llm: AzureOpenAIClient,
        chunk_size: int = 400,
        chunk_overlap: int = 80,
    ) -> None:
        self.framework_name = framework_name
        self.guideline_dir = guideline_dir
        self.cache_dir = cache_dir
        self.llm = llm
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.chunks: list[str] = []
        self.embeddings: list[list[float]] = []
        self.loaded = False

    # ------------------------------------------------------------------
    # File discovery
    # ------------------------------------------------------------------
    def _find_file(self) -> Path | None:
        safe = self.framework_name.replace(" ", "_")
        for ext in SUPPORTED_EXTENSIONS:
            p = self.guideline_dir / f"guidelines_{safe}{ext}"
            if p.exists():
                return p
        return None

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------
    def _parse(self, path: Path) -> str:
        if path.suffix in {".txt", ".md"}:
            return path.read_text(encoding="utf-8", errors="ignore")
        if path.suffix == ".pdf":
            try:
                import pdfplumber  # type: ignore
                pages: list[str] = []
                with pdfplumber.open(path) as pdf:
                    for page in pdf.pages:
                        text = page.extract_text()
                        if text:
                            pages.append(text)
                return "\n".join(pages)
            except ImportError:
                raise ImportError(
                    "pdfplumber is required for PDF guidelines. "
                    "Run: pip install pdfplumber"
                )
        if path.suffix == ".docx":
            try:
                import docx  # type: ignore
                doc = docx.Document(path)
                return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            except ImportError:
                raise ImportError(
                    "python-docx is required for Word guidelines. "
                    "Run: pip install python-docx"
                )
        raise ValueError(f"Unsupported guideline format: {path.suffix}")

    # ------------------------------------------------------------------
    # Chunking
    # ------------------------------------------------------------------
    def _chunk(self, text: str) -> list[str]:
        text = re.sub(r"\n{3,}", "\n\n", text)
        words = text.split()
        if not words:
            return []
        step = max(1, self.chunk_size - self.chunk_overlap)
        chunks = []
        for i in range(0, len(words), step):
            chunk = " ".join(words[i: i + self.chunk_size]).strip()
            if len(chunk) > 80:
                chunks.append(chunk)
        return chunks

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------
    def _cache_path(self) -> Path:
        safe = self.framework_name.replace(" ", "_").replace(".", "_")
        return self.cache_dir / f"guideline_index_{safe}.json"

    @staticmethod
    def _file_hash(path: Path) -> str:
        return hashlib.md5(path.read_bytes()).hexdigest()[:16]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def load_or_build(self) -> bool:
        """Find and index the guideline document. Returns True if found."""
        path = self._find_file()
        if path is None:
            return False

        cache_path = self._cache_path()
        file_hash = self._file_hash(path)

        if cache_path.exists():
            try:
                data = json.loads(cache_path.read_text(encoding="utf-8"))
                if data.get("hash") == file_hash:
                    self.chunks = data["chunks"]
                    self.embeddings = data["embeddings"]
                    self.loaded = True
                    print(f"  [Guideline RAG] Loaded index for '{self.framework_name}' "
                          f"({len(self.chunks)} chunks) from cache.", flush=True)
                    return True
            except Exception:
                pass

        # Build index from scratch
        print(f"  [Guideline RAG] Building index for '{self.framework_name}' from {path.name} ...", flush=True)
        raw_text = self._parse(path)
        self.chunks = self._chunk(raw_text)
        if not self.chunks:
            return False

        self.embeddings = []
        batch_size = 64
        for i in range(0, len(self.chunks), batch_size):
            batch = self.chunks[i: i + batch_size]
            self.embeddings.extend(self.llm.embed_texts(batch))

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(
                {"hash": file_hash, "chunks": self.chunks, "embeddings": self.embeddings},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"  [Guideline RAG] Index built and cached ({len(self.chunks)} chunks).", flush=True)
        self.loaded = True
        return True

    def retrieve(self, query_embedding: list[float], top_k: int = 3) -> list[str]:
        """Return the top-k most relevant guideline passages for a query embedding."""
        if not self.loaded or not self.embeddings:
            return []
        q = np.array(query_embedding, dtype=float)
        q_norm = float(np.linalg.norm(q))
        if q_norm == 0:
            return []
        scores = [
            float(np.dot(q, np.array(emb, dtype=float)) / (q_norm * (float(np.linalg.norm(np.array(emb, dtype=float))) or 1e-9)))
            for emb in self.embeddings
        ]
        top_idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
        return [self.chunks[i] for i in top_idx]
