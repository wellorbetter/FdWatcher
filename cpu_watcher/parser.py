"""解析 simpleperf report --csv 输出为 PerfSnapshot。

兼容两种 CSV 格式:
  普通模式:   Overhead,Sample,EventCount,Shared Object,Symbol
  --children: Children,Self,Sample,AccEventCount,SelfEventCount,Shared Object,Symbol
"""

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

    # 两阶段解析: 先找 CSV header 行，header 之前都是元数据，之后都是数据
    lines = csv_text.splitlines()
    csv_start_idx = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(("Overhead,", "Children,")):
            csv_start_idx = i
            break
        # 元数据行
        text = stripped.lstrip("# ")
        if m := re.match(r"(?:Event|event):\s*(\S+)", text):
            event_name = m.group(1)
        elif m := re.match(r"(?:Samples|samples):\s*(\d+)", text):
            total_samples = int(m.group(1))
        elif m := re.match(r"(?:Event count|event_count):\s*(\d+)", text):
            total_event_count = int(m.group(1))

    if csv_start_idx < 0:
        return None

    data_lines = [l.strip() for l in lines[csv_start_idx:] if l.strip()]

    reader = csv.DictReader(data_lines)
    fieldnames = reader.fieldnames or []
    is_children_mode = "Children" in fieldnames

    entries: list[PerfEntry] = []
    for row in reader:
        try:
            if is_children_mode:
                pct_str = row.get("Children", "0").strip().rstrip("%")
                event_count_str = row.get("AccEventCount", "0").strip()
            else:
                pct_str = row.get("Overhead", "0").strip().rstrip("%")
                event_count_str = (
                    row.get("EventCount")
                    or row.get("Event Count")
                    or "0"
                ).strip()

            dso = row.get("Shared Object", "").strip()
            symbol = row.get("Symbol", "").strip()
            if not dso and not symbol:
                continue

            entries.append(PerfEntry(
                dso=dso,
                symbol=symbol,
                event_count=int(event_count_str),
                sample_count=int(row.get("Sample", "0").strip()),
                percentage=float(pct_str) if pct_str else 0.0,
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
