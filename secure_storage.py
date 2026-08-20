"""
secure_storage.py
==================
Stores the SSP username/password locally with NO compiled/native
dependencies - deliberately avoiding the `cryptography` package, whose
compiled Rust component (`_rust.abi3.so`) fails to load on Android under
python-for-android with:

    ImportError: dlopen failed: cannot locate symbol "_Py_NoneStruct"

That's a known incompatibility, not something fixable via buildozer.spec
tweaks - the practical fix is to not depend on a compiled extension at
all.

What this does instead: a random per-install XOR key is generated once
and stored in the app's *private* internal storage (`App.user_data_dir`,
which on Android is sandboxed per-app and unreadable by other apps
without root). The credentials are XORed against that key and
base64-encoded before being written to disk - so nothing sensitive sits
in plaintext, but note this is simple obfuscation, not cryptographic-
grade encryption. That trade-off is intentional here: it removes an
entire class of native-build failures in exchange for lighter-weight
protection than AES/Fernet would give. Good enough to stop a casual
glance at the file, not a substitute for a real key vault.
"""

import base64
import json
import os
from pathlib import Path


class SecureStorage:
    def __init__(self, storage_dir: str):
        self.dir = Path(storage_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.key_path = self.dir / ".ediary_key"
        self.data_path = self.dir / ".ediary_creds.dat"
        self._key = self._load_or_create_key()

    def _load_or_create_key(self) -> bytes:
        if self.key_path.exists():
            key = self.key_path.read_bytes()
            if key:
                return key
        key = os.urandom(32)
        self.key_path.write_bytes(key)
        try:
            self.key_path.chmod(0o600)
        except (OSError, NotImplementedError):
            pass
        return key

    def _xor(self, data: bytes) -> bytes:
        key = self._key
        return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))

    def save_credentials(self, username: str, password: str) -> None:
        payload = json.dumps({"username": username, "password": password}).encode("utf-8")
        obfuscated = self._xor(payload)
        encoded = base64.b64encode(obfuscated)
        self.data_path.write_bytes(encoded)
        try:
            self.data_path.chmod(0o600)
        except (OSError, NotImplementedError):
            pass

    def load_credentials(self):
        if not self.data_path.exists():
            return None
        try:
            encoded = self.data_path.read_bytes()
            obfuscated = base64.b64decode(encoded)
            payload = json.loads(self._xor(obfuscated).decode("utf-8"))
            return payload.get("username", ""), payload.get("password", "")
        except (ValueError, json.JSONDecodeError, OSError):
            return None

    def clear_credentials(self) -> None:
        try:
            self.data_path.unlink(missing_ok=True)
        except OSError:
            pass
