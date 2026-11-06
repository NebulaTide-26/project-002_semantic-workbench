"""枚举用户桌面与公共桌面上的项目。

纯逻辑，不依赖 Qt，方便单测。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from app.core.models import ResourceKind

_HIDDEN_OR_SYSTEM = 0x2 | 0x4


@dataclass(slots=True)
class DesktopItem:
    path: Path
    location: str
    kind: ResourceKind
    kind_label: str


def kind_for_path(path: Path) -> ResourceKind:
    if path.is_dir():
        return ResourceKind.FOLDER
    if path.suffix.lower() in {".exe", ".com"}:
        return ResourceKind.APP
    return ResourceKind.FILE


def _kind_label(kind: ResourceKind, path: Path) -> str:
    if kind is ResourceKind.FOLDER:
        return "文件夹"
    if kind is ResourceKind.APP:
        return "程序"
    if path.suffix.lower() == ".lnk":
        return "快捷方式"
    return "文件"


def default_desktop_dirs() -> list[tuple[Path, str]]:
    user_desktop = Path.home() / "Desktop"
    public_root = Path(os.environ.get("PUBLIC", r"C:\Users\Public"))
    return [
        (user_desktop, "用户桌面"),
        (public_root / "Desktop", "公共桌面"),
    ]


def collect_desktop_items(
    desktop_dirs: list[tuple[Path, str]] | None = None,
) -> list[DesktopItem]:
    dirs = desktop_dirs or default_desktop_dirs()
    order = {location: index for index, (_, location) in enumerate(dirs)}
    items: list[DesktopItem] = []

    for directory, location in dirs:
        try:
            entries = list(directory.iterdir())
        except OSError:
            continue

        for path in entries:
            try:
                attributes = getattr(path.stat(), "st_file_attributes", 0)
            except OSError:
                continue
            if attributes & _HIDDEN_OR_SYSTEM:
                continue
            if path.name.lower() == "desktop.ini":
                continue

            kind = kind_for_path(path)
            items.append(
                DesktopItem(
                    path=path,
                    location=location,
                    kind=kind,
                    kind_label=_kind_label(kind, path),
                )
            )

    items.sort(
        key=lambda item: (
            order.get(item.location, 99),
            item.path.name.lower(),
        )
    )
    return items
