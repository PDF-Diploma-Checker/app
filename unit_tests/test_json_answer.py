"""Answers of the text model: JSON read from plain text, JSON mode only as the fallback."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from analysis.modules.llm.json_answer import chat_json, parse_json_answer  # noqa: E402


class FakeLlm:
    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def create_chat_completion(self, messages, **kwargs):
        self.calls.append(kwargs)
        return {"choices": [{"message": {"content": self.answers.pop(0)}}]}


class ParseTest(unittest.TestCase):
    def test_plain_object(self):
        self.assertEqual(parse_json_answer('{"zwiazany": true, "uzasadnienie": "tak"}'), {"zwiazany": True, "uzasadnienie": "tak"})

    def test_fenced_object(self):
        self.assertEqual(parse_json_answer('```json\n{"wynik": false}\n```'), {"wynik": False})
        self.assertEqual(parse_json_answer('```\n{"wynik": false}\n```'), {"wynik": False})

    def test_object_with_words_around_it(self):
        self.assertEqual(parse_json_answer('Oto odpowiedź: {"wynik": true} Mam nadzieję, że pomogłem.'), {"wynik": True})

    def test_text_in_braces_before_the_object(self):
        self.assertEqual(parse_json_answer('{nie json} a potem {"wynik": true}'), {"wynik": True})

    def test_no_object(self):
        for text in ("", None, "bez obiektu", "[1, 2]", "{broken"):
            self.assertIsNone(parse_json_answer(text), text)


class ChatJsonTest(unittest.TestCase):
    def test_a_parsable_answer_costs_one_plain_call(self):
        llm = FakeLlm('```json\n{"wynik": true}\n```')
        data, _ = chat_json(llm, [], temperature=0.0, response_format={"type": "json_object"})
        self.assertEqual(data, {"wynik": True})
        self.assertEqual(len(llm.calls), 1)
        self.assertNotIn("response_format", llm.calls[0])         # no grammar: that is the slow part

    def test_an_unparsable_answer_is_asked_again_in_json_mode(self):
        llm = FakeLlm("nie wiem", '{"wynik": false}')
        data, _ = chat_json(llm, [], temperature=0.0)
        self.assertEqual(data, {"wynik": False})
        self.assertEqual(llm.calls[1]["response_format"], {"type": "json_object"})

    def test_no_object_even_in_json_mode(self):
        data, text = chat_json(FakeLlm("a", "b"), [])
        self.assertIsNone(data)
        self.assertEqual(text, "b")


if __name__ == "__main__":
    unittest.main()
