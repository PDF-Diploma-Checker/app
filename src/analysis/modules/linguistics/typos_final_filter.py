import re
from .language_error_extractor import typo_check
import logging

logger = logging.getLogger(__name__)

def is_word_correct(word, language):
    if not word: return False
    return typo_check(word)

def refine_typos(errors, blocks):
    '''
    Error post-processing. It sifts through typos and checks whether they cease to be errors when combined with adjacent words.
    '''
    block_info_map = {}
    for b in blocks:
        if b.block.type not in {"acronym", "keywords"}:
            block_info_map[b.block.block_id] = {
                "contents": b.contents,
                "language": b.language
            }

    final_errors = []
    typos_report = {"before_total": len(errors), "resolved_typos": [], "after_total": 0}

    for err in errors:
        if err.category != "TYPOS":
            final_errors.append(err)
            continue
            
        b_info = block_info_map.get(err.block_id)
        if not b_info:
            final_errors.append(err)
            continue
            
        contents = b_info["contents"]
        lang = b_info["language"]
        typo_text = err.content
        
        context_left = contents[max(0, err.offset - 30):err.offset]
        context_right = contents[err.offset + err.error_length:min(len(contents), err.offset + err.error_length + 30)]
        
        left_match = re.search(r'(\w+)[^\w]*$', contents[:err.offset])
        left_word = left_match.group(1) if left_match else ""
        
        right_match = re.search(r'^[^\w]*(\w+)', contents[err.offset + err.error_length:])
        right_word = right_match.group(1) if right_match else ""

        is_resolved = False
        resolved_word = ""
        
        if left_word and not is_resolved:
            merged_left = left_word + typo_text
            if is_word_correct(merged_left, lang):
                is_resolved = True
                resolved_word = merged_left

        if right_word and not is_resolved:
            merged_right = typo_text + right_word
            if is_word_correct(merged_right, lang):
                is_resolved = True
                resolved_word = merged_right

        if is_resolved:
            resolved_info = {
                "original_typo": typo_text,
                "resolved_as": resolved_word,
                "context": f"...{context_left}[{typo_text}]{context_right}...",
                "language": lang
            }
            typos_report["resolved_typos"].append(resolved_info)
            logger.debug("Resolved typo: '%s' -> '%s' (Context: %s)", typo_text, resolved_word, resolved_info["context"])
        else:
            final_errors.append(err)

    logger.info("Typo refinement: %d resolved, %d kept", len(typos_report["resolved_typos"]), len(final_errors))
    return final_errors