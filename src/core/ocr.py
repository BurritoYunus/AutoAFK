"""Text recognition (OCR) for reading game text.

Uses RapidOCR (ONNX models bundled with the package, works offline). If it isn't
installed, read functions return None and callers fall back to image templates.
"""
import logging
import threading
from typing import List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

_engine = None
_failed = False
_lock = threading.Lock()


def _get_engine():
    global _engine, _failed
    if _engine is None and not _failed:
        with _lock:
            if _engine is None and not _failed:
                try:
                    try:
                        import onnxruntime
                        onnxruntime.disable_telemetry_events()   # no usage data sent to Microsoft
                    except Exception:
                        pass
                    from rapidocr_onnxruntime import RapidOCR
                    _engine = RapidOCR()
                except Exception as e:   # not installed or models missing
                    logger.warning(f"Text recognition unavailable ({e}); using image templates instead")
                    _failed = True
    return _engine


def available() -> bool:
    return _get_engine() is not None


def read_line(image) -> Optional[str]:
    """Read a single line of text (fast: no text detection step)"""
    engine = _get_engine()
    if engine is None:
        return None
    try:
        result, _ = engine(np.asarray(image.convert('RGB')), use_det=False, use_cls=False, use_rec=True)
    except Exception as e:
        logger.debug(f"OCR error: {e}")
        return None
    if not result:
        return ''
    return ' '.join(r[0] for r in result)


def read_lines(image) -> Optional[List[Tuple[int, str]]]:
    """Read all text lines in an image as (y, text), top to bottom"""
    engine = _get_engine()
    if engine is None:
        return None
    try:
        result, _ = engine(np.asarray(image.convert('RGB')), use_cls=False)
    except Exception as e:
        logger.debug(f"OCR error: {e}")
        return None
    if not result:
        return []
    lines = [(int(min(p[1] for p in box)), int(min(p[0] for p in box)), text) for box, text, _ in result]
    lines.sort(key=lambda l: (l[0] // 20, l[1]))
    return [(y, text) for y, _, text in lines]
