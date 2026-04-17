"""
自定义 Textual Widget — PerfTable / StatusPanel / DetailPanel / FilterInput

所有格式化输出使用 rich.text.Text，与 FdWatcher 保持一致的视觉风格。
"""

from __future__ import annotations

import re

from textual.message import Message
from textual.widgets import DataTable, Static, Input
from rich.text import Text

from .model import DeltaEntry, DeltaSnapshot


# ──────────────────────────────────────────────
# 格式化工具函数
# ──────────────────────────────────────────────

def format_count(n: int) -> str:
    """紧凑数字格式: 12345678 -> '12.3M', 345678 -> '345.7K', 1234 -> '1,234'"""
    abs_n = abs(n)
    if abs_n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if abs_n >= 10_000:
        return f"{n / 1_000:.1f}K"
    return f"{n:,}"


def format_delta(d: int) -> Text:
    """Delta 格式化: 正值红色 '+2.1M'，负值绿色 '-350K'，零灰色 '—'"""
    if d == 0:
        return Text("\u2014", style="dim")

    abs_d = abs(d)
    if abs_d >= 1_000_000:
        label = f"{d / 1_000_000:+.1f}M"
    elif abs_d >= 10_000:
        label = f"{d / 1_000:+.1f}K"
    else:
        label = f"{d:+,}"

    style = "bold red" if d > 0 else "bold green"
    return Text(label, style=style)


_DSO_STRIP_PREFIXES = (
    "/system/lib64/",
    "/system/lib/",
    "/system_ext/lib64/",
    "/system_ext/lib/",
    "/product/lib64/",
    "/product/lib/",
    "/vendor/lib64/",
    "/vendor/lib/",
)

_APEX_RE = re.compile(r"^/apex/[^/]+/lib(?:64)?/")


def shorten_dso(dso: str) -> str:
    """缩短 DSO 路径: 去掉常见前缀，保留文件名。base.apk 原样保留。"""
    for prefix in _DSO_STRIP_PREFIXES:
        if dso.startswith(prefix):
            return dso[len(prefix):]

    m = _APEX_RE.match(dso)
    if m:
        return dso[m.end():]

    return dso


def truncate_symbol(symbol: str, max_len: int = 45) -> str:
    """截断超长符号名，保留可读性。"""
    if len(symbol) <= max_len:
        return symbol
    return symbol[:max_len - 1] + "…"


_JAVA_DSO_SUFFIXES = (".apk", ".odex", ".oat", ".vdex", ".dex")


def is_java_entry(dso: str) -> bool:
    """判断 DSO 是否属于 Java/Kotlin 代码层。"""
    if "[JIT app cache]" in dso:
        return True
    if dso.endswith(_JAVA_DSO_SUFFIXES):
        return True
    return False


# ──────────────────────────────────────────────
# FilterInput
# ──────────────────────────────────────────────

class FilterInput(Input):
    """搜索输入框，值变化时发送 FilterChanged 消息。"""

    class FilterChanged(Message):
        """过滤文本已变更"""

        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    def __init__(self, id: str | None = None) -> None:
        super().__init__(placeholder="搜索函数名或模块名...", id=id)

    def on_input_changed(self, event: Input.Changed) -> None:
        self.post_message(self.FilterChanged(event.value))


# ──────────────────────────────────────────────
# StatusPanel
# ──────────────────────────────────────────────

class StatusPanel(Static):
    """顶部状态栏: PID / target / total / delta / event / interval"""

    def update_status(
        self,
        snapshot: DeltaSnapshot,
        target: str,
        interval: float,
    ) -> None:
        cur = snapshot.current
        total_str = format_count(cur.total_events)
        delta = format_delta(snapshot.total_delta_prev)

        line = Text()
        line.append(f"PID={cur.pid}", style="bold")
        line.append(f"  [{target}]", style="cyan")
        line.append(f"  Total: {total_str}", style="white")
        line.append("  \u0394: ")
        line.append_text(delta)
        line.append(f"  Event: {cur.event_name}", style="dim")
        line.append(f"  Interval: {interval}s", style="dim")
        self.update(line)


# ──────────────────────────────────────────────
# DetailPanel
# ──────────────────────────────────────────────

class DetailPanel(Static):
    """底部详情面板: 当前选中行的完整信息"""

    def update_detail(self, entry: DeltaEntry | None) -> None:
        if entry is None:
            self.update(Text("← 选择一行查看详情", style="dim"))
            return

        e = entry.entry
        info = Text()
        info.append("DSO: ", style="bold")
        info.append(f"{e.dso}\n", style="cyan")
        info.append("Symbol: ", style="bold")
        info.append(f"{e.symbol}\n", style="white")
        info.append("Events: ", style="bold")
        info.append(f"{e.event_count:,}", style="white")
        info.append("  Samples: ", style="bold")
        info.append(f"{e.sample_count:,}", style="white")
        info.append("  Pct: ", style="bold")
        info.append(f"{e.percentage:.2f}%", style="yellow")
        info.append("  \u0394prev: ")
        info.append_text(format_delta(entry.delta_prev))
        info.append("  \u0394base: ")
        info.append_text(format_delta(entry.delta_baseline))
        self.update(info)


# ──────────────────────────────────────────────
# PerfTable
# ──────────────────────────────────────────────

_COLUMNS = ("#", "占比%", "指令数", "Δ/prev", "Δ/base", "模块", "函数")


class PerfTable(DataTable):
    """函数级性能数据表格"""

    def on_mount(self) -> None:
        self.cursor_type = "row"
        self.zebra_stripes = True
        self.add_columns(*_COLUMNS)

    def update_data(
        self,
        snapshot: DeltaSnapshot,
        filter_text: str = "",
        java_only: bool = False,
    ) -> None:
        saved_key: str | None = None
        try:
            if self.row_count > 0:
                cursor = self.cursor_row
                rows = self.ordered_rows
                if 0 <= cursor < len(rows):
                    saved_key = rows[cursor].key.value
        except Exception:
            pass

        self.clear()

        entries = snapshot.entries
        if java_only:
            entries = [de for de in entries if is_java_entry(de.entry.dso)]
        if filter_text:
            needle = filter_text.lower()
            entries = [
                de for de in entries
                if needle in de.entry.symbol.lower()
                or needle in de.entry.dso.lower()
            ]

        for rank, de in enumerate(entries, 1):
            e = de.entry
            row_key = f"{e.dso}::{e.symbol}"

            self.add_row(
                Text(str(rank), style="dim"),
                Text(f"{e.percentage:5.1f}%", style="bold yellow"),
                Text(format_count(e.event_count), style="bold white"),
                format_delta(de.delta_prev),
                format_delta(de.delta_baseline),
                Text(shorten_dso(e.dso), style="cyan"),
                Text(truncate_symbol(e.symbol), style="white"),
                key=row_key,
            )

        cur = snapshot.current
        self.add_row(
            Text("", style="dim"),
            Text("100%", style="dim"),
            Text(format_count(cur.total_events), style="bold white"),
            format_delta(snapshot.total_delta_prev),
            format_delta(snapshot.total_delta_baseline),
            Text("═ TOTAL", style="bold white"),
            Text(""),
            key="__total__",
        )

        if saved_key is not None:
            try:
                self.move_cursor(row=self.get_row_index(saved_key))
            except Exception:
                pass
