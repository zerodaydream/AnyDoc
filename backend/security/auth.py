"""Auth boundary. v1: single local user. Production swaps the provider, not the callers."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from fastapi import Request

from backend.core.config import get_settings


@dataclass(frozen=True, slots=True)
class Principal:
    owner_id: UUID
    workspace_id: UUID
    actor: str


class AuthProvider(Protocol):
    def authenticate(self, request: Request) -> Principal: ...


class LocalSingleUserAuth:
    def authenticate(self, request: Request) -> Principal:
        s = get_settings()
        return Principal(s.local_owner_id, s.local_workspace_id, "local-user")


_provider: AuthProvider = LocalSingleUserAuth()


def get_principal(request: Request) -> Principal:
    return _provider.authenticate(request)
