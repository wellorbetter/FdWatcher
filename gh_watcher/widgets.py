"""
自定义 Textual Widget — IssueTable / PRTable / NotifTable / StatusBar / FilterInput

所有格式化输出使用 rich.text.Text，与 FdWatcher 保持一致的视觉风格。
"""

from __future__ import annotations

from datetime import datetime, timezone

from textual.widgets import DataTable, Static, Input
from rich.text import Text

from .model import DashboardSnapshot, Issue, Notification, PullRequest


# ──────────────────────────────────────────────
# 格式化工具
# ──────────────────────────────────────────────

_STATE_ICONS = {
    "open": Text("●", style="bold green"),
    "closed": Text("●", style="bold red"),
    "merged": Text("●", style="bold magenta"),
}


def _state_icon(state: str) -> Text:
    return _STATE_ICONS.get(state, Text(state, style="dim"))


def _time_ago(iso_str: str) -> str:
    """将 ISO 8601 时间转为 '2h ago' 风格的相对时间。"""
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff = now - dt
        secs = int(diff.total_seconds())
        if secs < 0:
            return "just now"
        if secs < 60:
            return f"{secs}s"
        mins = secs // 60
        if mins < 60:
            return f"{mins}m"
        hours = mins // 60
        if hours < 24:
            return f"{hours}h"
        days = hours // 24
        if days < 30:
            return f"{days}d"
        return f"{days // 30}mo"
    except (ValueError, TypeError):
        return iso_str[:10] if len(iso_str) >= 10 else iso_str


def _truncate(s: str, max_len: int) -> str:
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def _label_text(labels: tuple[str, ...], max_len: int = 20) -> Text:
    if not labels:
        return Text("—", style="dim")
    joined = ", ".join(labels)
    return Text(_truncate(joined, max_len), style="cyan")


# ──────────────────────────────────────────────
# Issue Table
# ──────────────────────────────────────────────

class IssueTable(DataTable):
    """Issues DataTable。"""

    COLUMNS = ("Repo", "#", "Title", "State", "Labels", "💬", "Updated")

    def on_mount(self) -> None:
        for col in self.COLUMNS:
            self.add_column(col, key=col)

    def refresh_data(
        self, issues: tuple[Issue, ...], filter_text: str = "",
    ) -> None:
        self.clear()
        for issue in issues:
            if filter_text and filter_text.lower() not in (
                f"{issue.repo} {issue.title} {' '.join(issue.labels)}"
            ).lower():
                continue
            self.add_row(
                Text(_truncate(issue.repo, 30)),
                Text(str(issue.number), style="bold"),
                Text(_truncate(issue.title, 50)),
                _state_icon(issue.state),
                _label_text(issue.labels),
                Text(str(issue.comments), style="yellow" if issue.comments else "dim"),
                Text(_time_ago(issue.updated_at), style="dim"),
                key=issue.url,
            )


# ──────────────────────────────────────────────
# PR Table
# ──────────────────────────────────────────────

class PRTable(DataTable):
    """Pull Requests DataTable。"""

    COLUMNS = ("Repo", "#", "Title", "State", "Draft", "Reviews", "Updated")

    def on_mount(self) -> None:
        for col in self.COLUMNS:
            self.add_column(col, key=col)

    def refresh_data(
        self, prs: tuple[PullRequest, ...], filter_text: str = "",
    ) -> None:
        self.clear()
        for pr in prs:
            if filter_text and filter_text.lower() not in (
                f"{pr.repo} {pr.title} {' '.join(pr.labels)}"
            ).lower():
                continue

            draft_text = Text("draft", style="dim italic") if pr.draft else Text("—", style="dim")
            self.add_row(
                Text(_truncate(pr.repo, 30)),
                Text(str(pr.number), style="bold"),
                Text(_truncate(pr.title, 50)),
                _state_icon(pr.state),
                draft_text,
                Text(str(pr.reviews), style="yellow" if pr.reviews else "dim"),
                Text(_time_ago(pr.updated_at), style="dim"),
                key=pr.url,
            )


# ──────────────────────────────────────────────
# Notification Table
# ──────────────────────────────────────────────

_REASON_STYLES = {
    "review_requested": "bold yellow",
    "mention": "bold cyan",
    "assign": "bold green",
    "subscribed": "dim",
    "author": "blue",
}


class NotifTable(DataTable):
    """Notifications DataTable。"""

    COLUMNS = ("Repo", "Type", "Title", "Reason", "Unread", "Updated")

    def on_mount(self) -> None:
        for col in self.COLUMNS:
            self.add_column(col, key=col)

    def refresh_data(
        self, notifs: tuple[Notification, ...], filter_text: str = "",
    ) -> None:
        self.clear()
        for n in notifs:
            if filter_text and filter_text.lower() not in (
                f"{n.repo} {n.title} {n.type} {n.reason}"
            ).lower():
                continue

            reason_style = _REASON_STYLES.get(n.reason, "dim")
            unread_icon = Text("●", style="bold blue") if n.unread else Text("○", style="dim")

            self.add_row(
                Text(_truncate(n.repo, 30)),
                Text(n.type, style="italic"),
                Text(_truncate(n.title, 50)),
                Text(n.reason, style=reason_style),
                unread_icon,
                Text(_time_ago(n.updated_at), style="dim"),
                key=n.url,
            )


# ──────────────────────────────────────────────
# Status Bar
# ──────────────────────────────────────────────

class StatusBar(Static):
    """底部状态栏：刷新时间、倒计时、条目数。"""

    def update_status(
        self,
        last_refresh: str = "",
        countdown: int = 0,
        total_items: int = 0,
        message: str = "",
    ) -> None:
        parts: list[str] = []
        if last_refresh:
            parts.append(f"🔄 Last: {last_refresh}")
        if countdown > 0:
            parts.append(f"Next: {countdown}s")
        parts.append(f"{total_items} items")
        if message:
            parts.append(message)
        self.update(" │ ".join(parts))


# ──────────────────────────────────────────────
# Filter Input
# ──────────────────────────────────────────────

class FilterInput(Input):
    """搜索过滤输入框。"""

    DEFAULT_CSS = """
    FilterInput {
        dock: top;
        display: none;
        height: 3;
        margin: 0 1;
    }
    FilterInput.visible {
        display: block;
    }
    """

    def __init__(self) -> None:
        super().__init__(placeholder="Type to filter…")
