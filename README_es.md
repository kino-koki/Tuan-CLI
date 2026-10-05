# Tuan-CLI

> **«Model + Harness = Agent»** — separa «pensar» de «correr a salvo» y te entrega ambas llaves.
> Un harness de agentes de IA en Python puro, seguro por diseño y sin ataduras a ningún modelo. `v0.2.018` · MIT · Python ≥ 3.10

**Idioma/Language:** [English](README.md) · [简体中文](README_zh-CN.md) · [繁體中文](README_zh-GAT.md) · [日本語](README_ja.md) · [한국어](README_ko.md) · **Español** · [Português (Brasil)](README_pt-BR.md) · [Français](README_fr.md) · [Deutsch](README_de.md) · [Русский](README_ru.md)

**Antes de abrir la caja:** [SECURITY.md](SECURITY.md) · [CHANGELOG.md](CHANGELOG.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · `qxt models list-providers`

---

## En una frase

La mayoría de los CLIs de agentes nacen *casados con un proveedor*. Este es lo contrario: un **chasis sin cerebro fijo**. Cambia entre 51 proveedores al vuelo, corre 100 % offline, revierte tus meteduras de pata y te muestra el radio de impacto **antes** de que el comando dispare. **El modelo piensa; él hace que no explote todo.**

**Lo que NO es**: ni un envoltorio cautivo de un modelo (hot-swap / self-host / offline, tú eliges); ni un lacayo de un IDE (es una herramienta de terminal, a la que además puedes manejar por ACP desde VSCode/Zed/JetBrains); ni una abstracción insegura de una sola capa (arquitectura de microkernel para los que saben + un `setup` de un clic para el resto).

---

## Por qué es distinto

| Lo que da | Hasta dónde llega |
|---|---|
| 🛡️ **Seguridad ante todo** | Cuatro compuertas: puntuación estática de riesgo, bloqueo por radio de impacto, suelo de líneas rojas en YOLO, y libro de contabilidad transaccional con `/undo` de precisión |
| 🔌 **Sin ataduras de modelo** | 51 proveedores + Ollama local + hot-swap + enrutado automático (`router.*`) |
| 🧠 **Tres bucles principales** | ReAct / Planner-Execute / DevLoop — enchufables: un mismo kernel, distintos «ritmos de pensamiento» |
| 🔧 **Microkernel** | Un `@plugin` de una línea, registro de servicios, bus de eventos append-only, middleware de hooks |
| 🗂️ **Memoria** | SQLite FTS5 + stream de eventos de sesión; memoria de 3 niveles, `/undo`, checkpoint, replay, exportar Trajectory |
| 🧩 **Ecosistema** | MCP + ACP — enchufa herramientas o deja que tu IDE te maneje |
| 🌍 **Diez idiomas** | por defecto simplificado, con localización real de la interfaz |
| 🐍 **Python puro** | ~412 `.py` / ~79 k líneas / 41 paquetes / 36 plugins, MIT |

---

## Sin rodeos

**Q: ¿Esto es «hecho en casa» de verdad? ¿Hay algún esqueleto en el armario?**
Son dos cosas, por separado. **El código es propio**: el kernel y la inmensa mayoría de las capacidades (`core/`, `runtime/`, `arch/`, `tools/`, `ports/`…) están escritos línea a línea en Python, alineados a los **protocolos** externos solo para interoperar. Pero **las ideas y el diseño sí se toman prestados** de proyectos de agentes conocidos — y no es nada que ocultar, es justo pararse sobre hombros de gigantes. **El código es nuestro; las ideas son compartidas.** La única parte donde se conserva incluso el *estilo* es la piel del TUI `--tui`, que mantiene a propósito el estilo y la paleta de **Kimi Code** (`#4FA8FF`, el spinner de fases lunares, la barra de dos líneas); está acreditado en [NOTICE](NOTICE). La lista completa de atribución está en [Inspiración y atribución](#inspiración-y-atribución).

**Q: ¿Por qué me bloquea antes de ejecutar comandos?**
Es una función, no un bug. Los comandos peligrosos piden permiso primero; YOLO respeta las líneas rojas. Si es muy pesado, `qxt safe allow <cmd>` para ponerlo en la lista blanca — no desactives la seguridad.

**Q: ¿Qué puede revertir `/undo` realmente?**
Toda **escritura** que pase por el libro de contabilidad: un solo archivo, un solo paso, un turno completo. Por dentro es el libro transaccional + `reverse_transform` de diff + snapshots de checkpoint. No es milagroso, pero convierte «la cagué» en «quizá la salvo».

**Q: ¿Leerá mis archivos privados?**
El alcance de las herramientas está limitado por una allow-list de dominios, la salida de red está controlada para evitar exfiltración y las claves se enmascaran en la salida.

**Q: ¿Offline total?**
`qxt models local` para sondear, `/offline` para gestionar Ollama. Sin internet, sin problema.

**Q: ¿Puedo escribir mis propias herramientas/plugins?**
Sí — metadatos con `@plugin`, `activate(kernel)` + `kernel.provide(...)` / `kernel.require(...)`. Tres pasos:

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

## Número de versión e historial del repositorio (divulgación transparente)

**¿Por qué la versión se queda en `0.x`?** Tuan-CLI sigue [SemVer](https://semver.org/): `0.x` significa que **la API aún no está congelada** — los cambios disruptivos se anuncian con antelación y se ofrecen pistas de migración (ver [VERSION_POLICY.md](VERSION_POLICY.md)). **El número de versión refleja la estabilidad de la interfaz, no la completitud de funciones.** En cuanto a capacidad, el `0.2.x` actual ofrece lo que productos comparables de Agent CLI llaman un **conjunto de funciones de nivel 2.x** — control de seguridad/rollback transaccional, cambio en caliente independiente del modelo (51 proveedores + Ollama local), tres bucles principales, arquitectura de microkernel con plugins, memoria de tres niveles, interoperabilidad de ecosistemas (puente MCP/ACP/Claude Code/Hermes), subagentes y Swarm, cron y tareas en segundo plano, modo Goal y permisos precisos — todo publicado y cubierto por pruebas. En una frase: **la madurez funcional está en "2.x"; la versión se queda en "0.x" porque mantenemos el criterio de que 1.0 solo llega tras congelar la API** — no por falta de capacidad.

| Semántica de versión | Significado |
|---|---|
| `0.x` (actual) | API sin congelar: cambios disruptivos anunciados + pistas de migración; completitud funcional a la par de competidores 2.x |
| `1.0` (planificado) | Se publica al congelar la API; a partir de ahí el número refleja directamente la estabilidad de la interfaz |

**Nota sobre el historial de Git (transparencia de código abierto):** El historial de commits de este repositorio se **reconstruyó el 2026-09-26 tras corromperse el repositorio local**; la evolución commit a commit anterior a esa fecha ya no es recuperable (se perdieron los objetos antiguos de `.git`). El código actual es totalmente revisable, de la arquitectura a la implementación; para la evolución de funciones anterior a 2026-09-26, confía en los registros de versión de [CHANGELOG.md](CHANGELOG.md) (la disciplina de versiones no se ve afectada). Elegimos divulgar esto sin adornos — sin pulir ni ocultar.

---

## Inspiración y atribución

Tuan-CLI no salió de la nada: su diseño se apoya explícitamente en los siguientes proyectos y protocolos de agentes conocidos. Los listamos sin esconder nada (y anotamos la fuente original en comentarios del código donde corresponde):

| Fuente | Qué tomamos prestado |
|---|---|
| **DeepSeek Harness / Cordis** | Arquitectura de microkernel + registro de servicios + bus de eventos append-only (anotado en `core/kernel.py`) |
| **Kimi Code** | El tacto y la paleta del TUI de terminal (ver [NOTICE](NOTICE)) |
| **Claude Code** | Sistema de comandos `/`, agentes con nombre (compatible `.claude/agents`), modo Goal, DevLoop — alineación de interfaz |
| **ACP (Agent Client Protocol)** | Como server/client, alineado a la semántica de mensajes y handshake para que un IDE maneje Tuan-CLI |
| **MCP (Model Context Protocol)** | Como client, alineado al protocolo para enchufarse al ecosistema de herramientas |
| **APIs de OpenAI / Anthropic / Google, etc.** | Adaptadores de proveedor implementados según la semántica REST oficial — solo adaptación de protocolo, sin replicar el interior |

> Límite: el **código** es propio; los **protocolos/interfaces** se alinean; las **ideas/diseños** se toman prestados y fusionan. Donde se referencia un detalle de implementación concreto, se declara en los comentarios del código y en [NOTICE](NOTICE).

---

## Inicio rápido

```bash
git clone <este repositorio> && cd tuan-cli
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

qxt setup
# o a mano: ~/.qingxiaotuan/config.yaml
#   model.provider: deepseek
#   model.model: deepseek-chat
#   model.api_key_env: DEEPSEEK_API_KEY      # las claves nunca en texto plano

qxt            # a chatear
qxt --print run "Hola, preséntate en una frase."
```

---

## Superficie de comandos: 105 subcomandos + 46 comandos slash

| Comando | Para qué |
|---|---|
| `qxt` | TUI interactivo (skin de Kimi Code) |
| `qxt setup` / `qxt models` | Configurar proveedor / listar 51 proveedores y 1100+ modelos |
| `qxt agent` | Agentes con nombre (compatible `.claude/agents`, descubrimiento de 3 niveles) |
| `qxt acp` | Arranca un server ACP para que VSCode / Zed / JetBrains te maneje |
| `qxt cron` | Tareas programadas en segundo plano |
| `qxt doctor` / `qxt bench` | Revisión de salud / benchmark |
| `qxt arch demo` | Verifica de un comando la arquitectura de 5 capas |

Slash que vas a vivir en ellos: `/plan`·`/model`·`/undo`·`/impact`·`/swarm`·`/log`·`/stats`·`/cost`·`/budget`·`/goal`·`/sandbox`·`/offline`·`/verify`·`/audit`·`/more`·`/help` — lista completa con `Ctrl-G` en el TUI.

---

## Tres bucles, una mano firme

- **ReActLoop** — piensa → actúa → observa, el ritmo por defecto.
- **PlannerExecuteLoop** — un modelo fuerte planifica, uno barato ejecuta (`router.*` permite compartimentar plan/ejecución). El ahorrador de tokens.
- **DevLoop** — escribe-verifica-sana: `/verify` detecta el proyecto (Python/Node/Rust/Go), infiere los comandos de test y se cura solo hasta N rondas.

## El modelo de seguridad: cuatro compuertas + deshacer con contabilidad

1. **Puntuación estática** — todo comando de shell puntuado `none→critical` por `safety_engine.score()`, con expansión de indirectas (IFS, `$VAR`, sustitución, escapes ANSI-C/octal/hex, PowerShell Base64, NFKC; ≤32 de recursión).
2. **Bloqueo por radio de impacto** — ves lo que tocará **antes** de que dispare (`--impact`).
3. **Suelo de líneas rojas en YOLO** — YOLO elimina confirmaciones por paso pero **no puede** tocar las líneas rojas (recursivo `rm`, force-push, `chmod -R 000 /`… jamás en automático).
4. **Libro de contabilidad** — todo write queda auditado; `/undo` restaura con diff `reverse_transform` + snapshots.

Las reglas resuelven siempre `deny > ask > allow`. Usa `qxt safe allow <cmd>` para la lista blanca; no desactives seguridad para ahorrar clics.

---

## Dónde corren tus ideas

- **Memoria** — tres niveles (usuario/proyecto/sesión) + SQLite FTS5 (trigram), degrada a texto plano si no está disponible.
- **Subagentes** — delegación tipada (general-purpose / explore / plan / coder), aislamiento, workers concurrentes y Swarm para atacar tareas largas.
- **Cron y segundo plano** — `qxt cron start --detach`; autonomía headless.
- **Hooks** — `PreToolUse` puede `block` o reescribir `args` (`hooks.allow_edit_args`).
- **Observabilidad** — `/stats`·`/audit`·`/impact`·`/bench`·`/cost`; el coste sobre la mesa.
- **crypto** — v2 es sólido: AES-GCM(AEAD) con `cryptography`, si no cifrado de flujo HMAC-SHA256; `open()` con MAC ausente/manipulada siempre hace fail-closed.

---

## Dev & contrato

```bash
python -m pytest tests/ -q        # 2500+ tests
python -m mypy qingxiaotuan       # puerta de tipos
qxt --print run "Hola. Una línea."  # humo
```

- **Disciplina i18n**: README_zh-CN es el maestro autoritativo; cada idioma es una localización viva y sin deriva — **nada de traducción mecánica.**
- **Escala**: ~412 `.py` / ~79 k líneas / 41 paquetes / 36 plugins.
- **Versión**: `v0.2.018` (0.x/Beta); los cambios ruptura avisan con versión minor + notas de migración.
- **A fondo**: firmas de los nueve motores y un tutorial de herramienta nueva viven en el apéndice de `README_zh-CN.md`.

---

## Inicio de sesión: GitHub / Apple / DeepSeek (opcional · offline por defecto)

- Tuan-CLI funciona sin conexión sin ninguna cuenta. El inicio de sesión es una capa opcional.
- `qxt login` / `qxt login github` / `qxt logout` / `qxt whoami`.
- Credenciales en `~/.qingxiaotuan/auth-config.toml` o variables de entorno `QXT_GITHUB_*` / `QXT_APPLE_*` / `QXT_DEEPSEEK_*` (las variables ganan).
- Callback OAuth por defecto `http://127.0.0.1:8765/callback`; `auth.json` guarda tokens en texto plano — protege tu directorio personal y cierra sesión en equipos compartidos.
- Detalles en README_zh-CN.md (maestro) y README.md.

---

## License y enlaces

- **License**: MIT (úsalo, modifícalo, redistribúyelo; conserva el aviso)
- **Léete esto**: [SECURITY.md](SECURITY.md) · [CHANGELOG.md](CHANGELOG.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [NOTICE](NOTICE)

> ¿Quieres «experiencia cerrada, de caja, casada con un vendor»? Eso abunda. ¿Quieres **correr con tus propios modelos, mantener el control y poder echarte atrás cuando algo sale mal**? Las llaves están aquí.