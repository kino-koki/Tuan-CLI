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



---

## 9. Testing & Regression Baseline

Core safety regression files (must be all green after changes):
`test_sandbox_system.py` / `test_mcp_checkpoint_convergence.py` / `test_security_network_ownership.py`
`test_permission_rules.py` / `test_security_integration.py` / `test_security_integration_tool_executor.py`
`test_security_hardening.py` / `test_security_auditor_provider.py` / `test_harden_network_policy.py`

> Note: `test_security_v2.py::TestSymlinkResolution` is Windows-environment-related and unrelated to safety logic; not a regression gate.
