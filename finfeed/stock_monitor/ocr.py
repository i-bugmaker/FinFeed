#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""股票监控模块 — 截图 OCR 识别（可插拔后端）。

按可用性依次尝试：
  1. rapidocr-onnxruntime（推荐，纯 pip 安装、无需系统依赖）
  2. easyocr
  3. pytesseract（需系统安装 Tesseract 且包含 chi_sim 语言包）

均不可用时返回 ``{"ok": False, "hint": ...}``，由路由层向用户给出安装指引。
本模块只负责「图片 -> 文本行」，代码提取与校验由 service.parse_and_import 完成。
"""

from __future__ import annotations

import io
import logging
from typing import Any, Dict, List

logger = logging.getLogger("stock_monitor")

_INSTALL_HINT = (
    "未检测到可用 OCR 引擎。请在服务端执行 "
    "`pip install rapidocr-onnxruntime` 安装推荐引擎后重启 FinFeed，"
    "或改用手动输入 / 文本批量导入。"
)


def _ocr_rapidocr(data: bytes) -> List[str]:
    from rapidocr_onnxruntime import RapidOCR  # noqa: PLC0415

    engine = RapidOCR()
    import numpy as np  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415

    img = Image.open(io.BytesIO(data)).convert("RGB")
    result, _ = engine(np.array(img))
    if not result:
        return []
    return [str(row[1]).strip() for row in result if row and len(row) > 1 and row[1]]


def _ocr_easyocr(data: bytes) -> List[str]:
    import easyocr  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415

    reader = easyocr.Reader(["ch_sim", "en"], gpu=False, verbose=False)
    img = Image.open(io.BytesIO(data)).convert("RGB")
    lines = reader.readtext(np.array(img), detail=0)
    return [str(t).strip() for t in lines if str(t).strip()]


def _ocr_pytesseract(data: bytes) -> List[str]:
    import pytesseract  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415

    img = Image.open(io.BytesIO(data))
    text = pytesseract.image_to_string(img, lang="chi_sim+eng")
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


_BACKENDS = [
    ("rapidocr", _ocr_rapidocr),
    ("easyocr", _ocr_easyocr),
    ("pytesseract", _ocr_pytesseract),
]


def extract_text(data: bytes) -> Dict[str, Any]:
    """识别截图文本。返回 {"ok": bool, "engine": str, "lines": [...]} 或 {"ok": False, ...}。"""
    if not data:
        return {"ok": False, "error": "图片内容为空"}
    errors: List[str] = []
    for name, fn in _BACKENDS:
        try:
            lines = fn(data)
        except ImportError:
            continue  # 未安装，尝试下一个后端
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {e}")
            continue
        if lines:
            return {"ok": True, "engine": name, "lines": lines}
        # 引擎可用但未识别出文字：继续尝试下一引擎
    if errors:
        return {"ok": False, "error": "OCR 识别失败：" + "；".join(errors[:3])}
    return {"ok": False, "error": _INSTALL_HINT}
