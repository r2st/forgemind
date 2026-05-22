"""Runtime user/credential store for the API gateway.

ForgeMind ships with environment-variable based credentials
(AUTH_ADMIN_USER / AUTH_ADMIN_PASS etc.) so a fresh stack can boot
with no extra setup. Once an operator opens the Admin Panel and
manages users from there, those entries are stored here — bcrypt
hashed — and take precedence over the env vars.

Store file lives next to `agent_config.json` (controlled by
AGENT_CONFIG_PATH). Mode 0o600. Format:

    {
      "users": {
        "admin": {
          "username": "admin",
          "role": "admin",
          "password_hash": "$2b$10$...",
          "created_at": "2026-05-22T...",
          "updated_at": "2026-05-22T..."
        }
      }
    }

The store is intentionally small and synchronous; per-request reads are
cached in-process and the JSON file is re-read on a 5-second TTL so
manual edits propagate quickly.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import bcrypt

from .config import get_settings

Role = Literal["viewer", "operator", "engineer", "admin"]
VALID_ROLES: tuple[str, ...] = ("viewer", "operator", "engineer", "admin")

_LOCK = threading.RLock()
_CACHE: dict[str, "User"] | None = None
_CACHE_TIME: float = 0.0
_CACHE_TTL_S: float = 5.0


@dataclass
class User:
    username: str
    role: Role
    password_hash: str
    created_at: str
    updated_at: str

    def to_public_dict(self) -> dict[str, str]:
        """Return the user without the password hash, safe for API responses."""
        return {
            "username": self.username,
            "role": self.role,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# ---------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------


def _store_path() -> Path:
    """Auth store lives alongside the agent config JSON."""
    agent_path = Path(get_settings().agent_config_path)
    return agent_path.parent / "auth_users.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_from_disk() -> dict[str, User]:
    path = _store_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    users_raw = (raw or {}).get("users") or {}
    out: dict[str, User] = {}
    for name, data in users_raw.items():
        if not isinstance(data, dict):
            continue
        role = data.get("role", "viewer")
        if role not in VALID_ROLES:
            role = "viewer"
        out[name] = User(
            username=name,
            role=role,
            password_hash=data.get("password_hash", ""),
            created_at=data.get("created_at", _now_iso()),
            updated_at=data.get("updated_at", _now_iso()),
        )
    return out


def _save_to_disk(users: dict[str, User]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "users": {
            u.username: {
                "username": u.username,
                "role": u.role,
                "password_hash": u.password_hash,
                "created_at": u.created_at,
                "updated_at": u.updated_at,
            }
            for u in users.values()
        }
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(path)


def _get_cache() -> dict[str, User]:
    """Read the on-disk store with a short TTL cache to keep auth fast
    without making manual edits invisible for too long."""
    global _CACHE, _CACHE_TIME
    with _LOCK:
        now = time.time()
        if _CACHE is None or (now - _CACHE_TIME) > _CACHE_TTL_S:
            _CACHE = _load_from_disk()
            _CACHE_TIME = now
        return _CACHE


def _invalidate_cache() -> None:
    global _CACHE, _CACHE_TIME
    with _LOCK:
        _CACHE = None
        _CACHE_TIME = 0.0


# ---------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=10)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    if not plain or not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------


def list_users() -> list[dict[str, str]]:
    return [u.to_public_dict() for u in _get_cache().values()]


def get_user(username: str) -> User | None:
    return _get_cache().get(username)


def upsert_user(username: str, password: str | None, role: Role) -> User:
    """Create or update a user.

    Password is optional on update — pass None to keep the existing hash.
    On insert the password is required (empty allowed but blocks login).
    """
    if not username or not isinstance(username, str):
        raise ValueError("username must be a non-empty string")
    if role not in VALID_ROLES:
        raise ValueError(f"role must be one of {VALID_ROLES}")
    with _LOCK:
        users = dict(_load_from_disk())
        existing = users.get(username)
        if password is not None and password != "":
            pw_hash = hash_password(password)
        elif existing is not None:
            pw_hash = existing.password_hash
        else:
            # Create a user without a password — login will fail until
            # an admin sets one. We store an unguessable random hash so
            # bcrypt verification never accidentally succeeds.
            pw_hash = hash_password(secrets.token_urlsafe(48))
        now = _now_iso()
        created = existing.created_at if existing else now
        user = User(
            username=username,
            role=role,
            password_hash=pw_hash,
            created_at=created,
            updated_at=now,
        )
        users[username] = user
        _save_to_disk(users)
        _invalidate_cache()
        return user


def delete_user(username: str) -> bool:
    with _LOCK:
        users = dict(_load_from_disk())
        if username not in users:
            return False
        del users[username]
        _save_to_disk(users)
        _invalidate_cache()
        return True


def authenticate(username: str, password: str) -> User | None:
    """Verify credentials against the runtime store ONLY.

    Returns the User on success, None on bad credentials or missing
    user. The api-gateway falls back to env-var credentials only when
    `bootstrap_user_from_env` returns a match — see
    `forgemind_common.auth_store.env_lookup`.
    """
    user = get_user(username)
    if user is None:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


# ---------------------------------------------------------------------
# Env-var bootstrap fallback
# ---------------------------------------------------------------------


_ENV_USERS: tuple[tuple[str, str, Role], ...] = (
    ("AUTH_ADMIN_USER",    "AUTH_ADMIN_PASS",    "admin"),
    ("AUTH_ENGINEER_USER", "AUTH_ENGINEER_PASS", "engineer"),
    ("AUTH_OPERATOR_USER", "AUTH_OPERATOR_PASS", "operator"),
    ("AUTH_VIEWER_USER",   "AUTH_VIEWER_PASS",   "viewer"),
)


def env_lookup(username: str, password: str) -> Role | None:
    """Match credentials against the env-var bootstrap users.

    Returns the role if both the username and password match an
    AUTH_*_USER / AUTH_*_PASS pair. Used as a fallback so an out-of-the-
    box deployment with no users configured can still log in. Constant-
    time password comparison.
    """
    if not username or not password:
        return None
    for user_var, pass_var, role in _ENV_USERS:
        env_user = os.getenv(user_var, "").strip()
        env_pass = os.getenv(pass_var, "")
        if not env_user or not env_pass:
            continue
        if username != env_user:
            continue
        if secrets.compare_digest(password, env_pass):
            return role
    return None


def has_store_users() -> bool:
    """True if at least one user is configured in the persistent store."""
    return len(_get_cache()) > 0
