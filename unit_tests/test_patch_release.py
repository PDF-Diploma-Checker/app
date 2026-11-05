"""A release with only the changed files, read by the updater over HTTP as a real update would."""

import http.server
import json
import os
import sys
import tempfile
import threading
import unittest
from functools import partial
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from common import delta, updater  # noqa: E402


class RangeHandler(http.server.SimpleHTTPRequestHandler):
    """Serves /releases/download/<tag>/<file> with HTTP Range, as GitHub does."""

    def log_message(self, *_):
        pass

    def do_GET(self):
        path = Path(self.translate_path(self.path))
        if not path.is_file():
            self.send_error(404)
            return
        data = path.read_bytes()
        wanted = self.headers.get("Range")
        if wanted:
            start, end = wanted.removeprefix("bytes=").split("-")
            data = data[int(start):int(end) + 1]
            self.send_response(206)
        else:
            self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def write_tree(root, files):
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def tree(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


class PatchReleaseTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.web = self.root / "web" / "releases" / "download"
        handler = partial(RangeHandler, directory=str(self.root / "web"))
        (self.root / "web").mkdir()
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.old_files = {"DiplomaChecker": b"exe" * 100, "_internal/ui/panel.py": b"old = 1\n" * 50,
                          "_internal/lib.so": os.urandom(5000), "_internal/removed.py": b"gone = 1\n"}
        self.new_files = {"DiplomaChecker": b"exe" * 100, "_internal/ui/panel.py": b"new = 2\n" * 50,
                          "_internal/lib.so": self.old_files["_internal/lib.so"], "_internal/added.py": b"added = 1\n"}

    def info(self, tag, version):
        directory = self.web / tag
        base = f"http://127.0.0.1:{self.server.server_address[1]}/releases/download/{tag}/"
        assets = [{"name": p.name, "size": p.stat().st_size, "url": base + p.name} for p in directory.iterdir()]
        return {"version": version, "assets": assets}

    def release(self, tag, version, build, base=None, base_tag=None):
        out = self.web / tag
        if base is None:
            return delta.build_pack(build, out, "linux", "base", version, log=lambda _: None)
        return delta.build_patch_pack(build, out, "linux", "base", version, base, base_tag, log=lambda _: None)

    def update(self, info, installed):
        plan = updater.plan_update(info, variant="base", platform="linux")
        new_root = self.root / "staged" / info["version"]
        work = delta.compute_delta(plan.manifest, installed, new_root)
        delta.stage_delta(plan.manifest, work, plan.pack_parts, new_root, lambda d, t: None, lambda: False)
        return new_root, work

    def test_only_changed_files_are_published_and_the_update_gives_the_new_build(self):
        v1, v2 = self.root / "v1", self.root / "v2"
        write_tree(v1, self.old_files)
        write_tree(v2, self.new_files)
        first = self.release("v0.4.1", "0.4.1", v1)
        manifest, changed = self.release("v0.4.2", "0.4.2", v2, first, "v0.4.1")

        self.assertEqual(sorted(changed), ["_internal/added.py", "_internal/ui/panel.py"])
        delta.validate_manifest(json.loads((self.web / "v0.4.2" / delta.manifest_name("linux", "base")).read_text()))
        published = sorted(p.name for p in (self.web / "v0.4.2").iterdir())
        self.assertEqual(published, [delta.manifest_name("linux", "base"), delta.pack_name("linux", "base") + ".002"])

        new_root, work = self.update(self.info("v0.4.2", "0.4.2"), v1)
        self.assertEqual(tree(new_root), self.new_files)
        self.assertEqual({e["p"] for e in work.need}, set(changed))

    def test_clean_install_takes_the_old_files_from_the_older_release(self):
        v1, v2 = self.root / "v1", self.root / "v2"
        write_tree(v1, self.old_files)
        write_tree(v2, self.new_files)
        first = self.release("v0.4.1", "0.4.1", v1)
        self.release("v0.4.2", "0.4.2", v2, first, "v0.4.1")
        empty = self.root / "empty"
        empty.mkdir()
        new_root, _ = self.update(self.info("v0.4.2", "0.4.2"), empty)
        self.assertEqual(tree(new_root), self.new_files)

    def test_chain_of_two_patches_keeps_each_part_with_its_release(self):
        v1, v2, v3 = self.root / "v1", self.root / "v2", self.root / "v3"
        write_tree(v1, self.old_files)
        write_tree(v2, self.new_files)
        third = {**self.new_files, "_internal/ui/panel.py": b"third = 3\n"}
        write_tree(v3, third)
        first = self.release("v0.4.1", "0.4.1", v1)
        second, _ = self.release("v0.4.2", "0.4.2", v2, first, "v0.4.1")
        manifest, _ = self.release("v0.4.3", "0.4.3", v3, second, "v0.4.2")
        self.assertEqual([p.get("release") for p in manifest["parts"]], ["v0.4.1", "v0.4.2", None])
        new_root, _ = self.update(self.info("v0.4.3", "0.4.3"), v1)
        self.assertEqual(tree(new_root), third)

    def test_nothing_changed_gives_no_new_part(self):
        v1 = self.root / "v1"
        write_tree(v1, self.old_files)
        first = self.release("v0.4.1", "0.4.1", v1)
        manifest, changed = self.release("v0.4.2", "0.4.2", v1, first, "v0.4.1")
        self.assertEqual(changed, [])
        self.assertEqual(len(manifest["parts"]), len(first["parts"]))


if __name__ == "__main__":
    unittest.main()
