"""Finding the fragments of the thesis that answer a question.

Two searches, joined by their ranks (reciprocal rank fusion):
- by words (BM25): exact terms, names and symbols ("OpenUSD", "PPO") that the embedding model does not know;
  Polish words are cut to their first letters, so "nagrody", "nagrodą" and "nagród" meet,
- by meaning (the embedding model already used by the analysis): a question asked in other words.

The index (fragments + their vectors) is saved per PDF, so a thesis is read and encoded once.
"""

import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path

import numpy as np

INDEX_VERSION = 1
RRF_K = 60
STEM = 6                    # letters kept of a longer word ("sterowania" -> "sterow")

_TOKEN = re.compile(r"[0-9A-Za-zÀ-ž]+", re.UNICODE)
STOPWORDS = set("""
a aby albo ale ani bez bo by być był była było były co czy dla do gdy gdzie i ich im in jak jaka jaki jakie jako
je jego jej jest jeśli już ku lub ma mi między może na nad nie niż o od oraz po pod przez przy się są ta tak także
te tego tej ten to tu tym tych w we wraz z za ze że który która które którego której których
praca pracy pracę pracą autor autora autorka opisuje opisano jest
the of and or to in on for is are was were be by with as at an a this that what which how why does do it its
thesis author
""".split())


def _fold(text):
    return unicodedata.normalize("NFKC", str(text)).lower()


def tokens(text):
    """Search words of a text: lower case, no stop words, long words cut to their stem."""
    out = []
    for word in _TOKEN.findall(_fold(text)):
        if word in STOPWORDS or (len(word) < 2 and not word.isdigit()):
            continue
        out.append(word[:STEM] if len(word) > STEM and not any(c.isdigit() for c in word) else word)
    return out


class Bm25:
    def __init__(self, texts, k1=1.4, b=0.75):
        self.docs = [Counter(tokens(t)) for t in texts]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.avg = (sum(self.lengths) / len(self.lengths)) if self.lengths else 1.0
        df = Counter(term for d in self.docs for term in d)
        n = len(self.docs)
        self.idf = {term: math.log(1 + (n - f + 0.5) / (f + 0.5)) for term, f in df.items()}
        self.k1, self.b = k1, b

    def scores(self, query):
        terms = set(tokens(query))
        out = np.zeros(len(self.docs), dtype=np.float32)
        for i, doc in enumerate(self.docs):
            norm = self.k1 * (1 - self.b + self.b * self.lengths[i] / (self.avg or 1.0))
            total = 0.0
            for term in terms:
                f = doc.get(term)
                if f:
                    total += self.idf.get(term, 0.0) * f * (self.k1 + 1) / (f + norm)
            out[i] = total
        return out


def chunk_text_for_embedding(chunk):
    section = chunk.get("section") or ""
    return f"{section}\n{chunk['text']}" if section else chunk["text"]


class ThesisIndex:
    """The fragments of one thesis with their vectors. `encode(texts) -> array (n, d)` gives normalized vectors."""

    def __init__(self, data, vectors):
        self.chunks = data["chunks"]
        self.sections = data.get("sections", [])
        self.vectors = np.asarray(vectors, dtype=np.float32) if vectors is not None else None
        self.bm25 = Bm25([chunk_text_for_embedding(c) for c in self.chunks])

    @classmethod
    def build(cls, data, encode):
        texts = [chunk_text_for_embedding(c) for c in data["chunks"]]
        vectors = encode(texts) if texts else np.zeros((0, 1), dtype=np.float32)
        return cls(data, vectors)

    def search(self, question, encode=None, k=6, boost=None):
        """[(chunk, info)] of the best `k` fragments; info: {"bm25", "cosine", "score"}. `boost(chunk) -> float`
        adds to the fused score (e.g. the introduction and the conclusions for a question about the whole thesis)."""
        n = len(self.chunks)
        if not n:
            return []
        lexical = self.bm25.scores(question)
        if encode is not None and self.vectors is not None and len(self.vectors) == n:
            cosine = self.vectors @ np.asarray(encode([question])[0], dtype=np.float32)
        else:
            cosine = np.zeros(n, dtype=np.float32)
        fused = np.zeros(n, dtype=np.float32)
        for scores in (lexical, cosine):
            order = np.argsort(-scores, kind="stable")
            for rank, i in enumerate(order):
                if scores[i] > 0:
                    fused[i] += 1.0 / (RRF_K + rank + 1)
        if boost is not None:
            fused += np.array([boost(c) for c in self.chunks], dtype=np.float32)
        best = [int(i) for i in np.argsort(-fused, kind="stable")[:k] if fused[i] > 0]
        return [(self.chunks[i], {"bm25": float(lexical[i]), "cosine": float(cosine[i]), "score": float(fused[i])})
                for i in best]

    # ------------------------------------------------------------------ saving
    def save(self, folder):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        tmp = folder / "chunks.json.tmp"
        tmp.write_text(json.dumps({"version": INDEX_VERSION, "chunks": self.chunks, "sections": self.sections},
                                  ensure_ascii=False), encoding="utf-8")
        np.save(folder / "vectors.npy", self.vectors if self.vectors is not None else np.zeros((0, 1)))
        tmp.replace(folder / "chunks.json")        # written last: a folder without it is not a finished index

    @classmethod
    def load(cls, folder):
        folder = Path(folder)
        try:
            data = json.loads((folder / "chunks.json").read_text(encoding="utf-8"))
            if data.get("version") != INDEX_VERSION:
                return None
            vectors = np.load(folder / "vectors.npy")
            if len(vectors) != len(data["chunks"]):
                return None
            return cls(data, vectors)
        except (OSError, ValueError, KeyError):
            return None


def index_key(pdf_path, embedding_model):
    """The name of the saved index of a PDF: its content (a changed file is indexed again) and the embedding model."""
    digest = hashlib.sha1()
    with open(pdf_path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    digest.update(f"|{embedding_model}|{INDEX_VERSION}".encode())
    return digest.hexdigest()[:24]
