"""Which words a rectangle drawn on a page selects, and what the selection box should show afterwards.

A word is selected when its centre is inside the rectangle: simple to predict for the person drawing it, the same for
every rectangle, independent of where the edges fall (in the margin, between two words, through a letter)."""


def select_words(words, rect):
    """`words`: PyMuPDF word tuples (x0, y0, x1, y1, text, block, line, word); `rect`: (x0, y0, x1, y1) in the same
    units. Returns (text, bounds): the selected words in reading order joined by spaces, and the rectangle that
    holds exactly those words (None when no word is selected)."""
    left, top, right, bottom = rect
    chosen = [w for w in words
              if left <= (w[0] + w[2]) / 2 <= right and top <= (w[1] + w[3]) / 2 <= bottom and str(w[4]).strip()]
    if not chosen:
        return "", None
    chosen.sort(key=lambda w: (w[5], w[6], w[7]))
    text = " ".join(str(w[4]) for w in chosen)
    bounds = (min(w[0] for w in chosen), min(w[1] for w in chosen),
              max(w[2] for w in chosen), max(w[3] for w in chosen))
    return text, bounds
