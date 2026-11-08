"""What the executable itself runs in a build. Everything else is plain files in _internal, so an update can change
all our code without touching the executable; keep this file this small."""

import os
import sys

# Windowed build has no console: stdout/stderr are None and break tqdm & co.
for _name in ("stdout", "stderr"):
    if getattr(sys, _name) is None:
        setattr(sys, _name, open(os.devnull, "w", encoding="utf-8"))

from app.main import run

run()
