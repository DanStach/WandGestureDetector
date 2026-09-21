"""CPU / memory / temperature sampling (display/metrics.py)."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

import psutil

_THERMAL = Path("/sys/class/thermal/thermal_zone0/temp")


def _cpu_temp_c() -> Optional[float]:
    try:
        return int(_THERMAL.read_text().strip()) / 1000.0
    except (OSError, ValueError):
        return None


def sample() -> Dict[str, Optional[float]]:
    """Non-blocking: cpu_percent(interval=None) reports usage since the previous call."""
    temp_c = _cpu_temp_c()
    return {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "mem_percent": psutil.virtual_memory().percent,
        "cpu_temp_c": temp_c,
        "cpu_temp_f": temp_c * 9 / 5 + 32 if temp_c is not None else None,
    }
