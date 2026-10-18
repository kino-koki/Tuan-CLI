---
name: tuan-design
description: >
  世界级公司 HTML 设计风格库（71 家精选、覆盖 20+ 领域，每家公司一份独立
  规格文件）。当用户要求按某家著名公司（Apple、Anthropic、Stripe、IBM、
  Airbnb、Duolingo、Pentagram、McKinsey、Linear、Vercel、Notion、Atlassian、
  Spotify、Slack、Figma、Framer、Netflix、Dropbox、BMW、Mercedes-Benz、
  Amazon、Shopify、YouTube、Starbucks、Coca-Cola、Gucci、Burberry、Reddit、
  Discord、Google、Microsoft、Meta、OpenAI、GitHub、GitLab、Salesforce、
  Adobe、X、LinkedIn、Pinterest、Instagram、TikTok、Medium、Substack、
  Squarespace、Webflow、Canva、Dribbble、Behance、Asana、Monday.com、
  Airtable、Intercom、Typeform、Calendly、Zoom、Uber、Booking.com、
  Coinbase、Klarna、Robinhood、PayPal、NVIDIA、Cloudflare、Supabase、
  Hugging Face、Perplexity、Arc、Nike、Lego、IKEA 等）的设计风格制作
  网页/HTML，或表达"世界级公司质感""顶级品牌设计语言""不 AI 味的知名
  品牌风""按 XX 公司的风格"等意图时使用；制作日报、落地页、产品页、
  作品集等 HTML 产物需要先选定一家风格起点时使用。
license: MIT
metadata:
  version: "2.2"
  changelog: |
    v2.2 目录定本：清单文件由 builtin/ 根下迁入本包 tuan-design/SKILL.md，使下方全部 `companies/...` 相对路径按技能包根 解析成立（此前清单与 companies/ 不在同一层，路径悬空）。
    v2.1 修复定本：修正 Netflix 重复收录（原 17/24 两份合并为 17 一份，
    编号顺延，总数为 71 家独立公司）；为全部公司规格补充核验说明字段；
    修正路由表（移除 Tesla 参考项、消除 Uber 重复、统一 Slack/Typeform
    分组）；将 TUAN Design 手册与 premium-design 降级为可选增强。
    v2.0 定本修复：72 家公司每家一份独立 md（companies/，全部可独立
    加载）；软件公司一律分「HTML 板块 · 官网与营销页」与「UI/UX 板块 ·
    产品界面」两个栏目；实体品牌公司为「官网板块 · 数字化品牌体验」；
    新增 42 家顶级公司（Google、Microsoft、OpenAI、GitHub、NVIDIA、
    Cloudflare、Supabase、Uber、Booking.com、Coinbase、Nike、Lego、
    IKEA 等）；原 30 家内容逐字保留定本。
    v1.0 整合 30 家公司 HTML 设计风格（用户整理的三个批次文档），原样
    收录为 references，并建立使用协议、快速检索总表、领域索引与反混搭
    规则。
---

# TUAN Design · 世界级公司设计风格库（71 家）

本 skill 是 TUAN Design 体系的独立版本——「风格起点库」：回答"这个页面像谁"。
71 家全球顶级公司、20+ 领域，每家一份独立规格文件，可被 AI Agent 单独加载并
直接复现：色彩、字体、间距、动效、记忆点，以及可执行的 CSS Token 与复现指令。

它与 TUAN Design 手册（`tuan-design` / `premium-design`）的分工：手册负责"怎么
判断、怎么做"，本库负责"像谁、从哪里起步"。手册为**可选增强**：本库自身包含
设计哲学、规格总览、CSS Token 与反混搭自查，单包即可独立完成风格起点选择与
落地；若环境中存在手册，可配套使用其四问校准、设计系统宣告、差异协议与完成
清单进一步打磨。

## 目录与读取方式

路径均相对本清单文件所在目录（`tuan-design/`）解析。


- `companies/index.md` — **全量快速检索总表**（71 家 × 画布色/强调色/字体/记忆点）+
  分组领域索引。选型先读这一份。
- `companies/01-apple.md` … `companies/71-ikea.md` — 每家公司一份独立规格文件，
  文件名规则 `NN-公司.md`。选中后只读该家的文件。
- 原三份聚合 references（`companies-01-10/11-20/21-30.md`）已随 v2.0 定本拆分为
  独立文件，不再直接引用。

## 使用协议（不可违反）

1. **一次只有一家**。每次只选择一家公司的设计系统作为起点，禁止跨公司混搭。若生成
   结果同时出现两家标志性特征（如 Anthropic 奶油底色 + Linear 暗色层级、Stripe 电光紫 +
   Vercel 网格渐变、Discord Blurple + 朱红 CTA、OpenAI 白绿克制 + Klarna 糖果粉），
   说明发生混搭，必须重做。
2. **起点由点名或领域决定**。用户点名某公司则直接使用该家；未点名时按领域标签、
   设计哲学与记忆点匹配最合适的一家，并在设计系统宣告中说明选择理由。
3. **只读一家的配方**。选定后读取 `companies/NN-公司.md` 中的完整规格与 Token。
   原 30 家定本（01–29）为单文件完整规格（`## 设计规格` + `## CSS Token`）；
   新增公司（30–71）按板块读取：软件公司取「HTML 板块」+「UI/UX 板块」两份
   Token，实体品牌公司取「官网板块」单份 Token。只取这一家的变量，不混用
   其他家的写法。
4. **字体不自由发挥**。专有字体不可用时使用规格内的 fallback 栈（如 Poppins → Arial、
   IBM Plex → sans-serif、gg sans → Noto Sans、Google Sans → Roboto），不另选风格不符
   的字体。
5. **风格库是起点不是模板**。在所选风格上必须做变异：至少两个维度与参考站点不同
   （差异维度：字体配对、主色色相、布局骨架、记忆点类型、密度）。

## 使用流程（四步）

1. **定起点**：点名即用该家；未点名先读 `companies/index.md`，按领域索引或记忆点
   匹配最合适的一家。
2. **读配方**：打开对应的 `companies/NN-公司.md`，只取该家完整规格（设计哲学、
   字体、色彩、间距、圆角、动效、记忆点、Token 与应用方式）。
3. **落 token**：画布色、强调色、正文色、字体栈、间距基准、圆角与动效以 CSS 变量
   落地；记忆点按规格"应用方式"实现；专有字体走 fallback 栈。
4. **变异与自查**：按使用协议第 5 条做至少两处变异；交付前按下方
   反混搭自查清单核对。

## 领域索引（71 家）

**科技与操作系统**：Apple、Microsoft、Google
**AI 与前沿研究**：Anthropic、OpenAI、Hugging Face、Perplexity
**金融科技与支付**：Stripe、PayPal、Coinbase、Klarna、Robinhood
**开发者平台与设计系统**：IBM Carbon、GitHub、GitLab、Vercel、Linear、Supabase、
Cloudflare、Webflow、NVIDIA、Arc
**企业软件与协作**：Notion、Atlassian、Salesforce、Asana、Monday.com、Airtable、
Intercom、Zoom、Slack、Dropbox
**消费市场与品牌平台**：Airbnb、Duolingo、Uber、Booking.com、Canva、Squarespace、
Calendly、Typeform
**社交与内容平台**：Meta、X、LinkedIn、Pinterest、Instagram、TikTok、Medium、
Substack、Reddit、Discord、Spotify、YouTube、Netflix
**创意工具与设计平台**：Figma、Framer、Adobe、Dribbble、Behance
**咨询与设计机构**：Pentagram、McKinsey
**汽车与出行**：BMW、Mercedes-Benz
**电商与零售**：Amazon、Shopify
**餐饮与快消**：Starbucks、Coca-Cola、Nike、Lego、IKEA
**奢侈品与时尚**：Gucci、Burberry

## 反混搭自查

生成结果若同时出现下列组合中的两个来源特征，即为混搭，需退回重做：

- 奶油画布（Anthropic/Notion/Dropbox/Starbucks）+ 暗色层级卡（Linear/Spotify/Discord）
- 电光紫交互（Stripe/Blurple）+ 网格渐变英雄区（Vercel/Framer）
- 朱红/亮红 CTA（Netflix/YouTube/Reddit）+ 自定义衬线正文（Pentagram/McKinsey/Burberry）
- 4px 零圆角工程网格（IBM/BMW）+ 三层暖阴影大圆角（Airbnb/Duolingo）
- 白绿克制科技感（OpenAI/Supabase/Robinhood）+ Material 动态圆角彩层（Google/Canva）
- 纯黑极简（Apple/X/Uber/Nike）+ 橙黑工具箱色（GitLab/Cloudflare/Framer）
- Facebook 蓝（Meta/LinkedIn）+ 深蓝信任商务（Booking.com/PayPal/Calendly）

暗色原生品牌之间也要保持区分：Linear 靠六级背景层级，Spotify 靠内容即色彩，
Netflix 靠红色极克制，Discord 靠 Blurple 发光 + 肥大圆角，X 靠城市公告板式编码流，
Uber 靠黑底白字出行极简——把任意两家的暗色语言混在一起会失去各自记忆点。

## 参考文件

- `companies/index.md` — 全量快速检索总表（71 家）+ 分组领域索引 + 说明。
- `companies/01-apple.md` … `companies/29-discord.md` — 原 30 家定本
  （Netflix 重复收录已合并，保留 29 家独立公司，内容逐字保留）。
- `companies/30-google.md` … `companies/71-ikea.md` — 新增 42 家顶级公司官网。
  - 软件/互联网公司（30–68）：含「HTML 板块 · 官网与营销页」+「UI/UX 板块 · 产品界面」。
  - 实体品牌公司（69–71：Nike、Lego、IKEA）：含「官网板块 · 数字化品牌体验」。

需要更系统的判断方法与完整设计流程（四问校准、宣告、无障碍、完成清单）时，
可（可选增强）查找并加载 TUAN Design 手册（`tuan-design` / `tuan-design-v2`）
与 `premium-design` 技能配套使用；本库不依赖它们，单包即可独立完成风格起点
选择与页面落地。