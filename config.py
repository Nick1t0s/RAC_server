from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ConfigError(RuntimeError):
    pass


@dataclass
class ServerCfg:
    host: str
    port: int


@dataclass
class AuthCfg:
    username: str
    password_hash: str
    session_secret: str
    session_lifetime_hours: int


@dataclass
class StorageCfg:
    cmds_dir: Path
    uploads_dir: Path
    db_path: Path
    max_upload_size_mb: int

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024


@dataclass
class PollingCfg:
    agent_poll_interval_sec: int
    online_threshold_sec: int


@dataclass
class Config:
    server: ServerCfg
    auth: AuthCfg
    storage: StorageCfg
    polling: PollingCfg
    raw: dict[str, Any]


def _require(d: dict, key: str, section: str) -> Any:
    if key not in d:
        raise ConfigError(f"config: missing '{section}.{key}'")
    return d[key]


def load_config(path: str | Path = "config.yaml") -> Config:
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"config: file '{p}' not found")
    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    srv = _require(data, "server", "root")
    au = _require(data, "auth", "root")
    st = _require(data, "storage", "root")
    pl = _require(data, "polling", "root")

    server = ServerCfg(
        host=str(_require(srv, "host", "server")),
        port=int(_require(srv, "port", "server")),
    )

    pw_hash = str(_require(au, "password_hash", "auth"))
    sess_secret = str(_require(au, "session_secret", "auth"))

    if not pw_hash or pw_hash.startswith("REPLACE_ME"):
        raise ConfigError(
            "config: auth.password_hash is a placeholder.\n"
            "Run `python generate_password.py` and paste the output into config.yaml."
        )
    if not sess_secret or sess_secret.startswith("REPLACE_ME") or len(sess_secret) < 32:
        raise ConfigError(
            "config: auth.session_secret is a placeholder or shorter than 32 chars.\n"
            "Run `python generate_password.py` to get a fresh value."
        )

    auth = AuthCfg(
        username=str(_require(au, "username", "auth")),
        password_hash=pw_hash,
        session_secret=sess_secret,
        session_lifetime_hours=int(au.get("session_lifetime_hours", 24)),
    )

    storage = StorageCfg(
        cmds_dir=Path(str(_require(st, "cmds_dir", "storage"))).resolve(),
        uploads_dir=Path(str(_require(st, "uploads_dir", "storage"))).resolve(),
        db_path=Path(str(_require(st, "db_path", "storage"))).resolve(),
        max_upload_size_mb=int(_require(st, "max_upload_size_mb", "storage")),
    )

    polling = PollingCfg(
        agent_poll_interval_sec=int(pl.get("agent_poll_interval_sec", 2)),
        online_threshold_sec=int(pl.get("online_threshold_sec", 30)),
    )

    return Config(server=server, auth=auth, storage=storage, polling=polling, raw=data)


def ensure_dirs(cfg: Config) -> None:
    cfg.storage.cmds_dir.mkdir(parents=True, exist_ok=True)
    cfg.storage.uploads_dir.mkdir(parents=True, exist_ok=True)
    cfg.storage.db_path.parent.mkdir(parents=True, exist_ok=True)


def load_or_die(path: str | Path = "config.yaml") -> Config:
    try:
        return load_config(path)
    except ConfigError as e:
        print(f"[CONFIG ERROR] {e}", file=sys.stderr)
        sys.exit(2)
