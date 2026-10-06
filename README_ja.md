# 青小团 / Tuan-CLI

> **「Model + Harness = Agent」** —— 「考えること」と「安全に走らせること」を分離して、両方の鍵をあなたに。
> 安全第一・モデル非依存・純 Python の AI Agent Harness。`v0.2.018` · MIT · Python ≥ 3.10

**言語/Language:** [English](README.md) · [简体中文](README_zh-CN.md) · [繁體中文](README_zh-GAT.md) · **日本語** · [한국어](README_ko.md) · [Español](README_es.md) · [Português (Brasil)](README_pt-BR.md) · [Français](README_fr.md) · [Deutsch](README_de.md) · [Русский](README_ru.md)

**手に取る前に：** [SECURITY.md](SECURITY.md)（脅威モデル）· [CHANGELOG.md](CHANGELOG.md)（バージョン規律）· [ARCHITECTURE.md](ARCHITECTURE.md)（アーキテクチャ）· `qxt models list-providers`

---

## ひとことで

他社は「モデルに殻を被せる」。青小团は違う——**脳みそ換え放題のボディ**を渡します。51 社のプロバイダをホットスワップ、完全オフライン動作、やらかした操作は巻き戻せて、実行する**前**に影響範囲を見せてくれます。**考えるのがモデル、それを支えるのがこいつ。**

**これは何でもない**：特定モデルの囲い込みではない（ホットスワップ・自前ホスト・オフライン、自由自在）；IDE の付属物ではない（標準ターミナルツール、ACP 経由で VSCode/Zed/JetBrains に駆動される）；一重の頼りない抽象でもない（開発者向けマイクロカーネル + 一般ユーザー向け一発 `setup`）。

---

## なにが違うのか

| こいつ | どこまでやる |
|---|---|
| 🛡️ **安全第一** | 四重ゲート：静的リスク判定、影響範囲の事前ブロック、YOLO レッドライン、トランザクション台帳の精密 `/undo` |
| 🔌 **モデル非依存** | 51 プロバイダ + ローカル Ollama + ホットスワップ + 自動ルーティング（`router.*`） |
| 🧠 **三つのメインループ** | ReAct / Planner-Execute / DevLoop を差し替え可能。一つのカーネル、複数の「思考リズム」 |
| 🔧 **マイクロカーネル** | 一行 `@plugin`、サービスレジストリ、追記専用イベントバス、hook ミドルウェア |
| 🗂️ **メモリ** | SQLite FTS5 + セッションイベントストリーム；3 層メモリ、`/undo`、checkpoint、replay、Trajectory 出力 |
| 🧩 **エコシステム** | MCP + ACP — ツールを刺すも良し、IDE に駆動されるも良し |
| 🌍 **10 言語** | デフォルトは翻訳品質込みの日本語UIにも対応、機能ごとローカライズ |
| 🐍 **純 Python** | 約 412 `.py` / 約 7.9 万行 / 41 パッケージ / 36 プラグイン、MIT |

---

## ぶっちゃけ

**Q: これって本当に「独立自研」？隠し事ない？**
二つに分けて答えます。**コード**は自前実装：カーネルと大半の機能（`core/`、`runtime/`、`arch/`、`tools/`、`ports/` など）は Python でアーキテクチャから一行ずつ手書きし、相互運用のためだけに外部**プロトコル**へ合わせています。ただし**アイデアと設計**は、既知の Agent プロジェクトから明確に借りて融合したものです——隠すことではなく、巨人の肩の上に立つことです。**コードは自分のもの、アイデアは借りたもの**、と分けて見てください。唯一「スタイル」まで保ったのは、`--tui` のターミナル UI——Kimi Code の看板スタイル（`#4FA8FF` 基調、ムーンフェイズスピナー、二行ステータスバー）を意図的に踏襲しています（「手触りがいいなら再発明しない」）。クレジットは [NOTICE](NOTICE)。完全なリストは下の[着想と帰属](#着想と帰属)。

**Q: なんでコマンドの前に止まるの？**
仕様、バグじゃない。危険なコマンドは確認を求める；YOLO でもレッドラインは硬く守る。煩わしければ `qxt safe allow <cmd>` で許可リスト化——安全を無効化するんじゃなく。

**Q: `/undo` で実際どこまで戻せる？**
台帳に載る**書き込み**全部：単一ファイル、単一 step、ターン全体。中身はトランザクション台帳 + diff `reverse_transform` + checkpoint スナップショット。万能じゃないけど、「やらかした → 確実に損」を「多分取り返せる」に変える。

**Q: プライベートファイル読まれない？**
権限ポリシーは domain allow-list でツール範囲を制限；外部送信は防がれ、出力の秘密鍵はマスク。

**Q: 完全オフラインは？**
`qxt models local` で検出、`/offline` で Ollama 管理。ネットなしでも動く。

**Q: 自前のツール / プラグイン書ける？**
もちろん。`@plugin` でメタデータ宣言、`activate(kernel)` で `kernel.provide(...)` / `kernel.require(...)`。3 ステップ：

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

## バージョン番号とリポジトリ履歴（透明な開示）

**なぜバージョン番号は `0.x` のままなのか？** Tuan-CLI のバージョン番号は [SemVer](https://semver.org/) に従います。`0.x` は **API がまだ凍結されていない**ことを意味します——破壊的変更は事前に告知し、移行ヒントを提供します（[VERSION_POLICY.md](VERSION_POLICY.md) 参照）。**バージョン番号はインターフェースの安定度を示すものであり、機能の完成度を示すものではありません**。機能面では、現在の `0.2.x` の実力は同種の Agent CLI 競合製品の **2.x 級の機能完成度**に相当します——安全ゲート/トランザクション式ロールバック、モデル非依存のホットスワップ（51 社のプロバイダー + ローカル Ollama）、3 つのメインループ、マイクロカーネルプラグインアーキテクチャ、3 層メモリ、エコシステム相互運用（MCP/ACP/Claude Code/Hermes 三方ブリッジ）、サブエージェントと Swarm、cron とバックグラウンドタスク、Goal モードと精密な権限制御——これらはすべて実装済みでテストも揃っています。一言で言えば：**機能の成熟度は「2.x」に達しているが、API 凍結後に 1.0 へ上げる方針を守っているため、バージョン番号は「0.x」のまま**なのです。

| バージョン番号の意味 | 説明 |
|---|---|
| `0.x`（現在） | API 未凍結：破壊的変更の告知 + 移行ヒント；機能完成度は競合 2.x 相当 |
| `1.0`（予定） | API 凍結後にリリース。以降のバージョン番号はインターフェース安定度を直接反映 |

**Git 履歴の説明（オープンソースとしての透明開示）**：本リポジトリの Git コミット履歴は **2026-09-26 にローカルリポジトリの破損により再構築**されました。それ以前の逐次コミットの変遷記録は遡れません（旧 `.git` オブジェクトは消失）。現在のコードはアーキテクチャから実装まで完全にレビュー可能です。2026-09-26 以前の機能変遷は [CHANGELOG.md](CHANGELOG.md) のバージョン記録を基準としてください（バージョン規律には影響ありません）。私たちはこの点をありのまま開示することを選びます。

---

## 着想と帰属

青小团はゼロからポッと出たわけではありません。設計は明確に以下の「既知の Agent プロジェクトとプロトコル」を参考にしています。隠さずリストアップします（可能な限りソースコメントにも出典を記載します）：

| 参考元 | 何を借りたか |
|---|---|
| **DeepSeek Harness / Cordis** | マイクロカーネル + サービスレジストリ + append-only イベントバスのアーキテクチャ（`core/kernel.py` にコメントあり） |
| **Kimi Code** | ターミナル TUI の操作感と配色（[NOTICE](NOTICE) 参照） |
| **Claude Code** | `/` スラッシュコマンド体系、名前付きエージェント（`.claude/agents` 互換）、Goal モード、DevLoop などのインターフェース整合 |
| **ACP（Agent Client Protocol）** | server/client としてメッセージとハンドシェイクのセマンティクスを整合し、IDE が青小团を駆動できるように |
| **MCP（Model Context Protocol）** | client としてプロトコルを整合し、ツールエコシステムに接続 |
| **OpenAI / Anthropic / Google など各社 API** | provider アダプタは公式 REST のセマンティクスどおりに実装、プロトコル適合のみで内部実装は複製しない |

> 境界：**コード**は自前実装；**プロトコル/インターフェース**は整合；**アイデア/設計**は借用と融合。具体的な実装詳細を参照した箇所は、対応するソースコメントと [NOTICE](NOTICE) で宣言します。

---

## クイックスタート

```bash
git clone <このリポジトリ> && cd tuan-cli
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

qxt setup
# 手動でも：~/.qingxiaotuan/config.yaml
#   model.provider: deepseek
#   model.model: deepseek-chat
#   model.api_key_env: DEEPSEEK_API_KEY      # 鍵を平文で書かない

qxt            # 会話開始
qxt --print run "こんにちは、あなたを一言で自己紹介して"
```

---

## コマンド面：105 サブコマンド + 46 スラッシュコマンド

| コマンド | 用途 |
|---|---|
| `qxt` | 対話型 TUI（Kimi Code スキン） |
| `qxt setup` / `qxt models` | プロバイダ設定 / 51 プロバイダ & 1100+ モデル一覧 |
| `qxt agent` | 名前付きエージェント（`.claude/agents` 互換、3 層ディスカバリ） |
| `qxt acp` | ACP server 起動、VSCode / Zed / JetBrains に駆動される |
| `qxt cron` | 定期バックグラウンドタスク |
| `qxt doctor` / `qxt bench` | 健康診断 / ベンチ |
| `qxt arch demo` | 5 層アーキテクチャを一発検証 |

よく使うスラッシュコマンド：`/plan` · `/model` · `/undo`·`/impact` · `/swarm` · `/log`·`/stats`·`/cost`·`/budget`·`/goal`·`/sandbox`·`/offline`·`/verify`·`/audit`·`/more`·`/help` — 全一覧は TUI で `Ctrl-G`。

---

## 三つのメインループ、変わらぬ安定

- **ReActLoop**：考え→動く→確認、デフォルトのリズム。
- **PlannerExecuteLoop**：強いモデルが計画、安いモデルが実行（`router.*` で compartmentalize 対応）。トークン節約家。
- **DevLoop**：書いて→検証して→自癒。`/verify` がプロジェクト種別（Python/Node/Rust/Go）を自動判定し、テストコマンドを推測して最大 N ラウンド自修。

## 安全モデル：四重ゲート + 台帳式取り消し

1. **静的スコアリング** — 全シェルコマンドを `safety_engine.score()` で `none→critical` 判定、間接入力展開に対応（IFS、`$VAR`、コマンド置換、ANSI-C/8進/16進エスケープ、PowerShell Base64、NFKC；再帰 ≤32）。
2. **影響範囲の事前ブロック** — 実行**前**に触る範囲を見せる（`--impact`）。
3. **YOLO レッドラインの床** — YOLO は逐次確認を消せるが、ハードレッドライン（再帰 `rm`、force-push、`chmod -R 000 /`…）は**絶対に自動実行できない**。
4. **トランザクション台帳** — 書き込みはすべて記録、`/undo` は diff `reverse_transform` + スナップショットで精密復元。

ルールは常に `deny > ask > allow`。`qxt safe allow <cmd>` で許可リスト化を、安全の無効化でクリックを節約しないで。

---

## アイデアを走らせる場所

- **メモリ** — 3 層（ユーザー/プロジェクト/セッション）+ SQLite FTS5（trigram）、使えなければ平文に自動ダウングレード。
- **サブエージェント** — 型付き委譲（general-purpose / explore / plan / coder）、隔離サブエージェント、並行ワーカー、Swarm で長タスクを分割。
- **Cron & バックグラウンド** — `qxt cron start --detach`；ヘッドレスで自律稼働。
- **Hooks** — `PreToolUse` が `block` や `args` 書き換え（`hooks.allow_edit_args`）。
- **可観測性** — `/stats`·`/audit`·`/impact`·`/bench`·`/cost`、コストを机の上へ。
- **crypto** — v2 は堅牢：`cryptography` があれば AES-GCM(AEAD)、無ければ HMAC-SHA256 ストリーム暗号、`open()` で MAC 欠落・改変は常に fail-closed。

---

## 開発 & 規約

```bash
python -m pytest tests/ -q        # 2500+ テスト
python -m mypy qingxiaotuan       # 型ゲート
qxt --print run "こんにちは。"     # スモーク
```

- **多言語文書規律**：`README_zh-CN.md` が権威あるマスター。各言語版は「生き生き、ドリフトなし」のローカライズで、**機械翻訳禁止**。
- **規模**：約 412 `.py` / 約 7.9 万行 / 41 パッケージ / プラグイン 36。
- **バージョン**：`v0.2.018`（0.x/Beta）；破壊的変更はマイナーバージョンで事前告知 + 移行ヒント。
- **深掘り**：九大エンジンのシグネチャと新規ツールのチュートリアルは `README_zh-CN.md` 末尾の付録。

---

## アカウントログイン: GitHub / Apple / DeepSeek（任意 · デフォルトはオフライン）

- ログインなしで完全にオフライン利用できます。ログインは任意の追加機能です。
- `qxt login` / `qxt login github` / `qxt logout` / `qxt whoami`。
- 認証情報は `~/.qingxiaotuan/auth-config.toml` か環境変数 `QXT_GITHUB_*` / `QXT_APPLE_*` / `QXT_DEEPSEEK_*`（環境変数優先）。
- OAuth コールバックは既定 `http://127.0.0.1:8765/callback`。`auth.json` のトークンは平文なので、ホームディレクトリを守り共有機ではログアウトを。
- DeepSeek 公式 API をモデルバックエンドに: `qxt models set deepseek`（公式 API キー, sk-）。
- 詳細は README_zh-CN.md（マスター）と README.md を参照。

---

## License & 関連

- **License**：MIT（自由な使用・変更・再配布、著作権表示を保持）
- **必読**：[SECURITY.md](SECURITY.md) · [CHANGELOG.md](CHANGELOG.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [NOTICE](NOTICE)

> 「箱出しでクローズド、特定ベンダーに縛られたい」なら他にもある。**自分のモデルで走らせ、コントロールを握り、トラブル時は取り戻せる**——鍵はここに。