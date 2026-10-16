"""Fail on top-level imports of modules that live inside src/ packages (break in PyInstaller)."""
import ast
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
roots = {p.name for p in SRC.iterdir() if p.is_dir()}
stems = {p.stem for p in SRC.rglob("*.py")} - {"__init__", "main"} - roots - set(sys.stdlib_module_names)

bad = 0
for f in SRC.rglob("*.py"):
    for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"), str(f))):
        if isinstance(node, ast.Import):
            names = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module.split(".")[0]]
        else:
            continue
        for n in names:
            if n in stems:
                print(f"{f.relative_to(SRC)}:{node.lineno}: top-level import '{n}'")
                bad += 1
sys.exit(1 if bad else 0)