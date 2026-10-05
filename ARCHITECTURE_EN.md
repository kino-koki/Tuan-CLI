# Tuan-CLI (qxt) Architecture Documentation

> Goal: Help new contributors understand "how the kernel works, how safety blocks, how loops switch, how models route" in 10 minutes, lowering the barrier to onboarding and contribution. Companion commands: `qxt others` (capability catalog), `qxt safe` (safety entry), `qxt models` (models and local LLM).

Tuan-CLI is a **microkernel + plugin** architecture Agent CLI. The kernel itself carries no Agent capabilities, only responsible for "plugin registration / service discovery / lifecycle events"; all capabilities (tools, model adapters, memory, skills, safety, routing, loops) are mounted as **plugins**.

Formula: **The model is responsible for thinking, the Harness (Tuan-CLI) is responsible for making thinking run in a controlled way.**

---

## 1. Five Subsystems Overview

| Subsystem | Responsibility | Core Module | Key Classes / Functions |
| --- | --- | --- | --- |
| **Kernel** | Microkernel: plugin lifecycle, service registry, event bus | `core/kernel.py` | `Kernel` · `Plugin` · `@plugin` · `ServiceContainer` · `MiddlewareEventBus` |
| **Plugin** | Capabilities as plugins: tools / models / memory / safety / loops all registered as services | `core/loop_plugin.py` and various `@plugin` classes | `LoopPlugin` · `provide()` / `require()` |
| **Loop** | Agent main loop strategies: ReAct / Planner-Execute / DevLoop, hot-swappable | `core/loop_provider.py` · `core/loop_plugin.py` | `LoopRegistry` · `ReActLoop` · `PlannerExecuteLoop` · `DevLoopProvider` · `set_current()` |
| **Security** | Redline interception, whitelist pass-through, audit logging, local blacklist override | `ext/safety_engine.py` · `core/whitelist.py` · `core/security_bus.py` · `core/blacklist_override.py` · `ext/security_gate.py` | `is_redline()` · `is_hard_redline()` · `score()` · `WhitelistManager` · `SecurityEventBus` · `emit_command_blocked()` |
| **Router** | Auto-escalate/de-escalate models based on task difficulty, save cost without quality loss, fail-safe | `models/router.py` · `core/auto_route.py` · `models/provider_catalog.py` | `ModelRouter.decide()` · `AutoRouter` · `RouteSession` · `decide_override()` |

---

## 2. Five Subsystems Interaction Diagram

```
                         ┌──────────────────────────────────────────┐
                         │              Kernel (Microkernel)          │
                         │  ServiceContainer  ·  MiddlewareEventBus   │
                         │  provide("loop_provider") / require(...)   │
                         └───────────────┬───────────────┬────────────┘
                                         │ activate plugin│ activate plugin
                       ┌─────────────────┘               └─────────────────┐
                       ▼                                                   ▼
              ┌─────────────────┐                                ┌────────────────────┐
              │  Loop Plugin    │  Register LoopRegistry          │  Other Plugins     │
              │  (loop_plugin)  │  ── ReAct / Planner / Dev       │  (tools/models/    │
              └────────┬────────┘                                │   memory/skills/   │
                       │ set_current(name)                       │   MCP...)           │
                       ▼                                        └─────────┬──────────┘
              ┌─────────────────┐  Before each tool call            │ Get model adapter
              │  LoopRegistry   │ ───────────────────────────▶ ┌────────────────────┐
              │  get_current()  │   Tool guard _pre_exec_guard  │  Security Subsystem │
              └────────┬────────┘                               │  is_redline? /      │
                       │ Execute tool                           │  whitelist?          │
                       ▼                                        └─────────┬──────────┘
              ┌─────────────────┐                      │ Block→emit / Pass
              │   Agent.run()   │ ── Difficulty/     ┌──────────────────────────┐
              │  (think→tool)   │    Failure observe  │  SecurityEventBus         │
              └────────┬────────┘                     │  emit_command_blocked()   │
                       │ Auto-route                   │  → security-audit.jsonl   │
                       ▼                              └──────────────────────────┘
              ┌─────────────────┐
              │  Router System  │  ModelRouter.decide() / AutoRouter.decide_override()
              │  Escalate/      │  Fail-safe: never switch without credentials
              │  De-escalate    │
              └─────────────────┘
```

One-liner call chain: **Kernel loads plugins → Loop decides how to think → Security gates every tool execution → Router escalates/de-escalates models based on difficulty/stuckness → All security events are audit-logged.**

---

## 3. Request Lifecycle (Complete Journey of `qxt run "task"`)

```
[1] Startup (fast_start / main)
    └─ load_dotenv() loads secrets from ~/.qingxiaotuan/.env into environment
    └─ build_parser() parses subcommands (run / dev / agent / safe / models / others ...)

[2] Kernel starts and activates plugins
    └─ Kernel scans @plugin classes, topologically sorts by requires, then activates each
    └─ config plugin activates first (provides "config" service)
    └─ LoopPlugin.activate(): creates LoopRegistry, registers ReAct/Planner/Dev
       Sets default from config.loop.provider → provide("loop_registry") / provide("loop_provider")
    └─ Model / tool / memory / skill / safety plugins each provide() their services

[3] Construct Agent
    └─ Agent gets current Loop from kernel.require("loop_provider")
    └─ Agent holds model adapter, tool set, router, auto_route state

[4] Loop drives main cycle (think → tool → observe → think ...)
    └─ Each round: model produces next step (possibly a tool call)

[5] Security gates (core! before every tool execution)
    └─ tools/shell.py _pre_exec_guard calls safety engine:
       · is_hard_redline(cmd) ? → never auto-execute (rm -rf / / dd / force push / shutdown ...)
       · is_redline(cmd)       ? → critical level, multi-stage confirmation (including SQL destructive ops)
       · WhitelistManager hit ? → pass through directly (user added locally)
       · Pass → execute; block → SecurityEventBus.emit_command_blocked(cmd, reason)
    └─ MCP calls go through security_gate.decide_mcp_tool(); file writes through decide_file_write()
    └─ Audit events asynchronously persisted to ~/.qingxiaotuan/security-audit.jsonl

[6] Router escalates/de-escalates models (parallel with Loop, per-round decision)
    └─ AutoRouter.observe_turn() tracks "consecutive failure rounds"
    └─ AutoRouter.decide_override(session) → difficulty override (0/2/10)
    └─ agent._maybe_route_model calls ModelRouter.decide(task, difficulty, available_providers)
       · Simple/stuck-resolved → de-escalate to cheaper model (save cost)
       · Hard/stuck → escalate to stronger model (preserve quality)
       · Fail-safe: candidate model has no configured key → keep current, never switch to credential-less endpoint

[7] Cleanup
    └─ Loop returns final answer; undo/impact ledger records changes
    └─ Session persisted; security audit retained for traceability
```

---

## 4. Detailed Subsystem Documentation

### 4.1 Kernel (Microkernel)
- File: `core/kernel.py`
- Three responsibilities: **plugin registration/activation/dependency resolution**, **service registry** (plugins discover each other via service names, not direct imports), **lifecycle events** (append-only event bus + middleware pipeline).
- Key APIs:
  - `@plugin("svc.name", provides=[...], requires=[...])` one-line plugin metadata declaration.
  - `kernel.provide("name", impl)` / `kernel.require("name")` service registration and discovery.
  - `kernel.emit("event", payload)` / `MiddlewareEventBus` supports middleware interception and event modification.
  - `ServiceContainer`: lazy factories (`provide_factory`), lifecycle hooks, type-safe `typed()`.
- Design principle: **Kernel has zero business logic**. Any capability you want to add, make it a plugin—don't put logic in the kernel.

### 4.2 Plugin (Capabilities as Plugins)
- Pattern: subclass `Plugin` + implement `activate(kernel)` (where you `provide` services).
- Example `LoopPlugin` (`core/loop_plugin.py`): declares `provides=["loop_registry","loop_provider"]`, `requires=["config"]`; in `activate` creates `LoopRegistry` and registers three built-in Loops.
- Runtime switching: `LoopPlugin.switch_loop(kernel, name)` → `registry.set_current(name)` + updates `loop_provider` shortcut reference + `kernel.emit("loop.switched", ...)` (for `/loop` command).
- Contributing new capabilities: write a `@plugin(...)` class, `provide` your service in `activate`, no kernel changes needed.

### 4.3 Loop (Main Loop Strategies)
- File: `core/loop_provider.py` · Registration: `core/loop_plugin.py`
- `LoopRegistry`: `register(loop)` / `set_current(name)` / `get_current()` / `current_name` / `list_available()`.
- Three built-in implementations:
  - `ReActLoop` (default): standard think→tool→observe.
  - `PlannerExecuteLoop`: strong model plans, cheap model executes.
  - `DevLoopProvider`: wraps DevLoop, autonomous iterative development.
- Switching semantics: `set_current("planner")` immediately swaps the "brain" without affecting loaded services; Agent reads `kernel.require("loop_provider")` each round to get the current Loop.
- **Hard redline semantics**: Loop switching is strategy switching, it does not change Security's interception criteria (see 4.4).

### 4.4 Security (Safety Subsystem)
- Files:
  - `ext/safety_engine.py` — Redline determination (`is_redline` / `is_hard_redline` / `score`) and pattern library (`_CRITICAL_PATTERNS` / `_HIGH_PATTERNS` / `_MEDIUM_PATTERNS`).
  - `core/whitelist.py` — `WhitelistManager`: user-local pass-through list.
  - `core/security_bus.py` — `SecurityEventBus`: event bus + JSONL persistence (default: `~/.qingxiaotuan/security-audit.jsonl`).
  - `ext/security_gate.py` — Unified gate: `decide_shell` / `decide_mcp_tool` / `decide_file_write`.
  - `core/blacklist_override.py` — **User-local blacklist override** (see below).
  - `tools/shell.py` — `_pre_exec_guard`: actual interception point before every shell tool execution.
- Two-layer determination:
  1. **Hard redline** (`is_hard_redline`): OS/filesystem-level destructive operations (rm -rf /, dd, mkfs, force push, shutdown etc. tokenized detection). **Never auto-executes** even in YOLO mode.
  2. **Comprehensive redline** (`is_redline`): builds on hard redline with `_CRITICAL_PATTERNS` regex library (including SQL destructive ops DROP/DELETE/TRUNCATE, classified as "confirmable critical level", allowed after multi-stage confirmation).
- **Audit logging**: blocked/allowed events written to `security-audit.jsonl` via `emit_command_blocked` / `emit_command_allowed`, viewable with `qxt safe status`.
- **User-local blacklist override (`blacklist_override`)**: some built-in patterns may be false positives or trusted in user environments. Users declare pattern label keywords to suppress in `~/.qingxiaotuan/blacklist-override.json`, and `is_redline` / `is_hard_redline` / `score` will skip these patterns.
  - Security boundary: **only suppresses regex pattern library entries**; irreversible/OS-level tokenized hard redlines (rm -rf / force push / shutdown ...) have independent determination, **never** affected by overrides.
  - Usage: `qxt safe reduce <keyword>` (e.g., `qxt safe reduce format`), `qxt safe restore <keyword>`, `qxt safe blacklist` to view the list.
- Whitelist: `qxt safe allow <command>` adds trusted commands (redline commands rejected); `qxt safe deny` removes.
- Multi-stage confirmation: extremely high risk 5 times, high risk 3 times confirmation (see `ext/security_gate.py`), including TOCTOU script detection.

### 4.5 Router (Model Routing)
- Files: `models/router.py` · `core/auto_route.py` · `models/provider_catalog.py`
- `ModelRouter.decide(task, context, current_provider, current_model, available_providers, …)` returns `{switch, reason, provider, model, capabilities, difficulty}`.
- Decision rules (save cost + no quality loss + fail-safe):
  - Custom model (not in presets) → don't switch, respect user-specified "brain".
  - Difficulty exceeds current model capability, or missing required capability (e.g., images need vision) → **escalate**.
  - Cheaper and still capable → **de-escalate** to save cost.
  - Candidate model has **no configured key** → keep current, never switch to credential-less endpoint (core fail-safe).
- `AutoRouter` (planner-execute + stuck escalation):
  - `RouteSession` tracks `stuck` (consecutive failure rounds) across turns.
  - `plan_execute`: planning uses strong model (difficulty 10), execution uses cheap model (difficulty 2).
  - `escalate_on_stuck`: cheap model consecutive failures reach threshold → escalate to strong model for rescue, then de-escalate back.
- Local models: `models/provider_catalog.py` presets `ollama` (:11434), `llamacpp` (:8080/v1) etc. self-hosted providers; `models/openai_compat.py` allows empty key for localhost endpoints (local LLMs don't need keys); `models/offline.py`'s `detect_local_models()` probes local Ollama + llama.cpp models (`qxt models local` invocation).

---

## 5. Key Data Flow: Safety Block → Audit Log → Loop Switch → Model Routing

This is the full chain covered by the E2E test baseline (`tests/test_e2e_security_loop_routing.py`):

```
Command string
  │
  ▼  tools/shell._pre_exec_guard
is_redline(cmd) / is_hard_redline(cmd)
  ├─ Hard redline hit          → Block (YOLO doesn't bypass either)
  ├─ Comprehensive redline hit → Multi-stage confirmation
  ├─ Whitelist hit             → Pass through
  └─ Pass                      → Execute
  │
  ▼  SecurityEventBus.emit_command_blocked(cmd, reason)
persist → ~/.qingxiaotuan/security-audit.jsonl   ← Audit log
  │
  ▼  LoopRegistry.set_current(name)              ← Loop switch (strategy hot-swap)
Agent runs next round with new Loop
  │
  ▼  AutoRouter.observe_turn / decide_override
ModelRouter.decide(task, difficulty, available_providers)
  ├─ switch=True, reason=escalate  → Switch to stronger model
  └─ switch=True, reason=de-escalate → Switch to cheaper model    ← Model routing
```

Four stages can each be independently unit-tested; the combination is the "safety→audit→loop→routing" end-to-end closed loop.

---

## 6. Extension Points (Contributing Guide)

| What to add | How to do it | Entry file |
| --- | --- | --- |
| New Loop strategy | Subclass `LoopProvider`, `register` in `LoopPlugin.activate` | `core/loop_provider.py` |
| New security pattern | Add `(regex, label)` to `_CRITICAL/_HIGH/_MEDIUM_PATTERNS`; redline commands reject whitelist addition | `ext/safety_engine.py` |
| Local blacklist override | User-side `qxt safe reduce <label_keyword>`, no code changes needed | `core/blacklist_override.py` |
| New model provider | Add `ProviderPreset` to `provider_catalog.py` (with `category="local"` for local deployment) | `models/provider_catalog.py` |
| New plugin capability | `@plugin("svc", provides=[...], requires=[...])` + `provide` in `activate` | `core/kernel.py` |
| New CLI subcommand | Add subparser in `cli/parser.py` + `_resolve_func` branch + `cli/cmd_*.py` | `qingxiaotuan/cli/` |

---

## 7. Localization & Configuration

- Home directory: `~/.qingxiaotuan` (can be overridden with environment variable `QXT_HOME` for test isolation).
- Key files:
  - `security-audit.jsonl` — Security audit log (viewable via `qxt safe status`).
  - `whitelist.json` — Whitelist.
  - `blacklist-override.json` — Local blacklist override declarations.
  - `.env` — Centralized secret management (permissions should be 600, not in version control).
- Local models: After installing Ollama (:11434) or llama.cpp (:8080/v1), use `qxt models local` to probe, `qxt models set ollama <model>` / `qxt models set llamacpp <model>` to connect.

---

## 8. Related Documentation
- `qxt help` — Complete subcommands and parameters.
- `qxt others` — Friendly capability catalog (newcomer entry point).
- `qxt safe` — Safety entry (status / whitelist / blacklist override / update).
- `qxt models` — Models and local LLM management.
- `SECURITY.md` · `CONTRIBUTING.md` · `CHANGELOG.md` — Security policy / contribution guidelines / changelog.
