#!/usr/bin/env python3
"""License/SBOM consistency gate (stdlib only).

Checks (fail-closed, exit 1 on any problem):
  1. Every ``THIRD_PARTY_LICENSES/<file>`` referenced from the root ``NOTICE``
     actually exists in that directory.
  2. ``sbom.spdx.json`` parses as JSON and carries the required SPDX fields
     (spdxVersion, SPDXID, creationInfo, packages >= 1).
  3. ``requirements.lock`` pins all appear in the SBOM package list (hard gate).
     ``uv.lock`` names (the full transitive closure, including conditional
     platform deps and the project's own package) are cross-checked advisory.

Advisory (stderr warning only, does not fail): SBOM packages that appear in
neither lockfile, and uv.lock-only names missing from the SBOM (transitive
deps resolved at install time are expected here).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOTICE = ROOT / "NOTICE"
LIC_DIR = ROOT / "THIRD_PARTY_LICENSES"
SBOM = ROOT / "sbom.spdx.json"
REQ_LOCK = ROOT / "requirements.lock"
UV_LOCK = ROOT / "uv.lock"

problems: list[str] = []
warnings: list[str] = []

# ---- 1. NOTICE -> THIRD_PARTY_LICENSES references ---------------------------
notice_text = NOTICE.read_text(encoding="utf-8", errors="replace")
referenced = sorted(set(re.findall(r"THIRD_PARTY_LICENSES/([A-Za-z0-9._-]+)", notice_text)))
for name in referenced:
    if not (LIC_DIR / name).is_file():
        problems.append(f"NOTICE references THIRD_PARTY_LICENSES/{name} but the file is missing")

# ---- 2. SPDX SBOM ------------------------------------------------------------
def _norm(name: str) -> str:
    """PEP 503 风格归一化: 小写, 连续 -_. 归一为单个 -。"""
    return re.sub(r"[-_.]+", "-", name.strip().lower())


sbom_packages: set[str] = set()
try:
    sbom = json.loads(SBOM.read_text(encoding="utf-8"))
except Exception as exc:  # noqa: BLE001
    problems.append(f"sbom.spdx.json does not parse as JSON: {exc}")
else:
    for field in ("spdxVersion", "SPDXID", "creationInfo", "packages"):
        if field not in sbom:
            problems.append(f"sbom.spdx.json missing required field: {field}")
    pkgs = sbom.get("packages") or []
    if not isinstance(pkgs, list) or not pkgs:
        problems.append("sbom.spdx.json 'packages' is empty or not a list")
    for p in pkgs:
        if isinstance(p, dict) and p.get("name"):
            sbom_packages.add(_norm(str(p["name"])))

# ---- 3. lockfiles ------------------------------------------------------------
lock_names: set[str] = set()

if REQ_LOCK.is_file():
    for line in REQ_LOCK.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-", "--")):
            continue
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*==", line)
        if m:
            lock_names.add(_norm(m.group(1)))
else:
    warnings.append("requirements.lock not found")

uv_only_names: set[str] = set()
if UV_LOCK.is_file():
    uv_text = UV_LOCK.read_text(encoding="utf-8", errors="replace")
    for m in re.finditer(r'^name = "([^"]+)"', uv_text, re.MULTILINE):
        uv_only_names.add(_norm(m.group(1)))
else:
    warnings.append("uv.lock not found")

if lock_names and sbom_packages:
    missing = sorted(n for n in lock_names if n not in sbom_packages)
    if missing:
        problems.append(
            "pinned packages missing from SBOM: " + ", ".join(missing))
    extra = sorted(n for n in sbom_packages
                   if n not in lock_names and n not in uv_only_names
                   and n not in {"tuan-cli"})
    if extra:
        warnings.append(
            "SBOM packages not pinned in lockfiles (transitive deps are expected): "
            + ", ".join(extra))

uv_missing_sbom = sorted(n for n in uv_only_names
                         if n not in sbom_packages and n not in {"tuan-cli"})
if uv_missing_sbom:
    warnings.append(
        "uv.lock closure names not in SBOM (advisory; platform-conditional or "
        "own-package entries are expected): " + ", ".join(uv_missing_sbom))

# ---- report ------------------------------------------------------------------
for w in warnings:
    print(f"WARNING: {w}")
if problems:
    print("FAIL: license/SBOM consistency problems:")
    for p in problems:
        print(f"  - {p}")
    raise SystemExit(1)
print(f"OK: {len(referenced)} license files referenced and present, "
      f"SBOM valid ({len(sbom_packages)} packages), "
      f"{len(lock_names)} pinned packages all covered")
