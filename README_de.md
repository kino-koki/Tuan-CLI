# Tuan-CLI

> **„Model + Harness = Agent."** — Trenne „wie denken" von „wie sicher ausführen" und bekomm beide Schlüssel.
> Ein sicherheitsorientiertes, modellneutrales, rein-python Agent-Harness. `v0.3.3` · MIT · Python ≥ 3.10

> ### Positionierung: ein Sicherheits-agent — ohne Entwickler-Erlebnis zu opfern
>
> **Sicherheit ist Priorität, keine Option** — und **Unterbrechen ist kein Ersatz für Sicherheit**.
>
> - **Sicherheit zuerst**: Gefährliche Befehle werden *vor* ihrem Lauf blockiert (Wirkradius-Vorschau → harte Redline → mehrstufige Bestätigung). Jeder Write läuft durch ein transaktionales Hauptbuch, damit `/undo` exakt zurückrollen kann.
> - **Sicherheitssemantik**: YOLO/`--yolo` genehmigt automatisch Aktionen, die normalerweise eine Bestätigung erfordern, umgeht aber **keine** harten Redlines. `--isolation` bietet Isolation auf Engine-/Prozessebene, um den Wirkungsradius und die Ausbreitung von Fehlern zu begrenzen; es ist **keine** vollständige Betriebssystem-Sandbox und ersetzt nicht die Befehlsfreigabe.
> - **Entwickler-Erlebnis bleibt erhalten**: Datei-Lesen/Schreiben, routinemäßige `git`-Operationen, Paketinstallationen, Testläufe und Linter werden mit `none` bewertet — **keine Bestätigung, kein Blockieren** (`safety_engine.is_benign_dev_command`). Nur wirklich gefährliche Aktionen werden zu Rat oder Blockade.
> - **Reproduzierbare Messwerte**: Unser Ziel ist„weniger gefährliche Befehle schlupfen durch, weniger harmlose Befehle nerven", und jede Zahl, die wir veröffentlichen, **muss von Dritten reproduzierbar sein** — keine unverifizierbaren Absolutversprechen. Benchmarks liegen in [`bench/`](bench/README.md): 10k adversariale bash/generic Samples + 5k PowerShell Samples + 2.321 handgemachte Bypass-Payloads (mit Consequence-Level-Disaster-Assertions). **Ein Befehl, `tuan safe bench`, reproduziert alles lokal** (kein Netz, kein Modell); `tuan safe report` erzeugt einen selbständigen HTML-Sicherheitsreport. Gemessen am aktuellen Code (2026-10): adversarial 10k → block recall 100 % / flag recall 100 % / false-positive 0,09 % (1) / bypass 0; PowerShell 5k → accuracy 100 % / misses 0 / false positives 0; bypass matrix 2.321 payloads → bypass 0 / false positive 1 / disaster-intent classes 100 % blockiert. Einige bewusst fail-closed-konservative Eskalationen bleiben (z. B. `nc`-Port-Probes, `tar|ssh`-exfil-geformte Payloads) und erklären die False-Positive-Zahlen; bitte lokal nachlaufen.
> - **Ökosystem-Interop**: Wir bauen keine Ökosysteme neu — wir **wiederverwenden, was Claude Code / Hermes Agent auf dieser Maschine schon angesammelt haben** (Skills, benannte Agents, Memory, SOUL-Persona, MCP-Configs). `tuan ecosystem` bewegt Assets in beide Richtungen in einem Befehl; `tuan ecosystem link` mountet tuan über MCP zurück hinein. Ein Harness, drei Ökosysteme an Assets.

**Sprache/Language:** [English](README.md) · [简体中文](README_zh-CN.md) · [繁體中文](README_zh-GAT.md) · [日本語](README_ja.md) · [한국어](README_ko.md) · [Español](README_es.md) · [Português (Brasil)](README_pt-BR.md) · [Français](README_fr.md) · **Deutsch** · [Русский](README_ru.md)

**Vor dem Handanlegen:** [SECURITY.md](SECURITY.md) · [CHANGELOG.md](CHANGELOG.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · `tuan models list-providers`

**Quick Start:**
- 🚀 **In 3 Schritten los:** `pip install tuan-cli` → `tuan setup` → `tuan "deine Aufgabe"`
- 📖 **Vollständiger Guide:** [docs/QUICKSTART.md](docs/QUICKSTART.md) — mit Entscheidungsbäumen, typischen Szenarien und FAQ
- 🎯 **Schnellreferenz:** `tuan help quickstart` — zeigt den Quickstart direkt im Terminal

---

## TL;DR

Die Kernidee: **das Modell denkt, der Harness lässt es sicher und kontrolliert laufen.** Tuan-CLI trennt „das Modell" von „dem Host": Hot-Swap zwischen vielen Anbietern, komplett offline laufen, zerstörerische Fehler zurückrollen und den Wirkradius *bevor* der Befehl schießt sehen. Ziel ist ein vernünftig neutraler, selbst hostbarer Terminal-Agent — kein gefangener Wrapper um einen einzelnen Anbieter.

**Was es NICHT ist**: kein gefangener Wrapper um ein Modell (Hot-Swap / Self-Host / Offline, ganz wie du willst); kein Handlanger eines IDEs (es ist ein Terminal-Tool, per ACP steuerbar von VSCode/Zed/JetBrains); keine einzelne leakige Abstraktion (Microkernel-Plugin-Architektur für Bastler, dazu ein einmaliges `setup` für alle anderen).

---

## Warum es anders ist

| Was | Details |
|---|---|
| 🛡️ **Sicherheit zuerst** | Vier Tore: statisches Risikoscoring, Wirkradius-Pre-Block, YOLO-Redline-Fußboden, transaktionales Hauptbuch mit exaktem `/undo` |
| 🎯 **Entwickler-Erlebnis** | Harmlose Dev-Befehle passieren ohne Bestätigung, `/undo` hat deinen Rücken, 40+ Slash-Befehle, `tuan safe allow` für explizite Opt-outs, YOLO für Wiederholungen |
| 🔌 **Modellneutral** | 58 Anbieter + lokales Ollama + Hot-Swap zur Laufzeit + automatisches Routing (`router.*`) |
| 🧠 **Drei Hauptschleifen** | ReAct / Planner-Execute / DevLoop — austauschbar; ein Kernel, verschiedene „Denkrhythmen" |
| 🔧 **Microkernel** | Einzeiliges `@plugin`, Service-Registry, append-only Event-Bus, Hook-Middleware |
| 🗂️ **Gedächtnis** | SQLite FTS5 + Session-Event-Stream; dreistufiger Speicher, `/undo`, Checkpoint, Replay, Trajectory-Export |
| 🧩 **Ökosystem** | MCP + ACP + **Claude Code / Hermes Agent Interop**: Skills / benannte Agents / Memory / SOUL / MCP-Configs laufen beide Wege (`tuan ecosystem`), ab Werk |
| 🌍 **Zehn Sprachen** | zh-CN als Default, echte Lokalisierung der ganzen Oberfläche |
| 🐍 **Reines Python** | Große `.py`-Codebasis, MIT-lizenziert |

---

## Gerade Antworten

**F: Ist das wirklich unabhängig? Wie viel ist selbst entwickelt?**
Zwei Dinge, sauber getrennt. **Der Code ist selbst geschrieben**: der Kernel und der allergrößte Teil der Fähigkeiten (`core/`, `runtime/`, `arch/`, `tools/`, `ports/`…) sind zeilenweise in Python gebaut, nur für Interoperabilität an externe Protokolle angeglichen. **Die Ideen und das Design sind entlehnt** — dieses Projekt fusioniert bewusst Konzepte aus bekannten Agent-Projekten, und das offen zu sagen ist besser als verstecken. Der eine Teil, wo sogar der *Stil* übernommen wird, ist die `--tui`-Terminal-Hülle, die bewusst das **Kimi Code**-Unterschriftsgefühl und die Palette übernimmt (`#4FA8FF` primär, der Mondphasen-Spinner, die zweizeilige Statusleiste), gutgeschrieben in [NOTICE](NOTICE). Die komplette Liste steht in [Inspiration & Attribution](#inspiration--attribution). **Code ist unserer; Ideen sind geteilt.**

**F: Warum blockiert es mich, bevor ich Befehle ausführe?**
Feature, kein Bug. Gefährliche Befehle fragen zuerst; YOLO respektiert harte Redlines. Zu schwatzhaft? `tuan safe allow <cmd>` für die Whitelist — Sicherheit nicht ausschalten.

**F: Und wenn ich blockiert bin, stecke ich fest?**
Nein. Jeder Block/Bestätigung bringt **befehlsbewusste sichere Alternativen** (`tuan safe suggest <cmd>` jederzeit anfragbar): `git push --force` → `--force-with-lease`, `rm -rf` → Trash/Recycle-Rezept, `curl | sh` → „erst herunterladen und prüfen". Wir stoppen dich nicht einfach — wir führen dich auf dem sicheren Weg zum Ziel.

**F: Was kann `/undo` tatsächlich zurückrollen?**
Jeden **Write**, der durchs Hauptbuch läuft: eine einzelne Datei, einen einzelnen Schritt, eine ganze Runde. Darunter: transaktionales Hauptbuch + diff `reverse_transform` + Checkpoint-Snapshots. Kein Wundermittel, aber es macht aus einem Ausrutscher einen sicheren Verlust zu einem wahrscheinlichen Save.

**F: Liest es meine privaten Dateien?**
Der Tool-Umfang ist durch eine Domain-Allowlist begrenzt, der Netzausgang gegen Exfiltration gesperrt und Secrets werden in der Ausgabe redacted. Defaults und was du einstellen kannst stehen in [SECURITY.md](SECURITY.md).

**F: Komplett offline?**
`tuan models local` zum Sondieren, `/offline` zum Verwalten von Ollama. Kein Internet, kein Problem.

**F: Kann ich eigene Tools/Plugins schreiben?**
Ja — Metadaten per `@plugin`, `activate(kernel)` + `kernel.provide(...)` / `kernel.require(...)`. Drei Schritte:

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

## Versionsnummer & Repository-Historie (transparente Offenlegung)

**Warum `0.3.3` und nicht `1.0`?** Ehrliche [SemVer](https://semver.org/)-Semantik: **eine `0.x`-Version bedeutet, dass die öffentliche API (CLI-Oberfläche, Konfigurationsschema, Tool-Protokoll, Plugin-Vertrag) noch nicht eingefroren ist** und sich zwischen Releases noch ändern kann. Tuan-CLI bietet bereits einen breiten Funktionsumfang — Sicherheits-Gating / transaktionales Rollback, modellneutraler Hot-Swap (58 Anbieter + lokales Ollama), drei Hauptschleifen, Microkernel-Plugin-Architektur, dreistufiger Speicher, Ökosystem-Interop (MCP / ACP / Claude Code / Hermes-Brücke), Subagents & Swarm, Cron & Hintergrundaufgaben, Goal-Modus & präzise Berechtigungen — alles durch Tests abgedeckt. Aber **die Versionsnummer spiegelt die Stabilität der Schnittstelle, nicht die Vollständigkeit der Funktionen**: ein vollständiger Funktionsumfang heißt nicht, dass die API eingefroren werden sollte. `1.0` ist für den Zeitpunkt reserviert, an dem die öffentliche API wirklich stabil ist und wir Rückwärtskompatibilität zusagen können. Bis dahin: Breaking Changes heben MINOR innerhalb von `0.x` (mit Migrationshinweisen), kompatible Funktionen MINOR, Fixes PATCH (siehe [VERSION_POLICY.md](VERSION_POLICY.md)).

| Versionssemantik | Bedeutung |
|---|---|
| `0.3.3` (aktuell) | **API noch nicht eingefroren**: `0.x` erlaubt Breaking-Anpassungen, angekündigt mit Migrationshinweisen; keine Rückwärtskompatibilität zugesagt |
| `1.0` (reserviert) | Wird aktiviert, sobald die öffentliche API eingefroren ist und Rückwärtskompatibilität zugesagt wird; erst dann heben Breaking Changes MAJOR (`2.0`) |

**Hinweis zur Git-Historie (Open-Source-Transparenz):** Die Commit-Historie dieses Repositories wurde **am 2026-09-26 bewusst neu aufgebaut — die frühere Commit-Historie wurde vom Autor absichtlich überschrieben**; die Entwicklung vor diesem Datum ist nicht mehr erhalten. Der aktuelle Code ist von der Architektur bis zur Implementierung vollständig prüfbar; für die Funktionsentwicklung vor 2026-09-26 stützen Sie sich bitte auf die Versionsaufzeichnungen in [CHANGELOG.md](CHANGELOG.md) (die Versionsdisziplin ist nicht betroffen). Wir entscheiden uns, dies offen darzulegen — ohne Beschönigung, ohne Verstecken.

---

## Inspiration & Attribution

Tuan-CLI ist nicht aus dem Nichts entstanden — sein Design stützt sich ausdrücklich auf die folgenden bekannten Agent-Projekte und -Protokolle. Wir listen sie offen auf (und vermerken die Originalquelle, wo möglich, im Quellcode als Kommentar):

| Quelle | Was wir übernommen haben |
|---|---|
| **DeepSeek Harness / Cordis** | Mikrokern + Service-Registry + Append-only-Eventbus (annotiert in `core/kernel.py`) |
| **Kimi Code** | Bediengefühl und Palette des Terminal-TUI (siehe [NOTICE](NOTICE)) |
| **Claude Code** | `/`-Slash-Befehlssystem, benannte Agents (`.claude/agents`-kompatibel), Goal-Modus, DevLoop — Interface-Angleichung |
| **Hermes Agent** | Dreistufiger Speicher, Skill-Selbstevolutions-Schleife, SOUL-Identität, self-registering Tools, Cron-Semantik — abgestimmt; `tuan ecosystem` synchronisiert Memory/Skills/SOUL bidirektional damit |
| **ACP (Agent Client Protocol)** | Als Client/Server auf die Semantik von Nachrichten und Handshake abgestimmt, damit ein IDE Tuan-CLI steuern kann |
| **MCP (Model Context Protocol)** | Als Client auf das Protokoll abgestimmt, um an die Werkzeug-Ökosphäre anzudocken |
| **APIs von OpenAI / Anthropic / Google usw.** | Provider-Adapter nach offizieller REST-Semantik umgesetzt — nur Protokoll-Adaption, keine interne Nachstellung |

> Grenze: Der **Code** ist selbst entwickelt; **Protokolle/Schnittstellen** werden angeglichen; **Ideen/Designs** werden entlehnt und fusioniert. Wo konkret ein Implementierungsdetail zitiert wird, steht das im Quellkommentar und in [NOTICE](NOTICE).

---

## Schnellstart

```bash
# 1) Installieren ([dev] = der ganze Stack; [openai]/[mcp] reicht, wenn du nur APIs brauchst)
git clone <dieses Repo> && cd tuan-cli
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# 2) Anbieter einrichten (14 eingebaute Profile: deepseek / groq-free / siliconflow-free / ollama…)
tuan setup
# oder manuell: ~/.tuan/config.yaml
#   model.provider: deepseek
#   model.model: deepseek-chat
#   model.api_key_env: DEEPSEEK_API_KEY      # Schlüssel nie im Klartext

# 3) Chat
tuan
# oder ein Smoke-Test:
tuan --print run "Hallo, stell dich in einem Satz vor."
```

---

## Kommandofläche: 38 Kern-Subcommands + Slash-Befehle

| Befehl | Wofür |
|---|---|
| `tuan` | Interaktives TUI (Kimi-Code-Skin) |
| `tuan setup` / `tuan models` | Anbieter konfigurieren / 58 Anbieter & 1400+ Modelle listen |
| `tuan sessions` / `--continue` / `--resume <id>` / `setup --skip` | Gespeicherte Sessions auflisten/fortsetzen/löschen; direkt aus der CLI fortsetzen; beim ersten Start läuft der Setup-Assistent automatisch (`setup --skip` überspringt) |
| `tuan models update` | Modell-/Anbieter-Katalog lokal aktualisieren: eingebaute Listen in `~/.tuan/models_catalog.json` mergen (offline, behält Benutzer-Einträge; `--check` zeigt nur Diffs, `--background` läuft asynchron) |
| `tuan agent` | Benannte Agents (`.claude/agents`-kompatibel, 3-Ebenen-Discovery) |
| `tuan acp` | ACP-Server starten, damit VSCode / Zed / JetBrains dich steuern kann |
| `tuan ecosystem` | **Ökosystem-Interop**: `scan` sondiert Claude Code / Hermes; `import` zieht deren Skills/Agents/Memory/SOUL/MCP-Configs in tuan; `export` schiebt zurück; `link` mountet tuan über MCP hinein; `serve` läuft als MCP-Server (siehe [docs/ecosystem_bridge.md](docs/ecosystem_bridge.md)) |
| `tuan cron` | Geplante Hintergrundaufgaben |
| `tuan doctor [--compact]` | Gesundheitscheck (`--compact` für Context-Compaction-Self-Check) |
| `tuan dev codedev ...` | Code-Dev-Subsystem (Retrieval / Verifikation / Dekomposition) |

Alltags-Slash-Befehle: `/plan`·`/model`·`/undo`·`/impact`·`/swarm`·`/log`·`/stats`·`/cost`·`/budget`·`/goal`·`/sandbox`·`/offline`·`/verify`·`/audit`·`/more`·`/help` — volle Liste über `Ctrl-G` im TUI.

---

## Ökosystem-Interop: Claude Code / Hermes Agent ab Werk

Neben „safety-first" und „modellneutral" ist das dritte Standbein: **Ökosysteme nicht neu bauen — wiederverwenden, was andere Agent-Ökosysteme schon angesammelt haben.** Skills (der SKILL.md-Open-Standard), benannte Agents (`.claude/agents`), Memory & Persona (Hermes' `MEMORY.md` / `USER.md` / `SOUL.md`), Kontextdateien (`AGENTS.md` / `CLAUDE.md`) und MCP-Server-Configs sind strukturell fast identisch über alle drei hinweg — tuan brückt sie:

```bash
tuan ecosystem scan                        # Claude Code / Hermes + deren Assets sondieren (nur lesen)
tuan ecosystem import all                  # beidseitige Skills/Agents/Memory/SOUL/MCP-Configs in tuan ziehen
tuan ecosystem export skills --to claude   # tuan-Skills → .claude/skills (Hermes: --to hermes)
tuan ecosystem link                        # Reverse-Mount: Claude Code/Hermes ruft tuan über MCP auf
```

- **Automatisch in der Session**: Skills, die Claude Code oder Hermes bereits installiert hat, sind sofort in tuan verfügbar (`~/.claude/skills`, `~/.hermes/skills` liegen im Suchpfad); `tuan ecosystem serve` exponiert tuan als MCP-Server, damit Claude Code / Hermes-Sessions `tuan_*`-Tools bekommen (Memory-Suche/-Write, Skill-Liste/-Lesen, Headless-Aufgaben).
- **Delegieren, nicht migrieren**: `claude_code_run` / `hermes_run`-Tools geben Aufgaben an das vollständige native Umfeld des anderen Agents weiter (deren eigene Config, Memory, Skills, MCP).
- Vollständiges Doc: [`docs/ecosystem_bridge.md`](docs/ecosystem_bridge.md) (Format-Map / Sicherheitsdesign / Layout).

---

## Drei Hauptschleifen, eine ruhige Hand

- **ReActLoop** — denken → handeln → beobachten, der Default-Rhythmus.
- **PlannerExecuteLoop** — ein starkes Modell plant, ein billigeres führt aus (`router.*` unterstützt Plan/Ausführungs-Kompartimentierung). Das Token-sparende Muster.
- **DevLoop** — schreiben-verifizieren-heilen: `/verify` erkennt das Projekt automatisch (Python/Node/Rust/Go), leitet Testbefehle ab und heilt sich bis zu N Runden selbst.

---

## Das Sicherheitsmodell: vier Tore + abgerechnetes Undo

1. **Statisches Scoring** — jeder Shell-Befehl von `SafetyEngine.score(params)` mit `none→critical` bewertet, mit Entfaltung von Indirektionen (IFS, `$VAR`, Befehlsersetzung, ANSI-C/Oktal/Hex-Escapes, PowerShell Base64, NFKC; ≤32 Rekursion).
2. **Wirkradius-Pre-Block** — du siehst, was es anfasst, *bevor* es schießt (`--impact`).
3. **YOLO-Redline-Fußboden** — YOLO killt Schritt-bestätigungen, aber **kann nicht** an harte Redlines (`rm` rekursiv, force-push, `chmod -R 000 /`… nie automatisch).
4. **Transaktionales Hauptbuch** — jeder Write hat eine Audit-Spur; `/undo` stellt via diff `reverse_transform` + Snapshots wieder her.

Regeln lösen immer `deny > ask > allow`. Whitelist mit `tuan safe allow <cmd>`; schalte Sicherheit nicht ab, um Klicks zu sparen.

---

## Sicherheitsbenchmarks: reproduzierbar mit einem Befehl

`tuan safe bench` packt die drei reproduzierbaren Suiten in einen Befehl (vollständig lokal, kein Modell — jeder Dritte kann sie wie sie sind nachlaufen):

- **Adversarial-Korpus** `bench/safety_bench_10k.py` — 10.000 bash/generic Befehle (seeded 20260906, reproduzierbar); meldet block recall / flag recall / False-Positive-Rate / Bypasses.
- **PowerShell-Korpus** `bench/bench_powershell_safety.py` — 5.000 Samples (2.300 gefährlich / 2.700 harmlos); meldet accuracy / misses / False-Positives.
- **Bypass-Matrix** `bench/bypass_matrix.py` — 2.321 handgemachte adversariale Payloads; über Pattern-Matching hinaus assertet **pro Disaster-Consequence-Klasse**, ob jede Klasse katastrophaler Absicht tatsächlich blockiert wurde.

```bash
tuan safe bench                 # voller Lauf (~3 Min)
tuan safe bench --quick         # schnelle Selbstprüfung (~30 s)
tuan safe bench --check         # Vergleich mit Archiv; exit 1 bei Regress (Gate)
tuan safe report                # selbständiger HTML-Sicherheitsreport (teilbar)
tuan safe report --release      # RELEASE: Zahlen + Zeitstempel + Git-Commit gebunden (keine alten Zahlen)
```

Gemessen am aktuellen Code (2026-10-25, reproduzierbar via `tuan safe bench`):

| Suite | Größe | Kernmetrik | Bypasses | False-Positives |
|---|---|---|---|---|
| Adversarial | 10.000 | block recall 100 % · flag recall 100 % · FP 0,09 % (1) | 0 | — |
| PowerShell | 5.000 | accuracy 100 % · misses 0 | 0 | 0 |
| Bypass-Matrix | 2.321 | disaster-intent classes 100 % blockiert | 0 | 1 |

Caveat: die Bypass-Matrix ist bewusst fail-closed und behält ein paar konservative Eskalationen (`nc` Unicode-Variante-Probes, `tar|ssh`-exfil-geformte Payloads), die „harmlos-aber-flagged" False-Positives erzeugen; die 0,09 % (1) FP in der Adversarial-Suite stammen vom selben Konservatismus. Zahlen gelten als autoritativ, wenn lokal mit `tuan safe bench` nachgelaufen.

**CI-Zahlen-Gate**: der `safety-benchmarks`-Job in `.github/workflows/security-ci.yml` läuft alle drei Suiten bei jedem Push durch und vergleicht gegen das eingecommittede Archiv — jede Regression (Bypasses, eine Disaster-Klasse wird nicht mehr komplett blockiert, ein deutlicher FP-Anstieg) **lässt CI failen**. Das Archiv `bench/security-bench.json` entspricht 1:1 der README-Tabelle.

---

## Head-to-Head vs Claude Code: ein Befehl

Neben selbstvermessenen Sicherheits-Suiten läuft `bench/vs_claude.py` **denselben Aufgaben-Satz auf beiden Agents** und rendert einen ehrlichen Seitenvergleich: dieselbe `bench/tasks.yaml`, dieselben Akzeptanz-Skripte, isolierte Workspaces, `tuan run -p` gegen `claude -p --output-format json`.

```bash
python bench/vs_claude.py --dry --tuan .venv/Scripts/tuan.exe   # nur Framework-Check, keine Modellaufrufe
python bench/vs_claude.py --tuan .venv/Scripts/tuan.exe         # echter Lauf (braucht laufende Endpoints auf beiden Seiten)
python bench/vs_claude.py --task fix_bug --model openrouter/deepseek/deepseek-chat
python bench/vs_claude.py --claude "C:\path\claude.cmd" --json
```

Gibt `bench/vs_report.md` / `.json` / `.html` mit Pass-Rate, Wall-Time, Kosten und Berechtigungs-Verweigerungen pro Aufgabe aus.

**Ehrlichkeitsvertrag**: der Runner prüft zuerst, ob `claude -p` tatsächlich eine Runde durchziehen kann; schlägt der Probe fehl, wird die Claude-Spalte mit **N/A und dem exakten Grund** markiert — es wird nie vorgegeben, ein Vergleich fand statt. Zahlen werden erst sinnvoll, wenn beide Endpoints auf deiner Maschine laufen; das ist der Punkt reproduzierbarer Messung. Windows-Hinweis: npm-installiertes `claude` ist ein `.ps1`/`.cmd`-Shim — das Skript löst das echte Executable automatisch auf, und ältere Versionen, die `--no-input` ablehnen, werden über Stdin-Redirect gehandhabt.

---

## Wo deine Ideen laufen

- **Gedächtnis** — drei Ebenen (User/Projekt/Session) + SQLite FTS5 (Trigram), fällt notfalls auf Klartext zurück.
- **Subagents** — typisierte Delegation (general-purpose / explore / plan / coder), isolierte Subagents, parallele Worker und Swarm zum Zerlegen langer Aufgaben.
- **Cron & Hintergrund** — `tuan cron start --detach`; headless autonome Läufe.
- **Hooks** — `PreToolUse` kann `block` oder `args` umschreiben (`hooks.allow_edit_args`).
- **Observability** — `/stats`·`/audit`·`/impact`·`/bench`·`/cost`; die Kosten auf den Tisch.
- **crypto** — AES-GCM(AEAD) mit `cryptography`, sonst HMAC-SHA256-Stream-Cipher als Fallback; fehlende MAC / manipulierte `open()` scheitert immer fail-closed.

---

## Dev & Vertrag

```bash
python -m pytest tests/ -q        # großer Suite
python -m mypy tuan_cli       # Typ-Gate
tuan --print run "Hallo. Eine Zeile." # Smoke
```

- **i18n-Disziplin**: README_zh-CN ist die maßgebliche Master-Version; jede Sprache ist eine lebendige, driftfreie Lokalisierung — **keine maschinelle Übersetzung.**
- **Version**: `v0.3.3` (eine `0.x`-Linie — die API ist noch nicht eingefroren); Breaking-Anpassungen mit Vorankündigung + Migrationshinweisen, `1.0` ist für den API-Freeze reserviert.
- **Tiefgang**: Engine-Signaturen und ein Schritt-für-Schritt-Tool-Walkthrough stehen im Anhang von `README_zh-CN.md`.

---

## Vollständig lokal & offline · keine Anmeldung

Tuan-CLI **bietet keine Anmeldung**: keine GitHub-/Apple-/DeepSeek-Bindung, kein OAuth-Callback, kein Token auf der Festplatte. Das ist Absicht — **alles läuft lokal, außer der Modell-API, die du selbst konfigurierst**.

- **Voll nutzbar ohne Anmeldung**: Datei-I/O, Befehlsausführung, Speicher, Skills, Subagents und der Sicherheits-Gate laufen lokal.
- **Das einzige „Cloud" ist deine Modell-API**: der Schlüssel gehört dir, wird nur an diesen Endpunkt gesendet, ohne Dritte.
- **Für eine Pipeline ganz ohne Netz**: Ollama oder llama.cpp installieren — `tuan models local` zum Erkennen, `tuan models set ollama <Modell>` zum Nutzen.

### Modell-API-Schlüssel konfigurieren

```bash
tuan models set deepseek deepseek-chat   # Anbieter und Modell wählen
tuan models                              # interaktive Einrichtung (Schlüssel in ~/.tuan/.env)
```

Schlüssel liegen in `~/.tuan/.env` (chmod 600, nie committen); Umgebungsvariablen (z. B. `DEEPSEEK_API_KEY`) funktionieren ebenfalls.

> **Transparenz**: frühere Versionen boten GitHub-/Apple-/DeepSeek-Anmeldung (inkl. Web-Session-Token-Pfad). Das widersprach der Positionierung „vollständig lokal & offline", und der Web-Endpunkt war eine private, nicht unterstützte Schnittstelle, die Risikokontrollen auslöste — die Fähigkeit wurde daher **vollständig entfernt**. Modellaufrufe laufen über offizielle APIs mit deinem eigenen Schlüssel.

## Lizenz & Links

- **Lizenz**: MIT (nutzen, ändern, weitergeben; Hinweis behalten)
- **Lies das**: [SECURITY.md](SECURITY.md) · [CHANGELOG.md](CHANGELOG.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [NOTICE](NOTICE)

> Du willst „aus der Dose, abgeschlossen, an einen Anbieter gebunden"? Davon gibt's genug. Du willst **auf deinen eigenen Modellen laufen, die Kontrolle behalten und im Notfall zurückrollen**? Hier liegen die Schlüssel.
