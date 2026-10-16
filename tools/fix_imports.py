"""Rewrite top-level imports of modules that live inside src/ (they break in PyInstaller).

    python tools/fix_imports.py          # dry run, only prints the planned changes
    python tools/fix_imports.py --apply  # writes the files

`from config import X` becomes `from analysis.modules.llm.config import X`.
The module is picked the way the old sys.path hack resolved it: a file in the same folder
first, then in a parent folder, then a unique match anywhere in src/. Ambiguous cases are listed
and left untouched, so nothing is guessed."""
import ast
import re
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
APPLY = "--apply" in sys.argv

roots = {p.name for p in SRC.iterdir() if p.is_dir()}
by_stem = {}
for f in SRC.rglob("*.py"):
    if f.stem in {"__init__", "main"} or f.stem in roots or f.stem in sys.stdlib_module_names:
        continue
    by_stem.setdefault(f.stem, []).append(f)


def dotted(path):
    return ".".join(path.relative_to(SRC).with_suffix("").parts)


def resolve(importer, name):
    cands = by_stem.get(name, [])
    if not cands:
        return None, "no such file in src/"
    here = [c for c in cands if c.parent == importer.parent]
    if here:
        return here[0], None
    for parent in importer.parents:
        if SRC not in parent.parents and parent != SRC:
            break
        up = [c for c in cands if c.parent == parent]
        if up:
            return up[0], None
    if len(cands) == 1:
        return cands[0], None
    return None, "ambiguous: " + ", ".join(str(c.relative_to(SRC)) for c in cands)


changed = skipped = 0
for f in sorted(SRC.rglob("*.py")):
    text = f.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    edits = []
    for node in ast.walk(ast.parse(text, str(f))):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            name = node.module.split(".")[0]
            if name not in by_stem:
                continue
            target, why = resolve(f, name)
            if not target:
                print(f"SKIP {f.relative_to(SRC)}:{node.lineno}: {name} ({why})")
                skipped += 1
                continue
            rest = node.module.split(".")[1:]
            new_mod = ".".join([dotted(target)] + rest)
            edits.append((node.lineno, re.compile(rf"\bfrom\s+{re.escape(node.module)}\b"), f"from {new_mod}"))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name.split(".")[0]
                if name not in by_stem:
                    continue
                target, why = resolve(f, name)
                if not target or len(node.names) != 1 or "." in alias.name:
                    print(f"SKIP {f.relative_to(SRC)}:{node.lineno}: import {alias.name} (fix by hand)")
                    skipped += 1
                    continue
                pkg = ".".join(dotted(target).split(".")[:-1])
                tail = f" as {alias.asname}" if alias.asname else ""
                new = f"from {pkg} import {name}{tail}" if pkg else None
                if new:
                    edits.append((node.lineno, re.compile(rf"\bimport\s+{re.escape(alias.name)}(\s+as\s+\w+)?"), new))
    if not edits:
        continue
    for lineno, pattern, replacement in sorted(edits, reverse=True):
        old = lines[lineno - 1]
        new_line, n = pattern.subn(replacement, old, count=1)
        if n:
            print(f"{f.relative_to(SRC)}:{lineno}: {old.strip()}  ->  {new_line.strip()}")
            lines[lineno - 1] = new_line
            changed += 1
    if APPLY:
        f.write_text("".join(lines), encoding="utf-8")

print(f"\n{changed} change(s), {skipped} skipped.", "Written." if APPLY else "Dry run: add --apply to write.")