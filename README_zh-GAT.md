# 青小團 · Tuan-CLI

> **「Model + Harness = Agent」** —— 把「會思考」跟「能穩穩跑」拆開，兩把鑰匙都交到你手上。
> 一個安全第一、模型不挑、純 Python 的 AI Agent Harness。`v0.2.018` · MIT · Python ≥ 3.10

**語言/Language:** [English](README.md) · [简体中文](README_zh-CN.md) · **繁體中文** · [日本語](README_ja.md) · [한국어](README_ko.md) · [Español](README_es.md) · [Português (Brasil)](README_pt-BR.md) · [Français](README_fr.md) · [Deutsch](README_de.md) · [Русский](README_ru.md)

**動手前先翻：** [SECURITY.md](SECURITY.md)（威脅模型）· [CHANGELOG.md](CHANGELOG.md)（版本紀律）· [ARCHITECTURE.md](ARCHITECTURE.md)（架構）· `qxt models list-providers`

---

## 一句話

別家賣的是「把一個模型套殼」，青小團給的是「一副能隨時換腦的殼」。模型熱切換、51 家供應商、本地離線全都行；下錯指令能撤、動手前先算影響半徑；微核心插件隨你插。**模型負責想，它負責穩。**

**它不是什麼**：不是某家模型的禁臠（熱切換、自託管、離線隨你）；不是 IDE 的附庸（標準終端工具，可被 ACP/IDE 驅動）；不是一層套娃（給開發者的是微核心插件架構，給一般人的是一條 `setup`）。

---

## 它憑什麼不同

| 給你的 | 頂到哪 |
|---|---|
|  **安全第一** | 四道閘：靜態評分、影響半徑預攔截、YOLO 紅線兜底、交易日誌 `/undo` 精準回滾 |
|  **模型不挑** | 51 家供應商 + 本地 Ollama + 熱切換 + 自動路由（`router.*`） |
|  **三種主迴圈** | ReAct / Planner-Execute / DevLoop 可插拔；一個核心、多種「思考節奏」 |
|  **微核心** | 一行 `@plugin`、服務註冊表、append-only 事件總線、hook 中介——愛玩的人有福了 |
|  **記憶** | SQLite FTS5 + 會話事件流；三層記憶、`/undo`、checkpoint、replay、Trajectory 匯出 |
|  **生態系** | MCP + ACP：能插工具、也能被 IDE 驅動 |
|  **十種語言** | 預設正體中文用戶開箱即用，介面整個在地化 |
|  **純 Python** | ~412 個 `.py` / ~7.9 萬行 / 41 包 / 36 插件，MIT |

---

## 攤開來講

**Q：它真的是「獨立自研」嗎？不遮不掩說清楚。**
兩件事分開看。**程式碼**是自研的：核心與絕大部分能力（`core/`、`runtime/`、`arch/`、`tools/`、`ports/` 等）從架構到實作逐行手寫，只對相關**協定**做介面對齊。但**理念與設計**確實大量借鑒、融合了已知的 Agent 專案——這沒什麼好遮掩的，恰恰是站在前人肩膀上。**程式碼是清的，理念是借的**。唯一連「風格」都保留的部分是終端 TUI——`--tui` 的操作手感與配色刻意沿用 Kimi Code 的招牌風格（`#4FA8FF` 主色、moon 旋轉、兩行狀態列），因為「手感好就不瞎折騰」，版權與署名見 [NOTICE](NOTICE)。完整受借鑒清單見下文[受借鑒與融合](#受借鑒與融合)。

**Q：幹嘛我下指令前總攔我？**
是功能不是 bug。危險指令預設要確認；YOLO 撞上硬紅線一樣拒。嫌囉嗦就 `qxt safe allow <cmd>` 白名單放行，別關安全。

**Q：/undo 到底撤得掉啥？**
所有進交易日誌的**寫入**：單檔、單 step、整段。底層 = 交易日誌 + diff `reverse_transform` + checkpoint 快照。不是萬靈丹，但把「一時手滑 = 穩輸」變成「大概撈得回來」。

**Q：怕它碰我隱私檔？**
權限策略用 domain allow-list 圈住工具範圍；網路出口有管控防外帶；輸出會對你金鑰脫敏。安全是它的日常 KPI。

**Q：想全離線？**
`qxt models local` 偵測、`/offline` 管 Ollama。沒網照跑。

**Q：能寫自己的工具/插件？**
當然。`@plugin` 宣告中繼資料，`activate(kernel)` 裡 `kernel.provide(...)` / `kernel.require(...)`，三步搞定：

```python
from ..core.kernel import Kernel, Plugin

@plugin("my.tool", provides=["loop_registry"])
class MyTool(Plugin):
    def activate(self, kernel):
        def _handler(ctx, query: str) -> str:
            return f"echo: {query}"
        kernel.provide("tools.my", _handler)
```

---

## 版本號與倉庫歷史（透明披露）

**為什麼版本號停在 `0.x`？** Tuan-CLI 的版本號遵循 [SemVer](https://semver.org/) 語義：`0.x` 表示 **API 尚未凍結**——破壞性變更會提前預告並提供遷移提示（見 [VERSION_POLICY.md](VERSION_POLICY.md)）。**版本號反映的是介面穩定度，不是功能完成度**：就功能面而言，目前 `0.2.x` 的實際能力對標同類 Agent CLI 競品的 **2.x 級功能完整度**——安全攔截/交易回滾、模型無關熱切換（51 家供應商 + 本地 Ollama）、三種主迴圈、微核心外掛架構、三層記憶、生態互操作（MCP/ACP/Claude Code/Hermes 三方橋）、子代理與 Swarm、cron 與背景任務、Goal 模式與精確權限等均已落地並配有測試。一句話：**功能成熟度已到「2.x」，版本號停在「0.x」是因為我們堅持 API 凍結後才升 1.0**，而不是能力不足。

| 版本號語義 | 說明 |
|---|---|
| `0.x`（當前） | API 未凍結：破壞性變更預告 + 遷移提示；功能完整度對標競品 2.x |
| `1.0`（計畫） | API 凍結後發布，此後版本號直接反映介面穩定性 |

**Git 歷史說明（開源透明披露）**：本倉庫的 Git 提交歷史於 **2026-09-26 因本地倉庫損壞而重建**，此前逐次提交的演進記錄已不可追溯（舊 `.git` 物件遺失）。目前程式碼從架構到實作完整可審查；2026-09-26 之前的功能演進請以 [CHANGELOG.md](CHANGELOG.md) 的版本記錄為準（版本紀律不受影響）。我們選擇如實披露這一點，不修飾、不隱藏。

---

## 受借鑒與融合

青小團不是從石頭裡蹦出來的，設計上明確借鑒、融合了以下幾種「已知 Agent 專案與協定」，在此如實列出（並盡可能在原始碼註解標註出處）：

| 借鑒對象 | 借鑒了什麼 |
|---|---|
| **DeepSeek Harness / Cordis** | 微核心 + 服務註冊表 + append-only 事件總線的架構理念（`core/kernel.py` 有註解標註） |
| **Kimi Code** | 終端 TUI 的操作手感與配色風格（見 [NOTICE](NOTICE)） |
| **Claude Code** | `/` 斜線指令體系、命名 Agents（`.claude/agents` 相容）、Goal 模式、DevLoop 等互動範式的介面對齊 |
| **ACP（Agent Client Protocol）** | 作為 server/client 對齊其訊息與握手語義，讓 IDE 能驅動青小團 |
| **MCP（Model Context Protocol）** | 作為 client 對齊其協定，接上工具生態 |
| **OpenAI / Anthropic / Google 等廠商 API** | provider 配接器按官方 REST 語義實作，只做協定配接、不復刻內部實作 |

> 邊界：**程式碼**為自研；**協定/介面**做對齊；**理念/設計**做借鑒與融合。若某處引用了具體實作細節，會在對應原始碼註解與 [NOTICE](NOTICE) 中聲明。

---

## 快速上手

```bash
git clone <此倉庫> && cd tuan-cli
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

qxt setup
# 或手動：~/.qingxiaotuan/config.yaml
#   model.provider: deepseek
#   model.model: deepseek-chat
#   model.api_key_env: DEEPSEEK_API_KEY      # 金鑰不寫明文

qxt            # 開聊
qxt --print run "你好，一句話介紹你自己"
```

---

## 指令面：105 個子指令 + 46 個斜線指令

| 指令 | 用途 |
|---|---|
| `qxt` | 互動 TUI（Kimi Code 皮） |
| `qxt setup` / `qxt models` | 配供應商 / 列出 51 家供應商 & 1100+ 模型 |
| `qxt agent` | 命名 Agents（相容 `.claude/agents`，三層發現） |
| `qxt acp` | 開 ACP server，讓 VS Code / Zed / JetBrains 來驅動你 |
| `qxt cron` | 定時背景任務 |
| `qxt doctor` / `qxt bench` | 體檢 / 跑分 |
| `qxt arch demo` | 一鍵驗證五層架構插件 |

常用斜線指令：`/plan` · `/model` · `/undo`·`/impact` · `/swarm` · `/log`·`/stats`·`/cost`·`/budget`·`/goal`·`/sandbox`·`/offline`·`/verify`·`/audit`·`/more`·`/help`——TUI 內按 `Ctrl-G` 看全部。

---

## 三種主迴圈，一樣的穩

- **ReActLoop**：想→做→看，預設節奏。
- **PlannerExecuteLoop**：強模型拆計畫、便宜模型打執行（`router.*` 支援分艙）。省點數大師。
- **DevLoop**：自動寫→測→自癒（`/verify` 自動認出 Python/Node/Rust/Go，推斷測試指令、自修最多 N 輪）。

## 安全模型：四道閘 + 記帳撤回

1. **靜態評分**：`safety_engine.score()` 判 `none→critical`，含間接呼叫展開（IFS、`$VAR`、指令替換、ANSI-C/八/十六進轉義、PowerShell Base64、Unicode NFKC，遞迴 ≤32 層）。
2. **影響半徑預攔**：動手前先看會碰到啥（`--impact`）。
3. **YOLO 紅線兜底**：YOLO 能關逐條確認，**關不掉**硬紅線（遞迴 `rm`、force-push、`chmod -R 000 /`…永不可自動執行）。
4. **交易日誌**：寫入全記帳，`/undo` 用 diff `reverse_transform` + 快照精準還原。

規則恆為 `deny > ask > allow`。用 `qxt safe allow <cmd>` 白名單，別拿安全換點擊。

---

## 各種開腦洞

- **記憶**：三層（使用者/專案/會話）+ SQLite FTS5（trigram），不可用自動降級純文字。
- **子代理**：型別化委派（general-purpose / explore / plan / coder）+ 隔離子代理 + 併發 Worker + Swarm 切碎長任務。
- **Cron & 背景**：`qxt cron start --detach`；headless 也能自己跑。
- **Hooks**：`PreToolUse` 可 `block` 或改寫 `args`（`hooks.allow_edit_args`）。
- **可觀測**：`/stats`·`/audit`·`/impact`·`/bench`·`/cost`，成本攤上檯面。
- **crypto**：v2 夠硬——有 `cryptography` 走 AES-GCM(AEAD)，否則 HMAC-SHA256 串流加密，`open()` 缺 MAC/被竄改一律 fail-closed。

---

## 開發 & 契約

```bash
python -m pytest tests/ -q        # 2500+ 用例
python -m mypy qingxiaotuan       # 型別門檻
qxt --print run "你好，一句話。"   # 冒煙
```

- **多語文檔紀律**：以 `README_zh-CN.md` 為權威母本，全部 10 份同步；對譯求「生動、零漂移」，**禁機械直譯**。
- **規模**：~412 `.py` / ~7.9 萬行 / 41 包 / 插件 36。
- **版本**：`v0.2.018`（0.x/Beta）；破壞性變更小版本先預告 + 給遷移提示。
- **深挖**：九大引擎簽名、新增工具走查，附錄在 `README_zh-CN.md` 尾段。

---

## 帳戶登入：GitHub / Apple / DeepSeek（可選 · 預設離線）

- 不登入即可完整離線使用；登入只是可選增強層。
- `qxt login` / `qxt login github` / `qxt logout` / `qxt whoami`。
- 憑證寫入 `~/.qingxiaotuan/auth-config.toml` 或環境變數 `QXT_GITHUB_*` / `QXT_APPLE_*` / `QXT_DEEPSEEK_*`（環境變數優先）。
- OAuth 回調預設 `http://127.0.0.1:8765/callback`；`auth.json` 為明文令牌，請保護主目錄、公共機器用完登出。
- 詳見 README_zh-CN.md（母本）與 README.md。

---

## License & 相關閱讀

- **License**：MIT（自由使用/修改/散佈，保留版權聲明）
- **必讀**：[SECURITY.md](SECURITY.md) · [CHANGELOG.md](CHANGELOG.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [NOTICE](NOTICE)

> 要「開箱即用、閉源、被綁在特定廠商」的是別家；要「跑在自己的模型上、拿得到控制權、出事能撤回」——鑰匙就在這。