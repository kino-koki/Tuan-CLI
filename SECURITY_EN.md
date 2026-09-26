# Qingxiaotuan Agent Safety Subsystem

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

- Main pipeline: [`qingxiaotuan/sandbox/`](qingxiaotuan/sandbox/) (`SandboxManager` unified entry).
- Tool execution gate: [`qingxiaotuan/core/tool_executor.py`](qingxiaotuan/core/tool_executor.py) (`_security_gate_check` + `_sandbox_gate_check`).

---

## 3. Four-Layer Sandbox Filters

| Layer | Module | Responsibility | Verdict |
|-------|--------|---------------|---------|
| L0 Intent | `sandbox/filters.py::IntentFilter` | Hard redline (`rm -rf /` / `format c:`), data exfiltration, remote execution → deny-critical/high | Model-agnostic, most deterministic |
| L1 Trust | `sandbox/filters.py::TrustFilter` | Workspace trust grading (trusted/limited/untrusted/unknown) + domain whitelist + plan mode | trusted → pass / untrusted → deny / unknown → confirm |
| L2 Resource | `sandbox/filters.py::ResourceFilter` | Default no-network → air-gapped; high-risk write → copy mode | Determines "whether to use L3" |
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
- **L2 Resource Filter**: Handles **existence + no-network switch**: contains network request and default no-network → `network=False + isolate=True` (air-gapped execution). Local commands unaffected.

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

| # | Module | Enhancement Direction |
|---|--------|----------------------|
| E1 | `tools/mcp/policy.py` + `security.py` | MCP **server trust grading**: persist each server's permission domain (read-only/tool whitelist/allowed domains) to persistent policy; add "pre-call tool-level authorization + in-session revocable" to replace scattered ad-hoc confirmations |
| E2 | `core/workspace_trust.py` | Trust **auto-decay and re-validation**: trusted auto-downgrades to limited when directory changes or new sensitive files (.env/.git config/keys) appear, prompting re-review |
| E3 | `sandbox/backends.py` + `arch/platform.py` | **Job Object resource quota enforcement**: CPU quota, memory limit, process tree kill timeout fallback (currently only existence probe) |
| E4 | `core/security_auditor.py` + `harden/audit_export.py` | Audit **correlation/consolidation + cross-session anomaly detection**: aggregate alerts for repeated same-source redlines (e.g., MCP repeated injection); export supports rotation and encryption |
| E5 | `core/tool_executor.py` | **Write storm detection**: high-frequency write/delete in single session triggers throttling and alerts, preventing batch accidental deletion |
| E6 | `tools/permissions.py` | `permissions.rules` enhancement: **negative glob** (`!bin/**`), MCP tool name rules, in-session temporary authorization elevation |
| E7 | `sandbox/isolation.py` | Copy mode **diff visualization confirmation**: display changes via CLI/interactive card before applying |
| E8 | `config` | `sandbox`/`permissions` config **schema strict validation + fail-closed observability** (enabled/degraded items visualization) |

> Priority judgment: High priority and independently evolvable → **E2, E3, E5**; depends on interaction design → **E1, E7**; polish/hardening → **E4, E6, E8**.

---

## 9. Testing & Regression Baseline

Core safety regression files (must be all green after changes):
`test_sandbox_system.py` / `test_mcp_checkpoint_convergence.py` / `test_security_network_ownership.py`
`test_permission_rules.py` / `test_security_integration.py` / `test_security_integration_tool_executor.py`
`test_security_hardening.py` / `test_security_auditor_provider.py` / `test_harden_network_policy.py`

> Note: `test_security_v2.py::TestSymlinkResolution` is Windows-environment-related and unrelated to safety logic; not a regression gate.
