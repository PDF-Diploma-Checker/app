"""Decide what a release needs: nothing, a patch of the newest release, or a full build, for every platform and variant.

Usage (the release workflow runs it after every merge to main; gh must be logged in):

    python tools/release_plan.py                    # compare with the newest published release
    python tools/release_plan.py --force-full       # everything from scratch

The newest release says which commit its builds were made from (its notes end with "Built from <commit>"). What
changed in the code since then decides:
  - nothing that reaches the app (only tests, docs, tools, workflows): no release;
  - only our Python files, importing nothing that the build does not hold (tools/list_bundled_modules.py made a list
    of what it holds): a PATCH of that platform/variant - the changed files go on top of the base release, no build;
  - anything else (other libraries, new data files, the launcher, the spec, build scripts), or no list of modules
    for the base release: a FULL build of that platform/variant.
Prints the plan as JSON; in GitHub Actions it also writes the outputs the workflow needs.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))

import patch_code  # noqa: E402
from common.update_check import GITHUB_REPO  # noqa: E402
from list_bundled_modules import modules_name  # noqa: E402

PLATFORMS = ("linux", "windows")
VARIANTS = ("base", "cpu", "gpu")
NOT_RELEASED = patch_code.IGNORED + ("docker/", ".gitignore")   # a change only here does not reach the app
BUILT_FROM = re.compile(r"Built from ([0-9a-f]{7,40})")


def gh(*args):
    result = subprocess.run(["gh", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])}... failed: {(result.stderr or '').strip()}")
    return result.stdout


def keys():
    return [f"{platform}-{variant}" for platform in PLATFORMS for variant in VARIANTS]


def reaches_the_app(since, changes):
    """The changes that end up in a build: not tests, docs, tools, workflows, and not a bare version number."""
    relevant = []
    for status, path in changes:
        if path.startswith(NOT_RELEASED):
            continue
        if path in patch_code.VERSION_ONLY and patch_code.version_only_change(since, path):
            continue
        relevant.append((status, path))
    return relevant


def load_modules(directory, key):
    """The set of module names a build holds, or None when the base release has no list for it."""
    platform, variant = key.split("-")
    path = Path(directory) / modules_name(platform, variant)
    if not path.is_file():
        return None
    try:
        return set(json.loads(path.read_text(encoding="utf-8"))["modules"])
    except (ValueError, KeyError, TypeError):
        return None


def plan_variants(since, changes, modules_dir, force_full=False):
    """{key: {'mode': 'patch' | 'full', 'reasons': [...]}} for every platform-variant."""
    plan = {}
    for key in keys():
        if force_full:
            plan[key] = {"mode": "full", "reasons": ["a full build was asked for"]}
            continue
        modules = load_modules(modules_dir, key) if modules_dir else None
        if modules is None:
            plan[key] = {"mode": "full", "reasons": ["the base release has no list of the modules of this build"]}
            continue
        reasons = patch_code.needs_full_build(since, changes, bundled_names=modules)
        plan[key] = {"mode": "full" if reasons else "patch", "reasons": reasons}
    return plan


def classify(since, modules_dir, force_full=False):
    """(the changes that reach the app, plan_variants for them). Files that never reach a build (tests, workflows,
    docker, tools) are left out first: they must not make a variant need a full build."""
    changes = reaches_the_app(since, patch_code.changed_files(since))
    if not changes:
        return [], {}
    return changes, plan_variants(since, changes, modules_dir, force_full)


def is_ancestor(since):
    return subprocess.run(["git", "merge-base", "--is-ancestor", since, "HEAD"], cwd=ROOT).returncode == 0


def make_plan(repo, force_full=False, since=None, base_tag=None):
    version = patch_code.app_version()
    plan = {"version": version, "tag": f"v{version}", "base": None, "since": None, "skip": False, "reason": "",
            "head": subprocess.run(["git", "rev-parse", "--short=7", "HEAD"], cwd=ROOT, capture_output=True,
                                   text=True, check=True).stdout.strip(),
            "sha": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                                  check=True).stdout.strip(), "variants": {}}
    latest = json.loads(gh("api", f"repos/{repo}/releases/latest"))
    base_tag = base_tag or latest["tag_name"]
    if base_tag == plan["tag"]:
        plan.update(skip=True, reason=f"{plan['tag']} is already released")
        return plan
    plan["base"] = base_tag
    notes = latest.get("body") or "" if latest["tag_name"] == base_tag else ""
    match = BUILT_FROM.search(notes)
    since = since or (match.group(1) if match else None)
    if since and not is_ancestor(since):
        since = None
    plan["since"] = since
    if not since or force_full:
        why = "a full build was asked for" if force_full else f"the commit of {base_tag} is unknown"
        plan["variants"] = {key: {"mode": "full", "reasons": [why]} for key in keys()}
        return plan
    with tempfile.TemporaryDirectory() as folder:
        try:
            gh("release", "download", base_tag, "-R", repo, "-p", "*.modules.json", "-D", folder, "--clobber")
        except RuntimeError:
            pass
        changes, variants = classify(since, folder)
    if not changes:
        plan.update(skip=True, reason=f"nothing since {since} reaches the app")
        return plan
    plan["variants"] = variants
    return plan


def outputs(plan):
    """What the workflow needs, as name -> value (lists are comma separated)."""
    values = {"skip": str(plan["skip"]).lower(), "reason": plan["reason"], "version": plan["version"],
              "tag": plan["tag"], "base": plan["base"] or "", "since": plan["since"] or "", "head": plan["head"],
              "sha": plan["sha"]}
    chosen = plan["variants"]
    values["patch"] = ",".join(key for key in keys() if chosen.get(key, {}).get("mode") == "patch")
    for platform in PLATFORMS:
        full = [key.split("-")[1] for key in keys() if key.startswith(platform) and chosen.get(key, {}).get("mode") == "full"]
        values[f"full_{platform}"] = ",".join(full)
    return values


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=GITHUB_REPO)
    ap.add_argument("--force-full", action="store_true", help="build everything from scratch")
    ap.add_argument("--since", help="the commit of the base release (default: from its notes)")
    ap.add_argument("--base", help="the base release (default: the newest published one)")
    args = ap.parse_args(argv)

    plan = make_plan(args.repo, args.force_full, args.since, args.base)
    print(json.dumps(plan, indent=2))
    values = outputs(plan)
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with open(target, "a", encoding="utf-8") as f:
            for name, value in values.items():
                f.write(f"{name}={value}\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"### Release plan for {plan['tag']}\n\n")
            if plan["skip"]:
                f.write(f"No release: {plan['reason']}.\n")
            else:
                f.write(f"Base {plan['base']} (built from `{plan['since']}`), head `{plan['head']}`.\n\n")
                for key, item in plan["variants"].items():
                    f.write(f"- **{key}**: {item['mode']}" + (f" - {'; '.join(item['reasons'][:3])}" if item["reasons"] else "") + "\n")


if __name__ == "__main__":
    main()
