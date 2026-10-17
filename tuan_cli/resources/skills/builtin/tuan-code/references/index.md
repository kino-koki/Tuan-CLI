# code-architect references 总导航

本目录是 `code-architect` 技能的深度蒸馏库：从 **45 个顶级开源项目**中提炼可迁移的工程法则，另附 **1 个从零到落地的完整案例（Lore，虚构示例，数值非实测）** 与 **1 个真实工程实战模块（事故复盘与实操经验）**。除明确标注为虚构示例的 Lore 外，所有项目事实（年份/作者/定位）均来自公开资料核验。

## 使用方法

1. 先在 SKILL.md 读十条工程心法总纲与标准工作流。
2. 按任务类型选一个模块文件读（见下表）。
3. 到具体决策点时，回读对应项目的"工程智慧/借鉴点/易踩坑"核对。
4. 需要从零做完整软件时，整体读 `06-from-zero-to-ship.md` 并对照它拆里程碑。
5. 做业务后端/框架选型/分布式一致性时读 `07-backend-and-business.md`；上线运营、事故处理、稳定性建设时读 `08-on-the-job-practice.md`。

## 模块速查总表（45 项目 + 1 虚构案例 + 1 实战模块）

| 模块文件 | 项目 | 一句话定位 |
|---|---|---|
| **01 系统与基础设施**（01-systems-foundations.md） | Linux | 开源操作系统内核，全世界超算与服务器的事实标准（1991，Linus Torvalds） |
| | Git | 分布式版本控制系统，替代 BitKeeper 而生（2005，Linus Torvalds） |
| | nginx | 事件驱动的高性能 Web/反向代理服务器（2004，Igor Sysoev） |
| | Redis | 内存键值数据库，单线程却吞吐极高（2009，antirez） |
| | SQLite | 零配置嵌入式数据库，"数据库就是一个文件"（2000，D. Richard Hipp） |
| | PostgreSQL | 功能最全的开源关系数据库，源自伯克利 POSTGRES（1996 开源） |
| | curl | 支持 30+ 协议的命令行传输工具（1996，Daniel Stenberg） |
| | FFmpeg | 音视频编解码/转码框架（2000，Fabrice Bellard） |
| **02 容器与云原生**（02-cloud-native.md） | Kubernetes | 容器编排事实标准，源自 Google Borg（2014，Google） |
| | Docker | 容器打包与运行时，"Build, Ship, Run"（2013，Solomon Hykes） |
| | etcd | 分布式一致性键值存储，Raft 实现标杆（2013，CoreOS） |
| | Prometheus | 指标采集与告警，pull 模型（2012，SoundCloud） |
| | Grafana | 指标可视化面板（2014，Torkel Ödegaard） |
| | ClickHouse | 列式分析数据库，为 Yandex.Metrica 而生（2009/2016 开源，Yandex） |
| | Terraform | 声明式基础设施编排（IaC）（2014，HashiCorp） |
| | Ansible | 无代理自动化运维，SSH + YAML（2012，Michael DeHaan） |
| **03 数据与机器学习**（03-data-and-ml.md） | Kafka | 分布式消息流平台（2010，LinkedIn） |
| | MongoDB | 文档型 NoSQL 数据库（2009，10gen） |
| | pandas | Python 数据分析库（2008，Wes McKinney） |
| | NumPy | Python 数值计算基础库（2005，Travis Oliphant） |
| | scikit-learn | 经典机器学习库（2007，David Cournapeau） |
| | PyTorch | 动态图深度学习框架（2016/2017，FAIR） |
| | TensorFlow | 数据流图深度学习框架（2015，Google Brain） |
| **04 语言与工具链**（04-languages-and-toolchains.md） | Python | 通用高级语言，代码可读性哲学（1991，Guido van Rossum） |
| | Go | 编译型系统语言，极简并发模型（2009，Google） |
| | Rust | 内存安全系统语言，零成本抽象（2010/2015 1.0，Mozilla） |
| | TypeScript | JS 的类型化超集，渐进采用（2012，Anders Hejlsberg） |
| | Node.js | 事件驱动 JS 运行时（2009，Ryan Dahl） |
| | Deno | 安全默认的现代 JS/TS 运行时（2018，Ryan Dahl） |
| | LLVM | 模块化编译器基础设施（2000 发起，Chris Lattner） |
| | webpack | 前端模块打包器（2012，Tobias Koppers） |
| | Vite | 基于原生 ESM 的极速前端构建工具（2019，尤雨溪） |
| **05 应用与生态**（05-apps-and-ecosystems.md） | VS Code | 开源编辑器，扩展生态之王（2015，微软） |
| | Chromium | Chrome 背后的开源浏览器内核（2008，Google） |
| | Svelte | 编译时框架，无虚拟 DOM（2016，Rich Harris） |
| | Godot | 开源游戏引擎，节点化架构（2014 开源，Juan & Ariel） |
| | Blender | 开源 3D 创作套件（1994/2002 开源，Ton Roosendaal） |
| | Homebrew | macOS 包管理器（2009，Max Howell） |
| **06 从零到落地**（06-from-zero-to-ship.md） | Lore | 本地优先 AI 编程助手的完整开发全程（案例，数值均为示例值非实测） |
| **07 后端与业务系统**（07-backend-and-business.md） | Django | 电池全带的 Python Web 框架（2005，Adrian Holovaty & Simon Willison） |
| | Ruby on Rails | 约定优于配置的 Ruby 全栈框架（2004，DHH） |
| | Spring Boot | 消除样板配置的 Java 企业框架（Spring 2004 / Boot 2014，Rod Johnson / Pivotal） |
| | gRPC | 契约先行的多语言 RPC 框架（2015，Google） |
| | Netty | 异步事件驱动网络框架，Kafka/Dubbo 底层（2004，Trustin Lee） |
| | Dubbo | 服务治理型 Java RPC 框架（2011 开源/2019 Apache 顶级，阿里巴巴） |
| | Seata | 分布式事务中间件，AT/TCC/SAGA/XA（2019 开源，阿里 TXC 积累） |
| **08 线上工程实战**（08-on-the-job-practice.md） | 4 起事故 + 7 专题 | Knight Capital / AWS S3 / GitLab / GitHub 事故复盘与变更管理、回滚、迁移、稳定性等实操经验（非项目） |

## 按任务场景推荐阅读顺序

- **要设计一个数据库/存储/高并发组件** → 01 模块 + Redis/SQLite/PostgreSQL 深拆
- **要把系统容器化/上云/做微服务** → 02 模块全文
- **要做数据管道/特征工程/模型服务** → 03 模块 + Kafka 深拆
- **要选语言/搭构建链/设计 DSL/做编译器** → 04 模块全文
- **要做一个用户产品/编辑器/创意工具** → 05 模块 + VS Code/Svelte 深拆
- **要做一个完整新软件** → 06 模块全文（案例里含所有阶段的模板与检查表）
- **要做业务后端/Web 框架/服务治理/分布式一致性** → 07 模块 + gRPC/Seata 深拆
- **要上线运营/做变更与回滚/事故复盘/稳定性建设** → 08 模块全文（4 起真实事故 + 7 组实操专题）

## 通用提醒

- 深拆中的"工程智慧"是可迁移方法论，"借鉴点"是落地时直接可抄的实践，"易踩坑"是这些项目曾踩过、你应避开的坑。
- 模块法则彼此独立，但十条心法是总纲；遇到法则冲突时，回心法找优先级（例如"简单性"通常优先于"功能完整"）。
- 项目速查表中的年份指开源/发布年份，作者为主要创始者。