from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from typing import Any

from equalizador_promax.config import JiraSettings, validate_jira_settings
from equalizador_promax.errors import JiraIntegrationError, ValidationError
from equalizador_promax.models import JiraItem


def save_jira_secret(settings: JiraSettings, secret: str) -> None:
    try:
        import keyring
    except ImportError as exc:
        raise JiraIntegrationError("The 'keyring' package is not installed.") from exc

    keyring.set_password(settings.credential_service, settings.credential_account, secret)


class JiraClient:
    story_batch_size = 20
    rate_limit_max_retries = 2
    rate_limit_auto_wait_seconds = 15

    def __init__(self, settings: JiraSettings) -> None:
        self.settings = settings
        self._client = None

    def validate_configuration(self) -> None:
        validate_jira_settings(self.settings)

    def has_secret(self) -> bool:
        return bool(self._resolve_secret())

    def validate_connectivity(self) -> None:
        client = self._get_client()
        try:
            client.myself()
        except Exception as exc:  # pragma: no cover - depends on remote Jira
            raise JiraIntegrationError(f"Unable to validate Jira connectivity: {exc}") from exc

    def fetch_story_with_subtasks(self, story_key: str) -> tuple[JiraItem, list[JiraItem]]:
        return self.fetch_stories_with_subtasks([story_key])[0]

    def fetch_stories_with_subtasks(self, story_keys: list[str]) -> list[tuple[JiraItem, list[JiraItem]]]:
        client = self._get_client()
        issues_by_key: dict[str, tuple[JiraItem, list[JiraItem]]] = {}

        for batch in self._chunked(story_keys, self.story_batch_size):
            try:
                response = self._request_json(
                    client,
                    "search",
                    params={
                        "jql": f"key in ({','.join(batch)}) ORDER BY key",
                        "startAt": 0,
                        "maxResults": len(batch),
                        "fields": "issuetype,subtasks",
                        "validateQuery": "true",
                    },
                )
            except JiraIntegrationError:
                raise
            except Exception as exc:  # pragma: no cover - depends on remote Jira
                batch_label = ", ".join(batch)
                raise JiraIntegrationError(f"Unable to fetch Jira issues {batch_label}: {exc}") from exc

            for issue_payload in response.get("issues", []):
                story_item, subtasks = self._parse_story_issue(issue_payload)
                if story_item.key:
                    issues_by_key[story_item.key] = (story_item, subtasks)

        missing_keys = [story_key for story_key in story_keys if story_key not in issues_by_key]
        if missing_keys:
            raise JiraIntegrationError(f"Unable to fetch Jira issues: {', '.join(missing_keys)}.")

        return [issues_by_key[story_key] for story_key in story_keys]

    def fetch_release_issue_keys(self, release_id: str) -> list[str]:
        client = self._get_client()
        start_at = 0
        page_size = 100
        issue_keys: list[str] = []

        while True:
            try:
                response = self._request_json(
                    client,
                    "search",
                    params={
                        "jql": f"fixVersion = {release_id} ORDER BY key",
                        "startAt": start_at,
                        "maxResults": page_size,
                        "fields": "key,parent",
                        "validateQuery": "true",
                    },
                )
            except JiraIntegrationError:
                raise
            except Exception as exc:  # pragma: no cover - depends on remote Jira
                raise JiraIntegrationError(f"Unable to fetch Jira release {release_id}: {exc}") from exc

            issues = response.get("issues", [])
            batch_count = len(issues)
            for issue in issues:
                fields = issue.get("fields") or {}
                if fields.get("parent"):
                    continue
                issue_key = issue.get("key")
                if issue_key:
                    issue_keys.append(issue_key)

            total = response.get("total")
            start_at += batch_count
            if batch_count == 0:
                break
            if total is not None and start_at >= total:
                break

        return issue_keys

    def fetch_release_name(self, release_id: str) -> str:
        client = self._get_client()
        try:
            response = self._request_json(client, f"version/{release_id}")
        except JiraIntegrationError:
            raise
        except Exception as exc:  # pragma: no cover - depends on remote Jira
            raise JiraIntegrationError(f"Unable to fetch Jira release metadata {release_id}: {exc}") from exc

        release_name = (response or {}).get("name", "").strip()
        if not release_name:
            raise JiraIntegrationError(f"Jira release {release_id} returned no name.")
        return release_name

    def _parse_story_issue(self, payload: dict[str, Any]) -> tuple[JiraItem, list[JiraItem]]:
        issue_key = str(payload.get("key", "")).strip()
        fields = payload.get("fields") or {}
        story_item = JiraItem(
            key=issue_key,
            parent_key=None,
            item_type=str((fields.get("issuetype") or {}).get("name") or "story"),
        )
        subtasks = [
            JiraItem(
                key=subtask_key,
                parent_key=issue_key,
                item_type="subtask",
            )
            for subtask in (fields.get("subtasks") or [])
            if (subtask_key := str(subtask.get("key", "")).strip())
        ]
        return story_item, subtasks

    def _request_json(self, client, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        attempts = 0
        while True:
            try:
                if params is None:
                    return client._get_json(path)  # noqa: SLF001 - controlled adapter boundary
                return client._get_json(path, params=params)  # noqa: SLF001 - controlled adapter boundary
            except Exception as exc:  # pragma: no cover - depends on remote Jira
                retry_after = self._extract_retry_after_seconds(exc)
                if (
                    self._is_rate_limit_error(exc)
                    and retry_after is not None
                    and retry_after <= self.rate_limit_auto_wait_seconds
                    and attempts < self.rate_limit_max_retries
                ):
                    time.sleep(max(retry_after, 1))
                    attempts += 1
                    continue
                if self._is_rate_limit_error(exc):
                    raise JiraIntegrationError(self._format_rate_limit_message(retry_after)) from exc
                raise

    def _is_rate_limit_error(self, exc: Exception) -> bool:
        status_code = getattr(exc, "status_code", None)
        if status_code == 429:
            return True
        response = getattr(exc, "response", None)
        response_status = getattr(response, "status_code", None) or getattr(response, "status", None)
        return response_status == 429

    def _extract_retry_after_seconds(self, exc: Exception) -> int | None:
        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", None) or getattr(exc, "headers", None) or {}
        retry_after = headers.get("Retry-After")
        if retry_after is None:
            return None
        try:
            return int(str(retry_after).strip())
        except ValueError:
            return None

    def _format_rate_limit_message(self, retry_after: int | None) -> str:
        if retry_after is None:
            return "Jira rate limit exceeded. Aguarde alguns minutos e tente novamente."
        retry_at = datetime.now() + timedelta(seconds=retry_after)
        return (
            "Jira rate limit exceeded. "
            f"Tente novamente em cerca de {retry_after} segundos ({retry_at:%d/%m/%Y %H:%M:%S})."
        )

    def _chunked(self, items: list[str], chunk_size: int) -> list[list[str]]:
        if chunk_size <= 0:
            return [items]
        return [items[index : index + chunk_size] for index in range(0, len(items), chunk_size)]

    def _get_client(self):
        if self._client is not None:
            return self._client

        validate_jira_settings(self.settings)
        secret = self._resolve_secret()
        if not secret:
            raise ValidationError("Jira secret not found in keyring or EQUALIZADOR_PROMAX_JIRA_SECRET.")

        try:
            from jira import JIRA
        except ImportError as exc:
            raise JiraIntegrationError("The 'jira' package is not installed.") from exc

        kwargs = {
            "server": self.settings.base_url.rstrip("/"),
            "validate": True,
            "get_server_info": False,
            "timeout": self.settings.timeout_seconds,
        }
        if self.settings.auth_mode == "basic":
            kwargs["basic_auth"] = (self.settings.username, secret)
        elif self.settings.auth_mode == "token":
            kwargs["token_auth"] = secret
        else:
            raise ValidationError("Unsupported Jira auth mode.")

        try:
            self._client = JIRA(**kwargs)
        except Exception as exc:  # pragma: no cover - depends on remote Jira
            raise JiraIntegrationError(f"Unable to initialize Jira client: {exc}") from exc
        return self._client

    def _resolve_secret(self) -> str | None:
        try:
            import keyring
        except ImportError:
            keyring = None

        if keyring is not None:
            secret = keyring.get_password(self.settings.credential_service, self.settings.credential_account)
            if secret:
                return secret

        env_secret = os.getenv("EQUALIZADOR_PROMAX_JIRA_SECRET", "").strip()
        return env_secret or None
