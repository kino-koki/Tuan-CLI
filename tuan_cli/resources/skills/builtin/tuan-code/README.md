# code-architect

给代码开发 Agent 的超级工程方法论技能：从 45 个顶级开源项目蒸馏工程法则，覆盖需求→设计→实现→验证→交付全流程，并加入 1 个从零到落地的完整案例（Lore，虚构示例，数值非实测）与 1 个真实工程实战模块（事故复盘与实操经验）。

## 入口与文件说明

- `Tuan-code.md` — 真入口：十条工程心法总纲 + 模块路由表 + 任务规模分档（S/M/L）+ 五阶段工作流 + 终检清单。
- `references/index.md` — 总导航 + 45 项目速查总表（按任务类型选模块）。
- `references/01..05` — 系统/云原生/数据/语言/应用 五类项目的深度蒸馏（档案 + 工程智慧 + 借鉴点 + 易踩坑）。
- `references/06-from-zero-to-ship.md` — 从零到落地的完整案例模板（可照拆里程碑）。
- `references/07-backend-and-business.md` — 后端与业务系统（Django/Rails/Spring Boot/gRPC/Netty/Dubbo/Seata）。
- `references/08-on-the-job-practice.md` — 线上工程实战：4 起真实事故复盘（Knight Capital/AWS S3/GitLab/GitHub）+ 7 组实操经验（变更/回滚/复盘/性能/迁移/评审/稳定性），事实与经验法则显式区分。
- `scripts/preflight.py` — 终检清单的可执行子集（无第三方依赖，交付项目前运行，无 FAIL 项即可交付）。

## 使用方式

把本目录（或解压后的 zip）放入 Agent 技能目录；加载后先读 SKILL.md 的十条心法与路由表，按任务规模分档决定工作流裁剪，再进入对应 `references/` 模块取用深度蒸馏；交付项目前在项目根目录运行 `python scripts/preflight.py .`。