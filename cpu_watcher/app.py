"""
CpuWatcherApp — 实时 simpleperf 函数级 CPU 监控 TUI 主入口。

依赖倒置: 通过 DataCollector Protocol 接收采集器，不直接依赖具体实现。
消息驱动: 后台采集线程 → post Message → 主线程渲染，与 FdWatcher 模式一致。
"""

from __future__ import annotations

import threading
from datetime import datetime

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Header, Footer, Static, Log
from textual import work
from rich.text import Text

from .model import DataCollector, CollectorConfig, DeltaTracker, DeltaEntry, DeltaSnapshot
from .messages import SnapshotUpdated, CollectorError, CollectorStatus
from .widgets import (
    PerfTable,
    StatusPanel,
    DetailPanel,
    FilterInput,
)
from .exporter import dump_snapshot, export_flamegraph_data


class CpuWatcherApp(App):
    """实时 simpleperf CPU 指令监控 TUI"""

    CSS = """
    Screen {
        layout: vertical;
    }
    #status_panel {
        height: 3;
        background: $panel;
        padding: 0 1;
        content-align: left middle;
    }
    #filter_input {
        height: 3;
        display: none;
    }
    #perf_table {
        height: 1fr;
        border: solid $primary;
    }
    #detail_panel {
        height: 5;
        border: solid $secondary;
        background: $surface;
        padding: 0 1;
    }
    #log_panel {
        height: 5;
        border: solid $accent;
        background: $surface-darken-1;
    }
    #help_overlay {
        display: none;
        layer: above;
        width: 64;
        height: auto;
        background: $surface;
        border: double $primary;
        padding: 1 2;
        offset: 8 3;
    }
    #help_overlay.visible {
        display: block;
    }
    DataTable {
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "退出"),
        Binding("p", "toggle_pause", "暂停/继续"),
        Binding("j", "cycle_filter_mode", "过滤:全部/Java/业务"),
        Binding("d", "dump", "Dump快照"),
        Binding("f", "flamegraph", "火焰图"),
        Binding("r", "refresh_now", "立即刷新"),
        Binding("z", "reset_baseline", "重置基线"),
        Binding("s", "screenshot_svg", "截图(SVG)"),
        Binding("slash", "toggle_filter", "搜索"),
        Binding("escape", "close_filter", "取消搜索", show=False),
        Binding("question_mark", "show_help", "帮助"),
    ]

    HELP_TEXT = """\
 [bold cyan]cpu_watcher 按键帮助[/bold cyan]

 [bold]导航[/bold]
   ↑ / ↓        上下移动光标
   选中行自动显示详情

 [bold]操作[/bold]
   p   暂停/继续采集
   r   立即刷新一次（不等定时器）
   z   重置「Δ/base」基线为当前快照
   d   Dump 当前快照到文件（待实现）
   f   生成火焰图（待实现）
   j   切换过滤模式: 全部 → 仅Java → 仅业务代码(排除framework)
   /   打开搜索框，过滤函数名或模块名
   Esc 关闭搜索框
   s   截图保存为 SVG 文件
   ?   显示本帮助
   q   退出

 [bold]列说明[/bold]
   模块(DSO)   共享库/APK 名称
   函数        符号名
   指令数      本周期事件计数
   Δ/prev     与上次快照的变化
   Δ/base     与基线快照的累计变化（z 键重置）
   占比%       该函数占总事件百分比

 [bold dim]按 ? 或任意键关闭帮助[/bold dim]"""

    def __init__(
        self,
        collector: DataCollector,
        config: CollectorConfig,
    ) -> None:
        super().__init__()
        self._collector = collector
        self._config = config
        self._delta_tracker = DeltaTracker()
        self._filter_text: str = ""
        self._last_snapshot: DeltaSnapshot | None = None
        self._entry_map: dict[str, DeltaEntry] = {}
        self._wake_event = threading.Event()
        self._paused = threading.Event()
        self._filter_mode: str = "all"  # "all" → "java" → "business" → "all"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield StatusPanel("正在连接...", id="status_panel")
        yield FilterInput(id="filter_input")
        yield PerfTable(id="perf_table")
        yield DetailPanel("← 选择一行查看详情", id="detail_panel")
        yield Log(id="log_panel", max_lines=100)
        yield Static("", id="help_overlay")
        yield Footer()

    def on_mount(self) -> None:
        self._start_polling()

    # ── 后台采集 ──

    @work(exclusive=True, thread=True, group="polling")
    def _start_polling(self) -> None:
        """后台线程: 检查就绪 → 循环采集 → post 消息到主线程"""
        ok, msg = self._collector.check_ready()
        self.call_from_thread(
            self.post_message,
            CollectorStatus("connected" if ok else "error", msg),
        )
        if not ok:
            return

        while True:
            # 暂停时阻塞，直到取消暂停或 wake
            while self._paused.is_set():
                self._wake_event.wait(timeout=1.0)
                self._wake_event.clear()
                if not self._paused.is_set():
                    break

            try:
                snapshot = self._collector.collect()
            except Exception as exc:
                self.call_from_thread(
                    self.post_message,
                    CollectorError(str(exc)),
                )
                self._wake_event.wait(timeout=self._config.interval_s)
                self._wake_event.clear()
                continue

            if snapshot is None:
                self.call_from_thread(
                    self.post_message,
                    CollectorStatus("waiting", f"进程 {self._config.target} 未找到"),
                )
                self._wake_event.wait(timeout=self._config.interval_s)
                self._wake_event.clear()
                continue

            delta = self._delta_tracker.update(snapshot)
            self.call_from_thread(
                self.post_message,
                SnapshotUpdated(delta),
            )
            self._wake_event.wait(timeout=self._config.interval_s)
            self._wake_event.clear()

    # ── 消息处理 ──

    def on_snapshot_updated(self, msg: SnapshotUpdated) -> None:
        self._last_snapshot = msg.snapshot

        self._entry_map = {
            f"{de.entry.dso}::{de.entry.symbol}": de
            for de in self._last_snapshot.entries
        }

        target = self._collector.get_target_display()
        self.query_one("#status_panel", StatusPanel).update_status(
            self._last_snapshot, target, self._config.interval_s,
        )
        self.query_one("#perf_table", PerfTable).update_data(
            self._last_snapshot, self._filter_text,
                self._filter_mode, self._config.target,
        )
        self._update_detail_from_cursor()

    def on_collector_error(self, msg: CollectorError) -> None:
        self._log(f"[red]采集错误: {msg.error}[/red]")

    def on_collector_status(self, msg: CollectorStatus) -> None:
        status_text = {
            "connected": "[green]已连接[/green]",
            "waiting": "[yellow]等待中[/yellow]",
            "disconnected": "[red]已断开[/red]",
            "error": "[red]错误[/red]",
        }.get(msg.status, msg.status)
        detail = f" {msg.detail}" if msg.detail else ""
        self._log(f"{status_text}{detail}")

    def on_filter_input_filter_changed(
        self,
        msg: FilterInput.FilterChanged,
    ) -> None:
        self._filter_text = msg.value
        if self._last_snapshot:
            self.query_one("#perf_table", PerfTable).update_data(
                self._last_snapshot, self._filter_text,
                self._filter_mode, self._config.target,
            )

    def on_data_table_row_highlighted(
        self,
        event: PerfTable.RowHighlighted,
    ) -> None:
        self._update_detail_from_cursor()

    # ── 内部辅助 ──

    def _update_detail_from_cursor(self) -> None:
        table = self.query_one("#perf_table", PerfTable)
        detail = self.query_one("#detail_panel", DetailPanel)
        try:
            if table.row_count == 0:
                detail.update_detail(None)
                return
            cursor = table.cursor_row
            rows = table.ordered_rows
            if 0 <= cursor < len(rows):
                key = rows[cursor].key.value
                entry = self._entry_map.get(key)
                detail.update_detail(entry)
        except Exception:
            detail.update_detail(None)

    def _log(self, msg: str) -> None:
        log_widget = self.query_one("#log_panel", Log)
        log_widget.write_line(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

    # ── 按键动作 ──

    def action_toggle_pause(self) -> None:
        if self._paused.is_set():
            self._paused.clear()
            self._wake_event.set()
            self._log("[green]▶ 已继续采集[/green]")
            self.query_one("#status_panel", StatusPanel).update(
                Text("▶ 已继续", style="bold green")
            )
        else:
            self._paused.set()
            self._log("[yellow]⏸ 已暂停采集 (按 p 继续)[/yellow]")
            self.query_one("#status_panel", StatusPanel).update(
                Text("⏸ 已暂停 — 按 p 继续", style="bold yellow")
            )

    def action_cycle_filter_mode(self) -> None:
        cycle = {"all": "java", "java": "business", "business": "all"}
        labels = {"all": "全部", "java": "仅Java/Kotlin", "business": "仅业务代码"}
        self._filter_mode = cycle[self._filter_mode]
        self._log(f"[cyan]过滤模式: {labels[self._filter_mode]}[/cyan]")
        if self._last_snapshot:
            self.query_one("#perf_table", PerfTable).update_data(
                self._last_snapshot, self._filter_text,
                self._filter_mode, self._config.target,
            )

    def action_dump(self) -> None:
        if not self._last_snapshot:
            self._log("[dim]暂无数据可导出[/dim]")
            return
        try:
            path = dump_snapshot(self._last_snapshot)
            self._log(f"[green]快照已导出: {path}[/green]")
        except Exception as exc:
            self._log(f"[red]导出失败: {exc}[/red]")

    def action_flamegraph(self) -> None:
        if not self._last_snapshot:
            self._log("[dim]暂无数据可导出[/dim]")
            return
        try:
            path = export_flamegraph_data(self._last_snapshot.current)
            self._log(f"[green]火焰图数据已导出: {path}[/green]")
        except Exception as exc:
            self._log(f"[red]导出失败: {exc}[/red]")

    def action_refresh_now(self) -> None:
        self._log("[dim]正在手动刷新...[/dim]")
        self._wake_event.set()

    def action_reset_baseline(self) -> None:
        self._delta_tracker.reset_baseline()
        self._log("[cyan]基线已重置[/cyan]")

    def action_screenshot_svg(self) -> None:
        path = self.save_screenshot(path=".")
        self.notify(f"截图已保存: {path}")
        self._log(f"[green]截图已保存: {path}[/green]")

    def action_toggle_filter(self) -> None:
        fi = self.query_one("#filter_input", FilterInput)
        if fi.display:
            fi.display = False
        else:
            fi.display = True
            fi.focus()

    def action_close_filter(self) -> None:
        fi = self.query_one("#filter_input", FilterInput)
        fi.value = ""
        fi.display = False
        self._filter_text = ""
        if self._last_snapshot:
            self.query_one("#perf_table", PerfTable).update_data(
                self._last_snapshot, "",
                self._filter_mode, self._config.target,
            )

    def action_show_help(self) -> None:
        overlay = self.query_one("#help_overlay", Static)
        if "visible" in overlay.classes:
            overlay.remove_class("visible")
        else:
            overlay.update(self.HELP_TEXT)
            overlay.add_class("visible")

    def on_key(self, event) -> None:
        """任意键关闭帮助面板 (? 键由 action_show_help 处理)"""
        if event.key != "question_mark":
            overlay = self.query_one("#help_overlay", Static)
            if "visible" in overlay.classes:
                overlay.remove_class("visible")
                event.stop()
