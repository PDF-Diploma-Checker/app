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

INDEX_VERSION = 3          # 3: vectors of sentences too; captions with a broken word are one text
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


_SENTENCE = re.compile(r"(?<=[.!?;:])\s+")
WINDOW_WORDS = 45


def sentence_windows(chunk):
    """Pieces of one or two sentences of a fragment (at most about WINDOW_WORDS words), each with the section title.
    A fragment of 170 words is about several things; its one vector is their average, and a single sentence that
    answers the question ("uczona na 32 środowiskach") is lost in it. Each piece gets a vector of its own."""
    section = chunk.get("section") or ""
    sentences = [x for x in _SENTENCE.split(chunk["text"].replace("\n", " ")) if x.strip()]
    windows, current = [], []
    for sentence in sentences:
        words = sentence.split()
        while len(words) > WINDOW_WORDS:                   # a very long sentence: cut it
            windows.append(" ".join(words[:WINDOW_WORDS]))
            words = words[WINDOW_WORDS:]
        if current and len(current) + len(words) > WINDOW_WORDS:
            windows.append(" ".join(current))
            current = []
        current += words
    if current:
        windows.append(" ".join(current))
    return [f"{section}: {w}" if section else w for w in windows] or [chunk_text_for_embedding(chunk)]


class ThesisIndex:
    """The fragments of one thesis with their vectors: one per fragment and one per piece of 1-2 sentences.
    `encode(texts) -> array (n, d)` gives normalized vectors."""

    def __init__(self, data, vectors, window_vectors=None, window_owner=None):
        self.chunks = data["chunks"]
        self.sections = data.get("sections", [])
        self.vectors = np.asarray(vectors, dtype=np.float32) if vectors is not None else None
        self.window_vectors = np.asarray(window_vectors, dtype=np.float32) if window_vectors is not None else None
        self.window_owner = np.asarray(window_owner, dtype=np.int64) if window_owner is not None else None
        self.bm25 = Bm25([chunk_text_for_embedding(c) for c in self.chunks])

    @classmethod
    def build(cls, data, encode):
        chunks = data["chunks"]
        texts = [chunk_text_for_embedding(c) for c in chunks]
        vectors = encode(texts) if texts else np.zeros((0, 1), dtype=np.float32)
        windows, owner = [], []
        for i, chunk in enumerate(chunks):
            for window in sentence_windows(chunk):
                windows.append(window)
                owner.append(i)
        window_vectors = encode(windows) if windows else np.zeros((0, 1), dtype=np.float32)
        return cls(data, vectors, window_vectors, owner)

    def _cosines(self, query_vector):
        """Closeness of every fragment to a query: the best of the whole fragment and of its sentences."""
        n = len(self.chunks)
        if self.vectors is None or len(self.vectors) != n:
            return np.zeros(n, dtype=np.float32)
        cosine = self.vectors @ query_vector
        if self.window_vectors is not None and len(self.window_vectors) and self.window_owner is not None:
            per_window = self.window_vectors @ query_vector
            best = np.full(n, -1.0, dtype=np.float32)
            np.maximum.at(best, self.window_owner, per_window)
            cosine = np.maximum(cosine, best)
        return cosine.astype(np.float32)

    def search_many(self, queries, encode=None, k=6, boost=None, weights=None):
        """[(chunk, info)] of the best `k` fragments for the question and the phrases the model wrote for it: the
        ranks of every query are added (the question itself counts most). info: {"bm25", "cosine", "score"}, the
        best bm25 / cosine of any query. `boost(chunk) -> float` adds to the fused score (e.g. the introduction and
        the conclusions for a question about the whole thesis)."""
        n = len(self.chunks)
        queries = [q for q in queries if q and str(q).strip()]
        if not n or not queries:
            return []
        weights = weights or [1.0] + [0.6] * (len(queries) - 1)
        query_vectors = np.asarray(encode(queries), dtype=np.float32) if encode is not None else None
        fused = np.zeros(n, dtype=np.float32)
        best_lexical = np.zeros(n, dtype=np.float32)
        best_cosine = np.zeros(n, dtype=np.float32)
        for qi, query in enumerate(queries):
            lexical = self.bm25.scores(query)
            cosine = self._cosines(query_vectors[qi]) if query_vectors is not None else np.zeros(n, dtype=np.float32)
            best_lexical = np.maximum(best_lexical, lexical)
            best_cosine = np.maximum(best_cosine, cosine)
            for scores in (lexical, cosine):
                order = np.argsort(-scores, kind="stable")
                for rank, i in enumerate(order):
                    if scores[i] > 0:
                        fused[i] += weights[qi] / (RRF_K + rank + 1)
        if boost is not None:
            fused += np.array([boost(c) for c in self.chunks], dtype=np.float32)
        best = [int(i) for i in np.argsort(-fused, kind="stable")[:k] if fused[i] > 0]
        return [(self.chunks[i], {"bm25": float(best_lexical[i]), "cosine": float(best_cosine[i]),
                                  "score": float(fused[i])}) for i in best]

    def search(self, question, encode=None, k=6, boost=None):
        return self.search_many([question], encode, k=k, boost=boost)

    # ------------------------------------------------------------------ saving
    def save(self, folder):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        np.savez(folder / "vectors.npz",
                 chunks=self.vectors if self.vectors is not None else np.zeros((0, 1)),
                 windows=self.window_vectors if self.window_vectors is not None else np.zeros((0, 1)),
                 owner=self.window_owner if self.window_owner is not None else np.zeros(0, dtype=np.int64))
        tmp = folder / "chunks.json.tmp"
        tmp.write_text(json.dumps({"version": INDEX_VERSION, "chunks": self.chunks, "sections": self.sections},
                                  ensure_ascii=False), encoding="utf-8")
        tmp.replace(folder / "chunks.json")        # written last: a folder without it is not a finished index

    @classmethod
    def load(cls, folder):
        folder = Path(folder)
        try:
            data = json.loads((folder / "chunks.json").read_text(encoding="utf-8"))
            if data.get("version") != INDEX_VERSION:
                return None
            with np.load(folder / "vectors.npz") as arrays:
                vectors, windows, owner = arrays["chunks"], arrays["windows"], arrays["owner"]
            if len(vectors) != len(data["chunks"]) or len(windows) != len(owner):
                return None
            return cls(data, vectors, windows, owner)
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
