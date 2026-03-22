from __future__ import annotations

from collections import OrderedDict
from typing import Iterable, Sequence

from equalizador_promax.models import CandidateCommit, JiraItem
from equalizador_promax.utils import extract_issue_keys


def normalize_story_keys(raw_story_keys: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_key in raw_story_keys:
        key = raw_key.strip().upper()
        if not key or key in seen:
            continue
        normalized.append(key)
        seen.add(key)
    return normalized


def consolidate_items(
    story_keys: Sequence[str],
    story_items: Sequence[JiraItem],
    subtasks: Sequence[JiraItem],
) -> list[JiraItem]:
    ordered: OrderedDict[str, JiraItem] = OrderedDict()
    for key in story_keys:
        ordered.setdefault(key, JiraItem(key=key, parent_key=None, item_type="story"))
    for item in story_items:
        ordered[item.key] = item
    for item in subtasks:
        ordered.setdefault(item.key, item)
    return list(ordered.values())


def match_merge_to_item(subject: str, eligible_keys: set[str]) -> str | None:
    matches = sorted(extract_issue_keys(subject) & eligible_keys)
    if len(matches) != 1:
        return None
    return matches[0]


def deduplicate_commits(commits: Sequence[CandidateCommit]) -> list[CandidateCommit]:
    by_hash: dict[str, CandidateCommit] = {}
    for commit in commits:
        current = by_hash.get(commit.commit_hash)
        if current is None:
            by_hash[commit.commit_hash] = commit
            continue

        combined_keys = tuple(sorted(set(current.source_keys) | set(commit.source_keys)))
        chosen = current if current.timestamp <= commit.timestamp else commit
        by_hash[commit.commit_hash] = CandidateCommit(
            commit_hash=chosen.commit_hash,
            timestamp=min(current.timestamp, commit.timestamp),
            author=chosen.author,
            subject=chosen.subject,
            source_merge=chosen.source_merge,
            source_keys=combined_keys,
        )
    return sorted(by_hash.values(), key=lambda item: (item.timestamp, item.commit_hash))


def find_unmatched_item_keys(eligible_items: Sequence[JiraItem], matched_item_keys: set[str]) -> list[str]:
    return [item.key for item in eligible_items if item.key not in matched_item_keys]
