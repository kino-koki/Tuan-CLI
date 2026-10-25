#!/usr/bin/env node
/**
 * §11 五模式静态验收 · 零依赖校验脚本
 * ------------------------------------------------------------------
 * 选型说明：`Tuan-App/package.json` 里既没有 `test` script，也没有
 * 任何 vitest / jest 依赖。为了「不装新依赖 + 不改 package.json」，
 * 这里用 node 直接跑一段纯文本 + 正则的静态断言，覆盖 modes.ts 的
 * 结构约束（模式 ID / 中文名 / level / 旧名拒绝 / 回落 / 切换规则），
 * 并把 W-2~W-8 移动端接入 token 与「全仓零 emoji」硬规则一起扫掉。
 *
 * 运行：`node Tuan-App/scripts/verify_modes.mjs`
 * 退出码：0 = 全绿；非 0 = 断言失败（stdout 打印失败明细）。
 */

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, '..');                       // Tuan-App/
const REPO = join(ROOT, '..');                       // 仓库根
const SRC = join(ROOT, 'src');
const MODES_TS = join(SRC, 'platform', 'modes.ts');

const results = [];
function ok(name, detail) { results.push({ ok: true,  name, detail }); }
function bad(name, detail) { results.push({ ok: false, name, detail }); }

// -------- 走目录树，跳过 node_modules / dist / .git --------
function walk(dir, exts = new Set()) {
  const out = [];
  let entries;
  try { entries = readdirSync(dir, { withFileTypes: true }); }
  catch { return out; }
  for (const e of entries) {
    if (e.name === 'node_modules' || e.name === 'dist' || e.name === '.git') continue;
    const p = join(dir, e.name);
    if (e.isDirectory()) out.push(...walk(p, exts));
    else if (e.isFile()) {
      const ext = e.name.slice(e.name.lastIndexOf('.') + 1).toLowerCase();
      if (exts.size === 0 || exts.has(ext)) out.push(p);
    }
  }
  return out;
}

// =====================================================================
// A. modes.ts 静态解析
// =====================================================================
const src = readFileSync(MODES_TS, 'utf-8');

// --- 1) ModeId 联合类型只有 5 个成员 ---
const typeMatch = src.match(/export\s+type\s+ModeId\s*=\s*([^;]+);/);
if (!typeMatch) {
  bad('ModeId 联合类型存在', '未在 modes.ts 找到 `export type ModeId` 声明');
} else {
  const body = typeMatch[1];
  const ids = [...body.matchAll(/'([a-z_]+)'/g)].map((m) => m[1]);
  const expected = new Set(['gantong', 'lingma', 'chat', 'boundless', 'collaboration']);
  if (ids.length === 5 && new Set(ids).size === 5 && ids.every((x) => expected.has(x))) {
    ok('ModeId 联合类型恰好 5 个成员', `ids = [${ids.join(', ')}]`);
  } else {
    bad('ModeId 联合类型恰好 5 个成员', `解析到 [${ids.join(', ')}]，期望 gantong/lingma/chat/boundless/collaboration`);
  }
}

// --- 2) MODES 数组：每个模式块 ---
// 匹配形如 `{\n id: 'xxx',\n name: '中文名',\n tagline: ...,\n desc: ...,\n level: 'L0|L2|L3|L4',\n risk: ...,\n badge: ...,\n },`
const blockRe = /\{\s*id:\s*'([a-z_]+)',\s*name:\s*'([^']*)',\s*tagline:\s*'([^']*)',\s*desc:\s*'([^']*)',\s*level:\s*'([A-Z]\d)',\s*risk:\s*'([^']*)',\s*badge:\s*'([^']*)',\s*\}/g;
const blocks = [...src.matchAll(blockRe)];
if (blocks.length === 5) {
  ok('MODES 数组恰好 5 项', `找到 ${blocks.length} 项`);
} else {
  bad('MODES 数组恰好 5 项', `找到 ${blocks.length} 项（期望 5）`);
}

const VALID_NAMES = new Set(['感通', '灵码', '闲聊', '无界', '协同']);
const VALID_LEVELS = new Set(['L0', 'L2', 'L3', 'L4']);
const expectedLevels = { chat: 'L0', boundless: 'L4' };
const byId = new Map();
for (const m of blocks) {
  const [, id, name, tagline, desc, level, risk, badge] = m;
  byId.set(id, { id, name, tagline, desc, level, risk, badge });
  if (!VALID_NAMES.has(name)) bad(`MODES[${id}].name 合法`, `name="${name}" 不在 ${[...VALID_NAMES].join('/')}`);
  else ok(`MODES[${id}].name 合法`, name);
  if (!VALID_LEVELS.has(level)) bad(`MODES[${id}].level 合法`, level);
  else ok(`MODES[${id}].level 合法`, level);
  if (expectedLevels[id] && expectedLevels[id] !== level) bad(`MODES[${id}].level 强制值`, `期望 ${expectedLevels[id]}，实际 ${level}`);
}
const ids = [...byId.keys()];
if (new Set(ids).size === 5 && ids.every((x) => ['gantong','lingma','chat','boundless','collaboration'].includes(x))) {
  ok('MODE_IDS 集合严格 5 个（无第 6 个）', `ids = [${ids.join(', ')}]`);
} else {
  bad('MODE_IDS 集合严格 5 个（无第 6 个）', `ids = [${ids.join(', ')}]`);
}

// --- 3) isModeId 拒绝旧名（静态断言：旧名不得出现在文件里的合法 ID 上下文）---
for (const legacy of ['yolo', 'standard', 'plan']) {
  // 只允许出现在「别名解析」语义里（当前 modes.ts 没有别名逻辑）
  const hits = [...src.matchAll(new RegExp(`'${legacy}'`, 'g'))].length;
  if (hits === 0) ok(`旧名 '${legacy}' 不得复活（isModeId 拒绝）`, '未在 modes.ts 命中');
  else bad(`旧名 '${legacy}' 不得复活`, `modes.ts 中出现 ${hits} 次`);
}

// --- 4) getModeSafe 静态存在 ---
if (/export\s+function\s+getModeSafe\s*\(/.test(src)) ok('getModeSafe 存在', '签名已导出');
else bad('getModeSafe 存在', '未导出 getModeSafe');
if (/DEFAULT_MODE/.test(src)) ok('DEFAULT_MODE 常量存在', '引用存在');
else bad('DEFAULT_MODE 常量存在', '未定义 DEFAULT_MODE');

// --- 5) needsConfirmSwitch 语义（静态读源码 + 行为模拟）---
const ncsMatch = src.match(/export\s+function\s+needsConfirmSwitch\s*\([^)]*\)\s*:\s*boolean\s*\{([\s\S]*?)\n\s*\}/);
if (ncsMatch) {
  const body = ncsMatch[1];
  const requiresBoundless = /to\s*===\s*'boundless'/.test(body);
  const excludesSameLevel = /from\s*!==\s*'boundless'/.test(body);
  if (requiresBoundless && excludesSameLevel) {
    ok('needsConfirmSwitch: 进入 boundless 需要确认；boundless→任意 不需要', `body = ${body.trim()}`);
  } else {
    bad('needsConfirmSwitch: 进入 boundless 需要确认；boundless→任意 不需要', `body = ${body.trim()}`);
  }
} else {
  bad('needsConfirmSwitch 存在', '未找到函数');
}

// --- 6) platformBlockReason: boundless 在安卓禁用 ---
if (/platformBlockReason/.test(src) && /BOUNDLESS_BLOCKED_PLATFORMS\s*=\s*new\s+Set\s*\(\s*\[['"]android['"]\]\s*\)/.test(src)) {
  ok('platformBlockReason: boundless 在 android 禁用', 'BOUNDLESS_BLOCKED_PLATFORMS={"android"}');
} else {
  bad('platformBlockReason: boundless 在 android 禁用', '未找到平台禁用集合');
}

// =====================================================================
// B. 静态红线：全 src 无旧名 + 无 emoji + W-2~W-8 token 覆盖
// =====================================================================

// 旧名红线：灵感 / 无限 / 工作模式（严格排除 `工作模式` 之外的合理上下文已不可能）
const OLD_NAMES = ['灵感', '无限', '工作模式'];
const srcFilesTS = walk(SRC, new Set(['ts', 'tsx']));
for (const forbidden of OLD_NAMES) {
  const hits = [];
  for (const f of srcFilesTS) {
    const c = readFileSync(f, 'utf-8');
    if (c.includes(forbidden)) {
      // 逐行找出命中
      c.split(/\r?\n/).forEach((line, i) => {
        if (line.includes(forbidden)) hits.push(`${relative(REPO, f)}:${i + 1}: ${line.trim()}`);
      });
    }
  }
  if (hits.length === 0) ok(`src/**/*.{ts,tsx} 无旧名「${forbidden}」`, `${srcFilesTS.length} 个文件全扫`);
  else bad(`src/**/*.{ts,tsx} 无旧名「${forbidden}」`, hits.join('\n'));
}

// Emoji 硬规则（严格限定到真正的 emoji 区，不含 →/→/①② 等常见 CJK 辅助符号）
const EMOJI_RX = /[\u{1F300}-\u{1FAFF}\u2600-\u27BF\u2705\u274C\u270B\u2714\u2716\u2764\u27A1\ud800-\udbff]/u;
const srcFilesAll = walk(SRC, new Set(['ts', 'tsx', 'css']));
let emojiHits = [];
for (const f of srcFilesAll) {
  const c = readFileSync(f, 'utf-8');
  if (EMOJI_RX.test(c)) {
    c.split(/\r?\n/).forEach((line, i) => {
      if (EMOJI_RX.test(line)) emojiHits.push(`${relative(REPO, f)}:${i + 1}`);
    });
  }
}
if (emojiHits.length === 0) ok('src/**/*.{ts,tsx,css} 零 emoji', `${srcFilesAll.length} 个文件全扫`);
else bad('src/**/*.{ts,tsx,css} 零 emoji', emojiHits.slice(0, 20).join('\n'));

// W-2~W-8 落地 token 存在性（此刻可能全绿，也可能部分红；红了说明主 agent 尚未提交）
const tokens = [
  { name: 'safe-area-inset',        reason: 'W-4 安全区 env()' },
  { name: 'orientationchange',      reason: 'W-7 横竖屏切换' },
  { name: 'visualViewport',         reason: 'W-8 软键盘' },
  { name: 'popstate',               reason: 'W-3 返回键 / 侧滑' },
  { name: 'ContextMenu',            reason: 'W-2 硬件菜单键' },
  { name: '__nav',                  reason: 'JSBridge 命名空间' },
];
let srcTextAll = '';
for (const f of srcFilesAll) srcTextAll += readFileSync(f, 'utf-8') + '\n';
for (const t of tokens) {
  if (srcTextAll.includes(t.name)) ok(`W token: ${t.name}`, t.reason);
  else bad(`W token: ${t.name}`, `${t.reason} — 未在 src/** 找到`);
}

// =====================================================================
// 报告
// =====================================================================
const pass = results.filter((r) => r.ok).length;
const fail = results.length - pass;
for (const r of results) {
  const tag = r.ok ? 'PASS' : 'FAIL';
  const d = r.detail.length > 160 ? r.detail.slice(0, 157) + '...' : r.detail;
  console.log(`[${tag}] ${r.name}` + (d ? ` — ${d}` : ''));
}
console.log(`\n${results.length} checks, ${pass} passed, ${fail} failed`);
process.exit(fail === 0 ? 0 : 1);
