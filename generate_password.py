"""CLI: generate bcrypt password hash and a session secret.

Usage:
    python generate_password.py

Reads password from stdin (no echo), prints hash and a fresh session secret.
Does not modify config.yaml — just prints values for the admin to paste.
"""
from __future__ import annotations

import getpass
import secrets
import sys

import bcrypt


def main() -> int:
    print("Generate admin credentials for config.yaml")
    print("-" * 50)

    pw1 = getpass.getpass("Password: ")
    if not pw1:
        print("ERROR: empty password", file=sys.stderr)
        return 1
    pw2 = getpass.getpass("Confirm password: ")
    if pw1 != pw2:
        print("ERROR: passwords do not match", file=sys.stderr)
        return 1

    pw_bytes = pw1.encode("utf-8")
    if len(pw_bytes) > 72:
        print("ERROR: password is longer than 72 bytes (bcrypt limit)", file=sys.stderr)
        return 1
    pw_hash = bcrypt.hashpw(pw_bytes, bcrypt.gensalt()).decode("ascii")
    sess_secret = secrets.token_urlsafe(48)

    print()
    print("Paste the following into config.yaml under `auth:`")
    print("-" * 50)
    print(f'  password_hash: "{pw_hash}"')
    print(f'  session_secret: "{sess_secret}"')
    print("-" * 50)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
