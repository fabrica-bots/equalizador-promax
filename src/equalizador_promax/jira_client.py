from __future__ import annotations

import os

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
        client = self._get_client()
        try:
            issue = client.issue(story_key, fields="issuetype,subtasks")
        except Exception as exc:  # pragma: no cover - depends on remote Jira
            raise JiraIntegrationError(f"Unable to fetch Jira issue {story_key}: {exc}") from exc

        story_item = JiraItem(
            key=issue.key,
            parent_key=None,
            item_type=getattr(getattr(issue.fields, "issuetype", None), "name", "story"),
        )
        subtasks = [
            JiraItem(
                key=subtask.key,
                parent_key=issue.key,
                item_type="subtask",
            )
            for subtask in (issue.fields.subtasks or [])
        ]
        return story_item, subtasks

    def fetch_release_issue_keys(self, release_id: str) -> list[str]:
        client = self._get_client()
        start_at = 0
        page_size = 100
        issue_keys: list[str] = []

        while True:
            try:
                response = client._get_json(  # noqa: SLF001 - controlled adapter boundary
                    "search",
                    params={
                        "jql": f"fixVersion = {release_id} ORDER BY key",
                        "startAt": start_at,
                        "maxResults": page_size,
                        "fields": "key,parent",
                        "validateQuery": "true",
                    },
                )
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
            response = client._get_json(f"version/{release_id}")  # noqa: SLF001 - controlled adapter boundary
        except Exception as exc:  # pragma: no cover - depends on remote Jira
            raise JiraIntegrationError(f"Unable to fetch Jira release metadata {release_id}: {exc}") from exc

        release_name = (response or {}).get("name", "").strip()
        if not release_name:
            raise JiraIntegrationError(f"Jira release {release_id} returned no name.")
        return release_name

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
