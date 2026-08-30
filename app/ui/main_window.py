"""主窗口：左摄像头预览/拍摄 + 右成绩表格，顶部工具栏。"""
from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
    QProgressBar, QPushButton, QSplitter, QStatusBar, QVBoxLayout, QWidget,
)

from app import config
from app.camera import CameraThread
from app.matcher import match_student
from app.roster import Roster, load_roster
from app.storage import save_photo
from app.ui.table_model import ScoreTableModel
from app.ui.workers import OcrQueueThread, PhotoResult
from app.workspace import Workspace


class MainWindow(QMainWindow):
    status_msg = Signal(str)
    progress_signal = Signal(int, int)  # done, total

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{config.APP_NAME} v{config.APP_VERSION}")
        self.resize(1280, 800)

        self.workspace = Workspace.load()
        self.roster: Roster | None = None
        self.thread_pool = QThreadPool()
        self.photo_dir = config.photos_dir()
        self.camera: CameraThread | None = None
        self._last_frame: np.ndarray | None = None
        self._preview_pixmap: QPixmap | None = None
        self._last_preview_ts = 0.0

        # 识别队列：拍摄/上传与识别解耦，界面永不阻塞
        self.ocr_queue = OcrQueueThread()
        self.ocr_queue.progress.connect(self._on_progress)
        self.ocr_queue.result.connect(self._on_ocr_result)
        self.ocr_queue.error.connect(self._on_worker_error)
        self.ocr_queue.model_ready.connect(
            lambda msg: self.status.showMessage(msg, 8000))
        self.ocr_queue.start()  # 启动即预热识别模型

        # ---- 顶部工具栏 ----
        toolbar = QHBoxLayout()
        title = QLabel(config.APP_NAME)
        title.setObjectName("title")
        toolbar.addWidget(title)
        toolbar.addStretch()
        self.btn_roster = QPushButton("导入学生名单")
        self.btn_photos = QPushButton("批量导入照片")
        self.btn_export = QPushButton("导出 Excel")
        self.btn_export.setObjectName("primary")
        self.btn_clear = QPushButton("删除全部")
        self.btn_clear.setObjectName("danger")
        for b in (self.btn_roster, self.btn_photos, self.btn_export, self.btn_clear):
            toolbar.addWidget(b)
        self.btn_roster.clicked.connect(self.import_roster)
        self.btn_photos.clicked.connect(self.import_photos)
        self.btn_export.clicked.connect(self.export_excel)
        self.btn_clear.clicked.connect(self.clear_all)

        # ---- 左：摄像头 ----
        left = QWidget()
        left_lay = QVBoxLayout(left)
        self.camera_view = QLabel("摄像头未连接")
        self.camera_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.camera_view.setMinimumSize(360, 320)
        self.camera_view.setStyleSheet(
            "background:#141519;border:1px solid #3d4148;border-radius:8px;color:#666;font-size:16px;")
        left_lay.addWidget(self.camera_view, 1)

        shutter_row = QHBoxLayout()
        shutter_row.addStretch()
        self.btn_shutter = QPushButton("")
        self.btn_shutter.setObjectName("shutter")
        self.btn_shutter.setToolTip("拍摄（快捷键：空格）")
        self.btn_shutter.clicked.connect(self.capture_frame)
        shutter_row.addWidget(self.btn_shutter)
        shutter_row.addStretch()
        left_lay.addLayout(shutter_row)

        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel("照片目录:"))
        self.lbl_dir = QLabel(str(self.photo_dir))
        self.lbl_dir.setObjectName("subtitle")
        dir_row.addWidget(self.lbl_dir, 1)
        btn_dir = QPushButton("更改…")
        btn_dir.clicked.connect(self.choose_photo_dir)
        dir_row.addWidget(btn_dir)
        left_lay.addLayout(dir_row)

        # ---- 右：表格 ----
        right = QWidget()
        right_lay = QVBoxLayout(right)
        self.model = ScoreTableModel(self.workspace)
        self.model.changed.connect(lambda: (self.workspace.save(), self._refresh_stats()))
        self.table = None  # 由 table_panel 构建（避免循环导入，用简单 QTableView 亦可）

        from PySide6.QtWidgets import QTableView, QHeaderView
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setDefaultSectionSize(30)
        # 双击进入编辑时保留原内容（光标在末尾，不自动全选）
        from PySide6.QtWidgets import QStyledItemDelegate

        class KeepTextDelegate(QStyledItemDelegate):
            def setEditorData(self, editor, index):
                text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
                editor.setText(text)
                editor.setCursorPosition(len(text))
                if hasattr(editor, "deselect"):
                    editor.deselect()

        self.table.setItemDelegate(KeepTextDelegate(self.table))
        right_lay.addWidget(self.table, 1)

        bottom_row = QHBoxLayout()
        self.chk_pending = QCheckBox("仅看待确认")
        self.chk_pending.toggled.connect(self.toggle_pending_filter)
        self.lbl_stats = QLabel("")
        self.lbl_stats.setObjectName("subtitle")
        bottom_row.addWidget(self.chk_pending)
        bottom_row.addStretch()
        bottom_row.addWidget(self.lbl_stats)
        right_lay.addLayout(bottom_row)

        # 进度条常驻（固定高度，避免显示/隐藏引起的布局跳动）
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setFixedHeight(16)
        self.progress.setTextVisible(False)
        right_lay.addWidget(self.progress)

        # ---- 布局 ----
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([560, 720])

        central = QWidget()
        central_lay = QVBoxLayout(central)
        central_lay.addLayout(toolbar)
        central_lay.addWidget(splitter)
        self.setCentralWidget(central)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("就绪。请先导入学生名单。")

        self._refresh_stats()
        self._start_camera()

    # ---- 删除全部 ----
    def clear_all(self):
        if not self.workspace.rows:
            self.status.showMessage("表格已为空")
            return
        reply = QMessageBox.question(
            self, "确认删除",
            f"将删除表格中的全部 {len(self.workspace.rows)} 条记录（姓名和分数），且无法恢复。\n是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.workspace.rows = []
        self.model.refresh_all()
        self.workspace.save()
        self.status.showMessage("已清空全部记录")
        self._refresh_stats()

    # ---- 名单 ----
    def import_roster(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择学生名单", "", "Excel/CSV 文件 (*.xlsx *.xls *.csv)")
        if not path:
            return
        try:
            self.roster = load_roster(Path(path))
        except ValueError as exc:
            QMessageBox.warning(self, "名单格式错误", str(exc))
            return
        self.workspace.init_from_roster(self.roster)
        self.model.refresh_all()
        self.workspace.save()
        self.status.showMessage(f"名单已导入：{len(self.roster)} 名学生，{len(self.roster.classes())} 个班")
        self._refresh_stats()

    # ---- 照片 ----
    def import_photos(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择试卷照片", "", "图片 (*.jpg *.jpeg *.png *.bmp)")
        if not files:
            return
        self._run_batch([Path(f) for f in files])

    # ---- 摄像头 ----
    def _start_camera(self):
        self.camera = CameraThread(0)
        self.camera.frame_ready.connect(self._on_frame)
        self.camera.camera_opened.connect(self.status.showMessage)
        self.camera.camera_failed.connect(self.status.showMessage)
        self.camera.start()

    def _on_frame(self, frame: np.ndarray):
        self._last_frame = frame
        # 预览节流：最多 10 帧/秒，避免高分辨率帧转换占满界面线程
        now = time.monotonic()
        if now - self._last_preview_ts < 0.1:
            return
        self._last_preview_ts = now
        # 预览缩小到宽 960 再转换，降低 CPU 占用
        h, w = frame.shape[:2]
        scale = min(1.0, 960 / w)
        if scale < 1.0:
            frame = cv2.resize(frame, (int(w * scale), int(h * scale)),
                               interpolation=cv2.INTER_AREA)
        h, w = frame.shape[:2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888)
        self._preview_pixmap = QPixmap.fromImage(img)
        self._render_preview()

    def _render_preview(self):
        """按当前显示区大小重绘预览（窗口缩放自适应）。"""
        if self._preview_pixmap is None:
            return
        self.camera_view.setPixmap(self._preview_pixmap.scaled(
            self.camera_view.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._render_preview()

    def capture_frame(self):
        if self.camera is None or self._last_frame is None:
            self.status.showMessage("摄像头未就绪，无法拍摄")
            return
        if not self.roster:
            QMessageBox.information(self, "提示", "请先导入学生名单，再拍摄。")
            return
        frame = self._last_frame
        # 1) 立刻保存照片（识别成功与否都不丢照片）
        import datetime
        tmp_path = self.photo_dir / f"拍摄_{datetime.datetime.now():%Y%m%d_%H%M%S}.jpg"
        try:
            self.photo_dir.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(tmp_path), frame)
        except Exception as exc:
            self.status.showMessage(f"照片保存失败：{exc}", 10000)
            return
        # 2) 快门动画 + 入队识别（可继续连拍，识别在后台排队进行）
        self._flash_overlay()
        self.ocr_queue.enqueue([tmp_path])
        self.status.showMessage(
            f"已拍摄（{tmp_path.name}），已加入识别队列，排队中 {self.ocr_queue.queue_length()} 张")

    def _flash_overlay(self):
        overlay = QLabel(self.camera_view)
        overlay.setStyleSheet("background:rgba(255,255,255,200);border-radius:8px;")
        overlay.setGeometry(self.camera_view.rect())
        overlay.show()
        QTimer.singleShot(200, overlay.deleteLater)

    def _run_batch(self, paths: list[Path]):
        if not self.roster:
            QMessageBox.information(self, "提示", "请先导入学生名单，再导入照片。")
            return
        self.ocr_queue.enqueue(paths)
        self.status.showMessage(
            f"已加入识别队列 {len(paths)} 张（当前排队 {self.ocr_queue.queue_length()} 张）")

    def _on_progress(self, done: int, total: int, detail: str = ""):
        if total > 0:
            self.progress.setRange(0, max(total, 1))
            self.progress.setValue(done)
        text = f"识别中 {done}/{total}｜{detail}" if detail else f"识别中 {done}/{total}…"
        self.status.showMessage(text)

    def _on_worker_error(self, message: str):
        self.status.showMessage(f"⚠ {message}", 15000)

    def _on_ocr_result(self, r: PhotoResult):
        """单张识别完成即回填（拍摄与批量共用）。"""
        if not self.roster:
            return
        m = match_student(r.name, r.student_id, self.roster)
        if m.is_unique:
            name, sid, klass = m.student.name, m.student.student_id, m.student.klass
            status = "unique"
        else:
            name, sid, klass, status = r.name, r.student_id, r.klass, \
                ("multiple" if m.status == "multiple" else "none")
        # 分数置信度不足（如 9/6 易混淆）→ 标记待确认
        if status == "unique" and r.score is not None and r.score_conf < 0.75:
            status = "low_score"
        # 照片存档：拍摄的照片已在本目录（拍摄_xxx.jpg）→ 重命名；导入的照片 → 拷贝
        src = Path(r.path)
        photo = ""
        try:
            if src.parent == self.photo_dir and src.name.startswith("拍摄_"):
                from app.storage import rename_photo
                photo = str(rename_photo(src, name or "待确认", r.score) or src)
            else:
                photo = str(save_photo(src, self.photo_dir, name or "待确认", r.score))
        except Exception:
            photo = r.path
        self.workspace.apply_result(sid, name, klass, r.score, photo, match_status=status)
        self.model.refresh_all()
        self.workspace.save()
        self._refresh_stats()
        score_text = f"{r.score:g}" if r.score is not None else "待确认"
        self.status.showMessage(
            f"识别完成：{name or '未识别'} 分数 {score_text}（{Path(photo).name}）", 15000)

    # ---- 导出 ----
    def export_excel(self):
        if not self.roster:
            QMessageBox.information(self, "提示", "请先导入学生名单。")
            return
        from app.excel.exporter import export_excel
        scores = {(r.student_id, r.name): r.score for r in self.workspace.rows}
        default = f"成绩_{self.roster.source.split('/')[-1].split('.')[0] if self.roster.source else '导出'}.xlsx"
        path, _ = QFileDialog.getSaveFileName(self, "导出成绩表", default, "Excel 文件 (*.xlsx)")
        if not path:
            return
        try:
            export_excel(self.roster, scores, Path(path))
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", str(exc))
            return
        self.status.showMessage(f"已导出：{path}")

    # ---- 其他 ----
    def choose_photo_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择照片保存目录", str(self.photo_dir))
        if d:
            self.photo_dir = Path(d)
            self.lbl_dir.setText(str(self.photo_dir))

    def toggle_pending_filter(self, checked: bool):
        self.model.set_pending_only(checked)

    def _refresh_stats(self):
        n = len(self.workspace.rows)
        filled = self.model.filled_count()
        pending = self.model.pending_count()
        self.lbl_stats.setText(f"共 {n} 人 | 已登 {filled} | 待确认 {pending}")

    def closeEvent(self, event):
        if self.camera is not None:
            self.camera.stop()
        self.ocr_queue.stop()
        self.workspace.save()
        super().closeEvent(event)
