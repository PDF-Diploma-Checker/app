"""The thesis assistant runs in its own process, like the AI part of the analysis (see app/llm_process.py): llama.cpp
fails in native code (out of video memory, a driver error) by ending the process. Here that ends only the assistant;
the app tells the user what happened and the next question starts it again with fewer layers on the graphics card.

The process stays alive between questions (loading the 12B model takes tens of seconds) and is stopped:
- when an analysis starts (it needs the video memory itself),
- after IDLE_MINUTES without a question (the video memory is given back),
- when the app closes.

Messages app -> process:   ("open", pdf_path, summaries) | ("ask", qid, question, history, language) | ("stop",)
Messages process -> app:   ("log", record) | ("status", text) | ("ready", info) | ("partial", qid, text)
                           | ("answer", qid, result) | ("failed", qid or None, text)
A question is cancelled through an Event (the generation stops within a token, see llama_factory).
"""

import logging
import os
import threading
import time
import traceback

from common import run_control
from common.cancellation import AnalysisCancelled, CancelToken

logger = logging.getLogger(__name__)

STDERR_LOG_NAME = "assistant_process.log"
IDLE_MINUTES = 10
FRAGMENTS_PER_ATTEMPT = 8       # more fragments at once make the model miss the one that answers
N_THREADS = max((os.cpu_count() or 4) - 1, 1)


# =========================================================================== availability
def availability():
    """(available, reason): the assistant works only in the GPU mode with the text model downloaded.
    reason is a key of "assistant" in the translations, or None."""
    try:
        from analysis.modules.llm import config
    except Exception:
        return False, "assistant.off_no_ai"
    if not config.llm_runtime_available():
        return False, "assistant.off_no_ai"
    if config.DEVICE != "cuda" or not config.N_GPU_LAYERS:
        return False, "assistant.off_cpu"
    from common import gpu_check
    if not gpu_check.llama_gpu_support():
        return False, "assistant.off_cpu"
    if not config.MODEL_PATH.is_file() or config.embedding_path() is None:
        return False, "assistant.off_models"
    return True, None


def context_size(vram_gb):
    """Tokens of context for a card with this much memory: the model takes about 8 GB, every 1024 tokens of context
    some 0.4 GB more. A smaller context means fewer fragments of the thesis per answer, not a failure."""
    if vram_gb >= 15.5:
        return 8192
    if vram_gb >= 11:
        return 6144
    return 4096


# =========================================================================== child process
class _Assistant:
    def __init__(self, send, gpu_layers):
        self.send = send
        self.gpu_layers = gpu_layers
        self.llm = None
        self.n_ctx = 4096
        self.encoder = None
        self.index = None
        self.summaries = []

    # -------------------------------------------------------------- models
    def _encode(self, texts):
        if self.encoder is None:
            from sentence_transformers import SentenceTransformer
            from analysis.modules.llm import config
            # on the processor: the video memory is for the language model, and these fragments are short
            self.encoder = SentenceTransformer(config.resolve_embedding_model(), device="cpu")
        return self.encoder.encode(list(texts), batch_size=32, normalize_embeddings=True, show_progress_bar=False)

    def _model(self):
        if self.llm is None:
            from analysis.modules.llm import config
            from analysis.modules.llm.llama_factory import make_llama
            from common import gpu_check
            from ui.i18n import t
            gpus = gpu_check.nvidia_gpus()
            self.n_ctx = context_size(gpus[0]["vram_gb"] if gpus else 0)
            self.send(("status", t("assistant.loading_model")))
            self.llm = make_llama(purpose="assistant", model_path=str(config.MODEL_PATH), n_ctx=self.n_ctx,
                                  n_threads=N_THREADS, n_batch=512, n_gpu_layers=self.gpu_layers,
                                  chat_format="gemma", verbose=False)
            logger.info("Assistant model ready: context %s tokens, GPU layers %s", self.n_ctx, self.gpu_layers)
        return self.llm

    def _count(self, text):
        return len(self.llm.tokenize(str(text).encode("utf-8"), add_bos=False, special=False))

    # -------------------------------------------------------------- jobs
    def open(self, pdf_path, summaries):
        from analysis.modules.llm import config
        from analysis.modules.llm.assistant.chunks import build_chunks
        from analysis.modules.llm.assistant.retrieval import ThesisIndex, index_key
        from common.path import DATA_DIR
        from ui.i18n import t

        self.summaries = list(summaries or [])
        folder = DATA_DIR / "assistant" / index_key(pdf_path, config.EMBEDDING_MODEL)
        index = ThesisIndex.load(folder)
        if index is None:
            self.send(("status", t("assistant.reading")))
            from analysis.extraction.main_extractor import extractPDF
            from analysis.extraction.linguistics_conversion.converter_linguistics_clean import PDFMapper
            document = PDFMapper().map_to_schema(extractPDF(pdf_path))
            data = build_chunks(document)
            self.send(("status", t("assistant.indexing", n=len(data["chunks"]))))
            index = ThesisIndex.build(data, self._encode)
            try:
                index.save(folder)
            except OSError:
                logger.warning("The assistant index could not be saved in %s", folder, exc_info=True)
        self.index = index
        logger.info("Assistant: %s fragments of %s", len(index.chunks), os.path.basename(pdf_path))
        self.send(("ready", {"chunks": len(index.chunks), "summaries": len(self.summaries)}))

    def _phrases(self, question, language):
        """Search phrases the model writes for the question (the words the thesis would use); [] on any problem."""
        from analysis.modules.llm.assistant import answer as A
        try:
            reply = self.llm.create_chat_completion(messages=A.expansion_messages(question, language),
                                                    temperature=0.0, max_tokens=A.EXPANSION_TOKENS)
            phrases = A.parse_expansion(reply["choices"][0]["message"]["content"])
        except AnalysisCancelled:
            raise
        except Exception:
            logger.warning("Assistant: no search phrases for the question", exc_info=True)
            return []
        logger.info("Assistant search phrases: %s", phrases)
        return phrases

    def _generate(self, qid, messages, max_tokens):
        text, last_sent = "", 0.0
        for part in self.llm.create_chat_completion(messages=messages, temperature=0.1, top_p=0.9,
                                                    repeat_penalty=1.1, max_tokens=max_tokens, stream=True):
            delta = (part.get("choices") or [{}])[0].get("delta", {}).get("content") or ""
            if delta:
                text += delta
                now = time.monotonic()
                if now - last_sent > 0.15:
                    self.send(("partial", qid, text))
                    last_sent = now
        return text

    def ask(self, qid, question, history, language):
        from analysis.modules.llm.assistant import answer as A
        from ui.i18n import t

        question = A.clean_question(question)
        if self.index is None:
            raise RuntimeError("no document")
        whole = A.is_whole_thesis_question(question)
        boost = A.combine_boosts(A.overview_boost if whole else None, A.count_boost(question))
        first_look = self.index.search(question, self._encode, k=10, boost=boost)
        if A.nothing_relevant(first_look) and not whole:
            # nothing in the thesis is near the question: no model, no chance to invent an answer
            self.send(("answer", qid, {"text": A.NOT_FOUND.get(language, A.NOT_FOUND["pl"]), "kind": "not_found",
                                       "sources": []}))
            return
        self._model()
        self.send(("status", t("assistant.thinking")))
        # the question and the thesis often say one thing in different words: the model adds the words the answer
        # would be written with, and the fragments are searched with all of them
        queries = [question] + self._phrases(question, language)
        found = self.index.search_many(queries, self._encode, k=2 * FRAGMENTS_PER_ATTEMPT, boost=boost)
        budget = self.n_ctx - A.ANSWER_TOKENS - 96
        result, sources, shown = None, {}, set()
        for attempt in range(2):
            remaining = [item for item in found if item[0]["id"] not in shown]
            if not remaining:
                break
            if attempt:
                # the best fragments did not hold the answer: once more with the next ones
                self.send(("status", t("assistant.searching_more")))
                self.send(("partial", qid, ""))
            messages, sources = A.build_messages(question, remaining[:FRAGMENTS_PER_ATTEMPT],
                                                 self.summaries if whole else [], history, language, self._count,
                                                 budget)
            shown |= {source["chunk"]["id"] for source in sources.values() if "chunk" in source}
            result = A.check_answer(self._generate(qid, messages, A.ANSWER_TOKENS), sources, language)
            if result["kind"] != "not_found":
                break
        result["sources"] = [A.source_view(key, sources[key], self.index.sections) for key in result["citations"]]
        self.send(("answer", qid, result))


def _child_main(conn, cancel_event, gpu_layers, language, stderr_path):
    """Entry point of the assistant process."""
    from app.llm_process import _PipeLogHandler, _redirect_native_stderr, _route_llama_log

    lock = threading.Lock()

    def send(message):
        with lock:
            try:
                conn.send(message)
            except (OSError, EOFError):
                pass

    stream = _redirect_native_stderr(stderr_path)
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.addHandler(_PipeLogHandler(send))
    root.setLevel(logging.INFO)
    _route_llama_log(stream)
    logger.info("Assistant process %s started (GPU layers: %s)", os.getpid(), gpu_layers)

    assistant = _Assistant(send, gpu_layers)
    while True:
        try:
            message = conn.recv()
        except (EOFError, OSError):
            break
        kind = message[0]
        if kind == "stop":
            break
        qid = message[1] if kind == "ask" else None
        token = CancelToken()
        cancel_event.clear()
        done = threading.Event()

        def watch(token=token, done=done):
            while not done.is_set():
                if cancel_event.wait(0.2):
                    token.cancel()
                    return

        threading.Thread(target=watch, daemon=True).start()
        run_control.bind(token, None)
        try:
            if kind == "open":
                assistant.open(message[1], message[2])
            elif kind == "ask":
                assistant.ask(*message[1:])
        except AnalysisCancelled:
            send(("answer", qid, {"text": "", "kind": "cancelled", "sources": []}))
        except BaseException as error:
            logger.exception("The assistant failed")
            send(("failed", qid, f"{type(error).__name__}: {error}", traceback.format_exc()))
        finally:
            done.set()
            run_control.unbind()
            try:
                stream.flush()
            except Exception:
                pass
    conn.close()


# =========================================================================== app side
class AssistantClient:
    """Starts the assistant process on demand and talks to it. `on_event(message)` is called from a reader thread
    with the messages of the process and ("crashed", text) when it died; the UI must hop to its own thread."""

    def __init__(self, on_event, language="pl"):
        self.on_event = on_event
        self.language = language
        self.process = None
        self.conn = None
        self.cancel_event = None
        self.gpu_layers = None
        self.last_used = time.monotonic()
        self._lock = threading.Lock()
        self._stopping = False
        self._document = None       # the open thesis, opened again in a new process (after a crash or an unload)

    def running(self):
        return self.process is not None and self.process.is_alive()

    def _start(self):
        import multiprocessing
        from analysis.modules.llm import config
        from app.llm_process import stderr_log_path

        if self.gpu_layers is None:
            self.gpu_layers = config.N_GPU_LAYERS
        ctx = multiprocessing.get_context("spawn")
        self.conn, child = ctx.Pipe(duplex=True)
        self.cancel_event = ctx.Event()
        self.process = ctx.Process(target=_child_main, name="assistant", daemon=True,
                                   args=(child, self.cancel_event, self.gpu_layers, self.language,
                                         str(stderr_log_path(STDERR_LOG_NAME))))
        self._stopping = False
        self.process.start()
        child.close()
        logger.info("Assistant process %s started (GPU layers: %s)", self.process.pid, self.gpu_layers)
        threading.Thread(target=self._read, args=(self.process, self.conn), name="assistant-reader",
                         daemon=True).start()

    def _read(self, process, conn):
        from app.llm_process import _forward_log
        while True:
            try:
                message = conn.recv()
            except (EOFError, OSError):
                break
            if message[0] == "log":
                _forward_log(message[1])
                continue
            self.on_event(message)
        process.join(timeout=5)
        if not self._stopping and process is self.process:
            self.on_event(("crashed", self._crash_text(process.exitcode)))
            self.process = None

    def _crash_text(self, exit_code):
        from app.llm_process import _fewer_layers, diagnose_crash, describe_exit_code, read_tail, stderr_log_path
        tail = read_tail(stderr_log_path(STDERR_LOG_NAME))
        kind, hint = diagnose_crash(exit_code, tail, self.gpu_layers)
        logger.error("The assistant process ended (%s, %s): %s", describe_exit_code(exit_code), kind, tail[-1500:])
        if kind in ("oom", "cuda", "unknown", "assert") and self.gpu_layers:
            self.gpu_layers = _fewer_layers(self.gpu_layers)       # the next question tries with less on the card
        return hint

    def _send(self, message):
        with self._lock:
            if not self.running():
                self._start()
                if message[0] != "open" and self._document is not None:
                    self.conn.send(("open",) + self._document)
            self.last_used = time.monotonic()
            self.conn.send(message)

    def open_document(self, pdf_path, summaries=None):
        self._document = (str(pdf_path), list(summaries or []))
        self._send(("open",) + self._document)

    def forget_document(self):
        self._document = None

    def ask(self, qid, question, history, language):
        self._send(("ask", qid, question, list(history or []), language))

    def cancel(self):
        if self.cancel_event is not None:
            self.cancel_event.set()

    def idle_for(self):
        return time.monotonic() - self.last_used

    def stop(self):
        """Ends the process and frees its memory (on the GPU too)."""
        with self._lock:
            process, conn = self.process, self.conn
            self._stopping = True
            self.process = None
            if process is None:
                return
            try:
                self.cancel()
                conn.send(("stop",))
            except (OSError, EOFError, BrokenPipeError):
                pass
            process.join(timeout=3)
            if process.is_alive():
                process.kill()
                process.join(timeout=3)
            try:
                conn.close()
            except OSError:
                pass
            logger.info("Assistant process stopped")
