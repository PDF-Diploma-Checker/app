'''Log lines from which a reader can judge whether a finding was right, without the thesis at hand:
what was reported or dropped, by which check and why, with the text around it.'''
import logging
import re

logger = logging.getLogger(__name__)

MAX_SENTENCE_CHARS = 1500
CONTEXT_CHARS = 500     # so much text on each side of a finding is shown to the model
_SENTENCE_END = re.compile(r"[.!?…]\s+(?=[\"„(\[]?[A-ZĄĆĘŁŃÓŚŹŻ])")


def _flat(text):
    return " ".join(str(text).split())


def sentence_with_mark(text, offset, length):
    '''The whole sentence with the finding, which stands between « ». A finding longer than a sentence stays whole.'''
    if not text:
        return ""
    end_of_hit = offset + length
    start, end = 0, len(text)
    for found in _SENTENCE_END.finditer(text):
        if found.end() <= offset:
            start = found.end()
        elif found.start() + 1 >= end_of_hit:
            end = found.start() + 1
            break
    left, hit, right = _flat(text[start:offset]), _flat(text[offset:end_of_hit]), _flat(text[end_of_hit:end])
    line = f"{left} «{hit}» {right}".strip()
    return line if len(line) <= MAX_SENTENCE_CHARS else line[:MAX_SENTENCE_CHARS] + "..."


def _position(match, block):
    '''Where the finding is in the text of its block. Some checks keep no position in `offset`, so it is looked up by
    the content: the occurrence nearest to `offset`. None when the text does not hold it.'''
    text = block.contents if block else ""
    content = match.content
    if not text or not content:
        return None
    if text[match.offset:match.offset + len(content)] == content:
        return match.offset
    places = [i for i in range(len(text)) if text.startswith(content, i)]
    return min(places, key=lambda i: abs(i - match.offset)) if places else None


def _match_context(match, block):
    position = _position(match, block)
    if position is None:
        return f"«{_flat(match.content)}»"
    return sentence_with_mark(block.contents, position, len(match.content))


_CONTEXT_BLOCK_TYPES = {"paragraph", "heading", "list", "image_description", "table_description"}
_MAX_NEIGHBOR_BLOCKS = 2


def _neighbor_text(blocks, start_index, step, budget):
    """Collect up to `budget` chars from adjacent prose/heading blocks so the model sees multi-sentence context
    even when a finding sits at the very start or end of its paragraph."""
    if not blocks or start_index is None or budget <= 0:
        return ""
    parts = []
    remaining = budget
    idx = start_index + step
    taken = 0
    while 0 <= idx < len(blocks) and taken < _MAX_NEIGHBOR_BLOCKS and remaining > 0:
        neighbor = blocks[idx]
        btype = str(getattr(neighbor.block, "type", "")).lower()
        if btype in _CONTEXT_BLOCK_TYPES:
            txt = _flat(neighbor.contents)
            if txt:
                if step < 0:
                    snippet = txt[-remaining:] if len(txt) > remaining else txt
                    parts.append(snippet)
                else:
                    snippet = txt[:remaining] if len(txt) > remaining else txt
                    parts.append(snippet)
                remaining -= len(snippet) + 1
                taken += 1
        idx += step
    if step < 0:
        parts.reverse()
    return "\n".join(parts)


def _text_around(match, block, blocks=None, block_index=None):
    '''The text around the finding, which stands between « ». Empty when the text does not hold it.
    Pulls adjacent paragraphs/headings when the finding sits near the start or end of its block.'''
    position = _position(match, block)
    if position is None:
        return ""
    end = position + len(match.content)
    text = block.contents
    before = _flat(text[max(0, position - CONTEXT_CHARS):position])
    hit = _flat(text[position:end])
    after = _flat(text[end:end + CONTEXT_CHARS])
    core = f"{before} «{hit}» {after}".strip()
    if blocks is not None and block_index is not None:
        prev_ctx = _neighbor_text(blocks, block_index, -1, CONTEXT_CHARS - len(before)) if len(before) < CONTEXT_CHARS else ""
        next_ctx = _neighbor_text(blocks, block_index, 1, CONTEXT_CHARS - len(after)) if len(after) < CONTEXT_CHARS else ""
        chunks = [c for c in (prev_ctx, core, next_ctx) if c]
        return "\n".join(chunks)
    return core


def _block_info(block):
    return f"block={block.block.block_id}/{block.block.type}/{block.language}" if block else "block=?"


def dropped(reason, category, rule, text, offset, length, block=None):
    '''A finding of a check that is not reported, and the reason.'''
    logger.info("[DROPPED] %s rule=%s reason=%s %s | sentence: %s", category, rule or "-", reason, _block_info(block),
                sentence_with_mark(text, offset, length))


def dropped_match(reason, match, block=None):
    logger.info("[DROPPED] %s rule=%s reason=%s %s | sentence: %s", match.category, match.rule or "-", reason, _block_info(block),
                _match_context(match, block))


def reported(source, match, block=None, section=""):
    '''A finding that goes into the report.'''
    logger.info("[REPORTED] %s source=%s rule=%s page=%s%s section=%r %s found=%r message=%s why=%s | sentence: %s", match.category,
                source, match.rule or "-", match.page_start,
                f"-{match.page_end}" if match.page_end != match.page_start else "", section, _block_info(block),
                _flat(match.content)[:80], _flat(match.message), match.why or "-", _match_context(match, block))


def _model_line(tag, match, note):
    logger.info("[%s] %s source=%s rule=%s page=%s found=%r message=%s model=%s | text: %s", tag, match.category, match.source or "-",
                match.rule or "-", match.page_start, _flat(match.content)[:80], _flat(match.message), _flat(note) or "-", match.context or "-")


def confirmed_by_model(match, reason):
    '''A finding the model read and found to be a real error.'''
    _model_line("MODEL CONFIRMED", match, reason)


def rejected_by_model(match, reason):
    '''A finding removed from the report, because the model found the text correct.'''
    _model_line("MODEL REJECTED", match, reason)


def not_reviewed(reason, match):
    '''A finding that stays in the report without the opinion of the model.'''
    _model_line("MODEL NOT ASKED", match, reason)


def report_sources(sources, kept, blocks):
    '''One line for every finding left after the last filter. `sources`: (name of the check, its findings).'''
    by_id = {b.block.block_id: b for b in blocks}
    index_by_id = {b.block.block_id: i for i, b in enumerate(blocks)}
    sections, section = {}, ""
    for b in blocks:
        if "head" in str(b.block.type).lower():
            section = _flat(b.contents)[:80]
        sections[b.block.block_id] = section
    kept_ids = {id(m) for m in kept}
    for source, matches in sources:
        for match in matches:
            match.source = source
            block = by_id.get(match.block_id)
            match.language = block.language if block else ""
            match.context = _text_around(match, block, blocks, index_by_id.get(match.block_id))
            if id(match) in kept_ids:
                reported(source, match, by_id.get(match.block_id), sections.get(match.block_id, ""))
            else:
                dropped_match("inside an image", match, by_id.get(match.block_id))
