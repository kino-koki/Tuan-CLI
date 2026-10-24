import { useEffect, useState } from 'react';
import type { Provider } from '../types';

/**
 * 助手形象资源说明
 * ------------------
 * 立绘来源于用户放入 `Tuan-App/dist/assets/` 的二次元形象。
 * 每家供应商有两张图（白底 / 黑底），随应用明暗主题自动切换，
 * 同主体仅换背景色，不会跳画。
 *
 * 二次元立绘是**唯一**的助手形象：不再有"官方星芒 vs 模型形象"的切换。
 * `DEFAULT_MASCOT` 仅作为应用图标（标题栏 / 设置页品牌区 / 标题旁小 logo）使用，
 * 不再是"默认助手形象"。
 *
 * ROSTER 收录了 15 家供应商，但其中 grok / mistral / perplexity 三家没有立绘，
 * 命中时会回落到图池第一张真实立绘作为代表形象。
 */

export interface Mascot {
  key: string;
  /** 完整立绘（空态大图、聊天头像位、设置页预览共用同一份资源） */
  img: string;
  name: string;
}

/** 应用图标（标题栏 / 设置页品牌区 / 标题旁小 logo）；不再是默认助手形象 */
export const DEFAULT_MASCOT = '/icons/star.png';

interface RosterEntry {
  key: string;
  name: string;
  /** 仅当 baseUrl 命中官方域名时才显示立绘；聚合/中转平台回落到代表立绘 */
  domains: string[];
  /** 供应商名 / 模型名命中关键词 */
  names: string[];
}

const ROSTER: RosterEntry[] = [
  { key: 'deepseek', name: 'DeepSeek', domains: ['deepseek.com'], names: ['deepseek'] },
  { key: 'claude', name: 'Claude', domains: ['anthropic.com'], names: ['anthropic', 'claude'] },
  { key: 'gpt', name: 'GPT', domains: ['openai.com'], names: ['openai', 'gpt'] },
  { key: 'qwen', name: '通义千问', domains: ['aliyuncs.com', 'dashscope'], names: ['qwen', '通义', '千问'] },
  { key: 'kimi', name: 'Kimi', domains: ['moonshot.cn', 'moonshot.ai'], names: ['moonshot', 'kimi'] },
  { key: 'glm', name: 'GLM', domains: ['bigmodel.cn', 'z.ai'], names: ['zhipu', 'glm', '智谱'] },
  // Seed（字节）属于豆包系：文件名前缀 Seed 在下方 FILE_TO_KEY 映射到本条目
  { key: 'doubao', name: '豆包', domains: ['volces.com'], names: ['doubao', '豆包', 'seed'] },
  { key: 'gemini', name: 'Gemini', domains: ['googleapis.com', 'google.com'], names: ['gemini', 'google'] },
  { key: 'grok', name: 'Grok', domains: ['x.ai'], names: ['xai', 'grok'] },
  { key: 'mistral', name: 'Mistral', domains: ['mistral.ai'], names: ['mistral'] },
  { key: 'minimax', name: 'MiniMax', domains: ['minimax.chat'], names: ['minimax'] },
  { key: 'hunyuan', name: '混元', domains: ['tencentmaas.com', 'tencentcloudapi.com'], names: ['hunyuan', '混元'] },
  { key: 'perplexity', name: 'Perplexity', domains: ['perplexity.ai'], names: ['perplexity'] },
  // dist/assets 下已收录的形象，ROSTER 补齐：
  { key: 'ernie', name: '文心', domains: ['baidu.com', 'xinfei'], names: ['ernie', '文心'] },
  { key: 'mimo', name: 'Mimo', domains: ['xiaomi'], names: ['mimo'] },
];

/**
 * 形象资源池（唯一来源：`Tuan-App/dist/assets/`）
 * ----------------------------------------------
 * 只从 `dist/assets` 读形象，其他 `src/assets/avatars*` 目录已删。
 * 文件名规则：`{ModelName}-白色背景...` / `{ModelName}-黑色背景...`。
 *  - 含 `白色背景` → 浅色主题
 *  - 含 `黑色背景` → 深色主题
 *  - 同一模型的两张图（白底 / 黑底）是**同一主体、仅背景色不同**，
 *    切换深浅色主题只换底色，绝不会换成另一张画。
 *
 * 实际文件名两种形态都要覆盖：
 *  - 手工放置的原名：`Claude-白色背景.jpg`
 *  - 带构建哈希后缀的：`Claude-白色背景-Bo2PXpbz.jpg`
 * 因此 glob 用宽松匹配 `*白色背景*`（而不是 `*-白色背景.*`），
 * 否则后者匹配不到哈希文件名，glob 会解析成空对象、形象图全部丢失。
 * 具体切分（前缀 → ROSTER key、白底 / 黑底判定）交给下方 buildPool 的正则。
 *
 * 目前每家只有 1 张图，`pickIndex` 的随机变体逻辑随之删除。
 *
 * Vite 的 `import.meta.glob` 路径相对**本文件**（`src/platform/mascot.ts`），
 * 项目根在 `Tuan-App/`，故 `dist` 需向上爬两级：`../../dist/assets/...`。
 * dist 是构建产物，构建时若目录不存在，glob 解析为空对象（回落占位图）；
 * 构建保留策略由 vite.config.ts 侧负责（preserveDistAssets 插件）。
 */
const globLight = import.meta.glob('../../dist/assets/*白色背景*', {
  eager: true,
  query: '?url',
  import: 'default',
}) as Record<string, string>;

const globDark = import.meta.glob('../../dist/assets/*黑色背景*', {
  eager: true,
  query: '?url',
  import: 'default',
}) as Record<string, string>;

/**
 * 文件名前缀 → ROSTER key 映射。
 * 前缀取自文件名第一个 `-` 之前的部分（大小写不敏感比较）。
 *
 * 特殊映射：
 *  - `Seed` → `doubao`：字节 Seed（豆包系）复用豆包条目，避免与豆包重复收录
 *    也避免破坏既有 doubao 的 domains / names 匹配规则。
 *  - `ERNIE` → `ernie`（百度文心，ROSTER 新增）
 *  - `Mimo`  → `mimo`（小米，ROSTER 新增）
 */
const FILE_TO_KEY: Record<string, string> = {
  claude: 'claude',
  deepseek: 'deepseek',
  ernie: 'ernie',
  gemini: 'gemini',
  glm: 'glm',
  gpt: 'gpt',
  hunyuan: 'hunyuan',
  kimi: 'kimi',
  mimo: 'mimo',
  minimax: 'minimax',
  qwen: 'qwen',
  seed: 'doubao',
};

/** 从 glob 结果构建 `{ ROSTER.key: url }` 映射，同 key 多图时取首个（当前场景仅 1 张）。 */
function buildPool(glob: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [path, url] of Object.entries(glob)) {
    const base = path.split('/').pop() ?? '';
    // 匹配 `前缀-...背景....jpg`，前缀不含 `-`
    const m = base.match(/^([^-\s]+)-.*背景.*\.(?:jpg|jpeg|png|webp|gif)$/i);
    if (!m) continue;
    const rk = FILE_TO_KEY[m[1].toLowerCase()];
    if (!rk) continue;
    if (!out[rk]) out[rk] = url;
  }
  return out;
}

const POOL_LIGHT = buildPool(globLight);
const POOL_DARK = buildPool(globDark);

/** 取当前主题应使用的图片 URL；缺失时回落另一主题，保证不出空图。 */
function imageFor(key: string, dark: boolean): string | undefined {
  if (dark) return POOL_DARK[key] ?? POOL_LIGHT[key];
  return POOL_LIGHT[key] ?? POOL_DARK[key];
}

/** 当前是否深色主题。主题切换会写 <html class="dark">，直接读 DOM 最可靠。 */
export function isDarkTheme(): boolean {
  if (typeof document === 'undefined') return false;
  return document.documentElement.classList.contains('dark');
}

/**
 * 订阅主题变化，返回是否深色。
 *
 * 形象资源按主题分两套（白底 / 黑底），主题切换后必须重算，
 * 否则会出现"切到深色还挂着白底立绘"的割裂感。
 * `applyTheme` 只改 `<html>` 的 class，没有事件可监听，故用
 * MutationObserver 监听 class 属性变化。
 */
export function useDarkTheme(): boolean {
  const [dark, setDark] = useState(isDarkTheme);
  useEffect(() => {
    const el = document.documentElement;
    const sync = () => setDark(el.classList.contains('dark'));
    sync();
    const mo = new MutationObserver(sync);
    mo.observe(el, { attributes: true, attributeFilter: ['class'] });
    return () => mo.disconnect();
  }, []);
  return dark;
}

/**
 * 极端边界占位图：构建时 dist/assets 为空（本不该发生）时不至于返回 star。
 * 正常构建下 dist/assets 始终包含 24 张立绘，不会走到这里。
 */
const PLACEHOLDER_IMG =
  'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48"><circle cx="24" cy="16" r="8" fill="%23cccccc"/><path d="M8 42c0-9 8-16 16-16s16 7 16 16" fill="%23cccccc"/></svg>';

/**
 * 取图池里第一张真实立绘作为代表性形象，跟随当前主题。
 * 供设置页「模型形象」预览、未收录供应商的回落使用。
 * 不得返回 star。
 */
export function sampleImage(dark?: boolean): string {
  const useDark = dark ?? isDarkTheme();
  const pool = useDark ? POOL_DARK : POOL_LIGHT;
  for (const r of ROSTER) {
    const url = pool[r.key] ?? (useDark ? POOL_LIGHT[r.key] : POOL_DARK[r.key]);
    if (url) return url;
  }
  return PLACEHOLDER_IMG;
}

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.toLowerCase();
  } catch {
    return '';
  }
}

/** 取一个代表立绘包装成 Mascot（未收录供应商 / 无立绘供应商的回落）。 */
function fallbackMascot(dark: boolean): Mascot {
  const useDark = dark ?? isDarkTheme();
  const pool = useDark ? POOL_DARK : POOL_LIGHT;
  for (const r of ROSTER) {
    const url = pool[r.key] ?? (useDark ? POOL_LIGHT[r.key] : POOL_DARK[r.key]);
    if (url) return { key: r.key, img: url, name: r.name };
  }
  return { key: 'unknown', img: PLACEHOLDER_IMG, name: 'Tuan-Chat' };
}

/**
 * 解析当前供应商 / 模型应展示的形象。
 *
 * 二次元立绘是唯一助手形象，本函数**永远返回非 null 的 Mascot**。
 * 匹配顺序：
 *   ① ROSTER 官方域名 + 名称命中 → 对应 key 的图
 *   ② 命中 ROSTER 条目但该 key 在图池里没有图（grok / mistral / perplexity）
 *      → 回落 sampleImage(dark)
 *   ③ 完全不命中 ROSTER（聚合/中转/自定义供应商）→ 同样回落 sampleImage(dark)
 *
 * 深色主题下取 `*-黑色背景.jpg`，浅色取 `*-白色背景.jpg`，同模型同主体，
 * 切换主题不换画。每家仅 1 张图，无随机变体。
 */
export function resolveMascot(
  provider: Provider | undefined,
  model?: string,
  dark?: boolean,
): Mascot {
  const useDark = dark ?? isDarkTheme();

  if (provider) {
    const host = hostOf(provider.baseUrl);
    const hay = `${provider.name} ${provider.format} ${model ?? ''}`.toLowerCase();

    for (const r of ROSTER) {
      const official = r.domains.some(
        (d) => host.includes(d) || provider.baseUrl.toLowerCase().includes(d),
      );
      const named = r.names.some(
        (n) => provider.name.toLowerCase().includes(n) || hay.includes(n),
      );
      if (official && named) {
        const img = imageFor(r.key, useDark);
        if (img) return { key: r.key, img, name: r.name };
        // 命中 ROSTER 但图池无此 key（如 grok / mistral / perplexity）：走下方回落
        break;
      }
    }
  }

  // 命中 ROSTER 但无立绘，或完全不命中 ROSTER：取图池第一张真实立绘作为代表
  return fallbackMascot(useDark);
}
