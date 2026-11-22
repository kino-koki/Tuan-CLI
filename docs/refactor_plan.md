# 巨型文件拆分与单一真源同步 — 重构方案 (审计 #29 / #28)

> 状态: 方案 (2026-11-20)。本文给出可执行边界与顺序; 落地必须逐步进行,
> 每步全量测试 + `sync_engine --check` + mypy 全绿后才进入下一步。

## 1. 现状测量 (2026-11-20, 字节数)

| 文件 | 大小 | 已有拆分 |
|---|---|---|
| `tuan_cli/web/frontend.py` | 238 KB | 无 (单文件内嵌 HTML+CSS+JS) |
| `tuan_cli/web/server.py` | 174 KB | 已拆出 `server_ops.py` (37KB) / `server_config.py` (28KB) / `server_sessions.py` (5KB) |
| `tuan_cli/ext/safety_patterns.py` | 147 KB | 数据已部分拆至 `ext/patterns_data/{critical,high,medium,extreme}.py` |
| `tuan_cli/ext/patterns_data/critical.py` | 124 KB | 纯数据文件 (规则常量) |

## 2. 拆分边界

### 2.1 `web/server.py` (继续既有方向)

按既有 `server_ops / server_config / server_sessions` 的 mixin/组合模式继续:

1. `web/server_auth.py` — GitHub 设备流登录 (`_auth_github_start/_auth_github_poll/_auth_logout`)、`_WebAuthStore` 会话管理、`_auth_status`。
2. `web/server_static.py` — 静态资源与首页 HTML 装配 (含 api_token 注入)。
3. `web/server_sse.py` — SSE 流式端点 (on_token/on_tool 回调装配、会话锁)。
4. `web/server_files.py` — `/api/file`、工作区文件读写与 `.tuan/` 内部文件访问拒绝逻辑 (审计 P0-06)。

约束: 每步只是**搬移 + import 收口**, 不改任何鉴权/审计行为; 搬移后 server.py 保留
`from .server_x import *` 兼容层一个迭代周期, 供外部引用方 (Tuan-App engine 拷贝)
同步过渡。

### 2.2 `web/frontend.py`

前端是内嵌静态资源, 拆法是「资源化」而不是「模块化」:

1. 抽成 `tuan_cli/web/static/` 包: `index.html` / `app.css` / `app.js` (可再按
   `js/` 会话、审批、MCP、i18n 分文件), `frontend.py` 退化为「读资源 + 注入
   api_token + 渲染」的薄层。
2. 用 `importlib.resources` 读取, 保持零第三方依赖; wheel 打包已含
   `resources/**` 模式, 需把 `web/static/` 加进 `[tool.setuptools.package-data]`。
3. 收益: 238KB 单文件 → 可按前端关注点 review; JS 修改不再触发整文件冲突。

### 2.3 `ext/safety_patterns.py` + `ext/patterns_data/`

安全规则**数据**与**判定逻辑**分离 (审计 #29 的核心诉求):

1. `safety_patterns.py` 只留: 模式装载、编译缓存、匹配入口。
2. 规则数据全部下沉 `ext/patterns_data/`: 现有 `critical/high/medium/extreme.py`
   之外, 把 `safety_patterns.py` 内嵌的字面量规则表迁到 `patterns_data/` 下按域
   分文件 (`fs_destructive.py`, `cred_exfil.py`, `net_egress.py`, `sql_danger.py`,
   `git_danger.py` …), 每条规则保持 `(pattern, label, severity, rationale)` 四元组。
3. 数据文件之间无 import 依赖, 可独立做「规则条数 / 覆盖域」的机器核验
   (可加 `scripts/check_patterns.py`: 重复 label、不可编译正则、severity 缺失即 fail)。
4. 红线匹配行为由现有 `tests/test_safety_*` 全量钉死, 拆分前后必须零差异。

## 3. 单一真源同步 (#28)

现状: 根 `tuan_cli/` 与 `Tuan-App/engine/tuan_cli/` 双份人工同步, CI 用
`scripts/sync_engine.py --check` 门禁防漂移 (本轮已修复一次 +5 新文件 / ~30 处漂移)。

目标态: **根 `tuan_cli/` 是唯一真源**, engine 目录变成构建产物:

1. 保留 `scripts/sync_engine.py --check` 作为 CI 门禁 (现状, 防漂移兜底)。
2. Tuan-App 侧打包脚本在 build 前执行 `python scripts/sync_engine.py`
   (build-time copy), 把「人工同步」从流程里去掉。
3. 中期: Tuan-App 打包直接以 wheel 为依赖 (`pip install tuan-cli`), 彻底删除
   engine 内的源码拷贝; 过渡期在 `Tuan-App` 构建说明里标注「engine/ 是产物,
   请勿手改」。
4. 验收: 删除 `Tuan-App/engine/tuan_cli` 后, 根目录测试与打包流程仍全绿。

## 4. 执行顺序与风险控制

| 步骤 | 内容 | 风险 | 回退 |
|---|---|---|---|
| 1 | safety_rules 数据下沉 (纯数据搬移) | 低 — 行为被 test_safety_* 钉死 | git revert 单步 |
| 2 | server_auth/server_files 搬移 | 中 — 鉴权路径 | 保留兼容 import 层, 逐步切换 |
| 3 | frontend 资源化 | 中 — 打包清单需同步 | package-data 校验 + 手动冒烟 |
| 4 | engine 构建期拷贝 | 低 — 现有门禁兜底 | 门禁仍在, 随时可回人工模式 |

每步完成判据: `pytest tests/ -q` 全绿 · `mypy tuan_cli` 0 错 ·
`sync_engine.py --check` 0 漂移 · `check_shell_true.py` 0 未授权。
