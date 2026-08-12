"""Ultralytics inference argument compatibility helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ultralytics.cfg import DEFAULT_CFG_DICT


def yolo_precision_kwargs(
    use_half: bool,
    *,
    default_cfg: Mapping[str, Any] = DEFAULT_CFG_DICT,
) -> dict[str, int | bool | None]:
    """Return precision kwargs accepted by the installed Ultralytics version."""
    if "quantize" in default_cfg:
        return {"quantize": 16 if use_half else None}
    return {"half": use_half}
