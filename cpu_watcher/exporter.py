"""导出功能 — 快照落盘 & flamegraph 折叠栈输出。"""

from __future__ import annotations

import os
from datetime import datetime

from .model import DeltaSnapshot, PerfSnapshot


def _format_count(n: int) -> str:
    """千分位格式化整数，如 12345678 → '12,345,678'"""
    return f"{n:,}"


def dump_snapshot(snapshot: DeltaSnapshot, out_dir: str = ".") -> str:
    """将 DeltaSnapshot 写入人类可读的文本文件，返回文件路径。"""
    cur = snapshot.current
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = os.path.join(out_dir, f"cpu_perf_dump_{cur.pid}_{timestamp}.txt")

    has_delta = any(
        e.delta_prev != 0 or e.delta_baseline != 0
        for e in snapshot.entries
    )

    lines: list[str] = []
    lines.append("# cpu_watcher snapshot")
    lines.append(
        f"# PID: {cur.pid}  Time: {cur.timestamp}  Event: {cur.event_name}"
    )
    lines.append(f"# Total events: {_format_count(cur.total_events)}")
    lines.append(f"# Duration: {cur.duration_ms}ms")
    lines.append("#")

    if has_delta:
        header = (
            f"# {'Rank':>4}  {'DSO':<28}  {'Symbol':<40}  "
            f"{'Events':>14}  {'%':>6}  {'Δ/prev':>12}  {'Δ/baseline':>12}"
        )
        sep_len = 4 + 2 + 28 + 2 + 40 + 2 + 14 + 2 + 6 + 2 + 12 + 2 + 12
    else:
        header = (
            f"# {'Rank':>4}  {'DSO':<28}  {'Symbol':<40}  "
            f"{'Events':>14}  {'%':>6}"
        )
        sep_len = 4 + 2 + 28 + 2 + 40 + 2 + 14 + 2 + 6

    lines.append(header)
    lines.append(f"# {'─' * sep_len}")

    for rank, de in enumerate(snapshot.entries, 1):
        e = de.entry
        evt_str = _format_count(e.event_count)
        pct_str = f"{e.percentage:.2f}%"
        dso = e.dso[:28]
        sym = e.symbol[:40]

        if has_delta:
            dp = f"+{_format_count(de.delta_prev)}" if de.delta_prev > 0 else _format_count(de.delta_prev)
            db = f"+{_format_count(de.delta_baseline)}" if de.delta_baseline > 0 else _format_count(de.delta_baseline)
            lines.append(
                f"  {rank:>4}  {dso:<28}  {sym:<40}  "
                f"{evt_str:>14}  {pct_str:>6}  {dp:>12}  {db:>12}"
            )
        else:
            lines.append(
                f"  {rank:>4}  {dso:<28}  {sym:<40}  "
                f"{evt_str:>14}  {pct_str:>6}"
            )

    with open(fname, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        f.write("\n")

    return fname


def export_flamegraph_data(snapshot: PerfSnapshot, out_dir: str = ".") -> str:
    """写出 Brendan Gregg 折叠栈格式文件，返回文件路径。

    每行格式: dso;symbol event_count
    可直接传给 flamegraph.pl 生成火焰图。
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = os.path.join(out_dir, f"cpu_perf_flame_{snapshot.pid}_{timestamp}.folded")

    with open(fname, "w", encoding="utf-8") as f:
        for entry in snapshot.entries:
            f.write(f"{entry.dso};{entry.symbol} {entry.event_count}\n")

    return fname
