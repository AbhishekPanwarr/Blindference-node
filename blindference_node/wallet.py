"""Ethereum wallet generation and loading."""

import getpass
import json
import os
import sys

from eth_account import Account
from eth_account.signers.local import LocalAccount


def _prompt_password(confirm: bool = True) -> str:
    """Prompt for a wallet encryption password.

    In non‑interactive mode reads ``BLF_KEY_PASSWORD``.
    """
    env_password = os.environ.get("BLF_KEY_PASSWORD")
    if env_password is not None:
        return env_password

    if not sys.stdin.isatty():
        print(
            "Error: stdin is not a terminal and BLF_KEY_PASSWORD is not set. "
            "Run in interactive mode or set BLF_KEY_PASSWORD.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    pw = getpass.getpass("Enter wallet encryption password: ")
    if not pw:
        print("Error: Password cannot be empty.", file=sys.stderr)
        raise SystemExit(1)

    if confirm:
        pw2 = getpass.getpass("Confirm password: ")
        if pw != pw2:
            print("Error: Passwords do not match.", file=sys.stderr)
            raise SystemExit(1)

    return pw


def generate_wallet(keystore_path: str, password: str | None = None) -> str:
    """Generate a new Ethereum wallet and save an encrypted keystore.

    Args:
        keystore_path: Where to save the keystore file.
        password: Encryption password. If ``None``, prompts interactively.

    Returns:
        The wallet's public address (hex, checksummed).
    """
    if password is None:
        password = _prompt_password()

    account: LocalAccount = Account.create()
    encrypted = Account.encrypt(account.key, password)

    os.makedirs(os.path.dirname(keystore_path), exist_ok=True)
    with open(keystore_path, "w") as f:
        json.dump(encrypted, f, indent=2)

    return account.address


def import_wallet(keystore_path: str, private_key: str, password: str | None = None) -> str:
    """Import an existing private key, encrypt it, and save a keystore.

    Args:
        keystore_path: Where to save the keystore file.
        private_key: Hex-encoded private key (with or without ``0x`` prefix).
        password: Encryption password. If ``None``, prompts interactively.

    Returns:
        The wallet's public address (hex, checksummed).
    """
    if password is None:
        password = _prompt_password()

    raw_key = private_key
    if raw_key.startswith("0x") or raw_key.startswith("0X"):
        raw_key = raw_key[2:]

    if len(raw_key) != 64:
        print("Error: Private key must be 64 hex characters.", file=sys.stderr)
        raise SystemExit(1)

    try:
        account: LocalAccount = Account.from_key(raw_key)
    except ValueError as exc:
        print(f"Error: Invalid private key: {exc}", file=sys.stderr)
        raise SystemExit(1)

    encrypted = Account.encrypt(account.key, password)

    os.makedirs(os.path.dirname(keystore_path), exist_ok=True)
    with open(keystore_path, "w") as f:
        json.dump(encrypted, f, indent=2)

    return account.address


def load_wallet(keystore_path: str, password: str | None = None) -> LocalAccount:
    """Load and decrypt a keystore file.

    Args:
        keystore_path: Path to the keystore JSON.
        password: Decryption password. If ``None``, prompts interactively.

    Returns:
        An unlocked ``LocalAccount`` ready for signing.
    """
    if password is None:
        password = _prompt_password(confirm=False)

    if not os.path.exists(keystore_path):
        print(f"Error: Keystore not found at {keystore_path}", file=sys.stderr)
        raise SystemExit(1)

    with open(keystore_path) as f:
        encrypted = json.load(f)

    try:
        key = Account.decrypt(encrypted, password)
    except ValueError:
        print("Error: Incorrect password.", file=sys.stderr)
        raise SystemExit(1)

    return Account.from_key(key)
