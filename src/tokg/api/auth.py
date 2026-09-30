# ABOUTME: Bearer-token auth. The token file stores only SHA-256 hashes mapped to principals, so a
# ABOUTME: leaked tokens file does not leak usable credentials. Roles: member (default) and admin.
import hashlib
import secrets
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, Field

Role = Literal["member", "admin"]


class Principal(BaseModel):
  person_id: str = Field(..., description="Person node id this token acts as")
  role: Role = "member"


def hash_token(token: str) -> str:
  return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> str:
  return secrets.token_urlsafe(32)


class TokenRegistry(BaseModel):
  tokens: dict[str, Principal] = Field(default_factory=dict, description="sha256(token) -> principal")

  @classmethod
  def from_yaml(cls, path: str | Path) -> Self:
    return cls.model_validate(yaml.safe_load(Path(path).read_text()) or {})

  def add(self, principal: Principal) -> str:
    token = new_token()
    self.tokens[hash_token(token)] = principal
    return token

  def authenticate(self, token: str) -> Principal | None:
    return self.tokens.get(hash_token(token))
