"""Configuration loading: merges config.yaml + environment secrets.

No third-party env loader needed — we parse a local .env ourselves so the
dependency list stays tiny. In GitHub Actions, secrets arrive as real env
vars, so the .env file simply won't exist and that's fine.
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader. Lines like KEY=value; ignores blanks/comments.
    Does not override variables already present in the environment."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_config(path: str | os.PathLike | None = None) -> dict:
    """Load config.yaml and fold in environment-driven overrides."""
    _load_dotenv(ROOT / ".env")

    cfg_path = Path(path) if path else (ROOT / "config.yaml")
    with open(cfg_path, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}

    # Secrets (never stored in yaml).
    cfg["secrets"] = {
        "hunter_api_key": os.environ.get("HUNTER_API_KEY", "").strip(),
        "apollo_api_key": os.environ.get("APOLLO_API_KEY", "").strip(),
        "smtp_host": os.environ.get("SMTP_HOST", "").strip(),
        "smtp_port": int(os.environ.get("SMTP_PORT", "587") or "587"),
        "smtp_user": os.environ.get("SMTP_USER", "").strip(),
        "smtp_password": os.environ.get("SMTP_PASSWORD", "").strip(),
        "from_email": os.environ.get("FROM_EMAIL", "").strip(),
        "from_name": os.environ.get("FROM_NAME", "").strip(),
    }

    # Env override for send mode (lets the Action flip behaviour without edits).
    send_mode_env = os.environ.get("SEND_MODE", "").strip().lower()
    if send_mode_env in {"auto", "review"}:
        cfg.setdefault("sending", {})["mode"] = send_mode_env

    # Let FROM_EMAIL/FROM_NAME env override the brand block when provided.
    brand = cfg.setdefault("brand", {})
    if cfg["secrets"]["from_email"]:
        brand["from_email"] = cfg["secrets"]["from_email"]
    if cfg["secrets"]["from_name"]:
        brand["name"] = cfg["secrets"]["from_name"]

    return cfg


def has_smtp(cfg: dict) -> bool:
    s = cfg.get("secrets", {})
    return bool(s.get("smtp_host") and s.get("smtp_user") and s.get("smtp_password"))
