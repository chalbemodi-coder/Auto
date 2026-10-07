"""Compatibility helpers for reading older encrypted Telegram session records."""

import os
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


DEFAULT_STATE_DIR = Path(os.environ.get("SESSION_STATE_DIR", ".state"))
KEY_FILENAME = "session-encryption.key"
ENV_KEY_NAME = "SESSION_ENCRYPTION_KEY"


def _decode_mountinfo_path(value: str) -> str:
    """Decode the octal escapes used for paths in /proc/self/mountinfo."""
    return (
        value.replace(r"\040", " ")
        .replace(r"\011", "\t")
        .replace(r"\012", "\n")
        .replace(r"\134", "\\")
    )


def _is_persistent_mount(
    state_dir: Path, *, mountinfo_text: str | None = None
) -> bool:
    """Fail closed unless the state directory is on an attached persistent volume."""
    mount_path = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")
    if mount_path:
        try:
            return Path(mount_path).resolve() == state_dir.resolve()
        except OSError:
            return False

    # os.path.ismount() can miss Docker bind mounts when source and container
    # paths are on the same filesystem. Linux mountinfo records bind mounts too.
    if mountinfo_text is None:
        try:
            mountinfo_text = Path("/proc/self/mountinfo").read_text(encoding="utf-8")
        except OSError:
            mountinfo_text = ""

    try:
        target = state_dir.resolve()
        for line in mountinfo_text.splitlines():
            fields = line.split()
            if len(fields) < 5:
                continue
            mountpoint = Path(_decode_mountinfo_path(fields[4])).resolve()
            if mountpoint == target:
                return True
    except OSError:
        return False
    return os.path.ismount(str(state_dir))


def _get_environment_key() -> bytes | None:
    raw_key = os.environ.get(ENV_KEY_NAME, "").strip()
    if not raw_key:
        return None
    try:
        key = raw_key.encode("ascii")
        Fernet(key)
    except (UnicodeEncodeError, TypeError, ValueError) as error:
        raise RuntimeError(
            f"{ENV_KEY_NAME} is invalid; set a valid Fernet key and keep it unchanged."
        ) from error
    return key


def get_or_create_key(key_path: str | Path | None = None, *, require_persistent: bool = True) -> bytes:
    environment_key = _get_environment_key()
    if environment_key is not None:
        return environment_key

    path = Path(key_path) if key_path else DEFAULT_STATE_DIR / KEY_FILENAME
    state_dir = path.parent

    if require_persistent and not _is_persistent_mount(state_dir):
        raise RuntimeError(
            "The legacy encrypted session needs its original persistent key or "
            "SESSION_ENCRYPTION_KEY; authenticate again with /login if that key is unavailable."
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
