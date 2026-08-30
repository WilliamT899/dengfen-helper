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
from app.ocr.engine import get_engine
from app.ocr.pipeline import recognize_image
from app.storage import save_photo
from app.ui.table_model import COL_SCORE, ScoreTableModel
from app.ui.workers import OcrBatchWorker
from app.workspace import PENDING, FILLED, Workspace


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
        self.camera_view.setMinimumSize(480, 600)
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

        self.progress = QProgressBar()
        self.progress.setVisible(False)
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
        self._warmup_engine()

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
        h, w = frame.shape[:2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888)
        self.camera_view.setPixmap(QPixmap.fromImage(img).scaled(
            self.camera_view.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))

    def capture_frame(self):
        if self.camera is None or self._last_frame is None:
            self.status.showMessage("摄像头未就绪，无法拍摄")
            return
        if not self.roster:
            QMessageBox.information(self, "提示", "请先导入学生名单，再拍摄。")
            return
        frame = self._last_frame
        # 快门动画：白色闪屏
        self._flash_overlay()
        self.status.showMessage("识别中…")
        QTimer.singleShot(50, lambda: self._process_captured(frame))

    def _flash_overlay(self):
        overlay = QLabel(self.camera_view)
        overlay.setStyleSheet("background:rgba(255,255,255,200);border-radius:8px;")
        overlay.setGeometry(self.camera_view.rect())
        overlay.show()
        QTimer.singleShot(200, overlay.deleteLater)

    def _warmup_engine(self):
        """启动时后台加载识别模型（首张照片不用等模型加载），失败提前提示。"""
        from app.ui.workers import EngineWarmupWorker
        self._warmup_worker = EngineWarmupWorker()
        self._warmup_worker.signals.done.connect(
            lambda result: self.status.showMessage(str(result[1]), 8000))
        self.thread_pool.start(self._warmup_worker)

    def _process_captured(self, frame: np.ndarray):
        try:
            result = recognize_image(frame, get_engine())
        except Exception as exc:
            self.status.showMessage(
                f"识别失败：{exc}\n若反复出现，请重启软件或将照片用'批量导入照片'处理", 15000)
            return
        if result.score is None and not result.name:
            self.status.showMessage("未能识别出姓名和分数，请在表格中手动录入")
            return
        # 存档照片
        photo_path = save_photo(self._frame_to_temp(frame), self.photo_dir,
                                result.name or "待确认", result.score)
        m = match_student(result.name, result.student_id, self.roster)
        if m.is_unique:
            row = self.workspace.apply_result(
                m.student.student_id, m.student.name, m.student.klass,
                result.score, str(photo_path), match_status="unique")
        else:
            row = self.workspace.apply_result(
                result.student_id, result.name, result.klass,
                result.score, str(photo_path),
                match_status="multiple" if m.status == "multiple" else "none")
        self.model.refresh_all()
        self.workspace.save()
        self._refresh_stats()
        name = row.name or "未识别"
        self.status.showMessage(
            f"已拍摄：{name} 分数 {result.score if result.score is not None else '待确认'}")

    @staticmethod
    def _frame_to_temp(frame: np.ndarray) -> Path:
        import tempfile
        fd, tmp = tempfile.mkstemp(suffix=".jpg")
        import os
        os.close(fd)
        cv2.imwrite(tmp, frame)
        return Path(tmp)

    def _run_batch(self, paths: list[Path]):
        if not self.roster:
            QMessageBox.information(self, "提示", "请先导入学生名单，再导入照片。")
            return
        self.progress.setVisible(True)
        self.progress.setRange(0, len(paths))
        worker = OcrBatchWorker(paths)
        worker.progress.connect(self._on_progress)
        worker.done.connect(self._on_batch_done)
        worker.error.connect(self._on_worker_error)
        self.thread_pool.start(worker)
        self.btn_photos.setEnabled(False)

    def _on_progress(self, done: int, total: int):
        self.progress.setValue(done)
        self.status.showMessage(f"识别中 {done}/{total}…")

    def _on_worker_error(self, message: str):
        self.status.showMessage(f"⚠ {message}", 15000)

    def _on_batch_done(self, results: list):
        self.btn_photos.setEnabled(True)
        self.progress.setVisible(False)
        if not self.roster:
            return
        for r in results:
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
            # 存档照片：姓名_分数.jpg
            photo = ""
            try:
                photo = str(save_photo(Path(r.path), self.photo_dir, name or "待确认", r.score))
            except Exception:
                photo = r.path
            self.workspace.apply_result(sid, name, klass, r.score, photo, match_status=status)
        self.model.refresh_all()
        self.workspace.save()
        self.status.showMessage(
            f"识别完成：{len(results)} 张，待确认 {self.model.pending_count()} 条")
        self._refresh_stats()

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
        self.workspace.save()
        super().closeEvent(event)
