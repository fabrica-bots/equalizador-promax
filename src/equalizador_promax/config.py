from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from equalizador_promax.errors import ValidationError


@dataclass(frozen=True)
class JiraSettings:
    base_url: str = "https://agile.corp.edp.pt"
    auth_mode: str = "token"
    username: str | None = None
    credential_service: str = "equalizador-promax/jira"
    credential_account: str = ""
    timeout_seconds: int = 15


@dataclass(frozen=True)
class AppConfig:
    jira: JiraSettings
    config_path: Path | None


def default_config_path() -> Path:
    appdata = os.getenv("APPDATA")
    if appdata:
        return Path(appdata) / "EqualizadorProMax" / "config.toml"
    return Path.home() / ".equalizador-promax" / "config.toml"


def ensure_config_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def load_config(config_path: Path | None = None) -> AppConfig:
    selected_path = config_path or default_config_path()
    if not selected_path.exists():
        default_config = AppConfig(jira=JiraSettings(), config_path=selected_path)
        save_config(default_config, selected_path)

    raw: dict[str, object] = tomllib.loads(selected_path.read_text(encoding="utf-8"))

    jira_raw = raw.get("jira", {})
    if jira_raw is None:
        jira_raw = {}
    if not isinstance(jira_raw, dict):
        raise ValidationError("Config file has invalid [jira] section.")

    base_url = os.getenv(
        "EQUALIZADOR_PROMAX_JIRA_BASE_URL",
        str(jira_raw.get("base_url", JiraSettings.base_url)),
    ).strip()
    auth_mode = os.getenv(
        "EQUALIZADOR_PROMAX_JIRA_AUTH_MODE",
        str(jira_raw.get("auth_mode", JiraSettings.auth_mode)),
    ).strip().lower()
    username = os.getenv("EQUALIZADOR_PROMAX_JIRA_USERNAME", str(jira_raw.get("username", ""))).strip() or None
    credential_service = os.getenv(
        "EQUALIZADOR_PROMAX_JIRA_CREDENTIAL_SERVICE",
        str(jira_raw.get("credential_service", JiraSettings.credential_service)),
    ).strip()
    credential_account = os.getenv(
        "EQUALIZADOR_PROMAX_JIRA_CREDENTIAL_ACCOUNT",
        str(jira_raw.get("credential_account", JiraSettings.credential_account)),
    ).strip()
    timeout_seconds = int(
        os.getenv(
            "EQUALIZADOR_PROMAX_JIRA_TIMEOUT_SECONDS",
            str(jira_raw.get("timeout_seconds", JiraSettings.timeout_seconds)),
        )
    )

    return AppConfig(
        jira=JiraSettings(
            base_url=base_url,
            auth_mode=auth_mode,
            username=username,
            credential_service=credential_service,
            credential_account=credential_account,
            timeout_seconds=timeout_seconds,
        ),
        config_path=selected_path if selected_path.exists() else None,
    )


def save_config(config: AppConfig, config_path: Path | None = None) -> Path:
    selected_path = config_path or config.config_path or default_config_path()
    ensure_config_parent(selected_path)

    jira = config.jira
    lines = [
        "[jira]",
        f'base_url = "{jira.base_url}"',
        f'auth_mode = "{jira.auth_mode}"',
    ]
    if jira.username:
        lines.append(f'username = "{jira.username}"')
    lines.extend(
        [
            f'credential_service = "{jira.credential_service}"',
            f'credential_account = "{jira.credential_account}"',
            f"timeout_seconds = {jira.timeout_seconds}",
            "",
        ]
    )
    selected_path.write_text("\n".join(lines), encoding="utf-8")
    return selected_path


def validate_jira_settings(settings: JiraSettings) -> None:
    if not settings.base_url:
        raise ValidationError("Jira base URL is not configured.")
    if settings.auth_mode not in {"basic", "token"}:
        raise ValidationError("Jira auth mode must be 'basic' or 'token'.")
    if settings.auth_mode == "basic" and not settings.username:
        raise ValidationError("Jira username is required for basic auth.")
