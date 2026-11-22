# THIRD_PARTY_LICENSES — index

This directory holds the license texts of upstream projects whose material is
referenced by the root [`../NOTICE`](../NOTICE). The NOTICE file is the
authoritative attribution record; this directory makes the referenced license
texts directly retrievable, as each upstream license requires.

| File | Upstream | License | NOTICE component |
|---|---|---|---|
| `Codex-LICENSE.txt` | openai/codex (`codex-rs/tui`) | Apache License 2.0 | 9) Approval overlay interaction contracts |
| `Codex-NOTICE.txt` | openai/codex (verbatim upstream NOTICE; also acknowledges Ratatui, MIT) | Apache 2.0 / MIT | 9) |
| `Kimi-Code-LICENSE.txt` | MoonshotAI/kimi-code | MIT | 1)-7) TUI visual tokens + `ports/{protocol,oauth,migration_legacy,transcript,telemetry,kaos}` |

Other acknowledged sources (Claude Code, Hermes Agent, DeepSeek Harness /
Cordis, ACP, MCP) contribute design patterns, interface conventions, or
project-structure defaults only — no license-text obligation attaches to those
references. See NOTICE §8 and the README "Inspiration & attribution" section.

## Reproducibility

- `../sbom.spdx.json` is the SPDX SBOM for the shipped package; it is refreshed
  alongside dependency lockfiles.
- Dependency pins live in `../requirements.lock` and `../uv.lock`; the SBOM and
  both lockfiles are checked for consistency by
  `python scripts/check_licenses_sbom.py` (wired into Security CI).
