"""v0.1 数据模型。

这一层只描述「数据长什么样」：不碰数据库、不碰界面、不做 IO。
整个程序（repo / launcher / UI）都用这里的对象交流。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ResourceKind(str, Enum):
    """进入项目时可以启动的资源类型。"""

    URL = "url"
    FILE = "file"
    FOLDER = "folder"
    APP = "app"

    @property
    def label(self) -> str:
        return _KIND_LABELS[self]


_KIND_LABELS = {
    ResourceKind.URL: "网页",
    ResourceKind.FILE: "文件",
    ResourceKind.FOLDER: "文件夹",
    ResourceKind.APP: "程序",
}


@dataclass(slots=True)
class Project:
    """一个有边界、有配置、有上下文的工作单元。"""

    id: int | None = None
    name: str = ""
    description: str = ""
    work_dir: str = ""
    maximize: bool = False
    created_at: datetime | None = None
    last_entered_at: datetime | None = None
    last_left_at: datetime | None = None


@dataclass(slots=True)
class Resource:
    """属于某个项目、进入项目时要启动的一个目标。"""

    id: int | None = None
    project_id: int = 0
    kind: ResourceKind = ResourceKind.URL
    target: str = ""
    args: list[str] = field(default_factory=list)
    sort_order: int = 0
    enabled: bool = True


@dataclass(slots=True)
class LaunchResult:
    """一次资源启动的结果（M3 使用）。"""

    resource: Resource
    ok: bool
    message: str = ""
    elapsed_ms: int = 0
