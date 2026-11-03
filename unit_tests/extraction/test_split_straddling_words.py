import unittest

from analysis.extraction.raw_extraction.text_extractor import split_straddling_words

HAT = "̂"


def _span(text, x0, x1, font="LMRoman12", size=12.0):
    return {"text": text, "bbox": (x0, 131.0, x1, 143.0), "font": font, "size": size}


def _block(*spans):
    return {"lines": [{"spans": list(spans)}]}


def _word(text, x0, x1):
    return (x0, 131.0, x1, 143.0, text, 0, 1, 0)


class SplitStraddlingWordsTest(unittest.TestCase):
    def test_word_after_math_with_accent_is_kept(self):
        block = _block(
            _span(HAT, 158.5, 158.5, "LatinModernMath"),
            _span("x", 151.8, 158.9),
            _span("k|j", 158.9, 170.3, "LatinModernMath", 8.4),
            _span("oznaczono oszacowanie", 173.6, 289.8),
        )
        words = split_straddling_words([_word(f"{HAT}xk|joznaczono", 151.8, 225.7)], block)
        self.assertEqual([w[4] for w in words], [f"x{HAT}", "k|j", "oznaczono"])

    def test_math_without_accent_is_split_as_before(self):
        block = _block(_span("V*", 100.0, 110.0, "LatinModernMath"), _span("oznacza coś", 110.5, 170.0))
        words = split_straddling_words([_word("V*oznacza", 100.0, 150.0)], block)
        self.assertEqual([w[4] for w in words], ["V*", "oznacza"])

    def test_accent_already_in_the_span_text_stays_in_place(self):
        block = _block(_span(f"{HAT}S", 100.0, 110.0, "LatinModernMath"), _span("oznacza coś", 110.5, 170.0))
        words = split_straddling_words([_word(f"{HAT}Soznacza", 100.0, 150.0)], block)
        self.assertEqual([w[4] for w in words], [f"{HAT}S", "oznacza"])


if __name__ == "__main__":
    unittest.main()
