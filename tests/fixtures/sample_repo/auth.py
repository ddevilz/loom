from __future__ import annotations


def validate_user(token: str) -> bool:
    def _normalize(t: str) -> str:
        return t.strip().lower()

    normalized = _normalize(token)
    return normalized == "ok"


def decorator(fn):
    def wrapper(*args, **kwargs):
        return fn(*args, **kwargs)

    return wrapper


@decorator
def decorated_function(x: int) -> int:
    return x + 1


async def async_login(user: str) -> str:
    return user


class AuthService:
    def __init__(self, secret: str) -> None:
        self._secret = secret

    def validate(self, token: str) -> bool:
        return validate_user(token)

    @property
    def secret(self) -> str:
        return self._secret

    @classmethod
    def from_env(cls) -> "AuthService":
        return cls(secret="env")

    @staticmethod
    def hash_pw(pw: str) -> str:
        return f"hashed:{pw}"
