"""Encrypt Telegram user sessions with a locally generated persistent Fernet key."""

import os
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


DEFAULT_STATE_DIR = Path(os.environ.get("SESSION_STATE_DIR", ".state"))
KEY_FILENAME = "session-encryption.key"


def _is_persistent_mount(state_dir: Path) -> bool:
    """Fail closed unless the state directory is on an attached persistent volume."""
    mount_path = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")
    if mount_path:
        try:
            return Path(mount_path).resolve() == state_dir.resolve()
        except OSError:
            return False
    return os.path.ismount(str(state_dir))


def get_or_create_key(key_path: str | Path | None = None, *, require_persistent: bool = True) -> bytes:
    path = Path(key_path) if key_path else DEFAULT_STATE_DIR / KEY_FILENAME
    state_dir = path.parent

    if require_persistent and not _is_persistent_mount(state_dir):
        raise RuntimeError(
            "Persistent storage is not mounted at /usr/src/app/.state. "
            "Attach a Railway volume there before using /login."
        )

    if not path.exists():
        state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(state_dir, 0o700)
        except OSError:
            pass
        key = Fernet.generate_key()
        fd, temp_name = tempfile.mkstemp(prefix=".session-key-", dir=str(state_dir))
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as key_file:
                key_file.write(key)
                key_file.flush()
                os.fsync(key_file.fileno())
            try:
                os.link(temp_name, path)
            except FileExistsError:
                pass
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass

    try:
        os.chmod(path, 0o600)
        key = path.read_bytes().strip()
    except OSError as error:
        raise RuntimeError("Unable to read the private session key file.") from error

    try:
        Fernet(key)
    except (TypeError, ValueError) as error:
        raise RuntimeError("The saved session key is invalid; do not delete it until you have a backup.") from error
    return key


def encrypt_session(
    session: str,
    *,
    key_path: str | Path | None = None,
    require_persistent: bool = True,
) -> str:
    key = get_or_create_key(key_path, require_persistent=require_persistent)
    return Fernet(key).encrypt(session.encode("utf-8")).decode("ascii")


def decrypt_session(
    token: str,
    *,
    key_path: str | Path | None = None,
    require_persistent: bool = True,
) -> str:
    key = get_or_create_key(key_path, require_persistent=require_persistent)
    try:
        return Fernet(key).decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError) as error:
        raise RuntimeError("Stored Telegram session could not be decrypted with the saved key.") from error
