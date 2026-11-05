"""A release may keep only its new pack parts and take the others from an older release."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from common import delta, updater  # noqa: E402

BASE = "https://github.com/org/repo/releases/download"
OLD_PACK = "DiplomaChecker-linux-gpu.pack.001"
NEW_PACK = "DiplomaChecker-linux-gpu.pack.002"
MANIFEST = "DiplomaChecker-linux-gpu.manifest.json"


def manifest(old_part=None):
    old = {"name": OLD_PACK, "size": 100, **(old_part if old_part is not None else {"release": "v0.4.1"})}
    return {
        "format": delta.FORMAT, "version": "0.4.2", "total": 150,
        "parts": [old, {"name": NEW_PACK, "size": 50}],
        "files": [
            {"p": "DiplomaChecker", "s": 1, "o": 0, "c": 1, "h": "a" * 64, "z": "store"},
            {"p": "_internal/x.py", "s": 1, "o": 100, "c": 1, "h": "b" * 64, "z": "store"},
        ],
        "links": [],
    }


def info(*names):
    assets = [{"name": n, "size": 50, "url": f"{BASE}/v0.4.2/{n}"} for n in (MANIFEST, *names)]
    return {"version": "0.4.2", "assets": assets}


class OlderReleasePartsTest(unittest.TestCase):
    def plan(self, data, release):
        response = mock.Mock()
        response.json.return_value = data
        with mock.patch.object(updater.requests, "get", return_value=response):
            return updater.plan_update(release, variant="gpu", platform="linux")

    def test_part_comes_from_the_named_release(self):
        plan = self.plan(manifest(), info(NEW_PACK))
        self.assertEqual([p["url"] for p in plan.pack_parts],
                         [f"{BASE}/v0.4.1/{OLD_PACK}", f"{BASE}/v0.4.2/{NEW_PACK}"])
        self.assertEqual(plan.parts, [])
        self.assertEqual(plan.full_size, 150)

    def test_part_without_a_release_has_to_be_published(self):
        with self.assertRaises(updater.UpdateError) as caught:
            self.plan(manifest(old_part={}), info(NEW_PACK))
        self.assertEqual(caught.exception.code, "no_asset")

    def test_full_archive_stays_the_fallback(self):
        archive = updater.archive_name("linux", "gpu")
        plan = self.plan(manifest(old_part={}), info(NEW_PACK, archive))
        self.assertIsNone(plan.manifest)
        self.assertEqual([p["name"] for p in plan.parts], [archive])

    def test_release_name_cannot_leave_the_download_folder(self):
        for tag in ("../../evil", "v1/../../evil", "https://evil.example", "main"):
            with self.subTest(tag=tag), self.assertRaises(updater.UpdateError):
                delta.validate_manifest(manifest(old_part={"release": tag}))


if __name__ == "__main__":
    unittest.main()
