"""The tools of the automatic release: patching from a manifest, the plan (patch or full build), the module lists."""
import json
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from common import delta  # noqa: E402
import list_bundled_modules  # noqa: E402
import patch_code  # noqa: E402
import release_plan  # noqa: E402


def _write(base, files):
    for relative, content in files.items():
        path = Path(base) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode())
        path.chmod(0o644)


class PatchFromOverridesTest(unittest.TestCase):
    def test_same_result_as_patching_the_whole_build(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            build = {"DiplomaChecker": b"\x7fELF" + b"x" * 5000, "_internal/ui/a.py": "a = 1\n" * 50,
                     "_internal/ui/b.py": "b = 2\n" * 50, "_internal/lib/big.so": bytes(range(256)) * 400,
                     "_internal/VERSION.txt": "1.0.0\n"}
            _write(folder / "build", build)
            (folder / "build" / "DiplomaChecker").chmod(0o755)
            base = delta.build_pack(folder / "build", folder / "base", "linux", "base", "1.0.0", log=lambda *_: None)

            # what changed: a.py edited, c.py new, b.py gone, the version
            new = dict(build, **{"_internal/ui/a.py": "a = 99\n" * 50, "_internal/ui/c.py": "c = 3\n" * 50,
                                 "_internal/VERSION.txt": "1.0.1\n"})
            del new["_internal/ui/b.py"]
            _write(folder / "new", new)
            (folder / "new" / "DiplomaChecker").chmod(0o755)
            whole, changed_whole = delta.build_patch_pack(folder / "new", folder / "out_whole", "linux", "base", "1.0.1",
                                                          base, "v1.0.0", log=lambda *_: None)

            _write(folder / "over", {"_internal/ui/a.py": new["_internal/ui/a.py"],
                                     "_internal/ui/c.py": new["_internal/ui/c.py"],
                                     "_internal/VERSION.txt": "1.0.1\n"})
            part, changed_part = delta.build_patch_from_overrides(folder / "over", ["_internal/ui/b.py"],
                                                                  folder / "out_part", "linux", "base", "1.0.1", base,
                                                                  "v1.0.0", log=lambda *_: None)

            delta.validate_manifest(part)
            self.assertEqual(sorted(changed_part), sorted(changed_whole))
            by_path = lambda manifest: {f["p"]: (f["s"], f["h"], f["m"]) for f in manifest["files"]}
            self.assertEqual(by_path(part), by_path(whole))
            self.assertNotIn("_internal/ui/b.py", by_path(part))
            self.assertEqual(part["total"], whole["total"])
            # the untouched files still point into the base pack, the new part is the only one without a release
            self.assertEqual([p["name"] for p in part["parts"] if "release" not in p], [f"{delta.pack_name('linux', 'base')}.002"])
            self.assertTrue(all(p["release"] == "v1.0.0" for p in part["parts"] if "release" in p))

    def test_an_unchanged_file_in_the_overrides_is_not_packed_again(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            _write(folder / "build", {"_internal/a.py": "a = 1\n", "_internal/VERSION.txt": "1\n"})
            base = delta.build_pack(folder / "build", folder / "base", "linux", "base", "1", log=lambda *_: None)
            _write(folder / "over", {"_internal/a.py": "a = 1\n"})
            _, changed = delta.build_patch_from_overrides(folder / "over", [], folder / "out", "linux", "base", "2", base,
                                                          "v1", log=lambda *_: None)
            self.assertEqual(changed, [])


class ModuleNamesTest(unittest.TestCase):
    def test_module_names_from_paths(self):
        f = list_bundled_modules._module_from_path
        self.assertEqual(f("PySide6/QtWidgets.abi3.so"), "PySide6.QtWidgets")
        self.assertEqual(f("numpy/_core/_multiarray_umath.cp312-win_amd64.pyd"), "numpy._core._multiarray_umath")
        self.assertEqual(f("pkg/__init__.py"), "pkg")
        self.assertIsNone(f("numpy-2.0.dist-info/METADATA"))


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, encoding="utf-8").stdout.strip()


class PlanTest(unittest.TestCase):
    def setUp(self):
        self._folder = tempfile.TemporaryDirectory()
        self.addCleanup(self._folder.cleanup)
        self.repo = Path(self._folder.name)
        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.email", "t@t")
        _git(self.repo, "config", "user.name", "t")
        _write(self.repo, {"src/app/x.py": "import json\n", "src/app/launcher.py": "pass\n", "src/common/version.py":
                           'APP_VERSION = "1.0.0"\n', "pyproject.toml": 'name = "a"\nversion = "1.0.0"\n',
                           "uv.lock": 'name = "pdf-diploma-checker"\nversion = "1.0.0"\n',
                           "build_linux.sh": "#!/bin/sh\n", "unit_tests/t.py": "pass\n"})
        self.since = self.commit("base")
        for module in (patch_code, release_plan):
            old = module.ROOT
            module.ROOT = self.repo
            self.addCleanup(setattr, module, "ROOT", old)
        old_version_file = patch_code.VERSION_FILE
        patch_code.VERSION_FILE = self.repo / "src" / "common" / "version.py"
        self.addCleanup(setattr, patch_code, "VERSION_FILE", old_version_file)

    def commit(self, message):
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", message)
        return _git(self.repo, "rev-parse", "HEAD")

    def plan(self, modules=None):
        changes = patch_code.changed_files(self.since)
        with tempfile.TemporaryDirectory() as folder:
            for key in release_plan.keys():
                platform, variant = key.split("-")
                if modules is not None:
                    (Path(folder) / list_bundled_modules.modules_name(platform, variant)).write_text(
                        json.dumps({"modules": sorted(modules)}))
            return release_plan.reaches_the_app(self.since, changes), release_plan.plan_variants(self.since, changes, folder)

    def test_only_tests_and_tools_do_not_reach_the_app(self):
        _write(self.repo, {"unit_tests/t.py": "pass # changed\n", "tools/x.py": "pass\n", ".github/w.yml": "a: 1\n",
                           "docker/Dockerfile": "FROM x\n"})
        self.commit("tests")
        reaching, _ = self.plan({"json"})
        self.assertEqual(reaching, [])

    def test_a_bare_version_change_does_not_reach_the_app(self):
        _write(self.repo, {"pyproject.toml": 'name = "a"\nversion = "1.0.1"\n'})
        self.commit("version")
        self.assertEqual(self.plan({"json"})[0], [])

    def test_code_that_imports_what_the_build_holds_is_patched(self):
        _write(self.repo, {"src/app/x.py": "import json\nimport uuid\n"})
        self.commit("code")
        reaching, plan = self.plan({"json", "uuid"})
        self.assertTrue(reaching)
        self.assertTrue(all(item["mode"] == "patch" for item in plan.values()))

    def test_a_module_the_build_does_not_hold_needs_a_full_build(self):
        _write(self.repo, {"src/app/x.py": "import json\nimport requests_cache\n"})
        self.commit("code")
        _, plan = self.plan({"json", "uuid"})
        self.assertTrue(all(item["mode"] == "full" for item in plan.values()))
        self.assertIn("requests_cache", plan["linux-base"]["reasons"][0])

    def test_a_module_that_only_one_variant_holds_is_patched_only_there(self):
        _write(self.repo, {"src/app/x.py": "import json\nimport torch\n"})
        self.commit("code")
        changes = patch_code.changed_files(self.since)
        with tempfile.TemporaryDirectory() as folder:
            for key in release_plan.keys():
                platform, variant = key.split("-")
                modules = {"json", "torch"} if variant != "base" else {"json"}
                (Path(folder) / list_bundled_modules.modules_name(platform, variant)).write_text(
                    json.dumps({"modules": sorted(modules)}))
            plan = release_plan.plan_variants(self.since, changes, folder)
        self.assertEqual({key: item["mode"] for key, item in plan.items()},
                         {"linux-base": "full", "linux-cpu": "patch", "linux-gpu": "patch",
                          "windows-base": "full", "windows-cpu": "patch", "windows-gpu": "patch"})

    def test_a_docker_or_workflow_change_next_to_code_does_not_force_a_full_build(self):
        _write(self.repo, {"src/app/x.py": "import json\n# changed\n", "docker/build_in_container.sh": "#!/bin/sh\n",
                           ".github/workflows/w.yml": "a: 2\n", ".gitignore": "x\n"})
        self.commit("code and ci")
        with tempfile.TemporaryDirectory() as folder:
            for key in release_plan.keys():
                platform, variant = key.split("-")
                (Path(folder) / list_bundled_modules.modules_name(platform, variant)).write_text(
                    json.dumps({"modules": ["json"]}))
            changes, plan = release_plan.classify(self.since, folder)
        self.assertEqual([path for _, path in changes], ["src/app/x.py"])
        self.assertTrue(all(item["mode"] == "patch" for item in plan.values()))

    def test_launcher_and_build_scripts_need_a_full_build(self):
        _write(self.repo, {"src/app/launcher.py": "pass # changed\n", "build_linux.sh": "#!/bin/sh\n# changed\n"})
        self.commit("build")
        _, plan = self.plan({"json"})
        self.assertTrue(all(item["mode"] == "full" for item in plan.values()))

    def test_no_list_of_modules_means_a_full_build(self):
        _write(self.repo, {"src/app/x.py": "import json\n# changed\n"})
        self.commit("code")
        _, plan = self.plan(None)
        self.assertTrue(all(item["mode"] == "full" for item in plan.values()))

    def make_plan(self, latest_tag="v1.0.0", **kwargs):
        body = json.dumps({"tag_name": latest_tag, "body": f"Built from {self.since[:7]}"})
        with mock.patch.object(release_plan, "gh", side_effect=lambda *args: body if args[0] == "api" else ""):
            return release_plan.make_plan("o/r", **kwargs)

    def test_code_that_came_while_the_version_was_being_released_gets_the_next_version(self):
        _write(self.repo, {"src/app/x.py": "import json\n# the code of a later merge\n"})
        self.commit("ctrl+f")
        plan = self.make_plan()                                  # the version of the files is the released one
        self.assertFalse(plan["skip"])
        self.assertTrue(plan["bumped"])
        self.assertEqual((plan["version"], plan["tag"]), ("1.0.1", "v1.0.1"))
        for name, expected in (("src/common/version.py", 'APP_VERSION = "1.0.1"'), ("pyproject.toml", 'version = "1.0.1"'),
                               ("uv.lock", 'version = "1.0.1"')):
            self.assertIn(expected, (self.repo / name).read_text(encoding="utf-8"), name)

    def test_a_released_version_without_new_code_is_not_released_again(self):
        _write(self.repo, {"unit_tests/t.py": "pass # changed\n"})
        self.commit("tests")
        plan = self.make_plan()
        self.assertTrue(plan["skip"])
        self.assertFalse(plan["bumped"])
        self.assertIn('"1.0.0"', (self.repo / "src/common/version.py").read_text(encoding="utf-8"))

    def test_nothing_is_bumped_when_asked_not_to(self):
        _write(self.repo, {"src/app/x.py": "import json\n# later\n"})
        self.commit("later")
        self.assertTrue(self.make_plan(bump=False)["skip"])

    def test_outputs_for_the_workflow(self):
        plan = {"version": "1.0.1", "tag": "v1.0.1", "base": "v1.0.0", "since": "abc1234", "skip": False, "reason": "",
                "head": "def5678", "sha": "def5678" + "0" * 33, "variants": {key: {"mode": "patch", "reasons": []} for key in release_plan.keys()}}
        plan["variants"]["windows-gpu"] = {"mode": "full", "reasons": ["x"]}
        plan["variants"]["linux-base"] = {"mode": "full", "reasons": ["x"]}
        values = release_plan.outputs(plan)
        self.assertEqual(values["patch"], "linux-cpu,linux-gpu,windows-base,windows-cpu")
        self.assertEqual((values["full_linux"], values["full_windows"]), ("base", "gpu"))
        self.assertEqual(values["skip"], "false")


if __name__ == "__main__":
    unittest.main()
