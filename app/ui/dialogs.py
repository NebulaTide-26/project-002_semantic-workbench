"""通用对话框：新建 / 编辑项目。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.models import LaunchResult, Project, Resource, ResourceKind
from app.core.resource_check import check_resource


class ProjectDialog(QDialog):
    """新建或编辑项目。调用方通过 values() 拿结果。"""

    def __init__(
        self, parent: QWidget | None = None, project: Project | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("编辑项目" if project else "新建项目")
        self.setMinimumWidth(480)

        self._name = QLineEdit(project.name if project else "")
        self._name.setPlaceholderText("必填，例如：OOPre 作业")

        self._description = QPlainTextEdit(project.description if project else "")
        self._description.setPlaceholderText("可选")
        self._description.setFixedHeight(84)

        self._work_dir = QLineEdit(project.work_dir if project else "")
        self._work_dir.setPlaceholderText("可选，例如：D:\\课程\\OOPre")
        browse = QPushButton("浏览…")
        browse.clicked.connect(self._browse_work_dir)
        work_row = QHBoxLayout()
        work_row.addWidget(self._work_dir, 1)
        work_row.addWidget(browse)

        form = QFormLayout()
        form.addRow("项目名", self._name)
        form.addRow("描述", self._description)
        form.addRow("工作目录", work_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _browse_work_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "选择工作目录", self._work_dir.text()
        )
        if path:
            self._work_dir.setText(path)

    def accept(self) -> None:
        if not self._name.text().strip():
            QMessageBox.warning(self, "无法保存", "项目名不能为空。")
            self._name.setFocus()
            return
        super().accept()

    def values(self) -> tuple[str, str, str]:
        return (
            self._name.text().strip(),
            self._description.toPlainText().strip(),
            self._work_dir.text().strip(),
        )


_PLACEHOLDERS = {
    ResourceKind.URL: "https://example.com",
    ResourceKind.FILE: "C:\\path\\to\\file",
    ResourceKind.FOLDER: "D:\\path\\to\\folder",
    ResourceKind.APP: "C:\\path\\to\\app.exe",
}

_BROWSE_TEXT = {
    ResourceKind.FILE: "选择文件…",
    ResourceKind.FOLDER: "选择文件夹…",
    ResourceKind.APP: "选择程序…",
}


class ResourceDialog(QDialog):
    """添加或编辑一个资源。调用方通过 values() 拿结果。"""

    def __init__(
        self, parent: QWidget | None = None, resource: Resource | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("编辑资源" if resource else "添加资源")
        self.setMinimumWidth(560)

        self._kind_combo = QComboBox()
        for kind in (
            ResourceKind.URL,
            ResourceKind.FILE,
            ResourceKind.FOLDER,
            ResourceKind.APP,
        ):
            self._kind_combo.addItem(kind.label, kind.value)

        self._target = QLineEdit(resource.target if resource else "")
        self._target.setClearButtonEnabled(True)

        self._browse = QPushButton("浏览…")
        self._browse.clicked.connect(self._browse_target)

        target_row = QHBoxLayout()
        target_row.addWidget(self._target, 1)
        target_row.addWidget(self._browse)

        self._hint = QLabel("")
        self._hint.setWordWrap(True)

        form = QFormLayout()
        form.addRow("类型", self._kind_combo)
        form.addRow("目标", target_row)
        form.addRow("", self._hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        self._kind_combo.currentIndexChanged.connect(self._on_kind_changed)
        self._target.textChanged.connect(self._update_hint)

        if resource is not None:
            index = self._kind_combo.findData(resource.kind.value)
            if index >= 0:
                self._kind_combo.setCurrentIndex(index)
        self._on_kind_changed()

    def _kind(self) -> ResourceKind:
        return ResourceKind(self._kind_combo.currentData())

    def _on_kind_changed(self) -> None:
        kind = self._kind()
        self._target.setPlaceholderText(_PLACEHOLDERS[kind])
        self._browse.setEnabled(kind is not ResourceKind.URL)
        self._browse.setText(_BROWSE_TEXT.get(kind, "浏览…"))
        self._update_hint()

    def _browse_target(self) -> None:
        kind = self._kind()
        start = self._target.text().strip() or str(Path.home())

        if kind is ResourceKind.FILE:
            path, _ = QFileDialog.getOpenFileName(self, "选择文件", start)
        elif kind is ResourceKind.FOLDER:
            path = QFileDialog.getExistingDirectory(self, "选择文件夹", start)
        elif kind is ResourceKind.APP:
            path, _ = QFileDialog.getOpenFileName(
                self, "选择程序", start, "可执行文件 (*.exe *.com)"
            )
        else:
            return

        if path:
            self._target.setText(str(Path(path)))

    def _update_hint(self) -> None:
        target = self._target.text().strip()
        if not target:
            self._hint.setText("")
            return

        reason = check_resource(
            Resource(kind=self._kind(), target=target)
        )
        if reason:
            self._hint.setText(f"⚠ {reason}")
            self._hint.setStyleSheet("color: #c62828;")
        else:
            self._hint.setText("✓ 目标有效")
            self._hint.setStyleSheet("color: #2e7d32;")

    def accept(self) -> None:
        target = self._target.text().strip()
        if not target:
            QMessageBox.warning(self, "无法保存", "资源目标不能为空。")
            self._target.setFocus()
            return

        reason = check_resource(
            Resource(kind=self._kind(), target=target)
        )
        if reason:
            answer = QMessageBox.question(
                self,
                "目标校验未通过",
                f"{reason}。\n\n仍然保存吗？",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        super().accept()

    def values(self) -> tuple[ResourceKind, str]:
        return self._kind(), self._target.text().strip()


class LaunchResultDialog(QDialog):
    """进入项目后的逐项启动结果。"""

    def __init__(
        self,
        results: list[LaunchResult],
        skipped: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("启动结果")
        self.resize(780, 420)

        succeeded = sum(1 for result in results if result.ok)
        failed = len(results) - succeeded
        summary = f"成功 {succeeded} 个，失败 {failed} 个"
        if skipped:
            summary += f"，跳过 {skipped} 个已禁用的资源"
        summary += "。"

        summary_label = QLabel(summary)
        summary_label.setWordWrap(True)
        color = "#c62828" if failed else "#2e7d32"
        summary_label.setStyleSheet(
            f"font-size: 14px; font-weight: 600; color: {color};"
        )

        table = QTableWidget(len(results), 4)
        table.setHorizontalHeaderLabels(["结果", "类型", "目标", "说明"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        table.setAlternatingRowColors(True)

        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(0, 80)
        table.setColumnWidth(1, 72)
        table.setColumnWidth(3, 200)

        for row, result in enumerate(results):
            item_color = QColor("#2e7d32" if result.ok else "#c62828")
            status_text = "✓ 成功" if result.ok else "✗ 失败"
            status_item = QTableWidgetItem(status_text)
            kind_item = QTableWidgetItem(result.resource.kind.label)
            target_item = QTableWidgetItem(result.resource.target)
            target_item.setToolTip(result.resource.target)
            message_item = QTableWidgetItem(result.message)
            message_item.setToolTip(result.message)

            status_item.setForeground(QBrush(item_color))
            if not result.ok:
                message_item.setForeground(QBrush(item_color))

            table.setItem(row, 0, status_item)
            table.setItem(row, 1, kind_item)
            table.setItem(row, 2, target_item)
            table.setItem(row, 3, message_item)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("关闭")
        buttons.accepted.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(summary_label)
        layout.addWidget(table, 1)
        layout.addWidget(buttons)
