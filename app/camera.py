"""摄像头采集：QThread 阻塞读帧，信号回传；DSHOW 优先（Windows）。

策略（Windows 11）：DSHOW 后端 + MJPG fourcc + BUFFERSIZE=1；
后端降级链 MSMF → DSHOW → ANY；macOS 开发用 AVFoundation（默认）。
"""
from __future__ import annotations

import sys
import time
from typing import List, Optional, Tuple

import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal

FRAME_W, FRAME_H = 1280, 960   # 期望分辨率（自动回退）


class CameraThread(QThread):
    frame_ready = Signal(np.ndarray)   # BGR 帧
    camera_opened = Signal(str)        # 描述文本
    camera_failed = Signal(str)        # 错误文本

    def __init__(self, camera_index: int = 0, parent=None):
        super().__init__(parent)
        self.index = camera_index
        self._stop = False
        self._cap: Optional[cv2.VideoCapture] = None

    def _backends(self) -> List[int]:
        """Windows 上 DSHOW 优先（MSMF 有首帧慢/分辨率失效缺陷）。"""
        if sys.platform == "win32":
            return [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY]
        return [cv2.CAP_AVFOUNDATION, cv2.CAP_ANY]

    def _open(self) -> Optional[cv2.VideoCapture]:
        last_err: Optional[str] = None
        for backend in self._backends():
            cap = cv2.VideoCapture(self.index, backend)
            if not cap.isOpened():
                cap.release()
                continue
            # MJPG 优先，1080p/720p 逐级回退
            for fourcc in (cv2.VideoWriter_fourcc(*"MJPG"), 0):
                for w, h in ((1920, 1080), (FRAME_W, FRAME_H), (960, 720), (640, 480)):
                    if fourcc:
                        cap.set(cv2.CAP_PROP_FOURCC, fourcc)
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # 防帧缓存延迟
                    ok, frame = cap.read()
                    if ok and frame is not None and frame.size > 0:
                        return cap
            cap.release()
        return None

    def run(self):
        cap = self._open()
        if cap is None:
            self.camera_failed.emit("未检测到摄像头。您仍可使用“批量导入照片”功能。")
            return
        self._cap = cap
        self.camera_opened.emit(f"摄像头已连接（{int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}×"
                                f"{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}）")
        while not self._stop:
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.05)
                continue
            self.frame_ready.emit(frame.copy())
        cap.release()

    def stop(self):
        self._stop = True
        self.wait(2000)

    def grab_frame(self) -> Optional[np.ndarray]:
        """同步取当前帧（拍摄用）。"""
        if self._cap is None or not self._cap.isOpened():
            return None
        for _ in range(3):   # 清缓存取最新帧
            ok, frame = self._cap.read()
            if ok and frame is not None:
                return frame
        return None


def list_cameras() -> List[Tuple[int, str]]:
    """枚举摄像头（Windows 用 DSHOW，macOS 默认）。最多试 4 个。"""
    cams = []
    for i in range(4):
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY)
        if cap.isOpened():
            cams.append((i, f"摄像头 {i}"))
            cap.release()
    return cams
