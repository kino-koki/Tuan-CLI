# Tuan-CLI

> **»Model + Harness = Agent«** — »Denken« und »Sicher laufen« getrennt, und du bekommst beide Schlüssel.
> Ein sicherheitsorientiertes, modellneutrales, reines-Python-Agenten-Harness. `v0.3.0` · MIT · Python ≥ 3.10

**Sprache/Language:** [English](README.md) · [简体中文](README_zh-CN.md) · [繁體中文](README_zh-GAT.md) · [日本語](README_ja.md) · [한국어](README_ko.md) · [Español](README_es.md) · [Português (Brasil)](README_pt-BR.md) · [Français](README_fr.md) · **Deutsch** · [Русский](README_ru.md)

**Vor dem Handanlegen:** [SECURITY.md](SECURITY.md) · [CHANGELOG.md](CHANGELOG.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · `qxt models list-providers`

---

## In einem Satz

Die meisten Agent-CLIs werden *an einen Anbieter verkauft* und damit oft geboren. Dieses hier ist das Gegenteil: ein **Chassis ohne festgeschriebenes Hirn**. Wechsle zu heiß zwischen 55 Anbietern, laufe komplett offline, mach Fehler rückgängig und sieh den Wirkradius **bevor** der Befehl abschießt. **Das Modell denkt; er sorgt dafür, dass nichts hochgeht.**

**Was es NICHT ist**: kein gefangener Wrapper um ein Modell (Hot-Swap / Self-Host / Offline, ganz wie du willst); kein Handlanger eines IDEs (es ist ein Terminal-Tool, per ACP sogar von VSCode/Zed/JetBrains steuerbar); keine fragile Einzelschicht-Abstraktion (Microkernel-Architektur für Bastler + ein Setup mit einem Klick für alle anderen).

---

## Warum es anders ist

| Was es bringt | Wie weit das geht |
|---|---|
| 🛡️ **Sicherheit zuerst** | Vier Schranken: statisches Risikoscoring, Wirkradius-Blockade, YOLO-Redline-Boden, transaktionales Hauptbuch mit präzisem `/undo` |
| 🔌 **Modellneutral** | 55 Anbieter + lokales Ollama + Hot-Swap + Auto-Routing (`router.*`) |
| 🧠 **Drei Hauptschleifen** | ReAct / Planner-Execute / DevLoop — steckbar: ein Kern, mehrere »Denkrhythmen« |
| 🔧 **Microkernel** | `@plugin` in einer Zeile, Service-Registry, Append-only-Eventbus, Hook-Middleware |
| 🗂️ **Gedächtnis** | SQLite FTS5 + Session-Event-Stream; 3-Ebenen-Speicher, `/undo`, Checkpoint, Replay, Trajectory-Export |
| 🧩 **Ökosystem** | MCP + ACP — Tools einstecken oder dein IDE dich steuern lassen |
| 🌍 **Zehn Sprachen** | standardmäßig vereinfachtes Chinesisch, echte Lokalisierung der Oberfläche |
| 🐍 **Reines Python** | ~412 `.py` / ~79 k Zeilen / 41 Pakete / 36 Plugins, MIT |

---

## Ohne Umschweife

**F: Ist das wirklich »selbst entwickelt«? Keine Leiche im Keller?**
Zwei Dinge, sauber getrennt. **Der Code ist selbst geschrieben**: der Kern und die allermeisten Fähigkeiten (`core/`, `runtime/`, `arch/`, `tools/`, `ports/`…) sind Zeile für Zeile in Python implementiert, nur für Interoperabilität an externe **Protokolle** angeglichen. **Die Ideen und das Design aber** sind ausdrücklich bekannten Agent-Projekten entlehnt und fusioniert — das ist nichts zu verstecken, sondern genau das: auf den Schultern von Riesen stehen. **Der Code ist unserer; die Ideen sind geteilt.** Der einzige Teil, der sogar seinen *Stil* behält, ist die Hülle des TUI `--tui`, die bewusst Stil und Palette von **Kimi Code** übernimmt (`#4FA8FF`, Mondphasen-Spinner, zweizeilige Statusleiste), gutgeschrieben in [NOTICE](NOTICE). Die vollständige Liste steht in [Inspiration & Attribuierung](#inspiration--attribuierung).

**F: Warum blockiert es mich, bevor ich Kommandos ausführe?**
Feature, kein Bug. Gefährliche Kommandos fragen zuerst; YOLO respektiert die Redlines. Zu redselig? `qxt safe allow <cmd>` für die Whitelist — Sicherheit nicht ausschalten.

**F: Was kann `/undo` wirklich zurückrollen?**
Jeden **Schreibzugriff**, der durchs Hauptbuch geht: eine Datei, einen Schritt, eine ganze Runde. Dahinter: transaktionales Hauptbuch + diff `reverse_transform` + Checkpoint-Snapshots. Kein Wundermittel, aber es macht aus »ich hab's versaut« einen wahrscheinlichen Save statt eines sicheren Verlusts.

**F: Liest es meine privaten Dateien?**
Der Tool-Umfang ist per Domain-Allowlist begrenzt, der Netzausgang gegen Exfiltration gesperrt und Schlüssel werden in der Ausgabe maskiert.

**F: Komplett offline?**
`qxt models local` zum Sondieren, `/offline` zum Verwalten von Ollama. Kein Internet, kein Problem.

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

**Warum `0.3.0` und nicht `1.0`?** Ehrliche [SemVer](https://semver.org/)-Semantik: **Eine `0.x`-Version bedeutet, dass die öffentliche API (CLI-Oberfläche, Konfigurationsschema, Tool-Protokoll, Plugin-Vertrag) noch nicht eingefroren ist** und sich zwischen Releases noch ändern kann. Tuan-CLI bietet bereits einen breiten Funktionsumfang — Sicherheits-Gating / transaktionales Rollback, modellneutraler Hot-Swap (55 Anbieter + lokales Ollama), drei Hauptschleifen, Microkernel-Plugin-Architektur, dreistufiger Speicher, Ökosystem-Interop (MCP/ACP/Claude Code/Hermes-Brücke), Subagents & Swarm, Cron & Hintergrundaufgaben, Goal-Modus & präzise Berechtigungen — alles durch Tests abgedeckt. Aber **die Versionsnummer spiegelt die Stabilität der Schnittstelle wider, nicht die Vollständigkeit der Funktionen**: ein vollständiger Funktionsumfang heißt nicht, dass die API eingefroren werden sollte. `1.0` ist für den Zeitpunkt reserviert, an dem die öffentliche API wirklich stabil ist und wir Rückwärtskompatibilität zusagen können. Bis dahin: Breaking Changes heben MINOR innerhalb von `0.x` (mit Migrationshinweisen), kompatible Funktionen MINOR, Fixes PATCH (siehe [VERSION_POLICY.md](VERSION_POLICY.md)).

| Versionssemantik | Bedeutung |
|---|---|
| `0.3.0` (aktuell) | **API noch nicht eingefroren**: `0.x` erlaubt Breaking-Anpassungen, angekündigt mit Migrationshinweisen; keine Rückwärtskompatibilität zugesagt |
| `1.0` (reserviert) | Wird aktiviert, sobald die öffentliche API eingefroren ist und Rückwärtskompatibilität zugesagt wird; erst dann heben Breaking Changes MAJOR (`2.0`) |

**Hinweis zur Git-Historie (Open-Source-Transparenz):** Die Commit-Historie dieses Repositories wurde **am 2026-09-26 bewusst neu aufgebaut — die frühere Commit-Historie wurde vom Autor absichtlich überschrieben**; die Entwicklung vor diesem Datum ist nicht mehr erhalten. Der aktuelle Code ist von der Architektur bis zur Implementierung vollständig prüfbar; für die Funktionsentwicklung vor 2026-09-26 stützen Sie sich bitte auf die Versionsaufzeichnungen in [CHANGELOG.md](CHANGELOG.md) (die Versionsdisziplin ist nicht betroffen). Wir entscheiden uns, dies offen darzulegen — ohne Beschönigung, ohne Verstecken.

---

## Inspiration & Attribuierung

Tuan-CLI ist nicht aus dem Nichts entstanden — sein Design stützt sich ausdrücklich auf die folgenden bekannten Agent-Projekte und -Protokolle. Wir listen sie offen auf (und vermerken die Originalquelle, wo möglich, im Quellcode als Kommentar) :

| Quelle | Was wir übernommen haben |
|---|---|
| **DeepSeek Harness / Cordis** | Mikrokern + Service-Registry + Append-only-Eventbus (annotiert in `core/kernel.py`) |
| **Kimi Code** | Bediengefühl und Palette des Terminal-TUI (siehe [NOTICE](NOTICE)) |
| **Claude Code** | `/`-Slash-Befehlssystem, benannte Agents (`.claude/agents`-kompatibel), Goal-Modus, DevLoop — Interface-Angleichung |
| **ACP (Agent Client Protocol)** | Als Server/Client auf die Semantik von Nachrichten und Handshake abgestimmt, damit ein IDE Tuan-CLI steuern kann |
| **MCP (Model Context Protocol)** | Als Client auf das Protokoll abgestimmt, um an die Werkzeug-Ökosphäre anzudocken |
| **APIs von OpenAI / Anthropic / Google usw.** | Provider-Adapter nach offizieller REST-Semantik umgesetzt — nur Protokoll-Adaption, keine interne Nachstellung |

> Grenze: Der **Code** ist selbst entwickelt; **Protokolle/Schnittstellen** werden angeglichen; **Ideen/Designs** werden entlehnt und fusioniert. Wo konkret ein Implementierungsdetail zitiert wird, steht das im Quellkommentar und in [NOTICE](NOTICE).

---

## Schnellstart

```bash
git clone <dieses Repo> && cd tuan-cli
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

qxt setup
# oder manuell: ~/.qingxiaotuan/config.yaml
#   model.provider: deepseek
#   model.model: deepseek-chat
#   model.api_key_env: DEEPSEEK_API_KEY      # Schlüssel nie im Klartext

qxt            # losplaudern
qxt --print run "Hallo, stell dich in einem Satz vor."
```

---

## Kommandofläche: 105 Subcommands + 46 Slash-Commands

| Befehl | Wofür |
|---|---|
| `qxt` | Interaktives TUI (Kimi-Code-Skin) |
| `qxt setup` / `qxt models` | Anbieter konfigurieren / 55 Anbieter & 1100+ Modelle listen |
| `qxt agent` | Benannte Agents (`.claude/agents`-kompatibel, 3-Ebenen-Discovery) |
| `qxt acp` | ACP-Server starten, damit VSCode / Zed / JetBrains dich steuern |
| `qxt cron` | Geplante Hintergrundaufgaben |
| `qxt doctor` / `qxt bench` | Gesundheitscheck / Benchmark |
| `qxt arch demo` | 5-Ebenen-Architektur mit einem Befehl verifizieren |

Slash-Commands im Alltag: `/plan`·`/model`·`/undo`·`/impact`·`/swarm`·`/log`·`/stats`·`/cost`·`/budget`·`/goal`·`/sandbox`·`/offline`·`/verify`·`/audit`·`/more`·`/help` — volle Liste via `Ctrl-G` im TUI.

---

## Drei Schleifen, eine ruhige Hand

- **ReActLoop** — denken → handeln → beobachten, der Default-Rhythmus.
- **PlannerExecuteLoop** — ein starkes Modell plant, ein billiges führt aus (`router.*` erlaubt Plan/Ausführung zu trennen). Der Tokensparer.
- **DevLoop** — schreib-verifiziere-heile: `/verify` erkennt das Projekt (Python/Node/Rust/Go), leitet Testbefehle ab und heilt sich bis zu N Runden.

## Das Sicherheitsmodell: vier Schranken + abbrechen mit Buchführung

1. **Statisches Scoring** — jeder Shell-Befehl von `safety_engine.score()` mit `none→critical` bewertet, mit Entfaltung von Indirektionen (IFS, `$VAR`, Befehlsersetzung, ANSI-C/Oktal/Hex-Escapes, PowerShell Base64, NFKC; ≤32 Rekursion).
2. **Wirkradius-Blockade** — du siehst, was es anfasst, **bevor** es abgeht (`--impact`).
3. **YOLO-Redline-Boden** — YOLO nimmt die Schritt-Bestätigungen, aber **nicht** die harten Redlines (`rm` rekursiv, force-push, `chmod -R 000 /`… nie automatisch).
4. **Transaktionales Hauptbuch** — jeder Write ist geprüft; `/undo` stellt via diff `reverse_transform` + Snapshots wieder her.

Regeln lösen immer `deny > ask > allow`. Whitelist mit `qxt safe allow <cmd>`; schalte Sicherheit nicht ab, um Klicks zu sparen.

---

## Wo deine Ideen laufen

- **Gedächtnis** — drei Ebenen (User/Projekt/Session) + SQLite FTS5 (Trigram), fällt notfalls auf Klartext zurück.
- **Subagents** — typisierte Delegation (general-purpose / explore / plan / coder), isolierte Subagents, parallele Worker und Swarm zum Zerlegen langer Aufgaben.
- **Cron & Hintergrund** — `qxt cron start --detach`; headless autonome Läufe.
- **Hooks** — `PreToolUse` kann `block` oder `args` umschreiben (`hooks.allow_edit_args`).
- **Observability** — `/stats`·`/audit`·`/impact`·`/bench`·`/cost`; die Kosten auf den Tisch.
- **crypto** — v2 solide: AES-GCM(AEAD) mit `cryptography`, sonst HMAC-SHA256-Stream-Cipher; `open()` ohne MAC / manipuliert ist immer fail-closed.

---

## Dev & Vertrag

```bash
python -m pytest tests/ -q        # 2500+ Tests
python -m mypy qingxiaotuan       # Typ-Gate
qxt --print run "Hallo. Eine Zeile." # Smoke
```

- **i18n-Disziplin**: README_zh-CN ist die maßgebliche Master-Version; jede Sprache ist eine lebendige, driftfreie Lokalisierung — **keine maschinelle Übersetzung.**
- **Umfang**: ~412 `.py` / ~79 k Zeilen / 41 Pakete / 36 Plugins.
- **Version**: `v0.3.0` (eine `0.x`-Linie — die API ist noch nicht eingefroren); Breaking-Anpassungen mit Vorankündigung + Migrationshinweisen, `1.0` ist für den API-Freeze reserviert.
- **Tiefgang**: Signaturen der neun Engines und ein Tool-Tutorial stehen im Anhang von `README_zh-CN.md`.

---

## Vollständig lokal & offline · keine Anmeldung

Tuan-CLI **bietet keine Anmeldung**: keine GitHub-/Apple-/DeepSeek-Bindung, kein OAuth-Callback, kein Token auf der Festplatte. Das ist Absicht — **alles läuft lokal, außer der Modell-API, die Sie selbst konfigurieren**.

- **Voll nutzbar ohne Anmeldung**: Datei-I/O, Befehlsausführung, Speicher, Skills, Subagents und der Sicherheits-Gate laufen lokal.
- **Das einzige „Cloud" ist Ihre Modell-API**: der Schlüssel gehört Ihnen, wird nur an diesen Endpunkt gesendet, ohne Dritte.
- **Für eine Pipeline ganz ohne Netz**: Ollama oder llama.cpp installieren — `qxt models local` zum Erkennen, `qxt models set ollama <Modell>` zum Nutzen.

### Modell-API-Schlüssel konfigurieren

```bash
qxt models set deepseek deepseek-chat   # Anbieter und Modell wählen
qxt models                              # interaktive Einrichtung (Schlüssel in ~/.qingxiaotuan/.env)
```

Schlüssel liegen in `~/.qingxiaotuan/.env` (chmod 600, nie committen); Umgebungsvariablen (z. B. `DEEPSEEK_API_KEY`) funktionieren ebenfalls.

> **Transparenz**: frühere Versionen boten GitHub-/Apple-/DeepSeek-Anmeldung (inkl. Web-Session-Token-Pfad). Das widersprach der Positionierung „vollständig lokal & offline", und der Web-Endpunkt war eine private, nicht unterstützte Schnittstelle, die Risikokontrollen auslöste — die Fähigkeit wurde daher **vollständig entfernt**. Modellaufrufe laufen über offizielle APIs mit Ihrem eigenen Schlüssel.

## Lizenz & Links

- **Lizenz**: MIT (nutzen, ändern, weitergeben; Hinweis behalten)
- **Lies das**: [SECURITY.md](SECURITY.md) · [CHANGELOG.md](CHANGELOG.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [NOTICE](NOTICE)

> Du willst »Haecke auf, closed, an einen Anbieter gebunden«? Davon gibt's genug. Du willst **auf deinen eigenen Modellen laufen, die Kontrolle behalten und im Notfall zurückrollen**? Hier liegen die Schlüssel.