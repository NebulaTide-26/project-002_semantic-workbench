"""设置对话框：选择 / 更换数据目录。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.adapters.os_open import open_folder
from app.core import app_settings
from app.core.app_settings import DataDirState

STATE_TEXT: dict[DataDirState, str] = {
    DataDirState.OK: "这里已有 Workbench 数据，会直接打开。",
    DataDirState.EMPTY: "空文件夹，将在这里初始化。",
    DataDirState.MISSING_DB: "像是 Workbench 数据目录，但 workbench.db 不见了。",
    DataDirState.NON_EMPTY: "文件夹里已有其他文件，不能用作数据目录。",
    DataDirState.MISSING: "文件夹不存在，可以创建。",
    DataDirState.NOT_A_DIR: "这个路径不是文件夹。",
    DataDirState.NOT_WRITABLE: "没有写入权限。",
}

REASON_TEXT: dict[DataDirState, str] = {
    DataDirState.OK: "",
    DataDirState.EMPTY: "文件夹是空的（数据文件缺失）",
    DataDirState.MISSING_DB: "数据文件缺失（workbench.db 不存在）",
    DataDirState.NON_EMPTY: "文件夹里已有其他文件，不是有效的 Workbench 数据目录",
    DataDirState.MISSING: "文件夹不存在（可能被移动或删除）",
    DataDirState.NOT_A_DIR: "路径不是文件夹",
    DataDirState.NOT_WRITABLE: "没有写入权限",
}

_REFUSE_TEXT = (
    "不能把这个文件夹用作数据目录。\n\n"
    "请选择一个空文件夹，或新建一个。"
)


class SettingsDialog(QDialog):
    """只负责选目录和确认；真正的初始化与开库由 MainWindow 执行。"""

    def __init__(
        self, parent: QWidget | None = None, current: str | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumWidth(620)

        self._selected: str | None = current
        self._confirmed: set[str] = set()

        self._path_edit = QLineEdit(current or "")
        self._path_edit.setReadOnly(True)
        self._path_edit.setPlaceholderText("尚未选择数据目录")

        choose = QPushButton("更改…")
        choose.clicked.connect(self._choose)
        open_btn = QPushButton("打开文件夹")
        open_btn.clicked.connect(self._open_current)

        row = QHBoxLayout()
        row.addWidget(self._path_edit, 1)
        row.addWidget(choose)
        row.addWidget(open_btn)

        self._state_label = QLabel("")
        self._state_label.setWordWrap(True)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("数据目录（所有项目数据都保存在这里）"))
        layout.addLayout(row)
        layout.addWidget(self._state_label)
        layout.addStretch(1)
        layout.addWidget(buttons)

        self._refresh_state()

    def _refresh_state(self) -> None:
        if not self._selected:
            self._state_label.setText("尚未选择数据目录。")
            return
        state = app_settings.inspect_data_dir(Path(self._selected))
        self._state_label.setText(STATE_TEXT.get(state, ""))

    def _choose(self) -> None:
        start = self._selected or str(Path.home())
        path = QFileDialog.getExistingDirectory(self, "选择数据目录", start)
        if not path:
            return

        path = str(Path(path))
        state = app_settings.inspect_data_dir(Path(path))

        if state in (
            DataDirState.NOT_A_DIR,
            DataDirState.NOT_WRITABLE,
            DataDirState.NON_EMPTY,
            DataDirState.MISSING_DB,
        ):
            text = f"{path}\n\n错误原因：{REASON_TEXT[state]}\n\n{_REFUSE_TEXT}"
            if state == DataDirState.MISSING_DB:
                text += "\n\n如果这是旧的数据目录，可以从 backups 文件夹里恢复一份备份。"
            QMessageBox.warning(self, "无法使用这个文件夹", text)
            return

        if state == DataDirState.OK:
            text = f"这个文件夹里已有 Workbench 数据：\n{path}\n\n要使用它吗？"
        elif state == DataDirState.MISSING:
            text = f"文件夹不存在：\n{path}\n\n要创建它吗？"
        else:  # EMPTY
            text = f"将在这个空文件夹里初始化 Workbench 数据：\n{path}\n\n继续吗？"

        answer = QMessageBox.question(self, "确认数据目录", text)
        if answer != QMessageBox.StandardButton.Yes:
            return

        self._selected = path
        self._confirmed.add(path)
        self._path_edit.setText(path)
        self._refresh_state()

    def _on_ok(self) -> None:
        if not self._selected:
            QMessageBox.warning(self, "尚未选择", "请先选择一个数据目录。")
            return

        path = Path(self._selected)
        state = app_settings.inspect_data_dir(path)
        if state in (
            DataDirState.NOT_A_DIR,
            DataDirState.NOT_WRITABLE,
            DataDirState.NON_EMPTY,
            DataDirState.MISSING_DB,
        ):
            text = f"{path}\n\n错误原因：{REASON_TEXT[state]}\n\n{_REFUSE_TEXT}"
            if state == DataDirState.MISSING_DB:
                text += "\n\n如果这是旧的数据目录，可以从 backups 文件夹里恢复一份备份。"
            QMessageBox.warning(self, "无法使用这个文件夹", text)
            return

        if state != DataDirState.OK and str(path) not in self._confirmed:
            if state == DataDirState.MISSING:
                text = f"文件夹不存在：\n{path}\n\n要创建它吗？"
            else:  # EMPTY
                text = f"将在这个空文件夹里初始化 Workbench 数据：\n{path}\n\n继续吗？"
            if QMessageBox.question(self, "确认数据目录", text) != QMessageBox.StandardButton.Yes:
                return
            self._confirmed.add(str(path))

        super().accept()

    def _open_current(self) -> None:
        if self._selected and Path(self._selected).exists():
            open_folder(self._selected)

    def selected_data_dir(self) -> str | None:
        return self._selected
