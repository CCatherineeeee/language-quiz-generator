"""Owner login (decision log #5: no password auth, no accounts).

Every visitor IS the Demo user until proven otherwise. The owner visits
/login?key=<OWNER_SECRET> once; that sets a cookie whose value is an HMAC
signature (a keyed hash: computable only with the secret, so it can't be
forged, and verified by just recomputing it — no session table). /logout
clears it.

If OWNER_SECRET is still the placeholder default, login is disabled
entirely — a deploy that forgot to set the env var must not have a
guessable owner key.
"""

import hmac
from hashlib import sha256

from app.config import settings

COOKIE_NAME = "lqg_owner"
COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # re-login monthly
OWNER_USER_ID = 1
DEMO_USER_ID = 2

_PLACEHOLDER = "change-me-in-env"
_PAYLOAD = b"owner-cookie-v1"


def _secret_configured() -> bool:
    return settings.owner_secret != _PLACEHOLDER


def login_key_valid(key: str) -> bool:
    return _secret_configured() and hmac.compare_digest(key, settings.owner_secret)


def owner_cookie_value() -> str:
    return hmac.new(settings.owner_secret.encode(), _PAYLOAD, sha256).hexdigest()


def resolve_user_id(cookie_value: str | None) -> int:
    if (
        _secret_configured()
        and cookie_value is not None
        and hmac.compare_digest(cookie_value, owner_cookie_value())
    ):
        return OWNER_USER_ID
    return DEMO_USER_ID
