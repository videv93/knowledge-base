"""Centralized environment variable loading and validation.

All configuration access MUST go through this module.
Raises RuntimeError at import time if required variables are missing.
"""

import os

_REQUIRED_VARS = [
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
]

def _validate_required():
    """Validate all required environment variables are present. Raises RuntimeError if any missing."""
    missing = [var for var in _REQUIRED_VARS if not os.environ.get(var)]
    if missing:
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing)}. "
            f"Set them in your .env file or environment."
        )


# Fail fast at import time — raises RuntimeError if required vars missing
_validate_required()

# Required
POSTGRES_HOST = os.environ["POSTGRES_HOST"]
POSTGRES_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.environ["POSTGRES_DB"]
POSTGRES_USER = os.environ["POSTGRES_USER"]
POSTGRES_PASSWORD = os.environ["POSTGRES_PASSWORD"]

# Optional — empty defaults are fine
CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY", "")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
OPENCLAW_BASE_URL = os.environ.get("OPENCLAW_BASE_URL", "")
BEEHIIV_API_KEY = os.environ.get("BEEHIIV_API_KEY", "")
BEEHIIV_PUBLICATION_ID = os.environ.get("BEEHIIV_PUBLICATION_ID", "")
VAULT_REPO_URL = os.environ.get("VAULT_REPO_URL", "")
VAULT_REPO_SSH_KEY_PATH = os.environ.get("VAULT_REPO_SSH_KEY_PATH", "")
VAULT_LOCAL_PATH = os.environ.get("VAULT_LOCAL_PATH", "/tmp/vault-clone")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

# Optional — alerting (email + Slack). Leave blank to disable.
ALERT_EMAIL = os.environ.get("ALERT_EMAIL") or None
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL") or None
try:
    CLAUDE_CONCURRENCY = int(os.environ.get("CLAUDE_CONCURRENCY", "4"))
except ValueError:
    CLAUDE_CONCURRENCY = 4
