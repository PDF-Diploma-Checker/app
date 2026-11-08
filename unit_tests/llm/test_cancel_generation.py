import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

try:
    from llama_cpp import Llama
    from analysis.modules.llm.llama_factory import _CancellableLlama
except ImportError as error:
    raise unittest.SkipTest(f"AI libraries are not available: {error}")

from common import run_control
from common.cancellation import AnalysisCancelled, CancelToken


class CancelGenerationTest(unittest.TestCase):
    def setUp(self):
        self.token = CancelToken()
        run_control.bind(self.token)
        self.addCleanup(run_control.unbind)
        self.llm = object.__new__(_CancellableLlama)    # no model is needed for this
        self.llm._stack = mock.Mock()                   # what Llama.__del__ closes

    def test_plain_prompt_gets_the_cancel_check(self):
        """The summaries call llm(prompt), which goes through create_completion and not through the chat API."""
        with mock.patch.object(Llama, "create_completion", return_value={"choices": []}) as generate:
            self.llm.create_completion("prompt")
        self.assertIn(self.llm._cancel_processor, generate.call_args.kwargs["logits_processor"])

    def test_chat_goes_on_to_get_it_once(self):
        def chat(_self=None, *args, **kwargs):
            return self.llm.create_completion("prompt", logits_processor=kwargs["logits_processor"])

        with mock.patch.object(Llama, "create_chat_completion", side_effect=chat), \
                mock.patch.object(Llama, "create_completion", return_value={}) as generate:
            self.llm.create_chat_completion(messages=[])
        self.assertEqual(list(generate.call_args.kwargs["logits_processor"]).count(self.llm._cancel_processor), 1)

    def test_cancelled_before_the_start(self):
        self.token.cancel()
        with mock.patch.object(Llama, "create_completion") as generate, self.assertRaises(AnalysisCancelled):
            self.llm.create_completion("prompt")
        generate.assert_not_called()

    def test_cut_off_answer_is_not_used(self):
        def cancel_during(*args, **kwargs):
            self.token.cancel()
            return {"choices": [{"text": "cut"}]}

        with mock.patch.object(Llama, "create_completion", side_effect=cancel_during), self.assertRaises(AnalysisCancelled):
            self.llm.create_completion("prompt")


if __name__ == "__main__":
    unittest.main()
