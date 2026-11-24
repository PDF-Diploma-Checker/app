"""The thesis assistant: questions about the opened thesis, answered by the text model from fragments of the thesis
(retrieval-augmented generation), with the page of every fragment it used.

    chunks.py     the thesis cut into fragments that keep their page and their place on it
    retrieval.py  finding the fragments for a question (words + meaning), the index saved next to the documents
    answer.py     the prompt, the context budget and the checks of the answer (sources, "not in the thesis")

Only answer.py's prompt building and the checks are free of heavy imports; the embedding model and llama.cpp are
used by app/assistant_process.py, in its own process.
"""
