"""Address of the problem-report relay (a Cloudflare Worker, see relay/README.md).

This is a public URL, not a secret: the mail credentials live on the relay, never in the app.
Leave it empty to turn "Report a problem" off in a build.
"""

REPORT_URL = "https://diploma-checker-report.diplomachecker.workers.dev/report"