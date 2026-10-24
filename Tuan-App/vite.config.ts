import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import process from 'node:process';

/**
 * 内联插件：把 `dist/assets/*.jpg|png` 在 `vite build` 前后做「快照 → 还原」，
 * 保证这些图按**原文件名**留在构建产物里，不被 hash、不被清空。
 *
 * 背景
 * ----
 * 用户明确要求 awa（社区二创）形象图只从 `Tuan-App/dist/assets/` 这个固定路径
 * 读取（`*-白色背景.jpg` / `*-黑色背景.jpg`），而 Tauri 又直接把 `dist/` 当作
 * 前端产物打包（`src-tauri/tauri.conf.json` 的 `frontendDist: "../dist"`）。
 *
 * 这些 jpg 不是从 `src/` 打进来的 Vite 资源：`src/platform/mascot.ts` 用的
 * `import.meta.glob` 只会匹配 `src/assets/avatars-community/` 下**再套一层子
 * 目录**的图（模式写作 `avatars-community 下两层目录里的 jpg/png`），顶层
 * `dist/assets/` 下的 jpg 谁都不认识。它们是被人手工放进 `dist/assets/` 的。
 *
 * 问题
 * ----
 * Vite 默认 `build.emptyOutDir = true`，每次 `vite build` 会 `emptyDir(dist)`
 * ——把 dist 下所有内容全部删掉，包括这些手工放置的 jpg。之后 Vite 只把
 * `public/` 拷回来（`dist/icons/`、`dist/data/`、`dist/avatars/`），并不会
 * 重新放置 `dist/assets/` 下的 jpg。
 *
 * 方案取舍
 * --------
 * **不选** `build.emptyOutDir = false`：上一次构建留下的旧 hash 的
 * `index-*.js` / `index-*.css` 会一直堆在 `dist/assets/` 里。index.html 只引用
 * 最新那份，但打包体积、浏览器缓存策略都会被旧文件拖累，且 Tauri 打包时
 * （`frontendDist: "../dist"`）会把所有历史残留一起塞进安装包。
 *
 * **不选** 把这些 jpg 移进 `src/assets/` 或加 `?url` 让它们被 Vite 收编：
 * Vite 会给资源加 hash（`xxx-abc123.jpg`），文件名变了，违背「按原文件名保留」。
 *
 * **不选** `publicDir` 或 `rollupOptions.output.assetFileNames` 定制：前者会把
 * 图放到 `dist/` 顶层（`publicDir` 的默认拷贝规则不保留 `assets/` 子目录语义，
 * 而且 `public/assets/xxx.jpg` 会被 Vite 认为是"用户自己的资源"、和构建产物
 * 混在一起），后者仍然会加 hash。
 *
 * **选定** 快照 → 还原：`buildStart` 抢在 Vite 清空 outDir 之前，把 jpg/png
 * 快照到 `os.tmpdir()` 下的临时目录；`closeBundle` 在 Vite 完成 write 之后，
 * 按原文件名复制回 `dist/assets/`。临时目录用完即清，不污染仓库。
 *
 * 时序保证
 * --------
 * 查了 Vite 6 源码（`node_modules/vite/dist/node/chunks/dep-*.js`），构建流程
 * 是：
 *   1. `rollup(rollupOptions)` —— 这里触发所有 `buildStart` 钩子
 *   2. `prepareOutDir(...)`     —— 这里 `emptyDir(outDir)` 才真正清空 dist
 *   3. `bundle.write(output)`   —— 这里写 hashed js/css
 *   4. `bundle.close()`         —— 这里触发 `closeBundle`（在 finally 里，
 *                                  构建失败也会调用）
 *
 * 所以 `buildStart` 一定在 `emptyOutDir` 之前；`closeBundle` 一定在 write 之后。
 * `enforce: 'pre'` 让本插件在 `buildStart` 阶段抢在其它用户插件之前，进一步
 * 保证快照时机足够早。
 *
 * 兜底
 * ----
 * 如果 `rollup()` 本身在某个 `buildStart` 钩子里抛错（比如别的并行 Agent 改坏
 * 了源码，react 插件的 buildStart 抛了），Vite 的 `finally` 块因为 `bundle`
 * 还是 undefined 不会调 `bundle.close()`，`closeBundle` 就跳过了。所以再挂一个
 * `process.on('exit')` 兜底：进程退出前同步把快照恢复回来。`vite build` 是同步
 * 退出路径，exit 事件里只用 sync fs API 是允许的。
 *
 * 异常处理
 * --------
 * 快照和还原的所有步骤都包在 try/catch 里，单张复制失败不影响其它文件；
 * 插件自身出错不阻断构建。这与用户要求「不能让插件失败阻断构建」一致。
 *
 * 文件名
 * ------
 * 用 `/\.(jpg|png)$/i` 正则匹配扩展名，不硬编码具体图片名——后续 Agent 增删
 * 形象图（新增 `*-黑色背景.jpg`、把 `GPT-白色背景_1792584425908edit.jpg` 改名
 * 成 `GPT-白色背景.jpg`）不需要改这份配置。
 */
const IMG_EXT = /\.(jpg|png)$/i;

function preserveDistAssets(): Plugin {
  let targetDir: string | null = null;
  let snapshotDir: string | null = null;

  function snapshot() {
    if (!targetDir) return;
    try {
      if (!fs.existsSync(targetDir)) return;
      const files = fs.readdirSync(targetDir).filter((n) => IMG_EXT.test(n));
      if (files.length === 0) return;
      const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'tuan-dist-assets-'));
      for (const name of files) {
        fs.copyFileSync(path.join(targetDir, name), path.join(tmp, name));
      }
      snapshotDir = tmp;
    } catch {
      // 快照失败也不能阻断构建：下次 closeBundle 会因为 snapshotDir 仍是 null 而跳过。
      snapshotDir = null;
    }
  }

  function restore() {
    if (!snapshotDir || !targetDir) return;
    try {
      if (!fs.existsSync(snapshotDir)) return;
      fs.mkdirSync(targetDir, { recursive: true });
      const files = fs.readdirSync(snapshotDir);
      for (const name of files) {
        try {
          fs.copyFileSync(path.join(snapshotDir, name), path.join(targetDir, name));
        } catch {
          // 单张复制失败不影响其它文件
        }
      }
    } finally {
      // 无论复制成功与否都清理临时目录；清理本身也 try/catch，绝不抛。
      try {
        if (snapshotDir) fs.rmSync(snapshotDir, { recursive: true, force: true });
      } catch {
        /* ignore */
      }
      snapshotDir = null;
    }
  }

  // 兜底：如果构建在 buildStart 之后、closeBundle 之前因为异常中断
  // （Vite 的 finally 里 `if (bundle) await bundle.close()` 因为 bundle 还是
  // undefined 而跳过 closeBundle），进程退出前仍然把 jpg 恢复回来。
  // restore() 只用 sync fs API，能在 exit 事件里安全执行。
  process.on('exit', restore);

  return {
    name: 'tuan-preserve-dist-assets',
    apply: 'build',
    enforce: 'pre',
    configResolved(config) {
      const outDir = path.resolve(config.root, config.build.outDir);
      targetDir = path.join(outDir, 'assets');
    },
    buildStart() {
      snapshot();
    },
    closeBundle() {
      restore();
    },
  };
}

export default defineConfig({
  plugins: [react(), preserveDistAssets()],
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    host: '127.0.0.1',
    watch: { ignored: ['**/src-tauri/**'] },
  },
  envPrefix: ['VITE_', 'TAURI_'],
  build: {
    target: 'es2021',
    minify: 'esbuild',
    sourcemap: false,
    rollupOptions: {
      output: {
        /**
         * 立绘图按**原文件名**输出，不加 hash。
         *
         * 原因：`src/platform/mascot.ts` 用 `import.meta.glob` 把 `dist/assets/*.jpg`
         * 收编进包后，Vite 默认会重命名为 `<原名>-<hash>.jpg`；而
         * `preserveDistAssets` 插件又在 `closeBundle` 把构建前的原文件按原名拷回。
         * 两者叠加会在 `dist/assets/` 留下两份副本（24 张 → 48 张，62MB → 119MB），
         * 全部被 `frontendDist: "../dist"` 塞进 Tauri 安装包。
         *
         * 只放开图片：JS / CSS 仍走默认的 `[name]-[hash]`，缓存策略不受影响。
         * 图片文件名本身唯一（供应商名 + 背景色 + 原哈希后缀），不会互相覆盖。
         */
        assetFileNames: (info) => {
          const n = info.name ?? '';
          if (/\.(?:jpg|jpeg|png|webp|gif)$/i.test(n)) return 'assets/[name][extname]';
          return 'assets/[name]-[hash][extname]';
        },
      },
    },
  },
});
