"""
secure_storage.py
==================
Lightweight encrypted credential storage for the mobile app.

Android has no direct equivalent of desktop `keyring`, so this module
rolls its own: a Fernet (AES-128-CBC + HMAC) symmetric key is generated
once and written to the app's *private* internal storage directory
(`App.user_data_dir`), which on Android is sandboxed per-app and is not
readable by other apps without root. The username/password are then
encrypted with that key before being written to a small JSON file next
to it - so nothing sensitive ever sits on disk in plaintext.

This is a reasonable baseline for a personal-use utility app. If you
want to harden it further, the natural next step is to move the key
itself into the Android Keystore (via pyjnius + `java.security.KeyStore`)
so the key never exists as a plain file at all - noted at the bottom of
this file for anyone who wants to extend it.
"""

import json
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


class SecureStorage:
    def __init__(self, storage_dir: str):
        self.dir = Path(storage_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.key_path = self.dir / ".ediary_key"
        self.data_path = self.dir / ".ediary_creds.enc"
        self._fernet = self._load_or_create_key()

    def _load_or_create_key(self) -> Fernet:
        if self.key_path.exists():
            key = self.key_path.read_bytes()
        else:
            key = Fernet.generate_key()
            self.key_path.write_bytes(key)
            try:
                # Best-effort: restrict permissions on platforms that support it.
                self.key_path.chmod(0o600)
            except (OSError, NotImplementedError):
                pass
        return Fernet(key)

    def save_credentials(self, username: str, password: str) -> None:
        payload = json.dumps({"username": username, "password": password}).encode()
        encrypted = self._fernet.encrypt(payload)
        self.data_path.write_bytes(encrypted)
        try:
            self.data_path.chmod(0o600)
        except (OSError, NotImplementedError):
            pass

    def load_credentials(self) -> tuple[str, str] | None:
        if not self.data_path.exists():
            return None
        try:
            encrypted = self.data_path.read_bytes()
            payload = json.loads(self._fernet.decrypt(encrypted).decode())
            return payload.get("username", ""), payload.get("password", "")
        except (InvalidToken, ValueError, json.JSONDecodeError, OSError):
            return None

    def clear_credentials(self) -> None:
        for path in (self.data_path,):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Optional hardening (not implemented here, left as a pointer):
#
# Instead of storing the Fernet key as a file, generate an AES key inside
# the Android Keystore itself:
#
#   from jnius import autoclass
#   KeyStore = autoclass('java.security.KeyStore')
#   KeyGenerator = autoclass('javax.crypto.KeyGenerator')
#   KeyGenParameterSpec = autoclass('android.security.keystore.KeyGenParameterSpec')
#   ... generate/retrieve a key with KeyStore.PROVIDER = "AndroidKeyStore" ...
#
# The key material then never exists outside secure hardware/TEE-backed
# storage. This requires more Android-version-specific boilerplate than fits
# cleanly here, so the file-based Fernet key above is the pragmatic default.
# ---------------------------------------------------------------------------
