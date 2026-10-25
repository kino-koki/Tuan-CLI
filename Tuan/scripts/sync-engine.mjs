#!/usr/bin/env node
/**
 * 打包前校验引擎副本是否落后于 tuan_cli/（`tauri build` 的 beforeBuildCommand 调用）。
 *
 * 背景
 * ----
 * 应用真正运行的引擎代码来自 `Tuan/engine/tuan_cli/` 这份副本，而不是仓库根。
 * 它靠 `scripts/sync_engine_bundle.py` 同步，但同步动作依赖 Python 解释器 ——
 * 而 Windows 上 PATH 里的 `python` 常常只是 Microsoft Store 的引导存根，
 * 于是"忘了同步"这件事会**静默发生**（此前就落后了 38 个文件，
 * 其中包含 `core/output_sanitize.py` 输出净化层）。
 *
 * 所以这个钩子是纯 Node 写的：它不需要 Python 就能通过 `.bundle_manifest.json`
 * 的 sha256 指纹发现漂移；只有在真正需要同步时才去找 Python 解释器。
 *
 * 退出策略：始终以 0 退出。副本落后不阻断前端构建（否则没有 Python 的机器
 * 连安装包都打不出来），但会在构建日志里高声警告，并且不会把错误当成功。
 */

import { createHash } from 'node:crypto';
import { promises as fs } from 'node:fs';
import { spawnSync } from 'node:child_process';
import path from 'node:path';

/** 向上找 package.json，确定 Tuan 根目录（兼容从 src-tauri 发起构建）。 */
async function findAppRoot(start) {
  let dir = path.resolve(start);
  for (let i = 0; i < 6; i += 1) {
    try {
      await fs.access(path.join(dir, 'package.json'));
      return dir;
    } catch {
      /* 继续向上 */
    }
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return path.resolve(start, '..');
}

const ROOT = await findAppRoot(process.cwd());
const REPO = path.dirname(ROOT);
const ENGINE_DIR = path.join(ROOT, 'engine');
const MANIFEST_PATH = path.join(ENGINE_DIR, '.bundle_manifest.json');
const BUNDLE = path.join(ENGINE_DIR, 'tuan_cli');
const SYNC = path.join(REPO, 'scripts', 'sync_engine_bundle.py');

function warn(line) {
  process.stderr.write(`[sync-engine] ${line}\n`);
}

function sha256(file) {
  const h = createHash('sha256');
  h.update(file);
  return h.digest('hex');
}

/** 判定候选解释器是否真的可用（排除 Windows Store 引导存根）。 */
function tryPython(candidate) {
  const r = spawnSync(candidate, ['--version'], {
    encoding: 'utf-8',
    timeout: 10_000,
    windowsHide: true,
  });
  if (r.error || r.status !== 0) return null;
  if (!/Python\s+\d+\.\d+/.test(`${r.stdout || ''}${r.stderr || ''}`)) return null;
  return candidate;
}

function findPython() {
  const env = process.env.TUAN_PYTHON;
  if (env) {
    const hit = tryPython(env);
    if (hit) return hit;
    warn(`TUAN_PYTHON 指向的解释器不可用：${env}`);
  }
  const candidates = [
    'python',
    'python3',
    'py',
    path.join(ROOT, '.venv', 'Scripts', 'python.exe'),
    path.join(process.env.USERPROFILE || '', '.venv', 'Scripts', 'python.exe'),
  ];
  for (const c of candidates) {
    const hit = tryPython(c);
    if (hit) return hit;
  }
  return null;
}

let driftCount = 0;
let manifest = null;
try {
  manifest = JSON.parse(await fs.readFile(MANIFEST_PATH, 'utf-8'));
} catch {
  warn(`缺少引擎指纹文件 ${path.relative(ROOT, MANIFEST_PATH)}：`
    + '打包前请运行 `python scripts/sync_engine_bundle.py`');
}

if (manifest) {
  const files = manifest.files || {};
  const drift = [];
  const missing = [];
  for (const rel of Object.keys(files)) {
    const abs = path.join(BUNDLE, rel);
    try {
      const buf = await fs.readFile(abs);
      if (sha256(buf) !== files[rel].sha256) drift.push(rel);
    } catch {
      missing.push(rel);
    }
  }
  driftCount = drift.length + missing.length;
  if (driftCount) {
    warn(`引擎副本已漂移：内容不符 ${drift.length} 个，缺失 ${missing.length} 个`);
    for (const rel of [...missing, ...drift].slice(0, 10)) warn(`  ${rel}`);
    if (driftCount > 10) warn(`  ... 及另外 ${driftCount - 10} 个`);
  } else {
    process.stdout.write(
      `[sync-engine] 引擎副本与指纹一致（${Object.keys(files).length} 个文件，`
      + `引擎 ${manifest.engineVersion || '?'}）\n`,
    );
  }
} else {
  driftCount = -1; // 未知：按"需要同步"处理
}

if (driftCount > 0) {
  const python = findPython();
  if (!python) {
    warn('未找到可用的 Python 解释器，无法自动同步。');
    warn('请设置 TUAN_PYTHON 指向解释器，或手动运行 `python scripts/sync_engine_bundle.py` 后重新打包。');
  } else {
    warn(`尝试自动同步：${python} ${path.relative(ROOT, SYNC)}`);
    const r = spawnSync(python, ['-X', 'utf8', SYNC], {
      cwd: ROOT,
      stdio: 'inherit',
      windowsHide: true,
    });
    if (r.status === 0) {
      process.stdout.write('[sync-engine] 引擎副本已同步到最新。\n');
    } else {
      warn(`自动同步失败（退出码 ${r.status}），请手动运行 `
        + '`python scripts/sync_engine_bundle.py` 后重新打包。');
    }
  }
}

process.exit(0);
