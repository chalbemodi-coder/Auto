"""Encrypt owner Telegram session strings with a Fernet key from the environment."""

import os

from cryptography.fernet import Fernet, InvalidToken


ENV_KEY_NAME = "SESSION_ENCRYPTION_KEY"


def _get_key() -> bytes:
    raw_key = os.environ.get(ENV_KEY_NAME, "").strip()
    if not raw_key:
        raise RuntimeError(
            f"{ENV_KEY_NAME} is required for secure login. Add a valid Fernet key "
            "to the host's environment/secrets and keep it backed up."
        )

    try:
        key = raw_key.encode("ascii")
        Fernet(key)
    except (UnicodeEncodeError, TypeError, ValueError) as error:
        raise RuntimeError(
            f"{ENV_KEY_NAME} is invalid; set a valid URL-safe Fernet key and keep it unchanged."
        ) from error
    return key


def validate_session_key() -> None:
    """Raise a clear configuration error if the session key is absent or invalid."""
    _get_key()


def encrypt_session(session: str) -> str:
    """Return the encrypted form of a Telethon StringSession."""
    session = str(session or "")
    if not session:
        raise ValueError("Refusing to encrypt an empty Telegram session.")
    return Fernet(_get_key()).encrypt(session.encode("utf-8")).decode("ascii")


def decrypt_session(token: str) -> str:
    """Decrypt a stored Telethon StringSession with the configured Fernet key."""
    key = _get_key()
    try:
        return Fernet(key).decrypt(str(token).encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError, ValueError) as error:
        raise RuntimeError(
            "Stored Telegram session could not be decrypted. Keep the original "
            "SESSION_ENCRYPTION_KEY or run /login again."
        ) from error
