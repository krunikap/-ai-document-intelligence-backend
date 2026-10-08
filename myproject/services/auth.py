import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

from myproject.config import JWT_ACCESS_TOKEN_EXPIRE_MINUTES, JWT_SECRET_KEY

_PBKDF2_ITERATIONS = 600_000
_TOKEN_ISSUER = "ai-document-intelligence"


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS
    )
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${_b64url(salt)}${_b64url(digest)}"


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        algorithm, iterations, salt, expected = encoded_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), _b64url_decode(salt), int(iterations)
        )
        return hmac.compare_digest(actual, _b64url_decode(expected))
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: int) -> tuple[str, str, int]:
    if JWT_ACCESS_TOKEN_EXPIRE_MINUTES <= 0:
        raise RuntimeError("JWT_ACCESS_TOKEN_EXPIRE_MINUTES must be positive")
    now = int(time.time())
    expires_in = JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60
    jti = _b64url(os.urandom(16))
    claims = {
        "sub": str(user_id),
        "jti": jti,
        "iss": _TOKEN_ISSUER,
        "iat": now,
        "exp": now + expires_in,
    }
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = f"{_json_b64(header)}.{_json_b64(claims)}"
    signature = hmac.new(_secret(), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url(signature)}", jti, expires_in


def decode_access_token(token: str) -> dict[str, Any]:
    if len(token) > 8192:
        raise ValueError("JWT is too large")
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Malformed JWT")
    header = json.loads(_b64url_decode(parts[0]))
    claims = json.loads(_b64url_decode(parts[1]))
    if not isinstance(header, dict) or not isinstance(claims, dict):
        raise ValueError("Invalid JWT payload")
    if header.get("alg") != "HS256" or header.get("typ") != "JWT":
        raise ValueError("Unsupported JWT")
    signing_input = f"{parts[0]}.{parts[1]}"
    expected = hmac.new(_secret(), signing_input.encode("ascii"), hashlib.sha256).digest()
    if not hmac.compare_digest(expected, _b64url_decode(parts[2])):
        raise ValueError("Invalid JWT signature")
    if claims.get("iss") != _TOKEN_ISSUER:
        raise ValueError("Invalid JWT issuer")
    if int(claims["exp"]) <= int(time.time()):
        raise ValueError("Expired JWT")
    if not str(claims.get("sub", "")).isdigit() or not claims.get("jti"):
        raise ValueError("Invalid JWT claims")
    return claims


def _secret() -> bytes:
    if not JWT_SECRET_KEY or len(JWT_SECRET_KEY.encode("utf-8")) < 32:
        raise RuntimeError("Set JWT_SECRET_KEY to a random value of at least 32 characters")
    return JWT_SECRET_KEY.encode("utf-8")


def _json_b64(value: dict[str, Any]) -> str:
    return _b64url(json.dumps(value, separators=(",", ":")).encode("utf-8"))


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
