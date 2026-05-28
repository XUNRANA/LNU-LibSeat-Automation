"""跨平台路径解析（开发态 / PyInstaller 冻结态，Windows 与 macOS 通用）。

两类目录需要区分：

- ``resource_root()`` —— 只读、随包分发的资源（ONNX 模型、logo 等）。
  冻结后位于 PyInstaller 解包目录 ``sys._MEIPASS``（Windows 是 ``_internal``，
  macOS 是 ``LNU-LibSeat.app/Contents/Frameworks``）。

- ``app_data_dir()`` —— 用户可编辑 / 运行时写入的数据（``config.py``、``logs/``、
  ``info/``、``profiles/``）。必须位于可写、用户可见的位置：
    * Windows：紧挨 ``LNU-LibSeat.exe``。
    * macOS：``.app`` 的**同级目录**（即发行夹），而非包内部——写进 ``.app``
      内部会破坏签名且不可见。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    """是否运行在 PyInstaller 打包产物中。"""
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """只读、随包分发的资源根目录。"""
    if is_frozen():
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    # 开发态：项目根（本文件位于 <root>/core/paths.py）
    return Path(__file__).resolve().parents[1]


def app_data_dir() -> Path:
    """用户可编辑 / 运行时写入数据的根目录。"""
    if is_frozen():
        exe = Path(sys.executable).resolve()
        if sys.platform == "darwin":
            # .../发行夹/LNU-LibSeat.app/Contents/MacOS/LNU-LibSeat
            #   parents[0]=MacOS  [1]=Contents  [2]=*.app  [3]=发行夹
            parents = exe.parents
            if len(parents) >= 4 and parents[2].suffix == ".app":
                return parents[3]
            # 兜底：非 .app 结构（极少见）时退回 exe 所在目录
            return exe.parent
        # Windows / Linux：紧挨可执行文件
        return exe.parent
    # 开发态：项目根
    return Path(__file__).resolve().parents[1]
