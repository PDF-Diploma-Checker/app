import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'src'))

from analysis.modules.linguistics.bibliography_check import check_bibliography, extract_authors


def bibliography_matches(entries, organizations=(), language='pl'):
    items = []
    for item_id, text in enumerate(entries):
        words = []
        offset = 0
        for index, token in enumerate(text.split()):
            start = text.index(token, offset)
            offset = start + len(token)
            words.append(SimpleNamespace(text=token, start_char=start, end_char=offset,
                                         italic=False, word_index=index, page_number=0,
                                         line=0, bbox=[start, 0, offset, 10]))
        items.append(SimpleNamespace(item_id=item_id, text=text, words=words))
    block = SimpleNamespace(type='list', is_bibliography=True, block_id=1,
                            items=items, language=language)
    return check_bibliography([SimpleNamespace(block=block)], '',
                              {'people': set(), 'organizations': set(organizations)})


class CorporateAuthorsTest(unittest.TestCase):
    def test_spaced_online_address_does_not_require_publication_date(self):
        from analysis.modules.linguistics.bibliography_check import URL_PATTERN, extract_fields
        entries = [
            "NVIDIA: NVIDIA Isaac Sim. B.r. h t t p s : / / d e v e l o p e r . n v i d i a . c o m / i s a ac/sim (dostęp: 25.03.2026).",
            "NVIDIA: NVIDIA Isaac Lab. B.r. h t t p s : / / d e v e l o p e r . n v i d i a . c o m / i s a ac/lab (dostęp: 25.03.2026).",
            "NVIDIA: Documentation. https://developer.nvidia.com/docs (dostęp: 25.03.2026).",
        ]
        for entry in entries:
            with self.subTest(entry=entry):
                self.assertIsNotNone(URL_PATTERN.search(entry))
                self.assertIn("access_date", extract_fields(entry))
                matches = bibliography_matches([entry], organizations={"NVIDIA"})
                self.assertFalse([m for m in matches if m.category in {"MISSING_DATE", "MISSING_ACCESS_DATE_OR_DOI"}])

    def test_book_without_publication_date_still_has_a_date_error(self):
        matches = bibliography_matches(["Kowalski J.: Robotyka. Wydawnictwo PWN."])
        self.assertTrue(any(m.category == "MISSING_DATE" for m in matches))

    def test_reported_corporate_authors_without_ner(self):
        for name in ('Boston Dynamics', 'Google DeepMind', 'Robotic Systems Lab',
                     'Open Robotics', 'Newton Physics'):
            with self.subTest(name=name):
                text = name + ': Documentation. 2026.'
                self.assertEqual(extract_authors(text, text, set()),
                                 (name, 'organization', 0, len(name)))

    def test_ner_organization_takes_precedence_over_person_pattern(self):
        text = 'Example Research: Documentation. 2026.'
        self.assertEqual(extract_authors(text, text, {'Example Research'},
                                        {'Example Research'})[:2],
                         ('Example Research', 'organization'))

    def test_affiliation_and_title_stay_out_of_author_name(self):
        text = 'Robotic Systems Lab, ETH Zürich: legged_gym.'
        self.assertEqual(extract_authors(text, text, set())[:2],
                         ('Robotic Systems Lab, ETH Zürich', 'organization'))
        text = 'NVIDIA: Newton Physics Engine.'
        self.assertEqual(extract_authors(text, text, {'NVIDIA'})[:2], ('NVIDIA', 'different'))
        self.assertIsNone(extract_authors(text, text, set())[0])

    def test_ner_label_must_not_consume_title(self):
        text = 'Boston Dynamics: Arm Door Command.'
        self.assertEqual(extract_authors(text, text, set(),
                                        {'Boston Dynamics: Arm Door Command'})[:2],
                         ('Boston Dynamics', 'organization'))

    def test_personal_names_and_boundaries(self):
        for name, fmt in [('Jan Kowalski', 'Jan Nowak'), ('Kowalski J.', 'Nowak J.'),
                          ('J. Kowalski', 'J. Nowak'), ('Kowalski, Jan', 'Nowak, Jan')]:
            text = name + ': Title. 2026.'
            self.assertEqual(extract_authors(text, text, set())[:2], (name, fmt))
        text = 'Open Roboticski: Title.'
        self.assertNotEqual(extract_authors(text, text, set())[1], 'organization')

    def test_coherence_excludes_organizations_but_reports_personal_outlier(self):
        entries = ['Kowalski J.: Title. 2026.'] * 4
        entries += [name + ': Documentation. 2026.' for name in
                    ('Boston Dynamics', 'Google DeepMind', 'Robotic Systems Lab',
                     'Open Robotics', 'Newton Physics')]
        entries += ['Jan Kowalski: Title. 2026.']
        for language in ('pl', 'en'):
            with self.subTest(language=language):
                matches = [m for m in bibliography_matches(entries, language=language)
                           if m.category == 'AUTHOR_FORMAT_COHERENCE']
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0].content, 'Jan Kowalski')
                self.assertNotIn('Nowak', matches[0].message)
                self.assertIn('nazwisko + inicjały' if language == 'pl' else 'surname + initials',
                              matches[0].message)


if __name__ == '__main__':
    unittest.main()
