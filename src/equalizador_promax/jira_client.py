from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from typing import Any

from equalizador_promax.config import JiraSettings, validate_jira_settings
from equalizador_promax.errors import JiraIntegrationError, ValidationError
from equalizador_promax.models import JiraItem, JiraPullRequest

DEV_STATUS_BASE_URL = "{server}/rest/dev-status/1.0/{path}"
GITPLUGIN_BASE_URL = "{server}/rest/gitplugin/1.0/{path}"


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

    def fetch_pull_requests_for_issue_keys(self, issue_keys: list[str]) -> dict[str, list[JiraPullRequest]]:
        client = self._get_client()
        pull_requests_by_key: dict[str, list[JiraPullRequest]] = {}
        for issue_key in sorted({key.strip().upper() for key in issue_keys if key.strip()}):
            try:
                response = self._request_json(
                    client,
                    f"issuegitdetails/issue/{issue_key}/pullRequest",
                    base=GITPLUGIN_BASE_URL,
                )
            except JiraIntegrationError:
                raise
            except Exception as exc:  # pragma: no cover - depends on remote Jira
                raise JiraIntegrationError(f"Unable to fetch Jira pull requests for {issue_key}: {exc}") from exc

            self._raise_gitplugin_errors(issue_key, response)
            pull_requests_by_key[issue_key] = self._parse_gitplugin_pull_requests(issue_key, response)
        return pull_requests_by_key

    def fetch_pull_requests_for_issues(self, issue_ids_by_key: dict[str, str]) -> dict[str, list[JiraPullRequest]]:
        client = self._get_client()
        pull_requests_by_key: dict[str, list[JiraPullRequest]] = {}

        for issue_key, issue_id in sorted(issue_ids_by_key.items()):
            if not issue_id:
                continue
            try:
                response = self._request_json(
                    client,
                    "issue/detail",
                    params={
                        "issueId": issue_id,
                        "applicationType": "stash",
                        "dataType": "pullrequest",
                    },
                    base=DEV_STATUS_BASE_URL,
                )
            except JiraIntegrationError:
                raise
            except Exception as exc:  # pragma: no cover - depends on remote Jira
                raise JiraIntegrationError(f"Unable to fetch Jira pull requests for {issue_key}: {exc}") from exc

            self._raise_dev_status_errors(issue_key, response)
            pull_requests_by_key[issue_key] = self._parse_dev_status_pull_requests(issue_key, issue_id, response)

        return pull_requests_by_key

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
            issue_id=str(payload.get("id", "")).strip() or None,
        )
        subtasks = [
            JiraItem(
                key=subtask_key,
                parent_key=issue_key,
                item_type="subtask",
                issue_id=str(subtask.get("id", "")).strip() or None,
            )
            for subtask in (fields.get("subtasks") or [])
            if (subtask_key := str(subtask.get("key", "")).strip())
        ]
        return story_item, subtasks

    def _request_json(
        self,
        client,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        base: str | None = None,
    ) -> dict[str, Any]:
        attempts = 0
        while True:
            try:
                if params is None:
                    if base is None:
                        return client._get_json(path)  # noqa: SLF001 - controlled adapter boundary
                    return client._get_json(path, base=base)  # noqa: SLF001 - controlled adapter boundary
                if base is None:
                    return client._get_json(path, params=params)  # noqa: SLF001 - controlled adapter boundary
                return client._get_json(path, params=params, base=base)  # noqa: SLF001 - controlled adapter boundary
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

    def _raise_dev_status_errors(self, issue_key: str, response: dict[str, Any]) -> None:
        errors = response.get("errors") or response.get("configErrors") or []
        if not errors:
            return
        error_text = "; ".join(str(error) for error in errors)
        raise JiraIntegrationError(f"Jira dev-status returned errors for {issue_key}: {error_text}")

    def _raise_gitplugin_errors(self, issue_key: str, response: dict[str, Any]) -> None:
        if response.get("success", True):
            return
        error = response.get("error") or response.get("message") or response.get("errors") or response
        raise JiraIntegrationError(f"Jira gitplugin returned errors for {issue_key}: {error}")

    def _parse_gitplugin_pull_requests(self, issue_key: str, response: dict[str, Any]) -> list[JiraPullRequest]:
        items = ((response.get("pullRequests") or {}).get("items") or []) if isinstance(response, dict) else []
        parsed: list[JiraPullRequest] = []
        seen: set[tuple[str, str, str, str, str, str]] = set()
        for raw_pull_request in items:
            if not isinstance(raw_pull_request, dict):
                continue
            pull_request = self._parse_pull_request(issue_key, "", raw_pull_request)
            identity = (
                pull_request.pr_id,
                pull_request.url,
                pull_request.title,
                pull_request.source_branch,
                pull_request.destination_branch,
                pull_request.repository_name,
            )
            if identity in seen:
                continue
            parsed.append(pull_request)
            seen.add(identity)
        return parsed

    def _parse_dev_status_pull_requests(
        self,
        issue_key: str,
        issue_id: str,
        response: dict[str, Any],
    ) -> list[JiraPullRequest]:
        parsed: list[JiraPullRequest] = []
        seen: set[tuple[str, str, str, str, str]] = set()
        for raw_pull_request in self._extract_pull_request_payloads(response):
            pull_request = self._parse_pull_request(issue_key, issue_id, raw_pull_request)
            identity = (
                pull_request.pr_id,
                pull_request.url,
                pull_request.title,
                pull_request.source_branch,
                pull_request.destination_branch,
            )
            if identity in seen:
                continue
            parsed.append(pull_request)
            seen.add(identity)
        return parsed

    def _extract_pull_request_payloads(self, payload: Any) -> list[dict[str, Any]]:
        pull_requests: list[dict[str, Any]] = []
        stack = [payload]
        while stack:
            current = stack.pop()
            if isinstance(current, dict):
                for key, value in current.items():
                    if key == "pullRequests" and isinstance(value, list):
                        pull_requests.extend(item for item in value if isinstance(item, dict))
                    elif isinstance(value, dict | list):
                        stack.append(value)
            elif isinstance(current, list):
                stack.extend(current)
        return pull_requests

    def _parse_pull_request(
        self,
        issue_key: str,
        issue_id: str,
        payload: dict[str, Any],
    ) -> JiraPullRequest:
        return JiraPullRequest(
            issue_key=issue_key,
            issue_id=issue_id,
            pr_id=self._string_value(payload.get("id") or payload.get("displayId")),
            title=self._string_value(payload.get("name") or payload.get("title")),
            url=self._extract_url(payload),
            status=self._string_value(payload.get("status") or payload.get("state")).upper(),
            source_branch=self._extract_branch_name(
                payload.get("compareBranch") or payload.get("source") or payload.get("fromRef")
            ),
            destination_branch=self._extract_branch_name(
                payload.get("baseBranch") or payload.get("destination") or payload.get("toRef")
            ),
            repository_name=self._extract_repository_name(payload),
        )

    def _extract_url(self, payload: dict[str, Any]) -> str:
        for key in ("url", "href"):
            value = self._string_value(payload.get(key))
            if value:
                return value

        link = payload.get("link")
        if isinstance(link, dict):
            value = self._string_value(link.get("url") or link.get("href"))
            if value:
                return value
        elif isinstance(link, str):
            return link.strip()

        links = payload.get("links")
        if isinstance(links, dict):
            self_links = links.get("self")
            if isinstance(self_links, list):
                for item in self_links:
                    if isinstance(item, dict):
                        value = self._string_value(item.get("href") or item.get("url"))
                        if value:
                            return value
        return ""

    def _extract_branch_name(self, payload: Any) -> str:
        if isinstance(payload, str):
            return payload.strip()
        if not isinstance(payload, dict):
            return ""

        branch = payload.get("branch")
        if isinstance(branch, dict | str):
            branch_name = self._extract_branch_name(branch)
            if branch_name:
                return branch_name

        for key in ("displayId", "name", "id"):
            value = self._string_value(payload.get(key))
            if value:
                return value.removeprefix("refs/heads/")
        return ""

    def _extract_repository_name(self, payload: dict[str, Any]) -> str:
        repository = payload.get("repository") or payload.get("repo")
        if isinstance(repository, str):
            return repository.strip()
        if isinstance(repository, dict):
            return self._string_value(repository.get("name") or repository.get("slug"))
        return ""

    def _string_value(self, value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

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
