"""
gh CLI 数据采集器 — 封装 gh 命令调用，实现 DataCollector Protocol。

调用策略:
  1. gh api /user → 获取 username（启动时一次）
  2. gh search issues --involves={user} → Issues
  3. gh search prs --involves={user} → PRs
  4. gh api /notifications → Notifications
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime
from typing import Any

from .model import (
    CollectorConfig,
    DashboardSnapshot,
    Issue,
    Notification,
    PullRequest,
)


def detect_gh(hint: str | None = None) -> str:
    """检测 gh CLI 可执行路径。"""
    if hint:
        return hint
    found = shutil.which("gh")
    if found:
        return found
    raise FileNotFoundError(
        "gh CLI not found. Install: https://cli.github.com/"
    )


def _run_gh(gh_bin: str, args: list[str], timeout: int = 30) -> str | None:
    """执行 gh 命令，返回 stdout。失败返回 None。"""
    try:
        result = subprocess.run(
            [gh_bin, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def _parse_json(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


class GhCollector:
    """通过 gh CLI 采集 GitHub 数据。"""

    _ISSUE_FIELDS = (
        "repository,number,title,state,author,labels,commentsCount,"
        "createdAt,updatedAt,url"
    )
    _PR_FIELDS = (
        "repository,number,title,state,author,labels,"
        "isDraft,commentsCount,createdAt,updatedAt,url"
    )

    def __init__(self, config: CollectorConfig) -> None:
        self._config = config
        self._gh = config.gh_bin
        self._username = config.username

    def check_ready(self) -> tuple[bool, str]:
        raw = _run_gh(self._gh, ["auth", "status"])
        if raw is None:
            stderr_check = subprocess.run(
                [self._gh, "auth", "status"],
                capture_output=True, text=True, timeout=10,
            )
            if stderr_check.returncode != 0:
                return False, f"gh auth failed: {stderr_check.stderr.strip()}"
        return True, "ok"

    def get_target_display(self) -> str:
        if self._username:
            return f"@{self._username}"
        return "@me"

    def _ensure_username(self) -> str:
        if self._username:
            return self._username
        raw = _run_gh(self._gh, ["api", "/user", "--jq", ".login"])
        if raw:
            self._username = raw.strip()
            return self._username
        raise RuntimeError("Failed to detect GitHub username via gh api /user")

    def collect(self) -> DashboardSnapshot | None:
        try:
            username = self._ensure_username()
        except RuntimeError:
            return None

        issues = self._collect_issues(username)
        prs = self._collect_prs(username)
        notifs = self._collect_notifications()

        all_repos = sorted({
            *(i.repo for i in issues),
            *(p.repo for p in prs),
            *self._config.extra_repos,
        })

        return DashboardSnapshot(
            timestamp=datetime.now().strftime("%H:%M:%S"),
            username=username,
            issues=tuple(issues),
            pull_requests=tuple(prs),
            notifications=tuple(notifs),
            repos=tuple(all_repos),
        )

    def _build_search_args(
        self, kind: str, username: str, fields: str,
    ) -> list[str]:
        args = [
            "search", kind,
            f"--involves={username}",
            "--sort=updated",
            f"--limit={self._config.limit}",
            f"--json={fields}",
        ]
        state = "open" if not self._config.include_closed else ""
        if state:
            args.append(f"--state={state}")

        if self._config.extra_repos:
            for repo in self._config.extra_repos:
                args.extend(["--repo", repo])

        return args

    def _collect_issues(self, username: str) -> list[Issue]:
        args = self._build_search_args("issues", username, self._ISSUE_FIELDS)
        raw = _run_gh(self._gh, args, timeout=30)
        items = _parse_json(raw)
        if not isinstance(items, list):
            return []

        results: list[Issue] = []
        for item in items:
            repo_info = item.get("repository", {})
            repo_name = repo_info.get("nameWithOwner", "") if isinstance(repo_info, dict) else ""
            author_info = item.get("author", {})
            author = author_info.get("login", "") if isinstance(author_info, dict) else ""
            labels_raw = item.get("labels", [])
            labels = tuple(
                lb.get("name", "") for lb in labels_raw
                if isinstance(lb, dict)
            )
            results.append(Issue(
                repo=repo_name,
                number=item.get("number", 0),
                title=item.get("title", ""),
                state=item.get("state", "").lower(),
                author=author,
                labels=labels,
                comments=item.get("commentsCount", 0),
                created_at=item.get("createdAt", ""),
                updated_at=item.get("updatedAt", ""),
                url=item.get("url", ""),
            ))
        return results

    def _collect_prs(self, username: str) -> list[PullRequest]:
        args = self._build_search_args("prs", username, self._PR_FIELDS)
        raw = _run_gh(self._gh, args, timeout=30)
        items = _parse_json(raw)
        if not isinstance(items, list):
            return []

        results: list[PullRequest] = []
        for item in items:
            repo_info = item.get("repository", {})
            repo_name = repo_info.get("nameWithOwner", "") if isinstance(repo_info, dict) else ""
            author_info = item.get("author", {})
            author = author_info.get("login", "") if isinstance(author_info, dict) else ""
            labels_raw = item.get("labels", [])
            labels = tuple(
                lb.get("name", "") for lb in labels_raw
                if isinstance(lb, dict)
            )
            reviews_count = item.get("commentsCount", 0)

            state_raw = item.get("state", "").lower()
            if state_raw == "merged":
                state = "merged"
            elif state_raw == "closed":
                state = "closed"
            else:
                state = "open"

            results.append(PullRequest(
                repo=repo_name,
                number=item.get("number", 0),
                title=item.get("title", ""),
                state=state,
                author=author,
                labels=labels,
                reviews=reviews_count,
                draft=item.get("isDraft", False),
                mergeable=True,
                created_at=item.get("createdAt", ""),
                updated_at=item.get("updatedAt", ""),
                url=item.get("url", ""),
            ))
        return results

    def _collect_notifications(self) -> list[Notification]:
        raw = _run_gh(self._gh, [
            "api", "/notifications",
            "--method=GET",
            "-q", ".",
        ], timeout=30)
        items = _parse_json(raw)
        if not isinstance(items, list):
            return []

        results: list[Notification] = []
        for item in items:
            repo_info = item.get("repository", {})
            repo_name = repo_info.get("full_name", "") if isinstance(repo_info, dict) else ""
            subject = item.get("subject", {})
            title = subject.get("title", "") if isinstance(subject, dict) else ""
            ntype = subject.get("type", "") if isinstance(subject, dict) else ""
            sub_url = subject.get("url", "") if isinstance(subject, dict) else ""

            html_url = self._api_url_to_html(sub_url, repo_name)

            results.append(Notification(
                id=item.get("id", ""),
                repo=repo_name,
                title=title,
                type=ntype,
                reason=item.get("reason", ""),
                unread=item.get("unread", False),
                updated_at=item.get("updated_at", ""),
                url=html_url,
            ))
        return results[: self._config.limit]

    @staticmethod
    def _api_url_to_html(api_url: str, repo: str) -> str:
        """将 GitHub API URL 转为 web URL。"""
        if not api_url or not repo:
            return f"https://github.com/{repo}" if repo else ""
        if "/issues/" in api_url or "/pulls/" in api_url:
            number = api_url.rsplit("/", 1)[-1]
            if "/pulls/" in api_url:
                return f"https://github.com/{repo}/pull/{number}"
            return f"https://github.com/{repo}/issues/{number}"
        return f"https://github.com/{repo}"
