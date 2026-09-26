# -*- coding: utf-8 -*-
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bench"))

from qingxiaotuan.ext.safety_engine import _normalize, is_hard_redline, is_redline, _segments

d = json.load(open(ROOT / "bench" / "safety_10k_result.json", encoding="utf-8"))

print("===== 漏放样例: 归一化前后对比 =====")
for s in d["samples_miss"]:
    p = s["payload"]
    n = _normalize(p)
    print(f"EXP={s['expect']:<5} {p!r}")
    print(f"        NORM: {n!r}")
    segs = _segments(n)
    print(f"        SEGS: {[x[:60] for x in segs]}")
    print(f"        hard={is_hard_redline(n)} redline={is_redline(n)}")
    print()
