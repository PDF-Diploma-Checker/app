'''
Tests for assigning unique identifiers (PDFMapper._assign_unique_ids) and grouping matches by block_id (check_exeptions).

Run (from the repository root):
    .venv/Scripts/python.exe -m unittest discover -s unit_tests -t . -v

- block_id is unique in the document ("list_N" for lists, N for other blocks),
- item_id is unique in the list, word_index in the block,
- a match from a block spanning two pages is still assigned to its block.
'''
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from analysis.extraction.linguistics_conversion.converter_linguistics_clean import PDFMapper
from analysis.extraction.linguistics_conversion.schema import ListBlock, ListItem, ParagraphBlock, WordInfo
from analysis.modules.linguistics.linguistics_types import Block_context, Error_type
from analysis.modules.linguistics.exeptions_check import check_exeptions


def make_words(content, page=1, word_index=0):
    '''Splits the text on spaces into WordInfo objects; all words share the same word_index,
    so renumbering must assign consecutive ones. Positions (bbox) are irrelevant for these tests.'''
    words = []
    pos = 0
    for text in content.split(" "):
        words.append(WordInfo(word_index=word_index, text=text, start_char=pos, end_char=pos + len(text),
                              font="Times", size=12.0, bold=False, italic=False,
                              bbox=[0.0, 0.0, 10.0, 10.0], page_number=page))
        pos += len(text) + 1
    return words


def make_list(block_id, item_id=0):
    items = [ListItem(item_id=item_id, marker_type="bullet", text=text, bbox=[0, 0, 0, 0], words=make_words(text))
             for text in ("pierwszy punkt", "drugi punkt")]
    return ListBlock(block_id=block_id, content="pierwszy punkt drugi punkt", bbox=[0, 0, 0, 0],
                     items=items, words=make_words("pierwszy punkt drugi punkt"))


def assign_ids(blocks):
    mapper = PDFMapper()
    mapper.logical_blocks = blocks
    mapper._assign_unique_ids()
    return blocks


class TestAssignUniqueIds(unittest.TestCase):
    '''After renumbering, identifiers must not repeat.'''

    def test_duplicated_block_ids(self):
        # The same block_id on different pages - previously distinguished only by the page number
        blocks = assign_ids([ParagraphBlock(block_id=3, content="a", words=make_words("a", page=1)),
                             ParagraphBlock(block_id=3, content="b", words=make_words("b", page=2)),
                             ParagraphBlock(block_id=0, content="c", words=make_words("c", page=2))])
        self.assertEqual([b.block_id for b in blocks], [0, 1, 2])

    def test_list_block_ids(self):
        # Numbering is shared by lists and other blocks
        blocks = assign_ids([ParagraphBlock(block_id=0, content="a", words=make_words("a")),
                             make_list(block_id="list_0"),
                             ParagraphBlock(block_id=0, content="b", words=make_words("b")),
                             make_list(block_id="list_0")])
        self.assertEqual([b.block_id for b in blocks], [0, "list_1", 2, "list_3"])

    def test_word_indexes(self):
        block = assign_ids([ParagraphBlock(block_id=0, content="Ala ma kota", words=make_words("Ala ma kota", word_index=5))])[0]
        self.assertEqual([w.word_index for w in block.words], [0, 1, 2])

    def test_list_item_ids_and_word_indexes(self):
        block = assign_ids([make_list(block_id="list_0", item_id=7)])[0]
        self.assertEqual([item.item_id for item in block.items], [0, 1])
        self.assertEqual([w.word_index for w in block.words], [0, 1, 2, 3])

    def test_empty_document(self):
        self.assertEqual(assign_ids([]), [])


class TestCheckExeptionsBlockId(unittest.TestCase):
    '''Matches are assigned to a block only by block_id, regardless of the page.'''

    def make_match(self, block_id, page):
        return Error_type(content="są", category="GRAMMAR", message="", offset=6, error_length=2, block_id=block_id,
                          page_start=page, page_end=page, word_idxs=[1], error_coordinate=[])

    def test_match_on_second_page_of_block_kept(self):
        content = "Tutaj są błędy"
        block = ParagraphBlock(block_id=7, content=content, words=make_words(content, page=1))
        block.words[1].page_number = 2
        block.words[2].page_number = 2
        match = self.make_match(block_id=7, page=2)
        self.assertEqual(check_exeptions([match], [Block_context(content, "pl", block)], [], "Times"), [match])

    def test_match_from_other_block_dropped(self):
        content = "Tutaj są błędy"
        block = ParagraphBlock(block_id=7, content=content, words=make_words(content))
        match = self.make_match(block_id=8, page=1)
        self.assertEqual(check_exeptions([match], [Block_context(content, "pl", block)], [], "Times"), [])


if __name__ == "__main__":
    unittest.main()
