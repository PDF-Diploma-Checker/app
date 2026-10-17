"""Check whether a newer release is published. No Qt here, so it can be tested on its own.

The app asks the GitHub API for the latest release of the repository that holds the downloads.
Only a version number is read; nothing is downloaded or installed, the user gets a link to the download page.
Any failure (no internet, rate limit, unexpected answer) simply means "no update known".
"""

import logging
import re

import requests

from common.version import APP_VERSION

logger = logging.getLogger(__name__)

GITHUB_REPO = "PDF-Diploma-Checker/diploma-checker-download"
API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"   # newest published, non-draft, non-pre-release
DOWNLOAD_PAGE_URL = "https://pdf-diploma-checker.github.io/diploma-checker-download/"
REQUEST_TIMEOUT_S = (5, 10)   # connect, read

_VERSION_RE = re.compile(r"^\s*v?(\d+(?:\.\d+){0,3})")


def parse_version(text):
    """"v1.2.3", "1.2" or "1.2.3-rc1" -> (1, 2, 3); None when the text does not start with a version."""
    match = _VERSION_RE.match(str(text or ""))
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def is_newer(candidate, current):
    """True when version `candidate` is higher than `current` (missing parts count as 0). Unparsable -> False."""
    a, b = parse_version(candidate), parse_version(current)
    if a is None or b is None:
        return False
    size = max(len(a), len(b))
    return a + (0,) * (size - len(a)) > b + (0,) * (size - len(b))


def check_for_update(current=APP_VERSION):
    """Return {"version": "0.3.0", "tag": "v0.3.0", "current": "0.2.0"} when a newer release exists, else None."""
    try:
        response = requests.get(
            API_URL,
            headers={"Accept": "application/vnd.github+json", "User-Agent": f"DiplomaChecker/{current}"},
            timeout=REQUEST_TIMEOUT_S,
        )
        if response.status_code != 200:     # 404 = no release yet, 403 = rate limit
            logger.info("Update check: GitHub answered %s", response.status_code)
            return None
        tag = str(response.json().get("tag_name", ""))
    except (requests.RequestException, ValueError, AttributeError) as e:
        logger.info("Update check skipped: %r", e)
        return None

    parsed = parse_version(tag)
    if parsed is None or not is_newer(tag, current):
        logger.info("Update check: latest release %r, this build %s, nothing to offer", tag, current)
        return None
    version = ".".join(str(part) for part in parsed)
    logger.info("Update check: version %s is available (this build %s)", version, current)
    return {"version": version, "tag": tag, "current": current}
