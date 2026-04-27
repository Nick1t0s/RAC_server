"""Entry point. Loads config, builds app, runs uvicorn."""
from __future__ import annotations

import logging

import uvicorn

from app import build_app
from config import load_or_die


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main() -> None:
    setup_logging()
    cfg = load_or_die("config.yaml")
    app = build_app(cfg)
    uvicorn.run(
        app,
        host=cfg.server.host,
        port=cfg.server.port,
        log_level="info",
        access_log=False,
    )


if __name__ == "__main__":
    main()
