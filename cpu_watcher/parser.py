"""解析 simpleperf report --csv 输出为 PerfSnapshot。"""

from __future__ import annotations

import csv
import re
from datetime import datetime

from .model import PerfEntry, PerfSnapshot


def parse_simpleperf_csv(csv_text: str, max_entries: int = 50) -> PerfSnapshot | None:
    if not csv_text or not csv_text.strip():
        return None

    event_name = ""
    total_samples = 0
    total_event_count = 0

    data_lines: list[str] = []
    for line in csv_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        # Header 元数据: 两种格式都兼容
        # 格式 1 (注释): # event: instructions
        # 格式 2 (Key:Val): Event: instructions:u (type 0, config 1)
        if stripped.startswith("#") or ":" in stripped and not stripped.startswith("Overhead"):
            text = stripped.lstrip("# ")
            if m := re.match(r"(?:Event|event):\s*(\S+)", text):
                event_name = m.group(1)
            elif m := re.match(r"(?:Samples|samples):\s*(\d+)", text):
                total_samples = int(m.group(1))
            elif m := re.match(r"(?:Event count|event_count):\s*(\d+)", text):
                total_event_count = int(m.group(1))
            # 跳过 Cmdline:, Arch: 等无关 header
            if not stripped.startswith("Overhead"):
                continue

        data_lines.append(stripped)

    if not data_lines:
        return None

    reader = csv.DictReader(data_lines)
    entries: list[PerfEntry] = []
    for row in reader:
        try:
            overhead = row.get("Overhead", "0").strip().rstrip("%")
            # 兼容两种列名: "EventCount" (实际) 和 "Event Count" (文档)
            event_count_str = (
                row.get("EventCount")
                or row.get("Event Count")
                or "0"
            ).strip()
            entries.append(PerfEntry(
                dso=row.get("Shared Object", "").strip(),
                symbol=row.get("Symbol", "").strip(),
                event_count=int(event_count_str),
                sample_count=int(row.get("Sample", "0").strip()),
                percentage=float(overhead) if overhead else 0.0,
            ))
        except (ValueError, KeyError):
            continue

    if not entries:
        return None

    entries.sort(key=lambda e: e.event_count, reverse=True)
    entries = entries[:max_entries]

    return PerfSnapshot(
        timestamp=datetime.now().strftime("%H:%M:%S"),
        pid="",
        total_events=total_event_count,
        total_samples=total_samples,
        event_name=event_name,
        duration_ms=0,
        entries=tuple(entries),
    )
