"""主窗口：左侧项目列表，右侧项目详情 + 资源列表。"""

from __future__ import annotations

import sqlite3
from collections import Counter
from pathlib import Path

from PySide6.QtCore import QThread, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.adapters import os_open
from app.core import app_settings, db, launcher, repo
from app.core.models import LaunchResult, Project, Resource, ResourceKind
from app.core.resource_check import check_resource, normalize_url
from app.ui.dialogs import LaunchResultDialog, ProjectDialog, ResourceDialog
from app.ui.settings_dialog import REASON_TEXT, STATE_TEXT, SettingsDialog


def _describe_open_error(exc: Exception) -> str:
    """把底层异常翻译成用户看得懂的原因。"""
    if isinstance(exc, sqlite3.DatabaseError):
        return f"数据文件损坏，或不是有效的 SQLite 数据库（{exc}）"
    if isinstance(exc, OSError):
        return f"文件读写失败：{exc}"
    return str(exc)


class ResourceTable(QTableWidget):
    """接受文件 / 文件夹拖放的资源表格。"""

    files_dropped = Signal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragEnabled(False)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = [
            url.toLocalFile()
            for url in event.mimeData().urls()
            if url.isLocalFile()
        ]
        paths = [path for path in paths if path]
        if paths:
            event.acceptProposedAction()
            self.files_dropped.emit(paths)
        else:
            super().dropEvent(event)


class LaunchWorker(QThread):
    """在后台线程里跑 launcher，避免界面卡住。"""

    progress_changed = Signal(int, int, str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        resources: list[Resource],
        opener,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._resources = resources
        self._opener = opener

    def run(self) -> None:
        try:
            results = launcher.run(
                self._resources,
                self._opener,
                progress=lambda index, total, resource: self.progress_changed.emit(
                    index, total, resource.target
                ),
            )
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
            return
        self.completed.emit(results)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Workbench")
        self.resize(1100, 720)

        self._conn: sqlite3.Connection | None = None
        self._data_dir: Path | None = None
        self._projects: dict[int, Project] = {}
        self._resources: list[Resource] = []
        self._worker: LaunchWorker | None = None

        self._build_ui()
        self._try_restore()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        menu = self.menuBar()
        file_menu = menu.addMenu("文件")

        settings_action = QAction("设置…", self)
        settings_action.setShortcut("Ctrl+,")
        settings_action.triggered.connect(self._open_settings)
        file_menu.addAction(settings_action)

        file_menu.addSeparator()
        quit_action = QAction("退出", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        # 左侧：项目列表
        self._search = QLineEdit()
        self._search.setPlaceholderText("搜索项目…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._apply_filter)

        self._list = QListWidget()
        self._list.currentItemChanged.connect(self._on_select)

        self._new_button = QPushButton("＋ 新建项目")
        self._new_button.clicked.connect(self._new_project)
        self._settings_button = QPushButton("设置")
        self._settings_button.clicked.connect(self._open_settings)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(8, 8, 8, 8)
        title = QLabel("项目")
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        left_layout.addWidget(title)
        left_layout.addWidget(self._search)
        left_layout.addWidget(self._list, 1)
        button_row = QHBoxLayout()
        button_row.addWidget(self._new_button)
        button_row.addWidget(self._settings_button)
        left_layout.addLayout(button_row)

        # 右侧：项目详情
        self._detail_title = QLabel("")
        self._detail_title.setStyleSheet("font-size: 20px; font-weight: 600;")
        self._detail_title.setWordWrap(True)

        self._detail_description = QLabel("")
        self._detail_description.setWordWrap(True)

        self._detail_work_dir = QLabel("")
        self._detail_work_dir.setWordWrap(True)

        self._detail_hint = QLabel("")
        self._detail_hint.setWordWrap(True)
        self._detail_hint.setStyleSheet("color: #666;")

        self._enter_button = QPushButton("▶  进入项目")
        self._enter_button.setStyleSheet(
            "font-size: 14px; font-weight: 600; padding: 6px 18px;"
        )
        self._enter_button.clicked.connect(self._enter_project)

        self._project_maximize = QCheckBox("启动时尝试最大化")
        self._project_maximize.setToolTip(
            "尽力而为：控制台程序已实测有效；"
            "记事本、已运行的 VS Code 等程序常会忽略；"
            "文件 / 文件夹 / 网址不保证生效。"
        )
        self._project_maximize.toggled.connect(
            self._on_project_maximize_toggled
        )

        enter_row = QHBoxLayout()
        enter_row.addWidget(self._enter_button)
        enter_row.addWidget(self._project_maximize)
        enter_row.addStretch(1)

        # 资源工具栏
        self._resource_title = QLabel("资源")
        self._resource_title.setStyleSheet("font-size: 15px; font-weight: 600;")

        self._resource_add_button = QPushButton("添加资源")
        self._resource_add_button.clicked.connect(self._add_resource)
        self._resource_edit_button = QPushButton("编辑")
        self._resource_edit_button.clicked.connect(self._edit_resource)
        self._resource_delete_button = QPushButton("删除")
        self._resource_delete_button.clicked.connect(self._delete_resource)
        self._resource_up_button = QPushButton("↑")
        self._resource_up_button.setToolTip("上移")
        self._resource_up_button.clicked.connect(
            lambda: self._move_resource(-1)
        )
        self._resource_down_button = QPushButton("↓")
        self._resource_down_button.setToolTip("下移")
        self._resource_down_button.clicked.connect(
            lambda: self._move_resource(1)
        )
        self._resource_refresh_button = QPushButton("刷新状态")
        self._resource_refresh_button.clicked.connect(
            lambda: self._reload_resources()
        )

        resource_toolbar = QHBoxLayout()
        resource_toolbar.addWidget(self._resource_title)
        resource_toolbar.addStretch(1)
        resource_toolbar.addWidget(self._resource_add_button)
        resource_toolbar.addWidget(self._resource_edit_button)
        resource_toolbar.addWidget(self._resource_delete_button)
        resource_toolbar.addWidget(self._resource_up_button)
        resource_toolbar.addWidget(self._resource_down_button)
        resource_toolbar.addWidget(self._resource_refresh_button)

        # 资源表格
        self._resource_table = ResourceTable()
        self._resource_table.setColumnCount(4)
        self._resource_table.setHorizontalHeaderLabels(
            ["启用", "类型", "目标", "状态"]
        )
        header = self._resource_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self._resource_table.setColumnWidth(0, 52)
        self._resource_table.setColumnWidth(1, 72)
        self._resource_table.setColumnWidth(3, 170)
        self._resource_table.verticalHeader().setVisible(False)
        self._resource_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._resource_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._resource_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._resource_table.setAlternatingRowColors(True)
        self._resource_table.itemChanged.connect(
            self._on_resource_item_changed
        )
        self._resource_table.itemSelectionChanged.connect(
            self._refresh_actions
        )
        self._resource_table.files_dropped.connect(self._on_files_dropped)
        self._resource_table.cellDoubleClicked.connect(
            lambda *_: self._edit_resource()
        )

        self._resource_summary = QLabel("")
        self._resource_summary.setWordWrap(True)
        self._resource_summary.setStyleSheet("color: #666;")

        # 项目操作按钮
        self._edit_button = QPushButton("编辑项目")
        self._edit_button.clicked.connect(self._edit_project)
        self._delete_button = QPushButton("删除项目")
        self._delete_button.clicked.connect(self._delete_project)
        project_buttons = QHBoxLayout()
        project_buttons.addStretch(1)
        project_buttons.addWidget(self._edit_button)
        project_buttons.addWidget(self._delete_button)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(16, 8, 16, 8)
        right_layout.addWidget(self._detail_title)
        right_layout.addWidget(self._detail_description)
        right_layout.addWidget(self._detail_work_dir)
        right_layout.addWidget(self._detail_hint)
        right_layout.addLayout(enter_row)
        right_layout.addSpacing(12)
        right_layout.addLayout(resource_toolbar)
        right_layout.addWidget(self._resource_table, 1)
        right_layout.addWidget(self._resource_summary)
        right_layout.addLayout(project_buttons)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([280, 820])
        self.setCentralWidget(splitter)

        self._status = QStatusBar()
        self.setStatusBar(self._status)

        self._progress = QProgressBar()
        self._progress.setFixedWidth(180)
        self._progress.setTextVisible(False)
        self._progress.setVisible(False)
        self._status.addPermanentWidget(self._progress)

        self._update_status()

    # -------------------------------------------------------------- 启动

    def _try_restore(self) -> None:
        try:
            settings = app_settings.load()
        except app_settings.SettingsError as exc:
            self._show_empty("设置文件损坏，请重新选择数据目录。")
            QTimer.singleShot(0, lambda msg=str(exc): self._warn_settings_error(msg))
            return

        if not settings.data_dir:
            self._show_empty("尚未配置数据目录。请点击「设置」选择一个文件夹。")
            QTimer.singleShot(0, self._welcome_first_run)
            return

        path = Path(settings.data_dir)
        state = app_settings.inspect_data_dir(path)
        if state is not app_settings.DataDirState.OK:
            self._show_empty(
                f"数据目录不可用：\n{path}\n"
                f"错误原因：{REASON_TEXT.get(state, '')}\n\n"
                "请重新选择数据目录。"
            )
            QTimer.singleShot(
                0, lambda p=path, s=state: self._warn_data_dir_unavailable(p, s)
            )
            return

        try:
            self._activate_data_dir(path)
        except Exception as exc:  # noqa: BLE001 - 需要把具体原因显示给用户
            self._show_empty(
                f"数据目录打不开：\n{path}\n{_describe_open_error(exc)}"
            )
            QTimer.singleShot(
                0, lambda p=path, e=exc: self._warn_open_failed(p, e)
            )

    def _welcome_first_run(self) -> None:
        QMessageBox.information(
            self,
            "首次使用",
            "请先选择一个文件夹作为数据目录。\n"
            "所有项目数据都会保存在那里，程序目录不写任何数据。",
        )
        self._open_settings()

    def _warn_settings_error(self, message: str) -> None:
        QMessageBox.warning(
            self,
            "设置文件损坏",
            f"{message}\n\n请重新选择数据目录。",
        )
        self._open_settings()

    def _warn_data_dir_unavailable(
        self, path: Path, state: app_settings.DataDirState
    ) -> None:
        reason = REASON_TEXT.get(state) or STATE_TEXT.get(state, "")
        extra = ""
        if state is app_settings.DataDirState.MISSING_DB:
            extra = "\n\n如果这是旧的数据目录，可以从 backups 文件夹里恢复一份备份。"
        QMessageBox.warning(
            self,
            "数据目录不可用",
            f"上次使用的数据目录不可用：\n{path}\n\n"
            f"错误原因：{reason}\n\n"
            f"程序不会自动新建空库，请重新选择数据目录。{extra}",
        )
        self._open_settings()

    def _warn_open_failed(self, path: Path, exc: Exception) -> None:
        QMessageBox.critical(
            self,
            "数据目录打不开",
            f"上次使用的数据目录不可用：\n{path}\n\n"
            f"错误原因：{_describe_open_error(exc)}\n\n"
            "程序不会自动新建空库，请重新选择数据目录。",
        )
        self._open_settings()

    def _activate_data_dir(self, path: Path) -> None:
        """初始化目录、备份旧库、打开数据库，然后刷新界面。失败时抛异常。"""
        app_settings.ensure_initialized(path)
        db_file = path / "workbench.db"

        note = ""
        if db_file.exists():
            # 先备份再迁移：即使结构升级失败，也有升级前的副本可回退
            raw = db.connect(db_file)
            try:
                db.backup(raw, path / "backups", keep=5)
            except (OSError, sqlite3.Error) as exc:
                note = f"（自动备份失败：{exc}）"
            finally:
                raw.close()

        conn = db.open_database(db_file)

        if self._conn is not None:
            self._conn.close()
        self._conn = conn
        self._data_dir = path
        self._update_status(note)
        self._reload_projects()

    def _open_settings(self) -> None:
        current = str(self._data_dir) if self._data_dir else None
        dialog = SettingsDialog(self, current)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        selected = dialog.selected_data_dir()
        if not selected:
            return
        path = Path(selected)

        if self._data_dir is not None and path == self._data_dir:
            return

        try:
            self._activate_data_dir(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(
                self, "无法使用该数据目录", f"{path}\n\n{_describe_open_error(exc)}"
            )
            return

        try:
            app_settings.save(app_settings.AppSettings(str(path)))
        except OSError as exc:
            QMessageBox.warning(
                self,
                "设置未保存",
                f"数据目录已切换，但设置写入失败：\n{exc}\n\n"
                "下次启动需要重新选择数据目录。",
            )

    # ---------------------------------------------------------- 项目列表

    def _reload_projects(self) -> None:
        self._projects.clear()
        if self._conn is None:
            self._list.clear()
            self._show_empty("尚未配置数据目录。请点击「设置」选择一个文件夹。")
            return

        for project in repo.list_projects(self._conn):
            self._projects[project.id] = project
        self._apply_filter()

    def _apply_filter(self) -> None:
        if self._conn is None:
            self._show_empty("尚未配置数据目录。请点击「设置」选择一个文件夹。")
            return

        keyword = self._search.text().strip().lower()
        current_id = self._current_project_id()
        projects = [
            project
            for project in self._projects.values()
            if not keyword or keyword in project.name.lower()
        ]
        projects.sort(key=lambda p: p.name.lower())

        self._list.blockSignals(True)
        self._list.clear()
        for project in projects:
            item = QListWidgetItem(project.name)
            item.setData(Qt.ItemDataRole.UserRole, project.id)
            if project.description:
                item.setToolTip(project.description)
            self._list.addItem(item)
        self._list.blockSignals(False)

        if not projects:
            if self._projects:
                self._show_empty("没有匹配的项目。")
            else:
                self._show_empty("还没有项目。点击左下角「＋ 新建项目」开始。")
            return

        target_id = (
            current_id
            if any(project.id == current_id for project in projects)
            else projects[0].id
        )
        self._select_project(target_id)

    def _select_project(self, project_id: int | None) -> None:
        for row in range(self._list.count()):
            item = self._list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == project_id:
                self._list.setCurrentRow(row)
                return

    def _current_project_id(self) -> int | None:
        item = self._list.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _current_project(self) -> Project | None:
        project_id = self._current_project_id()
        if project_id is None:
            return None
        return self._projects.get(project_id)

    def _on_select(
        self, current: QListWidgetItem | None, _previous: QListWidgetItem | None
    ) -> None:
        project = self._current_project()
        if project is None:
            self._show_empty("选择一个项目查看详情。")
        else:
            self._show_project(project)

    # ---------------------------------------------------------- 项目详情

    def _show_project(self, project: Project) -> None:
        self._detail_title.setText(project.name)
        self._detail_description.setText(project.description or "（无描述）")
        if project.work_dir:
            self._detail_work_dir.setText(f"工作目录：{project.work_dir}")
        else:
            self._detail_work_dir.setText("工作目录：（未设置）")
        self._detail_hint.setText("")

        self._project_maximize.blockSignals(True)
        self._project_maximize.setChecked(project.maximize)
        self._project_maximize.blockSignals(False)

        self._reload_resources()

    def _show_empty(self, message: str) -> None:
        self._detail_title.setText("")
        self._detail_description.setText("")
        self._detail_work_dir.setText("")
        self._detail_hint.setText(message)

        self._project_maximize.blockSignals(True)
        self._project_maximize.setChecked(False)
        self._project_maximize.blockSignals(False)

        self._clear_resources()
        self._refresh_actions()

    def _refresh_actions(self) -> None:
        has_dir = self._conn is not None
        self._new_button.setEnabled(has_dir)
        self._search.setEnabled(has_dir)
        self._list.setEnabled(has_dir)

        project = self._current_project()
        has_project = has_dir and project is not None
        has_resource = has_project and self._current_resource() is not None

        launching = self._worker is not None and self._worker.isRunning()

        self._edit_button.setEnabled(has_project)
        self._delete_button.setEnabled(has_project)
        self._enter_button.setEnabled(has_project and not launching)
        self._project_maximize.setEnabled(has_project)
        self._resource_add_button.setEnabled(has_project)
        self._resource_refresh_button.setEnabled(has_project)
        self._resource_table.setEnabled(has_project)
        for button in (
            self._resource_edit_button,
            self._resource_delete_button,
            self._resource_up_button,
            self._resource_down_button,
        ):
            button.setEnabled(has_resource)

    # ---------------------------------------------------------- 项目操作

    def _new_project(self) -> None:
        if self._conn is None:
            return
        dialog = ProjectDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        name, description, work_dir = dialog.values()
        try:
            project = repo.create_project(self._conn, name, description, work_dir)
        except repo.DuplicateNameError as exc:
            QMessageBox.warning(self, "无法创建项目", str(exc))
            return

        self._reload_projects()
        self._select_project(project.id)

    def _edit_project(self) -> None:
        project = self._current_project()
        if project is None or self._conn is None:
            return

        dialog = ProjectDialog(self, project)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        name, description, work_dir = dialog.values()
        project.name = name
        project.description = description
        project.work_dir = work_dir
        try:
            repo.update_project(self._conn, project)
        except (repo.DuplicateNameError, repo.NotFoundError) as exc:
            QMessageBox.warning(self, "无法保存", str(exc))
            return

        self._reload_projects()
        self._select_project(project.id)

    def _delete_project(self) -> None:
        project = self._current_project()
        if project is None or self._conn is None:
            return

        answer = QMessageBox.question(
            self,
            "删除项目",
            f"确定删除项目「{project.name}」吗？\n\n"
            "该项目的资源会一并删除。此操作不可撤销。",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            repo.delete_project(self._conn, project.id)
        except repo.NotFoundError as exc:
            QMessageBox.warning(self, "删除失败", str(exc))
        self._reload_projects()

    def _on_project_maximize_toggled(self, checked: bool) -> None:
        project = self._current_project()
        if project is None or self._conn is None:
            return
        if project.maximize == checked:
            return

        try:
            repo.set_project_maximize(self._conn, project.id, checked)
        except repo.NotFoundError as exc:
            QMessageBox.warning(self, "无法保存", str(exc))
            return

        project.maximize = checked
        state = "开" if checked else "关"
        self._update_status(f"项目「{project.name}」启动时最大化：{state}")

    # ---------------------------------------------------------- 资源列表

    def _reload_resources(self, select_resource_id: int | None = None) -> None:
        project = self._current_project()
        if project is None or self._conn is None:
            self._clear_resources()
            self._refresh_actions()
            return

        if select_resource_id is None:
            select_resource_id = self._current_resource_id()

        resources = repo.list_resources(self._conn, project.id)
        self._resources = resources
        self._populate_resources(resources, select_resource_id)
        self._refresh_actions()

    def _populate_resources(
        self, resources: list[Resource], select_resource_id: int | None
    ) -> None:
        self._resource_table.blockSignals(True)
        self._resource_table.setRowCount(len(resources))
        reasons = [check_resource(resource) for resource in resources]
        invalid_count = sum(1 for reason in reasons if reason)
        url_counts = Counter(
            normalize_url(resource.target)
            for resource, reason in zip(resources, reasons)
            if resource.kind is ResourceKind.URL and reason is None
        )
        duplicate_url_count = 0

        for row, resource in enumerate(resources):
            reason = reasons[row]
            is_duplicate_url = (
                resource.kind is ResourceKind.URL
                and reason is None
                and url_counts[normalize_url(resource.target)] > 1
            )
            if is_duplicate_url:
                duplicate_url_count += 1

            check_item = QTableWidgetItem()
            check_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            check_item.setCheckState(
                Qt.CheckState.Checked if resource.enabled else Qt.CheckState.Unchecked
            )
            check_item.setData(Qt.ItemDataRole.UserRole, resource.id)

            kind_item = QTableWidgetItem(resource.kind.label)
            target_item = QTableWidgetItem(resource.target)
            target_item.setToolTip(resource.target)

            if reason:
                status_text = reason
                status_color = QColor("#c62828")
            elif is_duplicate_url:
                status_text = "正常（重复网址）"
                status_color = QColor("#ef6c00")
            else:
                status_text = "正常"
                status_color = QColor("#2e7d32")

            if not resource.enabled:
                status_text = f"已禁用（{status_text}）"
                status_color = QColor("#9e9e9e")

            status_item = QTableWidgetItem(status_text)
            status_item.setToolTip(status_text)

            for item in (kind_item, target_item, status_item):
                item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                )
            status_item.setForeground(QBrush(status_color))
            if reason:
                target_item.setForeground(QBrush(QColor("#c62828")))
            elif is_duplicate_url:
                target_item.setForeground(QBrush(QColor("#ef6c00")))
            if not resource.enabled:
                for item in (kind_item, target_item):
                    item.setForeground(QBrush(QColor("#9e9e9e")))

            self._resource_table.setItem(row, 0, check_item)
            self._resource_table.setItem(row, 1, kind_item)
            self._resource_table.setItem(row, 2, target_item)
            self._resource_table.setItem(row, 3, status_item)

        self._resource_table.blockSignals(False)

        if not resources:
            summary = "还没有资源。把文件或文件夹拖到这里，或点「添加资源」。"
        else:
            parts = [f"共 {len(resources)} 个资源"]
            if invalid_count:
                parts.append(f"{invalid_count} 个不可用")
            if duplicate_url_count:
                parts.append(f"{duplicate_url_count} 个重复网址")
            if not invalid_count and not duplicate_url_count:
                parts.append("全部可用")
            summary = "，".join(parts) + "。"
        self._resource_summary.setText(summary)

        if select_resource_id is not None:
            self._select_resource(select_resource_id)
        if self._resource_table.currentRow() < 0 and resources:
            self._resource_table.selectRow(0)

    def _clear_resources(self) -> None:
        self._resources = []
        self._resource_table.blockSignals(True)
        self._resource_table.setRowCount(0)
        self._resource_table.blockSignals(False)
        self._resource_summary.setText("")

    def _select_resource(self, resource_id: int | None) -> None:
        for row, resource in enumerate(self._resources):
            if resource.id == resource_id:
                self._resource_table.selectRow(row)
                return

    def _current_resource(self) -> Resource | None:
        row = self._resource_table.currentRow()
        if 0 <= row < len(self._resources):
            return self._resources[row]
        return None

    def _current_resource_id(self) -> int | None:
        resource = self._current_resource()
        return resource.id if resource else None

    def _on_resource_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 0 or self._conn is None:
            return
        row = item.row()
        if not (0 <= row < len(self._resources)):
            return

        resource = self._resources[row]
        enabled = item.checkState() == Qt.CheckState.Checked
        if resource.enabled == enabled:
            return

        try:
            repo.set_resource_enabled(self._conn, resource.id, enabled)
        except repo.NotFoundError as exc:
            QMessageBox.warning(self, "无法更新", str(exc))
        self._reload_resources(select_resource_id=resource.id)

    # ---------------------------------------------------------- 资源操作

    def _is_duplicate_url(
        self, project_id: int, target: str, exclude_id: int | None = None
    ) -> bool:
        if self._conn is None:
            return False
        normalized = normalize_url(target)
        for resource in repo.list_resources(self._conn, project_id):
            if resource.id == exclude_id:
                continue
            if (
                resource.kind is ResourceKind.URL
                and normalize_url(resource.target) == normalized
            ):
                return True
        return False

    def _add_resource(self) -> None:
        project = self._current_project()
        if project is None or self._conn is None:
            return

        dialog = ResourceDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        kind, target = dialog.values()
        if kind is not ResourceKind.URL:
            existing = repo.find_resource(self._conn, project.id, kind, target)
            if existing is not None:
                QMessageBox.warning(
                    self, "资源已存在", f"这个目标已经在这个项目里了：\n{target}"
                )
                return

        duplicate_url = (
            kind is ResourceKind.URL
            and self._is_duplicate_url(project.id, target)
        )

        try:
            resource = repo.create_resource(self._conn, project.id, kind, target)
        except (repo.NotFoundError, ValueError) as exc:
            QMessageBox.warning(self, "无法添加", str(exc))
            return

        self._reload_resources(select_resource_id=resource.id)
        if duplicate_url:
            self._update_status(f"已添加资源（与已有网址重复）：{target}")
        else:
            self._update_status(f"已添加资源：{target}")

    def _edit_resource(self) -> None:
        resource = self._current_resource()
        if resource is None or self._conn is None:
            return

        dialog = ResourceDialog(self, resource)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        kind, target = dialog.values()
        if kind is not ResourceKind.URL:
            existing = repo.find_resource(
                self._conn, resource.project_id, kind, target
            )
            if existing is not None and existing.id != resource.id:
                QMessageBox.warning(
                    self, "资源已存在", f"这个目标已经在这个项目里了：\n{target}"
                )
                return

        duplicate_url = (
            kind is ResourceKind.URL
            and self._is_duplicate_url(
                resource.project_id, target, exclude_id=resource.id
            )
        )

        resource.kind = kind
        resource.target = target
        try:
            repo.update_resource(self._conn, resource)
        except (repo.NotFoundError, ValueError) as exc:
            QMessageBox.warning(self, "无法保存", str(exc))
            return

        self._reload_resources(select_resource_id=resource.id)
        if duplicate_url:
            self._update_status(f"已更新资源（与已有网址重复）：{target}")
        else:
            self._update_status(f"已更新资源：{target}")

    def _delete_resource(self) -> None:
        resource = self._current_resource()
        if resource is None or self._conn is None:
            return

        answer = QMessageBox.question(
            self,
            "删除资源",
            f"确定删除这个资源吗？\n\n[{resource.kind.label}] {resource.target}",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            repo.delete_resource(self._conn, resource.id)
        except repo.NotFoundError as exc:
            QMessageBox.warning(self, "删除失败", str(exc))
        self._reload_resources()

    def _move_resource(self, delta: int) -> None:
        resource = self._current_resource()
        if resource is None or self._conn is None:
            return

        try:
            moved = repo.move_resource(self._conn, resource.id, delta)
        except repo.NotFoundError as exc:
            QMessageBox.warning(self, "无法移动", str(exc))
            return

        if moved:
            self._reload_resources(select_resource_id=resource.id)

    def _on_files_dropped(self, paths: list[str]) -> None:
        project = self._current_project()
        if project is None or self._conn is None:
            return

        added = 0
        skipped = 0
        failed: list[str] = []
        added_ids: list[int] = []

        for raw in paths:
            path = Path(raw)
            kind = ResourceKind.FOLDER if path.is_dir() else ResourceKind.FILE
            target = str(path)
            try:
                if repo.find_resource(self._conn, project.id, kind, target):
                    skipped += 1
                    continue
                resource = repo.create_resource(
                    self._conn, project.id, kind, target
                )
                added_ids.append(resource.id)
                added += 1
            except Exception as exc:  # noqa: BLE001
                failed.append(f"{target}\n  {exc}")

        self._reload_resources(
            select_resource_id=added_ids[-1] if added_ids else None
        )

        if skipped or failed:
            lines = [f"已添加 {added} 个资源。"]
            if skipped:
                lines.append(f"跳过重复项 {skipped} 个。")
            if failed:
                lines.append("失败：\n" + "\n".join(failed))
            QMessageBox.warning(self, "拖入结果", "\n\n".join(lines))
        else:
            self._update_status(f"已添加 {added} 个资源。")

    # ---------------------------------------------------------- 进入项目

    def _enter_project(self) -> None:
        project = self._current_project()
        if project is None or self._conn is None:
            return
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(
                self, "正在启动", "当前项目还在启动中，请稍候。"
            )
            return

        resources = repo.list_resources(self._conn, project.id)
        enabled_count = sum(1 for resource in resources if resource.enabled)
        if enabled_count == 0:
            QMessageBox.information(
                self,
                "没有可启动的资源",
                "这个项目还没有启用的资源。\n请先添加资源，或勾选要启动的项。",
            )
            return
        skipped = len(resources) - enabled_count

        cwd: str | None = None
        if project.work_dir and Path(project.work_dir).is_dir():
            cwd = project.work_dir

        maximize = project.maximize

        def opener(resource: Resource) -> None:
            os_open.open_resource(resource, cwd=cwd, maximize=maximize)

        self._worker = LaunchWorker(resources, opener, self)
        self._worker.progress_changed.connect(self._on_launch_progress)
        self._worker.completed.connect(
            lambda results: self._on_launch_completed(project, results, skipped)
        )
        self._worker.failed.connect(self._on_launch_failed)
        self._worker.finished.connect(self._on_worker_finished)

        self._enter_button.setEnabled(False)
        self._progress.setRange(0, enabled_count)
        self._progress.setValue(0)
        self._progress.setVisible(True)
        self._status.showMessage(f"正在进入项目：{project.name}")
        self._worker.start()

    def _on_launch_progress(
        self, index: int, total: int, target: str
    ) -> None:
        self._progress.setValue(index)
        self._status.showMessage(f"正在启动 {index}/{total}：{target}")

    def _on_launch_completed(
        self, project: Project, results: list[LaunchResult], skipped: int
    ) -> None:
        succeeded = sum(1 for result in results if result.ok)
        failed = len(results) - succeeded
        detail = f"成功 {succeeded} 个，失败 {failed} 个，跳过 {skipped} 个"

        log_error: str | None = None
        if self._conn is not None:
            try:
                repo.mark_project_entered(self._conn, project.id)
                repo.add_event(self._conn, project.id, "enter", detail)
            except (sqlite3.Error, repo.NotFoundError) as exc:
                log_error = str(exc)

        message = f"进入项目「{project.name}」：{detail}"
        if log_error:
            message += f"（记录失败：{log_error}）"
        self._status.showMessage(message)

        # 启动时可能发现资源已经失效，把最新状态同步回表格
        self._reload_resources()

        LaunchResultDialog(results, skipped, self).exec()

    def _on_launch_failed(self, message: str) -> None:
        self._status.showMessage("启动过程出错")
        QMessageBox.critical(
            self, "启动失败", f"启动过程中出现错误：\n\n{message}"
        )

    def _on_worker_finished(self) -> None:
        worker = self._worker
        self._worker = None
        self._progress.setVisible(False)
        self._enter_button.setEnabled(self._current_project() is not None)
        if worker is not None:
            worker.deleteLater()

    # ------------------------------------------------------------ 状态栏

    def _update_status(self, note: str = "") -> None:
        if self._data_dir:
            text = f"数据目录：{self._data_dir}"
        else:
            text = "未配置数据目录 —— 请在「设置」中选择"
        if note:
            text = f"{text}  {note}"
        self._status.showMessage(text)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        if self._worker is not None and self._worker.isRunning():
            if not self._worker.wait(3000):
                QMessageBox.warning(
                    self, "正在启动", "还有启动任务未完成，请稍候再关闭。"
                )
                event.ignore()
                return
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        super().closeEvent(event)
