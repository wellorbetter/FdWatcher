"""
纯数据模型 — 所有模块的共享契约。

零外部依赖，只用标准库。其他模块 import model 获取数据结构，
不直接 import 彼此 → 依赖倒置的基础。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class Issue:
    """GitHub Issue（不可变）"""
    repo: str
    number: int
    title: str
    state: str
    author: str
    labels: tuple[str, ...]
    comments: int
    created_at: str
    updated_at: str
    url: str


@dataclass(frozen=True, slots=True)
class PullRequest:
    """GitHub Pull Request（不可变）"""
    repo: str
    number: int
    title: str
    state: str
    author: str
    labels: tuple[str, ...]
    reviews: int
    draft: bool
    mergeable: bool
    created_at: str
    updated_at: str
    url: str


@dataclass(frozen=True, slots=True)
class Notification:
    """GitHub Notification（不可变）"""
    id: str
    repo: str
    title: str
    type: str
    reason: str
    unread: bool
    updated_at: str
    url: str


@dataclass(frozen=True, slots=True)
class DashboardSnapshot:
    """一次完整刷新的聚合快照"""
    timestamp: str
    username: str
    issues: tuple[Issue, ...] = ()
    pull_requests: tuple[PullRequest, ...] = ()
    notifications: tuple[Notification, ...] = ()
    repos: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CollectorConfig:
    """采集器配置（不可变）"""
    username: str = ""
    extra_repos: tuple[str, ...] = ()
    interval_s: float = 60.0
    limit: int = 30
    gh_bin: str = "gh"
    include_closed: bool = False


@runtime_checkable
class DataCollector(Protocol):
    """数据采集器协议 — 依赖倒置的关键抽象。"""

    def collect(self) -> DashboardSnapshot | None:
        """执行一次数据采集，返回快照。采集失败返回 None。"""
        ...

    def check_ready(self) -> tuple[bool, str]:
        """检查采集环境是否就绪，返回 (ok, message)。"""
        ...

    def get_target_display(self) -> str:
        """返回监控目标的显示名称。"""
        ...
