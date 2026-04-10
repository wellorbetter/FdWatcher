#!/usr/bin/env python3
"""
fd_watcher.py — 实时监视 Android 进程的文件描述符分布 (类 csvlens 风格 TUI)

用法:
    python3 fd_watcher.py <package_or_pid> [--interval 5] [--adb /path/to/adb]

示例:
    python3 fd_watcher.py com.miui.personalassistant
    python3 fd_watcher.py com.miui.personalassistant --interval 1
    python3 fd_watcher.py com.miui.personalassistant -i 1 --adb /mnt/d/platform-tools/adb.exe
    python3 fd_watcher.py 28907 --interval 3 --adb adb.exe

操作说明:
    ↑/↓ 或 j/k   — 选择行
    Enter / Space — 展开/折叠该类型的 fd 详情
    d             — Dump 当前 /proc/pid/fd 快照到文件
    m             — 发送 monitortrack 信号 (kill -42，开始/停止记录)
    t             — 发送 fdtrack dump 信号 (kill -39)
    q / Ctrl+C    — 退出
"""

import re
import subprocess
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from typing import Optional

from textual.app import App, ComposeResult
from textual.widgets import (
    Header, Footer, DataTable, Static, Label, Log
)
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.reactive import reactive
from textual import work, on
from textual.binding import Binding
from rich.text import Text
from rich.style import Style


# ──────────────────────────────────────────────
# 数据层：从 adb 读取 /proc/pid/fd
# ──────────────────────────────────────────────

# 全局 adb 可执行路径，可通过 --adb 参数覆盖
ADB_BIN = "adb"

# WSL 下常见的 Windows adb.exe 位置，自动探测
_WSL_ADB_CANDIDATES = [
    "/mnt/c/platform-tools/adb.exe",
    "/mnt/d/platform-tools/adb.exe",
    "/mnt/c/Users/{}/AppData/Local/Android/Sdk/platform-tools/adb.exe",
]


def _detect_adb() -> str:
    """自动探测可用的 adb，返回可执行路径"""
    import shutil
    # 1. 系统 PATH 里有 adb
    if shutil.which("adb"):
        return "adb"
    # 2. WSL 下找 Windows 的 adb.exe
    import os
    for candidate in _WSL_ADB_CANDIDATES:
        if "{" in candidate:
            try:
                user = os.environ.get("USER", "")
                candidate = candidate.format(user)
            except Exception:
                continue
        if os.path.isfile(candidate):
            return candidate
    return "adb"  # fallback，出错时再提示


def adb_shell(cmd: str, timeout: int = 5) -> str:
    try:
        result = subprocess.run(
            [ADB_BIN, "shell", cmd],
            capture_output=True, text=True, timeout=timeout
        )
        return result.stdout
    except subprocess.TimeoutExpired:
        return ""
    except FileNotFoundError:
        return ""


def check_adb() -> tuple[bool, str]:
    """检查 adb 是否可用且有设备连接，返回 (ok, msg)"""
    try:
        r = subprocess.run([ADB_BIN, "devices"], capture_output=True, text=True, timeout=5)
        lines = [l for l in r.stdout.splitlines() if l.strip() and "List of devices" not in l]
        if not lines:
            return False, f"adb ({ADB_BIN}) 未找到连接的设备。\n  请检查：手机开启 USB 调试，USB 已连接 / adb connect <IP>:5555"
        if all("offline" in l for l in lines):
            return False, f"设备离线: {lines[0]}。请重新插拔或 adb reconnect"
        return True, lines[0].split()[0]  # 返回设备 serial
    except FileNotFoundError:
        return False, "找不到 adb 命令，请确认 adb 已安装并在 PATH 中"


def resolve_pid(target: str) -> Optional[str]:
    """将 package name 或 pid 字符串解析成 pid"""
    if target.isdigit():
        return target
    out = adb_shell(f"pidof {target}")
    pid = out.strip().split()[0] if out.strip() else None
    return pid


def read_fd_snapshot(pid: str) -> dict:
    """
    读取 /proc/pid/fd，返回:
    {
      'total': int,
      'types': {type_name: {'count': int, 'fds': [(fd_num, target), ...]}},
      'ashmem_inodes': {inode_name: [fd_num, ...]},   # ashmem 按 inode 聚合
      'timestamp': str,
      'pid': str,
    }
    """
    raw = adb_shell(f"ls -la /proc/{pid}/fd 2>/dev/null", timeout=8)
    lines = [l.strip() for l in raw.splitlines() if " -> " in l]

    result = {
        "total": len(lines),
        "types": defaultdict(lambda: {"count": 0, "fds": []}),
        "ashmem_inodes": defaultdict(list),
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "pid": pid,
    }

    for line in lines:
        # 格式: lrwxrwxrwx ... fd_num -> target
        m = re.search(r"(\d+) -> (.+)$", line)
        if not m:
            continue
        fd_num = int(m.group(1))
        target = m.group(2).strip()

        type_name = classify_fd(target)
        result["types"][type_name]["count"] += 1
        result["types"][type_name]["fds"].append((fd_num, target))

        if type_name.startswith("ashmem"):
            inode = target  # 用完整路径作为 inode key
            result["ashmem_inodes"][inode].append(fd_num)

    return result


def classify_fd(target: str) -> str:
    """将 fd 的目标路径分类"""
    if "ashmem" in target:
        return "ashmem"
    if target.startswith("socket:"):
        return "socket"
    if target.startswith("pipe:"):
        return "pipe"
    if target.startswith("anon_inode:[eventfd]"):
        return "anon_inode:eventfd"
    if target.startswith("anon_inode:[timerfd]"):
        return "anon_inode:timerfd"
    if target.startswith("anon_inode:[epoll]"):
        return "anon_inode:epoll"
    if target.startswith("anon_inode:sync_file"):
        return "anon_inode:sync_file"
    if target.startswith("anon_inode:"):
        return "anon_inode:other"
    if "/dev/binderfs" in target or "binder" in target:
        return "binder"
    if target == "/dev/null":
        return "dev/null"
    if target.startswith("/dev/"):
        dev = target.split("/")[2] if len(target.split("/")) > 2 else target
        return f"dev/{dev}"
    if any(target.endswith(x) for x in (".jar", ".apk", ".oat", ".dex", ".art", ".vdex")):
        return "framework_jars"
    if target.startswith("/data/"):
        return "data_files"
    if target.startswith("/system/") or target.startswith("/apex/") or target.startswith("/system_ext/"):
        return "system_files"
    if target.startswith("/product/"):
        return "product_files"
    return "other"


def dump_fd_snapshot(pid: str, out_dir: str = ".") -> str:
    """Dump /proc/pid/fd 到文件，返回文件路径"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = os.path.join(out_dir, f"fdwatch_dump_{pid}_{timestamp}.txt")
    raw = adb_shell(f"ls -la /proc/{pid}/fd 2>/dev/null", timeout=10)
    with open(fname, "w") as f:
        f.write(f"# fd dump for pid={pid}  time={timestamp}\n")
        f.write(raw)
    return fname


# ──────────────────────────────────────────────
# TUI 组件
# ──────────────────────────────────────────────

TYPE_COLORS = {
    "ashmem":           "bold red",
    "socket":           "cyan",
    "pipe":             "yellow",
    "binder":           "blue",
    "anon_inode:eventfd": "green",
    "anon_inode:epoll":   "green",
    "anon_inode:timerfd": "green",
    "anon_inode:sync_file": "magenta",
    "anon_inode:other":   "dim green",
    "framework_jars":   "dim white",
    "data_files":       "bright_white",
    "system_files":     "dim white",
    "product_files":    "dim white",
    "dev/null":         "dim",
}


def colored(text: str, type_name: str) -> Text:
    color = TYPE_COLORS.get(type_name, "white")
    return Text(text, style=color)


class FdWatcherApp(App):
    """主 TUI 应用"""

    CSS = """
    Screen {
        layout: vertical;
    }
    #top_bar {
        height: 3;
        background: $panel;
        padding: 0 1;
        layout: horizontal;
    }
    #status_label {
        width: 1fr;
        content-align: left middle;
    }
    #interval_label {
        width: auto;
        content-align: right middle;
        color: $text-muted;
    }
    #main_table {
        height: 1fr;
        border: solid $primary;
    }
    #detail_panel {
        height: 12;
        border: solid $secondary;
        background: $surface;
        padding: 0 1;
        overflow-y: auto;
    }
    #log_panel {
        height: 5;
        border: solid $accent;
        background: $surface-darken-1;
    }
    DataTable {
        height: 1fr;
    }
    #help_overlay {
        display: none;
        layer: above;
        width: 60;
        height: auto;
        background: $surface;
        border: double $primary;
        padding: 1 2;
        offset: 10 4;
    }
    #help_overlay.visible {
        display: block;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "退出"),
        Binding("d", "dump", "Dump快照"),
        Binding("m", "send_monitor", "Monitor(42)"),
        Binding("t", "send_fdtrack", "FdTrack(39)"),
        Binding("r", "refresh_now", "立即刷新"),
        Binding("z", "reset_baseline", "重置基线"),
        Binding("s", "screenshot", "截图(SVG)"),
        Binding("?", "show_help", "帮助"),
        Binding("up,k", "move_up", "上移", show=False),
        Binding("down,j", "move_down", "下移", show=False),
        Binding("enter,space", "toggle_detail", "展开详情", show=False),
    ]

    HELP_TEXT = """\
 [bold cyan]fd_watcher 按键帮助[/bold cyan]

 [bold]导航[/bold]
   ↑ / k        上移光标
   ↓ / j        下移光标
   Enter / Space  展开选中类型的 fd 详情（ashmem 显示 inode/dup 分布）

 [bold]操作[/bold]
   r   立即刷新一次（不等定时器）
   d   Dump 当前 /proc/pid/fd 快照到本地文件
   z   重置「△初始」基线为当前快照
   m   发送 kill -42  → monitortrack 开始/停止堆栈记录
   t   发送 kill -39  → fdtrack dump 调用栈到 logcat
   s   截图保存为 SVG 文件
   ?   显示本帮助
   q   退出

 [bold]列说明[/bold]
   数量      当前 fd 总数
   △5s      与上次刷新相比的变化（每 {interval}s 刷新一次）
   △初始    与启动时第一次快照相比的累计变化（z 键可重置）
   占比      该类型占总 fd 的百分比
   unique   ashmem 专属：unique inode 数 & 最大 dup 数

 [bold]启动参数[/bold]
   python3 fd_watcher.py <包名|pid|快照文件>
                         [--adb /path/to/adb.exe]
                         [--interval 5]

 [bold dim]按任意键关闭[/bold dim]"""

    # 响应式状态
    snapshot: reactive[Optional[dict]] = reactive(None)
    prev_snapshot: reactive[Optional[dict]] = reactive(None)
    selected_type: reactive[Optional[str]] = reactive(None)
    detail_expanded: reactive[bool] = reactive(False)

    def __init__(self, target: str, interval: float = 2.0):
        super().__init__()
        self.target = target
        self.interval = interval
        self.pid: Optional[str] = None
        self._history: list[dict] = []   # 保存最近 60 次快照用于趋势
        self.baseline_snapshot: Optional[dict] = None  # 第一次快照，作为基线

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="top_bar"):
            yield Label("正在连接...", id="status_label")
            yield Label(f"刷新间隔: {self.interval}s", id="interval_label")
        yield DataTable(id="main_table", cursor_type="row", zebra_stripes=True)
        yield ScrollableContainer(
            Static("← 选择一行后按 Enter 展开 ashmem inode 详情", id="detail_content"),
            id="detail_panel"
        )
        yield Log(id="log_panel", max_lines=50)
        # 帮助浮层，默认隐藏
        yield Static("", id="help_overlay")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#main_table", DataTable)
        table.add_columns(
            "类型", "数量", "△5s", "△初始", "占比", "unique(ashmem)"
        )
        self._start_polling()

    @work(exclusive=True, thread=True)
    def _start_polling(self) -> None:
        """后台线程轮询，自动重连"""
        # 先检查 adb 连接
        ok, msg = check_adb()
        if not ok:
            self.call_from_thread(self._log, f"[red]{msg}[/red]")
            return

        while True:
            # 每轮循环都重新解析 pid（进程重启后 pid 会变）
            pid = resolve_pid(self.target)
            if not pid:
                if self.pid:
                    # 之前连上过，现在进程消失了
                    self.call_from_thread(self._log, f"[yellow]进程 {self.target} 消失，等待重启...[/yellow]")
                    self.pid = None
                else:
                    self.call_from_thread(self._log, f"[dim]等待进程 {self.target} 启动...[/dim]")
                time.sleep(self.interval)
                continue

            if pid != self.pid:
                # 新 pid（首次连上或进程重启）
                self.pid = pid
                self.baseline_snapshot = None  # 重置基线
                self.call_from_thread(self._log, f"[green]已连接 PID={pid}[/green]")

            snap = read_fd_snapshot(pid)
            if not snap["total"] and snap["total"] == 0:
                # 读取失败（进程刚消失）
                time.sleep(self.interval)
                continue

            self.call_from_thread(self._update_ui, snap)
            time.sleep(self.interval)

    def _update_ui(self, snap: dict) -> None:
        """在主线程更新 UI"""
        self.prev_snapshot = self.snapshot
        self.snapshot = snap
        if self.baseline_snapshot is None:
            self.baseline_snapshot = snap  # 记录第一次作为基线
        self._history.append(snap)
        if len(self._history) > 60:
            self._history.pop(0)
        self._render_table()
        self._update_status()

    def _render_table(self) -> None:
        if not self.snapshot:
            return
        snap = self.snapshot
        prev = self.prev_snapshot
        base = self.baseline_snapshot
        table = self.query_one("#main_table", DataTable)

        # 刷新前记住当前光标所在的类型名（row key）
        # ordered_rows[i].key.value 是正确 API（get_row_at 返回的是 list[CellType]，没有 .key）
        saved_key = None
        try:
            if table.row_count > 0:
                cursor = table.cursor_row
                rows = table.ordered_rows
                if 0 <= cursor < len(rows):
                    saved_key = rows[cursor].key.value
        except Exception:
            pass

        table.clear()

        total = snap["total"]
        prev_total = prev["total"] if prev else total

        # 按数量排序
        sorted_types = sorted(
            snap["types"].items(),
            key=lambda x: x[1]["count"],
            reverse=True
        )

        for type_name, info in sorted_types:
            count = info["count"]
            prev_count = prev["types"][type_name]["count"] if prev and type_name in prev["types"] else count
            base_count = base["types"][type_name]["count"] if base and type_name in base["types"] else count
            delta = count - prev_count
            delta_base = count - base_count
            pct = f"{count/total*100:.1f}%" if total > 0 else "0%"

            # ashmem 专属：unique inode 统计
            unique_str = ""
            if type_name == "ashmem":
                unique_count = len(snap["ashmem_inodes"])
                max_dup = max((len(v) for v in snap["ashmem_inodes"].values()), default=0)
                unique_str = f"{unique_count} inode, max_dup={max_dup}"

            def fmt_delta(d: int) -> Text:
                if d > 0:  return Text(f"+{d}", style="bold red")
                if d < 0:  return Text(f"{d}", style="bold green")
                return Text("—", style="dim")

            # 类型名着色
            type_text = colored(type_name, type_name)

            # 数量：ashmem 特别标红
            count_style = "bold red" if type_name == "ashmem" and count > 100 else "white"
            count_text = Text(str(count), style=count_style)

            table.add_row(
                type_text,
                count_text,
                fmt_delta(delta),
                fmt_delta(delta_base),
                Text(pct, style="dim"),
                Text(unique_str, style="yellow") if unique_str else Text(""),
                key=type_name,
            )

        # 底部总计行
        base_total = base["total"] if base else total
        delta_total = total - prev_total if prev else 0
        delta_total_base = total - base_total

        def fmt_delta(d: int) -> Text:
            if d > 0:  return Text(f"+{d}", style="bold red")
            if d < 0:  return Text(f"{d}", style="bold green")
            return Text("—", style="dim")

        table.add_row(
            Text("═ TOTAL", style="bold white"),
            Text(str(total), style="bold white"),
            fmt_delta(delta_total),
            fmt_delta(delta_total_base),
            Text("100%"),
            Text(""),
            key="__total__",
        )

        # 恢复光标到同一类型名（即使排名变了也跟对行）
        if saved_key is not None:
            try:
                table.move_cursor(row=table.get_row_index(saved_key))
            except Exception:
                pass  # 该类型消失了就不恢复

    def _update_status(self) -> None:
        if not self.snapshot:
            return
        snap = self.snapshot
        label = self.query_one("#status_label", Label)
        label.update(
            f"PID={snap['pid']}  [{self.target}]  "
            f"总FD={snap['total']}  "
            f"时间={snap['timestamp']}"
        )

    def _log(self, msg: str) -> None:
        log = self.query_one("#log_panel", Log)
        log.write_line(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

    def _show_detail(self, type_name: str) -> None:
        if not self.snapshot:
            return
        snap = self.snapshot
        detail = self.query_one("#detail_content", Static)

        if type_name == "ashmem":
            lines = [f"[bold yellow]── ashmem inode 详情 ({snap['timestamp']}) ──[/bold yellow]"]
            inodes = snap["ashmem_inodes"]
            sorted_inodes = sorted(inodes.items(), key=lambda x: -len(x[1]))
            for inode, fds in sorted_inodes:
                fds_str = ", ".join(str(f) for f in sorted(fds)[:20])
                suffix = f"... (+{len(fds)-20})" if len(fds) > 20 else ""
                lines.append(
                    f"  [red]{len(fds):5d}x[/red]  [dim]{inode}[/dim]\n"
                    f"         fds: {fds_str}{suffix}"
                )
            detail.update("\n".join(lines))

        elif type_name in snap["types"]:
            info = snap["types"][type_name]
            lines = [f"[bold cyan]── {type_name} 详情 (共{info['count']}个) ──[/bold cyan]"]
            # 按 target 分组
            target_counter = Counter(t for _, t in info["fds"])
            for target, cnt in target_counter.most_common(30):
                lines.append(f"  {cnt:5d}x  {target}")
            detail.update("\n".join(lines))
        else:
            detail.update(f"无 {type_name} 数据")

    # ── 按键动作 ──

    def action_move_up(self) -> None:
        table = self.query_one("#main_table", DataTable)
        table.action_cursor_up()

    def action_move_down(self) -> None:
        table = self.query_one("#main_table", DataTable)
        table.action_cursor_down()

    def action_toggle_detail(self) -> None:
        table = self.query_one("#main_table", DataTable)
        if table.cursor_row is None or table.row_count == 0:
            return
        try:
            type_name = table.get_row_at(table.cursor_row).key.value
            if type_name and type_name != "__total__":
                self.selected_type = type_name
                self._show_detail(type_name)
        except Exception:
            pass

    @on(DataTable.RowSelected, "#main_table")
    def on_row_selected(self, event: DataTable.RowSelected) -> None:
        type_name = str(event.row_key.value) if event.row_key else None
        if type_name and type_name != "__total__":
            self.selected_type = type_name
            self._show_detail(type_name)

    def on_key(self, event) -> None:
        """任意键关闭帮助面板（? 键由 action_show_help toggle 处理）"""
        if event.key != "question_mark":
            overlay = self.query_one("#help_overlay", Static)
            if "visible" in overlay.classes:
                overlay.remove_class("visible")
                event.stop()

    def action_show_help(self) -> None:
        overlay = self.query_one("#help_overlay", Static)
        if "visible" in overlay.classes:
            overlay.remove_class("visible")
        else:
            # 把 interval 插入帮助文本
            text = self.HELP_TEXT.replace("{interval}", str(self.interval))
            overlay.update(text)
            overlay.add_class("visible")

    def action_reset_baseline(self) -> None:
        self.baseline_snapshot = self.snapshot
        self._log(f"[cyan]基线已重置为当前快照 ({self.snapshot['timestamp'] if self.snapshot else ''})[/cyan]")

    def action_refresh_now(self) -> None:
        if self.pid:
            snap = read_fd_snapshot(self.pid)
            self._update_ui(snap)
            self._log("手动刷新完成")

    @work(thread=True)
    def action_dump(self) -> None:
        if not self.pid:
            self.call_from_thread(self._log, "[red]未连接设备[/red]")
            return
        out_dir = os.path.dirname(os.path.abspath(__file__))
        fname = dump_fd_snapshot(self.pid, out_dir)
        self.call_from_thread(self._log, f"[green]Dump 完成: {fname}[/green]")

    @work(thread=True)
    def action_send_monitor(self) -> None:
        if not self.pid:
            return
        adb_shell(f"kill -42 {self.pid}")
        self.call_from_thread(self._log, f"[yellow]已发送 kill -42 到 pid={self.pid} (monitortrack toggle)[/yellow]")

    @work(thread=True)
    def action_send_fdtrack(self) -> None:
        if not self.pid:
            return
        adb_shell(f"kill -39 {self.pid}")
        self.call_from_thread(self._log, f"[yellow]已发送 kill -39 到 pid={self.pid} (fdtrack dump)[/yellow]")

    def action_screenshot(self) -> None:
        path = self.save_screenshot(path=".")
        self.notify(f"截图已保存: {path}")


# ──────────────────────────────────────────────
# 入口
# ──────────────────────────────────────────────

def analyze_file(path: str) -> None:
    """离线分析已有的 fd 快照文件（无需连接设备）"""
    with open(path) as f:
        content = f.read()

    lines = [l.strip() for l in content.splitlines() if " -> " in l]
    total = len(lines)

    type_groups: dict[str, list] = defaultdict(list)
    ashmem_inodes: dict[str, list] = defaultdict(list)

    for line in lines:
        m = re.search(r"(\d+) -> (.+)$", line)
        if not m:
            continue
        fd_num = int(m.group(1))
        target = m.group(2).strip()
        t = classify_fd(target)
        type_groups[t].append((fd_num, target))
        if t == "ashmem":
            ashmem_inodes[target].append(fd_num)

    print(f"\n{'═'*60}")
    print(f"  FD Snapshot Analysis: {os.path.basename(path)}")
    print(f"  Total FDs: {total}")
    print(f"{'═'*60}")
    print(f"{'类型':<30}  {'数量':>6}  {'占比':>6}")
    print(f"{'─'*60}")

    for t, fds in sorted(type_groups.items(), key=lambda x: -len(x[1])):
        pct = len(fds) / total * 100 if total else 0
        marker = " ◀ LEAK?" if t == "ashmem" and len(fds) > 200 else ""
        print(f"  {t:<28}  {len(fds):>6}  {pct:>5.1f}%{marker}")

    print(f"{'─'*60}")
    print(f"  {'TOTAL':<28}  {total:>6}  100.0%\n")

    if ashmem_inodes:
        print(f"{'─'*60}")
        print(f"  ashmem inode 分析 (共 {len(ashmem_inodes)} 个 inode):")
        print(f"{'─'*60}")
        for inode, fds in sorted(ashmem_inodes.items(), key=lambda x: -len(x[1])):
            dup_info = f"  [{len(fds)} fds = 1 inode × {len(fds)} dup]" if len(fds) > 1 else ""
            print(f"  {len(fds):>6}x  {inode}{dup_info}")
            # 打印前 10 个 fd 编号
            fd_sample = ", ".join(str(f) for f in sorted(fds)[:10])
            suffix = f" ...+{len(fds)-10}" if len(fds) > 10 else ""
            print(f"         fds: [{fd_sample}{suffix}]")
        print()


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="fd_watcher — 实时监视 Android 进程 fd 分布",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("target", help="包名、pid 或本地快照文件路径")
    parser.add_argument("--interval", "-i", type=float, default=5.0, help="刷新间隔（秒），默认 5")
    parser.add_argument("--adb", default=None,
                        help="adb 可执行路径，例如 /mnt/d/platform-tools/adb.exe 或 adb.exe")
    args = parser.parse_args()

    # 设置全局 ADB_BIN
    global ADB_BIN
    if args.adb:
        ADB_BIN = args.adb
    else:
        ADB_BIN = _detect_adb()

    print(f"使用 adb: {ADB_BIN}", file=sys.stderr)

    # 如果传入的是文件路径，走离线分析模式
    if os.path.isfile(args.target):
        analyze_file(args.target)
        sys.exit(0)

    app = FdWatcherApp(target=args.target, interval=args.interval)
    app.run()


if __name__ == "__main__":
    main()
