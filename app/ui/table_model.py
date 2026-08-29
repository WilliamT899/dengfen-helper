"""成绩表格模型：序号/学号/姓名/班级/分数/状态，分数列可编辑，待确认行高亮。"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QColor, QFont

from app.workspace import EMPTY, FILLED, PENDING, Row, Workspace

HEADERS = ("序号", "学号", "姓名", "班级", "分数", "状态")
COL_INDEX, COL_ID, COL_NAME, COL_CLASS, COL_SCORE, COL_STATUS = range(6)

COLOR_PENDING_BG = QColor("#5a4a1a")   # 待确认行背景（深黄）
COLOR_PENDING_FG = QColor("#ffd75e")


class ScoreTableModel(QAbstractTableModel):
    changed = Signal()   # 数据编辑后发出（用于自动保存）

    def __init__(self, workspace: Workspace, parent=None):
        super().__init__(parent)
        self.workspace = workspace
        self.pending_only = False   # "仅看待确认"过滤
        self._font_normal = QFont()
        self._font_pending = QFont()
        self._font_pending.setBold(True)

    # ---- Qt 模型接口 ----
    def rowCount(self, parent=QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._visible_rows())

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(HEADERS)

    def _visible_rows(self) -> list:
        if not self.pending_only:
            return self.workspace.rows
        return [r for r in self.workspace.rows if r.status == PENDING]

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        rows = self._visible_rows()
        if index.row() >= len(rows):
            return None
        row: Row = rows[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == COL_INDEX:
                return index.row() + 1
            if col == COL_ID:
                return row.student_id
            if col == COL_NAME:
                return row.name
            if col == COL_CLASS:
                return row.klass
            if col == COL_SCORE:
                return "" if row.score is None else f"{row.score:g}"
            if col == COL_STATUS:
                return {"": "", EMPTY: "", PENDING: "待确认", FILLED: "✓"}[row.status]
        elif role == Qt.ItemDataRole.EditRole and col == COL_SCORE:
            return row.score
        elif role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (COL_INDEX, COL_ID, COL_SCORE, COL_STATUS):
                return int(Qt.AlignmentFlag.AlignCenter)
        elif role == Qt.ItemDataRole.BackgroundRole and row.status == PENDING:
            return COLOR_PENDING_BG
        elif role == Qt.ItemDataRole.ForegroundRole and row.status == PENDING:
            return COLOR_PENDING_FG
        elif role == Qt.ItemDataRole.FontRole and row.status == PENDING:
            return self._font_pending
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False
        rows = self._visible_rows()
        if index.row() >= len(rows):
            return False
        row = rows[index.row()]
        col = index.column()
        if col == COL_SCORE:
            text = str(value).strip()
            if text in ("", "None"):
                row.score = None
                row.status = EMPTY if row.status == FILLED else row.status
            else:
                try:
                    row.score = float(text)
                except ValueError:
                    return False
                row.status = FILLED
            self.dataChanged.emit(index, index)
            self.changed.emit()
            return True
        if col in (COL_NAME, COL_ID, COL_CLASS):
            text = str(value).strip()
            setattr(row, "name" if col == COL_NAME else "student_id" if col == COL_ID else "klass", text)
            self.dataChanged.emit(index, index)
            self.changed.emit()
            return True
        return False

    def flags(self, index) -> Qt.ItemFlag:
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() in (COL_SCORE, COL_NAME, COL_ID, COL_CLASS):
            base |= Qt.ItemFlag.ItemIsEditable
        return base

    def set_pending_only(self, on: bool):
        if self.pending_only == on:
            return
        self.pending_only = on
        self.beginResetModel()
        self.endResetModel()

    # ---- 行操作 ----
    def append_row(self, row: Row):
        idx = len(self.workspace.rows)
        self.beginInsertRows(QModelIndex(), idx, idx)
        self.workspace.rows.append(row)
        self.endInsertRows()

    def remove_rows(self, indexes):
        for index in sorted({i.row() for i in indexes}, reverse=True):
            self.beginRemoveRows(QModelIndex(), index, index)
            self.workspace.rows.pop(index)
            self.endRemoveRows()

    def refresh_all(self):
        self.beginResetModel()
        self.endResetModel()
        self.changed.emit()

    def pending_count(self) -> int:
        return sum(1 for r in self.workspace.rows if r.status == PENDING)

    def filled_count(self) -> int:
        return sum(1 for r in self.workspace.rows if r.status == FILLED)
