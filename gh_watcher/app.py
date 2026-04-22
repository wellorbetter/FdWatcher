"""
GhWatcherApp — GitHub 聚合活动看板 TUI 主入口。

消息驱动: 后台采集线程 → post Message → 主线程渲染，
与 FdWatcher / CpuWatcher 模式一致。
"""

from __future__ import annotations

import threading
import webbrowser

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Header, Footer, TabbedContent, TabPane, Static
from textual import work
from rich.text import Text

from .model import CollectorConfig, DataCollector, DashboardSnapshot
from .messages import SnapshotUpdated, CollectorError, CollectorStatus
from .widgets import (
    IssueTable,
    PRTable,
    NotifTable,
    StatusBar,
    FilterInput,
)


class GhWatcherApp(App):
    """GitHub 聚合活动看板 TUI。"""

    TITLE = "gh_watcher"
    CSS = """
    TabbedContent {
        height: 1fr;
    }
    TabPane {
        padding: 0;
    }
    DataTable {
        height: 1fr;
    }
    StatusBar {
        dock: bottom;
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    #error-banner {
        dock: top;
        height: auto;
        display: none;
        background: $error;
        color: $text;
        padding: 0 1;
    }
    #error-banner.visible {
        display: block;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("slash", "toggle_filter", "Search", key_display="/"),
        Binding("enter", "open_in_browser", "Open"),
        Binding("s", "cycle_sort", "Sort"),
    ]

    def __init__(
        self,
        collector: DataCollector,
        config: CollectorConfig,
    ) -> None:
        super().__init__()
        self._collector = collector
        self._config = config
        self._snapshot: DashboardSnapshot | None = None
        self._stop_event = threading.Event()
        self._countdown: int = 0
        self._filter_text: str = ""

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(id="error-banner")
        yield FilterInput()
        with TabbedContent("Issues", "Pull Requests", "Notifications"):
            with TabPane("Issues", id="tab-issues"):
                yield IssueTable(id="issue-table")
            with TabPane("Pull Requests", id="tab-prs"):
                yield PRTable(id="pr-table")
            with TabPane("Notifications", id="tab-notifs"):
                yield NotifTable(id="notif-table")
        yield StatusBar(id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = self._collector.get_target_display()
        ok, msg = self._collector.check_ready()
        if not ok:
            self._show_error(f"gh CLI not ready: {msg}")
            return
        self._start_collection()

    def _start_collection(self) -> None:
        self._collect_once()
        self._start_timer()

    @work(thread=True)
    def _collect_once(self) -> None:
        self.post_message(CollectorStatus("Refreshing…"))
        snapshot = self._collector.collect()
        if snapshot is None:
            self.post_message(CollectorError("Failed to fetch data from GitHub"))
            return
        self.post_message(SnapshotUpdated(snapshot))

    def _start_timer(self) -> None:
        self._countdown = int(self._config.interval_s)
        self.set_interval(1.0, self._tick)

    def _tick(self) -> None:
        self._countdown -= 1
        if self._countdown <= 0:
            self._countdown = int(self._config.interval_s)
            self._collect_once()
        self._update_status_bar()

    def on_snapshot_updated(self, message: SnapshotUpdated) -> None:
        self._snapshot = message.snapshot
        self.sub_title = f"@{message.snapshot.username}"
        self._hide_error()
        self._render_tables()
        self._update_status_bar()

    def on_collector_error(self, message: CollectorError) -> None:
        self._show_error(message.error)
        self._update_status_bar(message=message.error)

    def on_collector_status(self, message: CollectorStatus) -> None:
        self._update_status_bar(message=message.status)

    def _render_tables(self) -> None:
        if not self._snapshot:
            return
        issue_table = self.query_one("#issue-table", IssueTable)
        pr_table = self.query_one("#pr-table", PRTable)
        notif_table = self.query_one("#notif-table", NotifTable)

        issue_table.refresh_data(self._snapshot.issues, self._filter_text)
        pr_table.refresh_data(self._snapshot.pull_requests, self._filter_text)
        notif_table.refresh_data(self._snapshot.notifications, self._filter_text)

    def _update_status_bar(self, message: str = "") -> None:
        bar = self.query_one("#status-bar", StatusBar)
        total = 0
        last = ""
        if self._snapshot:
            total = (
                len(self._snapshot.issues)
                + len(self._snapshot.pull_requests)
                + len(self._snapshot.notifications)
            )
            last = self._snapshot.timestamp
        bar.update_status(
            last_refresh=last,
            countdown=max(0, self._countdown),
            total_items=total,
            message=message,
        )

    def _show_error(self, msg: str) -> None:
        banner = self.query_one("#error-banner", Static)
        banner.update(Text(f"⚠ {msg}", style="bold"))
        banner.add_class("visible")

    def _hide_error(self) -> None:
        banner = self.query_one("#error-banner", Static)
        banner.remove_class("visible")

    # ── 快捷键操作 ──

    def action_refresh(self) -> None:
        self._countdown = int(self._config.interval_s)
        self._collect_once()

    def action_toggle_filter(self) -> None:
        fi = self.query_one(FilterInput)
        if fi.has_class("visible"):
            fi.remove_class("visible")
            self._filter_text = ""
            self._render_tables()
        else:
            fi.add_class("visible")
            fi.focus()

    def on_input_changed(self, event: FilterInput.Changed) -> None:
        self._filter_text = event.value
        self._render_tables()

    def action_open_in_browser(self) -> None:
        tabs = self.query_one(TabbedContent)
        active_id = tabs.active
        table: DataTable | None = None
        if active_id == "tab-issues":
            table = self.query_one("#issue-table", IssueTable)
        elif active_id == "tab-prs":
            table = self.query_one("#pr-table", PRTable)
        elif active_id == "tab-notifs":
            table = self.query_one("#notif-table", NotifTable)

        if table is None or table.row_count == 0:
            return

        cursor_row = table.cursor_row
        if cursor_row < 0 or cursor_row >= table.row_count:
            return

        row_key = list(table.rows.keys())[cursor_row]
        url = str(row_key.value)
        if url.startswith("http"):
            webbrowser.open(url)

    def action_cycle_sort(self) -> None:
        pass
