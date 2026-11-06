"""从用户桌面 / 公共桌面选择项目的对话框。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.desktop_items import collect_desktop_items


class DesktopPickerDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("从桌面导入")
        self.resize(760, 480)
        self.setMinimumSize(620, 400)

        self._summary = QLabel("")
        self._search = QLineEdit()
        self._search.setPlaceholderText("搜索桌面项目…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._apply_filter)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["名称", "位置", "类型"])
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._table.setAlternatingRowColors(True)

        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(1, 90)
        self._table.setColumnWidth(2, 80)
        self._table.cellDoubleClicked.connect(lambda *_: self._accept_selected())

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("选择")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._accept_selected)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self._summary)
        layout.addWidget(self._search)
        layout.addWidget(self._table, 1)
        layout.addWidget(buttons)

        self._items = collect_desktop_items()
        self._load_items()

    def _load_items(self) -> None:
        user_count = sum(
            1 for item in self._items if item.location == "用户桌面"
        )
        public_count = sum(
            1 for item in self._items if item.location == "公共桌面"
        )
        self._summary.setText(
            f"用户桌面 {user_count} 项 · 公共桌面 {public_count} 项"
        )
        self._apply_filter()

    def _apply_filter(self) -> None:
        keyword = self._search.text().strip().lower()
        visible = [
            item
            for item in self._items
            if not keyword or keyword in item.path.name.lower()
        ]

        self._table.setRowCount(len(visible))
        for row, item in enumerate(visible):
            name_item = QTableWidgetItem(item.path.name)
            name_item.setData(Qt.ItemDataRole.UserRole, str(item.path))
            name_item.setToolTip(str(item.path))
            location_item = QTableWidgetItem(item.location)
            type_item = QTableWidgetItem(item.kind_label)
            self._table.setItem(row, 0, name_item)
            self._table.setItem(row, 1, location_item)
            self._table.setItem(row, 2, type_item)

        if visible:
            self._table.selectRow(0)

    def _accept_selected(self) -> None:
        if self.selected_path() is None:
            return
        super().accept()

    def selected_path(self) -> Path | None:
        row = self._table.currentRow()
        if row < 0:
            return None
        item = self._table.item(row, 0)
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return Path(value) if value else None
