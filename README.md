# Qingxiaotuan Agent CLI (青小团)

> **"Model + Harness = Agent."** — Split "how to think" from "how to run it safely," and hand you both keys.
> A safety-first, model-agnostic, pure-Python AI Agent harness. `v0.2.018` · MIT · Python ≥ 3.10

> ### Positioning: a safety-first agent — without sacrificing developer experience
>
> **Safety is a priority, not an option** — and **interruption is not a substitute for safety**.
>
> - **Safety first**: dangerous commands are blocked *before* they run (blast-radius preview → hard redline → multi-stage confirmation). Every write is journaled in a transactional ledger for exact `/undo`. YOLO mode still cannot cross a hard redline.
> - **Developer experience preserved**: file reads/writes, routine `git` operations, package installs, test runs and linters are scored `none` — **zero confirmation, zero blocking** (`safety_engine.is_benign_dev_command`). Only genuinely dangerous actions escalate to advice or blocking.
> - **Reproducible measurements**: our goal is "fewer dangerous commands slip through, fewer benign commands nag," and any number we publish **must be reproducible by a third party** — no unverifiable absolute promises. Benchmarks live in [`bench/`](bench/README.md): 10k adversarial bash/generic samples + 5k PowerShell samples + 2,310 hand-crafted bypass payloads (with consequence-level disaster assertions). **One command, `qxt safe bench`, reproduces everything locally** (no network, no model); `qxt safe report` emits a self-contained HTML security report. Current code measured (2026-09): adversarial 10k → block recall 100% / flag recall 100% / false-positive 1.87% / bypass 0; PowerShell 5k → accuracy 100% / misses 0 / false positives 0; bypass matrix 2,310 payloads → bypass 0 / false positive 1 / disaster-intent classes 100% blocked. Some deliberately fail-closed conservative escalations remain (e.g. `nc` port probes, `tar|ssh` exfil-shaped payloads) and explain the false-positive figures; please re-run locally.
> - **Ecosystem interop**: we don't rebuild ecosystems — we **reuse what Claude Code / Hermes Agent already accumulated** on this machine (skills, named agents, memory, SOUL persona, MCP configs). `qxt ecosystem` moves assets both ways in one command; `qxt ecosystem link` mounts qxt back into them over MCP. One harness, three ecosystems' worth of assets.

**Language:** **English** · [简体中文](README_zh-CN.md) · [繁體中文](README_zh-GAT.md) · [日本語](README_ja.md) · [한국어](README_ko.md) · [Español](README_es.md) · [Português (Brasil)](README_pt-BR.md) · [Français](README_fr.md) · [Deutsch](README_de.md) · [Русский](README_ru.md)

**Must-reads:** [SECURITY.md](SECURITY.md) · [CHANGELOG.md](CHANGELOG.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · `qxt models list-providers`

---

## TL;DR

The core idea: **the model does the thinking; the harness makes that thinking run safely and controllably.** Qingxiaotuan decouples "the model" from "the host": hot-swap across many providers, run fully offline, roll back destructive mistakes, and see the blast radius *before* the command fires. It aims to be a reasonably neutral, self-hostable terminal agent host — not a captive wrapper around a single vendor.

**What it is not**: a captive wrapper around one model (hot-swap / self-host / offline, your call); an IDE sidekick (it's a plain terminal tool, drivable via ACP by VSCode/Zed/JetBrains); or a single leaky abstraction (microkernel plugin architecture for builders, plus a one-shot `setup` for everyone else).

---

## Why it's different

| The thing | Details |
|---|---|
| 🛡️ **Safety-first** | Four gates: static risk scoring, blast-radius pre-blocking, YOLO-redline floor, transactional ledger with exact `/undo` |
| 🎯 **Developer experience** | Benign dev commands pass with zero confirmation, `/undo` has your back, 40+ slash commands, `qxt safe allow` for explicit opt-outs, YOLO to skip repeat prompts |
| 🔌 **Model-agnostic** | 51 providers + local Ollama + runtime hot-swap + automatic routing (`router.*`) |
| 🧠 **Three main loops** | ReAct / Planner-Execute / DevLoop — pluggable; one kernel, different "thinking rhythms" |
| 🔧 **Microkernel** | One-line `@plugin`, service registry, append-only event bus, hook middleware |
| 🗂️ **Memory** | SQLite FTS5 + session event stream; three-tier memory, `/undo`, checkpoint, replay, Trajectory export |
| 🧩 **Ecosystem** | MCP + ACP + **Claude Code / Hermes Agent interop**: skills / named agents / memory / SOUL / MCP configs move both ways (`qxt ecosystem`), out-of-the-box |
| 🌍 **Ten languages** | zh-CN default, native localization of the whole UI |
| 🐍 **Pure Python** | Large `.py` codebase, MIT-licensed |

---

## Straight answers

**Q: "Is this really independent? How much is self-developed?"**
Two things, kept separate. **The code is self-written**: the kernel and the vast majority of capabilities (`core/`, `runtime/`, `arch/`, `tools/`, `ports/`…) are built line-by-line in Python, aligned to external protocols for interoperability only. **The ideas and design are borrowed** — this project deliberately fuses concepts from known agent projects, and that's worth saying plainly rather than hiding. The one part where even the *style* is kept is the `--tui` terminal skin, which intentionally follows **Kimi Code's** signature interaction feel and palette (`#4FA8FF` primary, the moon-phase spinner, the two-line status bar), credited in [NOTICE](NOTICE). The full attribution list is in [Inspiration & attribution](#inspiration--attribution). **Code is ours; ideas are shared.**

**Q: Why does it block me before I run commands?**
Feature, not bug. Dangerous commands ask first; YOLO still respects hard redlines. If it's too chatty, `qxt safe allow <cmd>` to allowlist — don't disable safety.

**Q: So when I'm blocked, am I stuck?**
No. Every block/confirm carries **command-aware safe alternatives** (`qxt safe suggest <cmd>` queries any time): `git push --force` → `--force-with-lease`, `rm -rf` → trash/recycle recipe, `curl | sh` → "download and review first". We don't just stop you — we take you to the safe way to get it done.

**Q: What can `/undo` actually roll back?**
Every **write** that goes through the ledger: a single file, a single step, a whole turn. Under the hood it's the transactional ledger + diff `reverse_transform` + checkpoint snapshots. Not a miracle cure, but it turns a slip from a guaranteed loss into a probable save.

**Q: Will it read my private files?**
Tool scope is constrained by a domain allow-list, egress is gated to prevent exfiltration, and secrets are redacted from output. Defaults and what you can tune are in [SECURITY.md](SECURITY.md).

**Q: Fully offline?**
`qxt models local` to probe, `/offline` to manage Ollama. No internet, no problem.

**Q: Can I write my own tools/plugins?**
Yes — `@plugin` metadata, `activate(kernel)` + `kernel.provide(...)` / `kernel.require(...)`. Three steps:

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

## Inspiration & attribution

Qingxiaotuan isn't born from nothing — its design explicitly builds on the following known agent projects and protocols. We list them plainly (and annotate the original sources in code comments where relevant):

| Source | What we borrowed |
|---|---|
| **DeepSeek Harness / Cordis** | Microkernel + service registry + append-only event bus architecture (annotated in `core/kernel.py`) |
| **Kimi Code** | Terminal TUI interaction feel & palette (see [NOTICE](NOTICE)) |
| **Claude Code** | `/` slash-command system, named agents (`.claude/agents`-compatible), Goal mode, DevLoop — interface alignment |
| **Hermes Agent** | Three-tier memory, skill self-evolution loop, SOUL identity, self-registering tools, cron semantics — aligned; `qxt ecosystem` two-way-syncs memory/skills/SOUL with it |
| **ACP (Agent Client Protocol)** | As client/server, aligned message & handshake semantics so an IDE can drive Qingxiaotuan |
| **MCP (Model Context Protocol)** | As a client, aligned protocol to plug into the tools ecosystem |
| **OpenAI / Anthropic / Google etc. APIs** | Provider adapters implemented per official REST semantics — protocol adaptation only, no internal replication |

> Boundary: **code** is self-developed; **protocols/interfaces** are aligned; **ideas/designs** are borrowed and fused. Where concrete implementation detail is referenced, it's declared in the source comments and [NOTICE](NOTICE).

---

## Quick start

```bash
# 1) Install (—[dev] is the full stack; drop to [openai]/[mcp] if you only need APIs)
git clone <this repo> && cd qingxiaotuan-agent-cli
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# 2) Point at a provider (14 built-in profiles: deepseek / groq-free / siliconflow-free / ollama…)
qxt setup
# or by hand: ~/.qingxiaotuan/config.yaml
#   model.provider: deepseek
#   model.model: deepseek-chat
#   model.api_key_env: DEEPSEEK_API_KEY      # keys never in plaintext

# 3) Chat
qxt
# or a smoketest:
qxt --print run "Hi, describe yourself in one sentence."
```

---

## The command surface: 36 core subcommands + slash commands

| Command | What it's for |
|---|---|
| `qxt` | Interactive TUI (Kimi Code skin) |
| `qxt setup` / `qxt models` | Configure providers / list 51 providers & 1100+ models |
| `qxt models update` | Update the model/provider catalog locally: merge the built-in lists into `~/.qingxiaotuan/models_catalog.json` (offline, preserves user-added entries; `--check` reports diffs only, `--background` runs async) |
| `qxt agent` | Named agents (`.claude/agents`-compatible, 3-tier discovery) |
| `qxt acp` | Run an ACP server so VSCode / Zed / JetBrains can drive you |
| `qxt ecosystem` | **Ecosystem interop**: `scan` probes Claude Code / Hermes; `import` pulls their skills/agents/memory/SOUL/MCP configs into qxt; `export` pushes back; `link` mounts qxt into them over MCP; `serve` runs the MCP server (see [docs/ecosystem_bridge.md](docs/ecosystem_bridge.md)) |
| `qxt cron` | Scheduled background tasks |
| `qxt doctor [--compact]` | Health check (add `--compact` for context-compaction survival self-check) |
| `qxt dev codedev ...` | Code-dev subsystem (retrieval / verification / decomposition) |

Slash commands you'll live in: `/plan` · `/model` · `/undo`·`/impact` · `/swarm` · `/log`·`/stats`·`/cost`·`/budget`·`/goal`·`/sandbox`·`/offline`·`/verify`·`/audit`·`/more`·`/help` — full list via `Ctrl-G` in the TUI.

---

## Ecosystem interop: Claude Code / Hermes Agent out of the box

Beyond "safety-first" and "model-agnostic", the third leg is: **don't rebuild ecosystems — reuse what the other agent ecosystems already accumulated.** Skills (the SKILL.md open standard), named agents (`.claude/agents`), memory & persona (Hermes' `MEMORY.md` / `USER.md` / `SOUL.md`), context files (`AGENTS.md` / `CLAUDE.md`) and MCP server configs are structurally near-identical across the three — qxt bridges them:

```bash
qxt ecosystem scan                        # probe Claude Code / Hermes + their assets (read-only)
qxt ecosystem import all                  # pull both sides' skills/agents/memory/SOUL/MCP configs into qxt
qxt ecosystem export skills --to claude   # qxt skills → .claude/skills (Hermes: --to hermes)
qxt ecosystem link                        # reverse-mount: Claude Code/Hermes call qxt over MCP
```

- **Automatic in-session**: skills Claude Code or Hermes already installed are usable in qxt immediately (`~/.claude/skills`, `~/.hermes/skills` are on the search path); `qxt ecosystem serve` exposes qxt as an MCP server so Claude Code / Hermes sessions gain `qxt_*` tools (memory search/write, skill list/read, headless task dispatch).
- **Delegate, don't migrate**: `claude_code_run` / `hermes_run` tools hand tasks to the other agent's full native environment (their own config, memory, skills, MCP).
- Full doc: [`docs/ecosystem_bridge.md`](docs/ecosystem_bridge.md) (format map / security design / layout).

---

## Three main loops, one steady hand

- **ReActLoop** — think → act → observe, the default rhythm.
- **PlannerExecuteLoop** — a stronger model plans, a cheaper one executes (`router.*` supports plan/execute compartmentalization). A token-saving pattern.
- **DevLoop** — write-verify-heal: `/verify` auto-detects the project (Python/Node/Rust/Go), infers test commands, and self-heals for up to N rounds.

---

## The safety model: four gates + ledgered undo

1. **Static scoring** — every shell command scored `none→critical` by `safety_engine.score()`, with indirect-expansion unfolding (IFS, `$VAR`, command substitution, ANSI-C/octal/hex escapes, PowerShell Base64, NFKC; ≤32 recursion).
2. **Blast-radius pre-block** — you see what it'll touch *before* it fires (`--impact`).
3. **YOLO-redline floor** — YOLO kills per-step confirmations but **cannot** touch hard redlines (recursive `rm`, force-push, `chmod -R 000 /`… never auto-run).
4. **Transactional ledger** — every write has an audit trail; `/undo` restores via diff `reverse_transform` + snapshots.

Rules always resolve `deny > ask > allow`. Whitelist with `qxt safe allow <cmd>`; never disable safety to save clicks.

---

## Security benchmarks: reproducible with one command

`qxt safe bench` packages the three reproducible suites into one command (fully local, no model — any third party can re-run them as-is):

- **Adversarial corpus** `bench/safety_bench_10k.py` — 10,000 bash/generic commands (seeded 20260906, reproducible); reports block recall / flag recall / false-positive rate / bypasses.
- **PowerShell corpus** `bench/bench_powershell_safety.py` — 5,000 samples (2,300 dangerous / 2,700 benign); reports accuracy / misses / false positives.
- **Bypass matrix** `bench/bypass_matrix.py` — 2,310 hand-crafted adversarial payloads; beyond pattern matching, it asserts **per disaster-consequence class** whether every class of catastrophic intent was actually blocked.

```bash
qxt safe bench                 # full run (~3 min)
qxt safe bench --quick         # quick self-check (~30 s)
qxt safe bench --check         # compare vs archive; exit 1 if numbers regressed (gate)
qxt safe report                # self-contained HTML security report (shareable)
qxt safe report --release      # RELEASE: numbers + timestamp + git commit bound (no stale numbers)
```

Measured on current code (2026-09-19, reproducible via `qxt safe bench`):

| Suite | Size | Core metric | Bypasses | False positives |
|---|---|---|---|---|
| Adversarial | 10,000 | block recall 100% · flag recall 100% · FP 1.87% | 0 | — |
| PowerShell | 5,000 | accuracy 100% · misses 0 | 0 | 0 |
| Bypass matrix | 2,310 | disaster-intent classes 100% blocked | 0 | 1 |

Caveat: the bypass matrix is deliberately fail-closed and keeps a few conservative escalations (`nc` Unicode-variant probes, `tar|ssh` exfil-shaped payloads), which produce "benign-but-flagged" false positives; the 1.87% FP in the adversarial suite comes from the same conservatism. Numbers are authoritative as re-run locally with `qxt safe bench`.

**CI numbers gate**: the `safety-benchmarks` job in `.github/workflows/security-ci.yml` re-runs all three suites on every push and compares against the committed archive — any regression (bypasses, a disaster class no longer fully blocked, a clear FP rise) **fails CI**. The archive `bench/security-bench.json` corresponds 1:1 to the README table. 

---

## Where your ideas go to run

- **Memory** — three tiers (user/project/session) + SQLite FTS5 (trigram), auto-degrades to plaintext if unavailable.
- **Subagents** — typed delegation (general-purpose / explore / plan / coder), isolated subagents, concurrent workers, Swarm for sharding long tasks.
- **Cron & background** — `qxt cron start --detach`; headless autonomy.
- **Hooks** — `PreToolUse` can `block` or rewrite `args` (`hooks.allow_edit_args`) — a big seam for builders.
- **Observability** — `/stats`·`/audit`·`/impact`·`/bench`·`/cost`; cost on the table.
- **crypto** — AES-GCM(AEAD) with `cryptography`, else an HMAC-SHA256 stream-cipher fallback; missing-MAC / tampered `open()` always fails closed.

---

## Dev & contract

```bash
python -m pytest tests/ -q        # large suite
python -m mypy qingxiaotuan       # typing gate
qxt --print run "Hi, one line."   # smoke
```

- **i18n discipline**: README_zh-CN is the authoritative master; every locale is a vivid, zero-drift localization — **no mechanical translation.**
- **Version**: `v0.2.018` (0.x / Beta); breaking changes get a minor-version heads-up + migration notes.
- **Deep dive**: engine signatures & a step-by-step tool walkthrough live in the appendix of `README_zh-CN.md`.

---

## License & links

- **License**: MIT (use/modify/redistribute freely, keep the notice)
- **Read these**: [SECURITY.md](SECURITY.md) · [CHANGELOG.md](CHANGELOG.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [NOTICE](NOTICE)

> Want "open-box, closed, vendor experience"? Plenty of others do that. Want to **run on your own models, keep the control, and be able to take it back when things go sideways**? The keys are right here.