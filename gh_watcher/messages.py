"""Textual Message 定义 — 后台采集线程 → 主线程渲染。"""

from __future__ import annotations

from textual.message import Message

from .model import DashboardSnapshot


class SnapshotUpdated(Message):
    """采集到新的 Dashboard 快照。"""

    def __init__(self, snapshot: DashboardSnapshot) -> None:
        self.snapshot = snapshot
        super().__init__()


class CollectorError(Message):
    """采集过程发生错误。"""

    def __init__(self, error: str) -> None:
        self.error = error
        super().__init__()


class CollectorStatus(Message):
    """采集状态变更（如 "正在刷新..."）。"""

    def __init__(self, status: str) -> None:
        self.status = status
        super().__init__()
