"""Admin gate: a shared token from ADMIN_TOKEN, sent as the X-Admin-Token header.

v1 has one local user and no roles, so admin actions are gated by a secret instead. With ADMIN_TOKEN unset the admin
endpoints answer 404, as if they didn't exist. Production replaces this with a role on the Principal.
"""

import hmac

from fastapi import Request

from backend.core.config import get_settings
from backend.core.errors import AppError, Forbidden


class _Hidden(AppError):
    status_code = 404

    def __init__(self) -> None:
        super().__init__("not_found", "Not found.")


def require_admin(request: Request) -> None:
    token = get_settings().admin_token
    if not token:
        raise _Hidden()
    sent = request.headers.get("x-admin-token", "")
    if not hmac.compare_digest(sent.encode(), token.encode()):
        raise Forbidden("forbidden", "Admin token missing or wrong.")
