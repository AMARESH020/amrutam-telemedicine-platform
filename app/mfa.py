"""TOTP MFA and one-time recovery-code helpers."""

import hashlib
import hmac
import json
import secrets
import time

import pyotp
from cryptography.fernet import Fernet, InvalidToken

from app.config import settings
from app.models import User


def _fernet() -> Fernet:
    key = settings.mfa_encryption_key.strip()
    if not key:
        raise RuntimeError(
            "MFA_ENCRYPTION_KEY must be configured before using MFA."
        )
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise RuntimeError(
            "MFA_ENCRYPTION_KEY is not a valid Fernet key."
        ) from exc


def encrypt_mfa_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode("utf-8")).decode("ascii")


def decrypt_mfa_secret(encrypted_secret: str) -> str:
    try:
        return _fernet().decrypt(
            encrypted_secret.encode("ascii")
        ).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeDecodeError) as exc:
        raise RuntimeError(
            "Unable to decrypt the MFA secret; check MFA_ENCRYPTION_KEY."
        ) from exc


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def get_totp_provisioning_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(
        name=email,
        issuer_name="Amrutam Telemedicine",
    )


def matching_totp_counter(secret: str, code: str) -> int | None:
    """Return the matching time counter, allowing one step of clock drift."""
    code = code.strip()
    if not code.isdigit() or len(code) != 6:
        return None

    totp = pyotp.TOTP(secret)
    current = int(time.time() // totp.interval)
    matches = []

    for counter in range(max(0, current - 1), current + 2):
        if hmac.compare_digest(
            totp.at(counter * totp.interval),
            code,
        ):
            matches.append(counter)

    return max(matches) if matches else None


def verify_totp_secret(secret: str, code: str) -> bool:
    # Used for enrollment confirmation. Authentication replay checks are
    # performed by verify_user_mfa_code.
    return matching_totp_counter(secret, code) is not None


def _recovery_digest(code: str) -> str:
    normalized = code.strip().replace("-", "").upper()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def generate_recovery_codes() -> tuple[list[str], str]:
    """Return plaintext codes once and the JSON-encoded stored digests."""
    codes = [secrets.token_hex(8).upper() for _ in range(8)]
    digests = [_recovery_digest(code) for code in codes]
    return codes, json.dumps(digests)


def verify_user_mfa_code(user: User, code: str) -> tuple[bool, bool]:
    """
    Return (valid, recovery_code_used).

    Successful TOTP authentication updates the last accepted counter.
    Recovery-code changes must be committed by the calling transaction.
    """
    if (
        not user.mfa_enabled
        or not user.mfa_secret_encrypted
        or not code.strip()
    ):
        return False, False

    secret = decrypt_mfa_secret(user.mfa_secret_encrypted)
    counter = matching_totp_counter(secret, code)

    if counter is not None:
        last_counter = user.mfa_last_totp_counter
        if last_counter is not None and counter <= last_counter:
            return False, False

        user.mfa_last_totp_counter = counter
        return True, False

    try:
        stored_digests = json.loads(user.mfa_recovery_codes or "[]")
    except (TypeError, json.JSONDecodeError):
        return False, False

    supplied_digest = _recovery_digest(code)

    for index, stored_digest in enumerate(stored_digests):
        if isinstance(stored_digest, str) and hmac.compare_digest(
            supplied_digest, stored_digest
        ):
            stored_digests.pop(index)
            user.mfa_recovery_codes = json.dumps(stored_digests)
            return True, True

    return False, False