"""The prompt of the assistant and the checks of its answer.

The safeguards against an invented answer:
- the model gets only numbered fragments of the thesis and must end every statement with the number of the fragment
  it comes from; the numbers become links to the page in the app,
- when the fragments do not hold the answer it must say so in one fixed sentence (and when nothing in the thesis is
  even close to the question, the model is not asked at all),
- citations of fragments it was not given are removed; an answer left without any source is shown with a warning,
- the context is measured in the model's own tokens and cut to fit, so a long question or history cannot overflow it.
"""

import re

NOT_FOUND = {
    "pl": "W pracy nie znalazłem informacji na ten temat.",
    "en": "I could not find this in the thesis.",
}
MAX_QUESTION_CHARS = 600
ANSWER_TOKENS = 600
HISTORY_TURNS = 2           # earlier questions and answers kept, so "a w rozdziale 3?" can be understood

# a question about the whole thesis cannot be answered from a few fragments: the summaries of the sections help
_WHOLE_THESIS = re.compile(
    r"cał(a|ej|ą|ość)\s+prac|o czym (jest|traktuje)|podsumuj|streść|streszcz|główn\w* (wnios|cel|tez|wynik)|"
    r"\bwnioski\b|cel(em)? pracy|zakres pracy|układ pracy|struktur\w* pracy|najważniejsz|"
    r"whole thesis|summar|main (conclusion|goal|result|contribution)|what is the thesis about|structure of",
    re.IGNORECASE)
_OVERVIEW_SECTIONS = re.compile(
    r"wst[eę]p|wprowadzenie|cel|streszczenie|abstract|podsumowanie|wnioski|zakończenie|introduction|conclusion|summary",
    re.IGNORECASE)
_CITATION = re.compile(r"\[\s*(S?\d+(?:\s*[,;]\s*S?\d+)*)\s*\]")

# the fragments are relevant enough to ask the model (below both, nothing in the thesis is close to the question)
MIN_COSINE = 0.22


def is_whole_thesis_question(question):
    return bool(_WHOLE_THESIS.search(question or ""))


def overview_boost(chunk):
    """A small bonus for the introduction, the purpose and the conclusions (for a question about the whole thesis)."""
    return 0.04 if _OVERVIEW_SECTIONS.search(chunk.get("section") or "") else 0.0     # above two first places


def nothing_relevant(found):
    """True when no fragment shares a word with the question and none is close to it in meaning."""
    return not found or all(info["bm25"] <= 0 and info["cosine"] < MIN_COSINE for _, info in found)


def clean_question(question):
    return " ".join(str(question or "").split())[:MAX_QUESTION_CHARS]


def _system(language):
    if language == "en":
        return (
            "You help a thesis supervisor read a diploma thesis. Answer ONLY from the numbered fragments of the thesis "
            "given below, never from your own knowledge.\n"
            "Rules:\n"
            "1. End every sentence that uses the thesis with the number of its fragment in square brackets, e.g. [2] "
            "or [1, 3]. Summaries of sections are cited as [S1].\n"
            f"2. If the fragments do not contain the answer, reply exactly: \"{NOT_FOUND['en']}\" and nothing else.\n"
            "3. Do not guess, do not add facts, numbers or names that are not in the fragments.\n"
            "4. Do not grade the thesis unless asked. Be brief: at most 6 sentences, in English."
        )
    return (
        "Pomagasz promotorowi czytać pracę dyplomową. Odpowiadasz WYŁĄCZNIE na podstawie ponumerowanych fragmentów "
        "pracy podanych niżej, nigdy z własnej wiedzy.\n"
        "Zasady:\n"
        "1. Każde zdanie korzystające z pracy zakończ numerem fragmentu w nawiasie kwadratowym, np. [2] albo [1, 3]. "
        "Streszczenia rozdziałów cytuj jako [S1].\n"
        f"2. Jeśli fragmenty nie zawierają odpowiedzi, odpowiedz dokładnie: \"{NOT_FOUND['pl']}\" i nic więcej.\n"
        "3. Nie zgaduj, nie dodawaj faktów, liczb ani nazw, których nie ma we fragmentach.\n"
        "4. Nie oceniaj pracy, jeśli o to nie pytano. Odpowiadaj krótko: najwyżej 6 zdań, po polsku."
    )


def _fragment(number, chunk, language):
    page = chunk["page"] + 1
    where = (f"page {page}" if language == "en" else f"str. {page}")
    section = chunk.get("section") or ""
    label = f"[{number}] ({where}{', ' + section if section else ''})"
    return f"{label}\n{chunk['text']}"


def _summary(number, item, language):
    title = item.get("display") or item.get("title") or ""
    note = "automatic summary of the section" if language == "en" else "automatyczne streszczenie rozdziału"
    return f"[S{number}] ({note}: {title})\n{item.get('summary', '')}"


def build_messages(question, found, summaries, history, language, count_tokens, budget):
    """Chat messages for the model, at most `budget` tokens (counted by `count_tokens(text)`).

    found:     [(chunk, info)] best first; fragments that do not fit are left out (the worst ones)
    summaries: [{"display", "summary"}] of the sections, for a question about the whole thesis (else [])
    history:   [(question, answer)] earlier turns, newest last
    Returns (messages, sources): sources maps "1".."n" and "S1".. to the chunk / summary used."""
    system = _system(language)
    used = count_tokens(system) + count_tokens(_reminder(language)) + count_tokens(question) + 64
    turns = []
    for old_q, old_a in reversed(list(history or [])[-HISTORY_TURNS:]):
        cost = count_tokens(old_q) + count_tokens(old_a) + 16
        if used + cost > budget * 0.25 + count_tokens(system):     # history never takes the room of the thesis
            break
        turns.insert(0, (old_q, old_a))
        used += cost

    parts, sources = [], {}
    for i, item in enumerate(summaries or [], start=1):
        text = _summary(i, item, language)
        cost = count_tokens(text) + 4
        if used + cost > budget * 0.45:
            break
        parts.append(text)
        sources[f"S{i}"] = {"summary": item}
        used += cost
    number = 0
    for chunk, _info in found:
        text = _fragment(number + 1, chunk, language)
        cost = count_tokens(text) + 4
        if used + cost > budget:
            continue
        number += 1
        parts.append(text)
        sources[str(number)] = {"chunk": chunk}
        used += cost

    head = "Fragments of the thesis:" if language == "en" else "Fragmenty pracy:"
    ask = "Question:" if language == "en" else "Pytanie:"
    # Gemma has no system role (llama.cpp's "gemma" chat format silently drops a system message): the rules go into
    # the user's turn, and the two that matter most are repeated after the question, where the model reads last
    messages = []
    for old_q, old_a in turns:
        messages.append({"role": "user", "content": old_q})
        messages.append({"role": "assistant", "content": old_a})
    messages.append({"role": "user", "content": f"{system}\n\n{head}\n\n" + "\n\n".join(parts)
                     + f"\n\n{ask} {question}\n\n{_reminder(language)}"})
    return messages, sources


def _reminder(language):
    if language == "en":
        return (f"Remember: a fragment number in square brackets after every sentence, e.g. [1]; if the fragments do "
                f"not answer the question, write only: \"{NOT_FOUND['en']}\"")
    return (f"Pamiętaj: numer fragmentu w nawiasie kwadratowym po każdym zdaniu, np. [1]; jeśli fragmenty nie "
            f"odpowiadają na pytanie, napisz tylko: \"{NOT_FOUND['pl']}\"")


def check_answer(text, sources, language):
    """{"text", "kind" (answer | not_found | unsourced), "citations": [keys in the order they appear]}.
    Citations of fragments the model was not given are taken out of the text."""
    text = (text or "").strip()
    not_found = NOT_FOUND.get(language, NOT_FOUND["pl"])
    if not text or _same(text, not_found) or _same(text, NOT_FOUND["pl"]) or _same(text, NOT_FOUND["en"]):
        return {"text": not_found, "kind": "not_found", "citations": []}

    citations = []

    def keep_known(match):
        keys = [k.strip().upper() for k in re.split(r"[,;]", match.group(1))]
        known = [k for k in keys if k in sources]
        for k in known:
            if k not in citations:
                citations.append(k)
        return f"[{', '.join(known)}]" if known else ""

    cleaned = _CITATION.sub(keep_known, text)
    cleaned = re.sub(r"[ \t]+([.,;:])", r"\1", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
    if not_found in cleaned and len(cleaned) < len(not_found) + 40:
        return {"text": not_found, "kind": "not_found", "citations": []}
    return {"text": cleaned, "kind": "answer" if citations else "unsourced", "citations": citations}


def _same(a, b):
    def norm(s):
        return re.sub(r"[\W_]+", " ", s.lower()).strip()
    return norm(a) == norm(b)


def source_view(key, source, sections=None):
    """What the app shows for a citation: {"key", "page", "label", "rects", "text"}."""
    if "chunk" in source:
        chunk = source["chunk"]
        return {"key": key, "page": chunk["page"], "label": chunk.get("section") or "", "rects": chunk.get("rects", []),
                "text": chunk["text"][:400]}
    item = source["summary"]
    title = item.get("display") or item.get("title") or ""
    page, rects = None, []
    for section in sections or []:
        if _same(section.get("title", ""), title) or (title and _same(title, section.get("title", "")[:len(title)])):
            page, rects = section.get("page"), section.get("rects", [])
            break
    return {"key": key, "page": page, "label": title, "rects": rects, "text": item.get("summary", "")[:400]}
