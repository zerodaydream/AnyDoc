class AppError(Exception):
    """Error with a stable machine code and a user-facing message. Never include document content."""

    status_code = 400

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class NotFound(AppError):
    status_code = 404

    def __init__(self, what: str = "Document") -> None:
        super().__init__("not_found", f"{what} not found.")


class Conflict(AppError):
    status_code = 409


class InvalidFile(AppError):
    """Deterministic file problem: never retried."""

    status_code = 422


class TransientError(Exception):
    """Retryable infrastructure failure (rate limit, timeout)."""
