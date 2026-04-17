"""自定义 Textual Message 类型 — 组件间解耦通信。

借鉴 posting/toolong 的 message-driven 模式：
- 组件只发/收 Message，不直接引用其他组件
- can_replace() 防止采集慢于渲染时消息堆积
"""

from __future__ import annotations

from textual.message import Message

from .model import DeltaSnapshot


class SnapshotUpdated(Message):
    """新的性能快照已就绪"""

    def __init__(self, snapshot: DeltaSnapshot) -> None:
        super().__init__()
        self.snapshot = snapshot

    def can_replace(self, message: Message) -> bool:
        return isinstance(message, SnapshotUpdated)


class CollectorError(Message):
    """采集器遇到错误"""

    def __init__(self, error: str) -> None:
        super().__init__()
        self.error = error


class CollectorStatus(Message):
    """采集器状态变更 (连接、断开、等待进程)"""

    def __init__(self, status: str, detail: str = "") -> None:
        super().__init__()
        self.status = status  # "connected" | "waiting" | "disconnected" | "error"
        self.detail = detail
