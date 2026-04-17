"""
纯数据模型 — 所有模块的共享契约。

零外部依赖，只用标准库。其他模块 import model 获取数据结构，
不直接 import 彼此 → 依赖倒置的基础。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class PerfEntry:
    """单个函数的性能采样条目（不可变）"""
    dso: str                  # 共享库/模块名 (e.g. "base.apk", "libhwui.so")
    symbol: str               # 函数符号名 (e.g. "com.miui.maml.ScreenElementRoot.doTick")
    event_count: int          # 本周期该函数的事件计数 (instructions)
    sample_count: int         # 采样命中次数
    percentage: float         # 占总事件的百分比 (0-100)


@dataclass(frozen=True, slots=True)
class PerfSnapshot:
    """一次完整采样周期的快照（不可变）"""
    timestamp: str            # 采集时间 "HH:MM:SS"
    pid: str                  # 进程 PID
    total_events: int         # 该周期总事件计数
    total_samples: int        # 该周期总采样数
    event_name: str           # 事件类型名 (e.g. "instructions")
    duration_ms: int          # record 持续时间 (ms)
    entries: tuple[PerfEntry, ...] = ()  # 按 event_count 降序排列


@dataclass(slots=True)
class DeltaEntry:
    """带 delta 变化的展示条目"""
    entry: PerfEntry          # 当前数据
    delta_prev: int = 0       # 与上次快照的 event_count 差值
    delta_baseline: int = 0   # 与基线快照的 event_count 差值


@dataclass(slots=True)
class DeltaSnapshot:
    """带 delta 追踪的完整快照，用于 TUI 渲染"""
    current: PerfSnapshot
    entries: list[DeltaEntry] = field(default_factory=list)
    total_delta_prev: int = 0
    total_delta_baseline: int = 0


class DeltaTracker:
    """计算快照间的 delta 变化。线程安全 — 可从后台线程 update 同时从主线程 reset。"""

    def __init__(self) -> None:
        import threading
        self._lock = threading.Lock()
        self._baseline: PerfSnapshot | None = None
        self._baseline_map: dict[tuple[str, str], int] = {}
        self._prev: PerfSnapshot | None = None

    def reset_baseline(self) -> None:
        with self._lock:
            self._baseline = self._prev
            self._baseline_map = (
                self._build_lookup(self._prev) if self._prev else {}
            )

    def update(self, snapshot: PerfSnapshot) -> DeltaSnapshot:
        with self._lock:
            if self._baseline is None:
                self._baseline = snapshot
                self._baseline_map = self._build_lookup(snapshot)

            prev_map = self._build_lookup(self._prev) if self._prev else {}

            delta_entries: list[DeltaEntry] = []
            for entry in snapshot.entries:
                key = (entry.dso, entry.symbol)
                prev_count = prev_map.get(key, 0)
                base_count = self._baseline_map.get(key, 0)
                delta_entries.append(DeltaEntry(
                    entry=entry,
                    delta_prev=entry.event_count - prev_count,
                    delta_baseline=entry.event_count - base_count,
                ))

            total_prev = self._prev.total_events if self._prev else snapshot.total_events
            total_base = self._baseline.total_events

            self._prev = snapshot

            return DeltaSnapshot(
                current=snapshot,
                entries=delta_entries,
                total_delta_prev=snapshot.total_events - total_prev,
                total_delta_baseline=snapshot.total_events - total_base,
            )

    @staticmethod
    def _build_lookup(snap: PerfSnapshot) -> dict[tuple[str, str], int]:
        return {(e.dso, e.symbol): e.event_count for e in snap.entries}


@runtime_checkable
class DataCollector(Protocol):
    """数据采集器协议 — 依赖倒置的关键抽象。

    TUI 层依赖此 Protocol，不依赖具体的 SimpleperfCollector。
    未来可扩展 PerfettoCollector、MockCollector 等实现。
    """

    def collect(self) -> PerfSnapshot | None:
        """执行一次数据采集，返回快照。采集失败返回 None。"""
        ...

    def check_ready(self) -> tuple[bool, str]:
        """检查采集环境是否就绪，返回 (ok, message)。"""
        ...

    def get_target_display(self) -> str:
        """返回监控目标的显示名称 (如包名或 PID)。"""
        ...


@dataclass(frozen=True, slots=True)
class CollectorConfig:
    """采集器配置（不可变）"""
    target: str               # 包名或 PID
    duration_s: float = 1.0   # 每次 record 持续时间 (秒)
    interval_s: float = 3.0   # 采集周期间隔 (秒)
    event: str = "instructions:u"  # PMU 事件名 (:u = 仅用户空间，兼容性更好)
    max_entries: int = 50     # 最多保留 top N 条目
    adb_bin: str = "adb"      # adb 可执行路径
    device_tmp: str = "/data/local/tmp"  # 设备临时目录
