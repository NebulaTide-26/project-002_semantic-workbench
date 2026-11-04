"""机器级设置：只保存「数据目录在哪里」这个指针。

业务数据（项目、资源、事件）一律在数据目录里的 workbench.db，不在这里。
指针文件位置：%APPDATA%\\NebulaTide\\Workbench\\settings.json
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class SettingsError(Exception):
    """设置文件无法读取或格式损坏。"""


class DataDirState(Enum):
    """选择数据目录时可能遇到的状态。"""

    OK = "ok"                      # 已有 workbench.db
    EMPTY = "empty"                # 完全空的目录
    MISSING_DB = "missing_db"      # 只有本程序生成的文件，但 workbench.db 不见了
    NON_EMPTY = "non_empty"        # 有其他文件，但没有 workbench.db
    MISSING = "missing"            # 目录不存在
    NOT_A_DIR = "not_a_dir"        # 路径存在但不是文件夹
    NOT_WRITABLE = "not_writable"  # 没有写入权限


@dataclass(slots=True)
class AppSettings:
    data_dir: str | None = None


# 本程序会在数据目录里创建的东西；只有这些时仍视为「空目录」
_KNOWN_ENTRIES = {"workbench.db", "logs", "backups", "README.txt", "profiles"}

_README_TEXT = """这是一个由「Workbench / 本地语义化工作台」使用的数据目录。

- workbench.db   主数据库（项目、资源、事件）
- logs/          运行日志
- backups/       自动备份

注意：不要把这里当成存放文件的仓库。被整理的文件夹仍留在它们原来的位置。
手动备份或移动本目录前，请先关闭程序。
"""


def settings_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return base / "NebulaTide" / "Workbench"


def settings_path() -> Path:
    return settings_dir() / "settings.json"


def load() -> AppSettings:
    """读取指针文件。文件不存在返回空设置；损坏则抛 SettingsError。"""
    path = settings_path()
    if not path.exists():
        return AppSettings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SettingsError(f"设置文件读取失败：{path}（{exc}）") from exc
    if not isinstance(data, dict):
        raise SettingsError(f"设置文件格式不正确：{path}")
    data_dir = data.get("data_dir")
    if data_dir is not None and not isinstance(data_dir, str):
        raise SettingsError(f"设置文件中的 data_dir 不是字符串：{path}")
    return AppSettings(data_dir=data_dir)


def save(settings: AppSettings) -> None:
    """原子写入：先写临时文件，再整体替换，避免半截文件。"""
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {"data_dir": settings.data_dir}, ensure_ascii=False, indent=2
    )
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


def inspect_data_dir(path: Path) -> DataDirState:
    """判断一个文件夹能不能用作数据目录。"""
    if not path.exists():
        return DataDirState.MISSING
    if not path.is_dir():
        return DataDirState.NOT_A_DIR
    probe = path / f".write_test_{os.getpid()}"
    try:
        probe.write_text("", encoding="utf-8")
    except OSError:
        return DataDirState.NOT_WRITABLE
    finally:
        try:
            probe.unlink()
        except OSError:
            pass

    names = {entry.name for entry in path.iterdir()}
    if "workbench.db" in names:
        return DataDirState.OK
    if not names:
        return DataDirState.EMPTY
    if names <= _KNOWN_ENTRIES:
        return DataDirState.MISSING_DB
    return DataDirState.NON_EMPTY


def ensure_initialized(path: Path) -> None:
    """创建目录结构（logs / backups / README）。可重复调用。"""
    path.mkdir(parents=True, exist_ok=True)
    (path / "logs").mkdir(exist_ok=True)
    (path / "backups").mkdir(exist_ok=True)
    readme = path / "README.txt"
    if not readme.exists():
        readme.write_text(_README_TEXT, encoding="utf-8")
