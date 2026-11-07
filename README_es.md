# Tuan-CLI

> **«Model + Harness = Agent.»** — separa «cómo pensar» de «cómo ejecutarlo a salvo» y te entrega las dos llaves.
> Un harness de agentes de IA en Python puro, seguro por diseño y sin ataduras a ningún modelo. `v0.3.4` · MIT · Python ≥ 3.10

> ### Posicionamiento: un agente safety-first — sin sacrificar la experiencia del desarrollador
>
> **La seguridad es prioridad, no opción** — y **interrumpir no es sustituto de seguridad**.
>
> - **Seguridad primero**: los comandos peligrosos se bloquean *antes* de ejecutarse (vista previa de radio de impacto → línea roja dura → confirmación multinivel). Cada escritura queda registrada en un libro transaccional para un `/undo` exacto.
> - **Semántica de seguridad**: YOLO/`--yolo` aprueba automáticamente las operaciones que normalmente requieren confirmación, pero **no** elude las líneas rojas duras. `--isolation` proporciona aislamiento a nivel de motor/proceso para reducir el radio de impacto y contener fallos; **no** es un sandbox completo del sistema operativo ni sustituye la aprobación de comandos.
> - **Experiencia del desarrollador preservada**: lecturas/escrituras de archivos, operaciones `git` rutinarias, instalación de paquetes, corridas de tests y linters se puntúan `none` — **cero confirmaciones, cero bloqueos** (`safety_engine.is_benign_dev_command`). Solo acciones genuinamente peligrosas escalan a consejo o bloqueo.
> - **Mediciones reproducibles**: nuestra meta es «menos comandos peligrosos se escapan, menos comandos inofensivos molestan», y cualquier número que publiquemos **debe poder reproducirlo un tercero** — sin promesas absolutas inverificables. Los benchmarks viven en [`bench/`](bench/README.md): 10k muestras adversariales bash/generic + 5k muestras de PowerShell + 2.497 payloads de bypass hechos a mano (con assertions de nivel de consecuencia catastrófica). **Un solo comando, `tuan safe bench`, reproduce todo en local** (sin red, sin modelo); `tuan safe report` emite un informe de seguridad HTML autocontenido. Código actual medido (2026-10): adversarial 10k → recall de bloqueo 100 % / recall de flag 100 % / falso positivo 0,45 % (5) / bypass 0; PowerShell 5k → precisión 100 % / fallos 0 / falsos positivos 0; matriz de bypass 2.497 payloads → bypass 0 / falso positivo 1 / clases de intención catastrófica 100 % bloqueadas. Quedan algunas escalaciones deliberadamente conservadoras de fail-closed (p. ej. probes de puerto con `nc`, payloads con forma de exfiltración `tar|ssh`) que explican las cifras de falsos positivos; por favor vuelven a correr en local.
> - **Interoperabilidad de ecosistemas**: no reconstruimos ecosistemas — **reutilizamos lo que Claude Code / Hermes Agent ya acumularon** en esta máquina (skills, agentes nombrados, memoria, SOUL persona, configs MCP). `tuan ecosystem` mueve assets en ambos sentidos en un solo comando; `tuan ecosystem link` monta tuan de vuelta en ellos sobre MCP. Un harness, el equivalente a tres ecosistemas en assets.

**Idioma/Language:** [English](README.md) · [简体中文](README_zh-CN.md) · [繁體中文](README_zh-GAT.md) · [日本語](README_ja.md) · [한국어](README_ko.md) · **Español** · [Português (Brasil)](README_pt-BR.md) · [Français](README_fr.md) · [Deutsch](README_de.md) · [Русский](README_ru.md)

**Antes de abrir la caja:** [SECURITY.md](SECURITY.md) · [CHANGELOG.md](CHANGELOG.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · `tuan models list-providers`

**Quick Start:**
- 🚀 **A empezar en 3 pasos:** `pip install tuan-cli` → `tuan setup` → `tuan "tu tarea"`
- 📖 **Guía completa:** [docs/QUICKSTART.md](docs/QUICKSTART.md) — incluye árboles de decisión, escenarios comunes y FAQ
- 🎯 **Referencia rápida:** `tuan help quickstart` — muestra la guía de inicio directo en la terminal

---

## TL;DR

La idea central: **el modelo piensa; el harness hace que ese pensamiento corra de forma segura y controlada.** Tuan-CLI desacopla «el modelo» de «el host»: hot-swap entre muchos proveedores, correr completamente offline, revertir errores destructivos y ver el radio de impacto *antes* de que el comando dispare. Busca ser un agente de terminal razonablemente neutral, autoalojable — no un envoltorio cautivo alrededor de un solo proveedor.

**Lo que NO es**: ni un envoltorio cautivo de un modelo (hot-swap / self-host / offline, tú eliges); ni un lacayo de un IDE (es una herramienta de terminal, manejable vía ACP por VSCode/Zed/JetBrains); ni una sola abstracción fugaz (arquitectura de contenedor de plugins para los que construyen, más un `setup` de un solo golpe para el resto).

---

## Por qué es distinto

| Lo | Detalles |
|---|---|
| 🛡️ **Seguridad primero** | Cuatro compuertas: puntuación estática de riesgo, bloqueo previo por radio de impacto, suelo de líneas rojas en YOLO, libro transaccional con `/undo` exacto |
| 🎯 **Experiencia del desarrollador** | Comandos dev inofensivos pasan sin confirmación, `/undo` te tiene cubierto, 40+ comandos slash, `tuan safe allow` para opt-outs explícitos, YOLO para saltarse confirmaciones repetidas |
| 🔌 **Modelo-agnóstico** | 58 proveedores + Ollama local + hot-swap en runtime + enrutado automático (`router.*`) |
| 🧠 **Tres bucles principales** | ReAct / Planner-Execute / DevLoop — enchufables; un solo kernel, diferentes «ritmos de pensamiento» |
| 🔧 **Contenedor de Plugins** | `@plugin` de una línea, registro de servicios, bus de eventos append-only, middleware de hooks |
| 🗂️ **Memoria** | SQLite FTS5 + stream de eventos de sesión; memoria de tres niveles, `/undo`, checkpoint, replay, exportar Trajectory |
| 🧩 **Ecosistema** | MCP + ACP + **interoperabilidad con Claude Code / Hermes Agent**: skills / agentes nombrados / memoria / SOUL / configs MCP viajan en ambos sentidos (`tuan ecosystem`), de fábrica |
| 🌍 **Diez idiomas** | zh-CN por defecto, localización nativa de toda la interfaz |
| 🐍 **Python puro** | Base de código `.py` extensa, licencia MIT |

---

## Respuestas directas

**Q: ¿Esto es realmente independiente? ¿Cuánto es desarrollado en casa?**
Dos cosas, mantenidas separadas. **El código es escrito por nosotros**: el kernel y la inmensa mayoría de capacidades (`core/`, `runtime/`, `arch/`, `tools/`, `ports/`…) se construyeron línea por línea en Python, alineados a protocolos externos solo por interoperabilidad. **Las ideas y el diseño son tomadas prestadas** — este proyecto fusiona deliberadamente conceptos de proyectos de agentes conocidos, y decirlo abiertamente vale más que esconderlo. La única parte donde se conserva incluso el *estilo* es la piel de terminal `--tui`, que siguiendo a propósito la sensación de interacción y paleta distintivas de **Kimi Code** (`#4FA8FF` primario, el spinner de fases lunares, la barra de estado de dos líneas), acreditado en [NOTICE](NOTICE). La lista completa de atribución está en [Inspiración y atribución](#inspiración-y-atribución). **El código es nuestro; las ideas son compartidas.**

**Q: ¿Por qué me bloquea antes de ejecutar comandos?**
Es función, no bug. Los comandos peligrosos piden primero; YOLO respeta las líneas rojas duras. ¿Es demasiado parlanchín? `tuan safe allow <cmd>` para la lista blanca — no desactives la seguridad.

**Q: Entonces, cuando me bloquea, ¿estoy atascado?**
No. Cada bloqueo/confirmación lleva **alternativas seguras conscientes del comando** (`tuan safe suggest <cmd>` consultable en cualquier momento): `git push --force` → `--force-with-lease`, `rm -rf` → receta para la papelera/reciclaje, `curl | sh` → «descarga y revisa primero». No nos limitamos a detenerte — te llevamos al camino seguro para lograrlo.

**Q: ¿Qué puede revertir `/undo` realmente?**
Cada **escritura** que pase por el libro: un solo archivo, un solo paso, un turno entero. Por debajo es el libro transaccional + `reverse_transform` de diff + snapshots de checkpoint. No es cura milagrosa, pero convierte un descuido de pérdida garantizada en un salvamento probable.

**Q: ¿Leerá mis archivos privados?**
El alcance de las herramientas está acotado por una allow-list de dominios, la salida de red está regateada contra exfiltración y los secretos se enmascaran en la salida. Los valores por defecto y lo que puedes ajustar están en [SECURITY.md](SECURITY.md).

**Q: ¿Completamente offline?**
`tuan models local` para sondear, `/offline` para gestionar Ollama. Sin internet, sin problema.

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

## Número de versión

**¿Por qué `0.3.4` y no `1.0`?** Semántica [SemVer](https://semver.org/) honesta: **una versión `0.x` significa que la API pública (superficie CLI, esquema de configuración, protocolo de herramientas, contrato de plugins) aún no está congelada** y puede cambiar entre lanzamientos. Tuan-CLI ya trae un amplio conjunto de funciones — control de seguridad / rollback transaccional, hot-swap modelo-neutro (58 proveedores + Ollama local), tres bucles principales, arquitectura de contenedor de plugins, memoria de tres niveles, interoperabilidad de ecosistemas (MCP / ACP / puente Claude Code / Hermes), subagentes y Swarm, cron y tareas en segundo plano, modo Goal y permisos precisos — todo cubierto por pruebas. Pero **el número de versión refleja la estabilidad de la interfaz, no la completitud de funciones**: un conjunto completo de funciones no significa que la API deba congelarse. `1.0` se reserva para cuando la API pública sea verdaderamente estable y podamos prometer compatibilidad hacia atrás. Hasta entonces: los cambios disruptivos suben MINOR dentro de `0.x` (con pistas de migración), funciones compatibles suben MINOR, correcciones suben PATCH (ver [VERSION_POLICY.md](VERSION_POLICY.md)).

| Semántica de versión | Significado |
|---|---|
| `0.3.4` (actual) | **API aún no congelada**: `0.x` permite ajustes disruptivos, anunciados con pistas de migración; no se promete compatibilidad hacia atrás |
| `1.0` (reservado) | Se habilita cuando la API pública se congele y se prometa compatibilidad hacia atrás; solo entonces los cambios disruptivos suben MAJOR (`2.0`) |

---

## Inspiración y atribución

Tuan-CLI no nació de la nada: su diseño se construye explícitamente sobre los siguientes proyectos y protocolos de agentes conocidos. Los listamos abiertamente (y anotamos la fuente original en comentarios del código donde corresponde):

| Fuente | Qué tomamos prestado |
|---|---|
| **DeepSeek Harness / Cordis** | Arquitectura de contenedor de plugins + registro de servicios + bus de eventos append-only (anotado en `core/kernel.py`) |
| **Kimi Code** | El tacto de interacción del TUI de terminal y la paleta (ver [NOTICE](NOTICE)) |
| **Claude Code** | Sistema de comandos `/`, agentes nombrados (compatible `.claude/agents`), modo Goal, DevLoop — alineación de interfaz |
| **Hermes Agent** | Memoria de tres niveles, bucle de auto-evolución de skills, identidad SOUL, herramientas auto-registrables, semántica cron — alineado; `tuan ecosystem` sincroniza memoria/skills/SOUL bidireccionalmente con él |
| **ACP (Agent Client Protocol)** | Como client/server, alineado a la semántica de mensajes y handshake para que un IDE maneje Tuan-CLI |
| **MCP (Model Context Protocol)** | Como client, alineado al protocolo para enchufarse al ecosistema de herramientas |
| **APIs de OpenAI / Anthropic / Google, etc.** | Adaptadores de proveedor implementados según la semántica REST oficial — solo adaptación de protocolo, sin replicar el interior |

> Límite: el **código** es desarrollado en casa; los **protocolos/interfaces** se alinean; las **ideas/diseños** se toman prestadas y fusionan. Donde se referencia un detalle de implementación concreto, se declara en los comentarios del código y en [NOTICE](NOTICE).

---

## Inicio rápido

```bash
# 1) Instalar (—[dev] es el stack completo; baja a [openai]/[mcp] si solo necesitas APIs)
git clone <este repositorio> && cd tuan-cli
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# 2) Apuntar a un proveedor (14 perfiles integrados: deepseek / groq-free / siliconflow-free / ollama…)
tuan setup
# o a mano: ~/.tuan/config.yaml
#   model.provider: deepseek
#   model.model: deepseek-chat
#   model.api_key_env: DEEPSEEK_API_KEY      # las claves nunca en texto plano

# 3) Chatear
tuan
# o un smoke test:
tuan --print run "Hola, descríbete en una frase."
```

---

## Superficie de comandos: 50 subcomandos principales + comandos slash

| Comando | Para qué |
|---|---|
| `tuan` | TUI interactivo (skin de Kimi Code) |
| `tuan setup` / `tuan models` | Configurar proveedores / listar 58 proveedores y 1400+ modelos |
| `tuan sessions` / `--continue` / `--resume <id>` / `setup --skip` | Listar/reanudar/eliminar sesiones guardadas; reanudar directamente desde la CLI; el asistente de configuración se ejecuta en el primer arranque (`setup --skip` lo omite) |
| `tuan models update` | Actualizar el catálogo de modelos/proveedores en local: fusiona las listas integradas en `~/.tuan/models_catalog.json` (offline, preserva entradas añadidas por el usuario; `--check` reporta solo diffs, `--background` corre asíncrono) |
| `tuan agent` | Agentes nombrados (compatible `.claude/agents`, descubrimiento de 3 niveles) |
| `tuan acp` | Arranca un servidor ACP para que VSCode / Zed / JetBrains te maneje |
| `tuan ecosystem` | **Interoperabilidad de ecosistemas**: `scan` sondea Claude Code / Hermes; `import` trae sus skills/agents/memoria/SOUL/configs MCP a tuan; `export` empuja de vuelta; `link` monta tuan de vuelta en ellos sobre MCP; `serve` corre el servidor MCP (ver [docs/ecosystem_bridge.md](docs/ecosystem_bridge.md)) |
| `tuan cron` | Tareas programadas en segundo plano |
| `tuan doctor [--compact]` | Revisión de salud (agrega `--compact` para auto-revisión de supervivencia ante compaction de contexto) |
| `tuan dev codedev ...` | Subsistema de code-dev (recuperación / verificación / descomposición) |

Comandos slash del día a día: `/plan`·`/model`·`/undo`·`/impact`·`/swarm`·`/log`·`/stats`·`/cost`·`/budget`·`/goal`·`/sandbox`·`/offline`·`/verify`·`/audit`·`/more`·`/help` — lista completa con `Ctrl-G` en el TUI.

---

## Interoperabilidad de ecosistemas: Claude Code / Hermes Agent de fábrica

Más allá de «seguridad primero» y «modelo-agnóstico», la tercera pata es: **no reconstruir ecosistemas — reutilizar lo que otros ecosistemas de agentes ya acumularon.** Skills (el estándar abierto SKILL.md), agentes nombrados (`.claude/agents`), memoria y persona (el `MEMORY.md` / `USER.md` / `SOUL.md` de Hermes), archivos de contexto (`AGENTS.md` / `CLAUDE.md`) y configs de servidores MCP son estructuralmente casi idénticos entre los tres — tuan los puentea:

```bash
tuan ecosystem scan                        # sondea Claude Code / Hermes + sus assets (solo lectura)
tuan ecosystem import all                  # trae skills/agents/memoria/SOUL/configs MCP de ambos lados a tuan
tuan ecosystem export skills --to claude   # skills de tuan → .claude/skills (Hermes: --to hermes)
tuan ecosystem link                        # montaje inverso: Claude Code/Hermes llaman a tuan sobre MCP
```

- **Automático en la sesión**: las skills que Claude Code o Hermes ya instalaron están disponibles en tuan de inmediato (`~/.claude/skills`, `~/.hermes/skills` están en la ruta de búsqueda); `tuan ecosystem serve` expone tuan como servidor MCP para que las sesiones de Claude Code / Hermes ganen herramientas `tuan_*` (búsqueda/escritura de memoria, listado/lectura de skills, despacho headless de tareas).
- **Delegar, no migrar**: las herramientas `claude_code_run` / `hermes_run` entregan tareas al entorno nativo completo del otro agente (su propia config, memoria, skills, MCP).
- Documento completo: [`docs/ecosystem_bridge.md`](docs/ecosystem_bridge.md) (mapa de formatos / diseño de seguridad / layout).

---

## Tres bucles principales, una mano firme

- **ReActLoop** — piensa → actúa → observa, el ritmo por defecto.
- **PlannerExecuteLoop** — un modelo fuerte planifica, uno más barato ejecuta (`router.*` soporta compartimentar plan/ejecución). Un patrón que ahorra tokens.
- **DevLoop** — escribe-verifica-sana: `/verify` detecta automáticamente el proyecto (Python/Node/Rust/Go), infiere comandos de test y se auto-cura hasta N rondas.

---

## El modelo de seguridad: cuatro compuertas + undo en libro

1. **Puntuación estática** — cada comando shell puntuado de `none→critical` vía la fachada `SafetyEngine.score(params)`, con despliegue de expansiones indirectas (IFS, `$VAR`, sustitución de comandos, escapes ANSI-C/octal/hex, Base64 de PowerShell, NFKC; ≤32 de recursión).
2. **Bloqueo previo por radio de impacto** — ves lo que tocará *antes* de que dispare (`--impact`).
3. **Suelo de líneas rojas en YOLO** — YOLO elimina las confirmaciones por paso pero **no puede** tocar las líneas rojas duras (`rm` recursivo, force-push, `chmod -R 000 /`… jamás se ejecutan solos).
4. **Libro transaccional** — cada escritura tiene una pista de auditoría; `/undo` restaura vía `reverse_transform` de diff + snapshots.

Las reglas siempre resuelven `deny > ask > allow`. Usa `tuan safe allow <cmd>` para la lista blanca; nunca desactives la seguridad para ahorrar clics.

---

## Benchmarks de seguridad: reproducibles con un solo comando

`tuan safe bench` empaqueta las tres suites reproducibles en un solo comando (totalmente en local, sin modelo — cualquier tercero puede re-correrlas tal cual):

- **Corpus adversarial** `bench/safety_bench_10k.py` — 10.000 comandos bash/generic (sembrados 20260906, reproducibles); reporta recall de bloqueo / recall de flag / tasa de falsos positivos / bypasses.
- **Corpus de PowerShell** `bench/bench_powershell_safety.py` — 5.000 muestras (2.300 peligrosas / 2.700 inofensivas); reporta precisión / fallos / falsos positivos.
- **Matriz de bypass** `bench/bypass_matrix.py` — 2.497 payloads adversariales hechos a mano; además del patrón, asiente **por clase de consecuencia catastrófica** si cada clase de intención catastrófica fue realmente bloqueada.

```bash
tuan safe bench                 # corrida completa (~3 min)
tuan safe bench --quick         # auto-revisión rápida (~30 s)
tuan safe bench --check         # compara contra archivo; exit 1 si hay regresión (gate)
tuan safe report                # informe de seguridad HTML autocontenido (compartible)
tuan safe report --release      # RELEASE: números + timestamp + commit git ligados (sin números viejos)
```

Medido en el código actual (2026-10-25, reproducible vía `tuan safe bench`):

| Suite | Tamaño | Métrica principal | Bypasses | Falsos positivos |
|---|---|---|---|---|
| Adversarial | 10.000 | recall de bloqueo 100 % · recall de flag 100 % · FP 0,45 % (5) | 0 | — |
| PowerShell | 5.000 | precisión 100 % · fallos 0 | 0 | 0 |
| Matriz de bypass | 2.497 | clases de intención catastrófica 100 % bloqueadas | 0 | 1 |

Aviso: la matriz de bypass es deliberadamente fail-closed y mantiene algunas escalaciones conservadoras (probes Unicode-variante de `nc`, payloads con forma de exfiltración `tar|ssh`), que producen falsos positivos «inofensivo pero marcado»; el 0,45 % (5) de FP en la suite adversarial viene del mismo conservadurismo (5 variantes del mismo caso benigno `tar|ssh`, todas solo marcadas, ninguna bloqueada). Los números son autoritativos como se re-corren en local con `tuan safe bench`.

**Gate de números en CI**: el job `safety-benchmarks` en `.github/workflows/security-ci.yml` vuelve a correr las tres suites en cada push y las compara contra el archivo comprometido — cualquier regresión (bypasses, una clase de desastre ya no se bloquea completa, un aumento claro de FP) **hace fallar la CI**. El archivo `bench/security-bench.json` corresponde 1:1 con la tabla del README.

---

## Cara a cara vs Claude Code: un solo comando

Más allá de las suites de seguridad auto-medidas, `bench/vs_claude.py` corre **el mismo set de tareas en ambos agentes** y renderiza un lado a lado honesto: misma `bench/tasks.yaml`, mismos scripts de aceptación, workspaces aislados, `tuan run -p` vs `claude -p --output-format json`.

```bash
python bench/vs_claude.py --dry --tuan .venv/Scripts/tuan.exe   # solo chequeo de framework, sin llamadas a modelo
python bench/vs_claude.py --tuan .venv/Scripts/tuan.exe         # corridas real (necesita endpoints funcionando en ambos lados)
python bench/vs_claude.py --task fix_bug --model openrouter/deepseek/deepseek-chat
python bench/vs_claude.py --claude "C:\path\claude.cmd" --json
```

Escribe `bench/vs_report.md` / `.json` / `.html` con tasa de aprobación, tiempo en pared, costo y cuentas de rechazos de permisos por tarea.

**Contrato de honestidad**: el runner primero sondea si `claude -p` puede completar una vuelta; si la sonda falla, la columna de Claude se marca **N/A con la razón exacta** — nunca da por hecho que el comparación ocurrió. Los números se vuelven significativos solo cuando ambos endpoints funcionan en tu máquina; ese es el punto de la medición reproducible. Nota para Windows: `claude` instalado por npm es un shim `.ps1`/`.cmd` — el script resuelve el ejecutable real automáticamente, y las versiones viejas que rechazan `--no-input` se manejan vía redirección de stdin.

---

## Dónde corren tus ideas

- **Memoria** — tres niveles (usuario/proyecto/sesión) + SQLite FTS5 (trigram), degrada a texto plano si no está disponible.
- **Subagentes** — delegación tipada (general-purpose / explore / plan / coder), subagentes aislados, workers concurrentes y Swarm para trocear tareas largas.
- **Cron y segundo plano** — `tuan cron start --detach`; autonomía headless.
- **Hooks** — `PreToolUse` puede `block` o reescribir `args` (`hooks.allow_edit_args`) — una gran costura para los que construyen.
- **Observabilidad** — `/stats`·`/audit`·`/impact`·`/bench`·`/cost`; el costo sobre la mesa.
- **crypto** — AES-GCM(AEAD) con `cryptography`, si no cifra de flujo HMAC-SHA256 como respaldo; `open()` con MAC ausente / manipulada siempre hace fail-closed.

---

## Dev y contrato

```bash
python -m pytest tests/ -q        # suite grande
python -m mypy tuan_cli       # puerta de tipos
tuan --print run "Hola. Una línea."  # humo
```

- **Disciplina i18n**: README_zh-CN es el maestro autoritativo; cada idioma es una localización viva, sin deriva — **nada de traducción mecánica.**
- **Versión**: `v0.3.4` (una línea `0.x` — la API aún no está congelada); los ajustes disruptivos llegan con aviso previo + notas de migración, y `1.0` está reservado para el congelamiento de la API.
- **A fondo**: firmas de los motores y un paseo paso a paso de herramienta nueva viven en el apéndice de `README_zh-CN.md`.

---

## Totalmente local y offline · sin inicio de sesión

Tuan-CLI **no ofrece inicio de sesión**: sin vinculación con GitHub / Apple / DeepSeek, sin callback OAuth, sin tokens en disco. Es deliberado — **todo se ejecuta en local salvo la API del modelo que tú configures**.

- **Totalmente usable sin iniciar sesión**: E/S de archivos, ejecución de comandos, memoria, skills, subagentes y la barrera de seguridad son locales.
- **Lo único «en la nube» es tu API de modelo**: la clave es tuya, se envía solo a ese endpoint y sin intermediarios de terceros.
- **Si quieres un flujo sin red**: instala Ollama o llama.cpp — `tuan models local` para detectar, `tuan models set ollama <modelo>` para usarlo.

### Configurar la clave de API del modelo

```bash
tuan models set deepseek deepseek-chat   # elegir proveedor y modelo
tuan models                              # configuración interactiva (clave en ~/.tuan/.env)
```

Las claves viven en `~/.tuan/.env` (chmod 600, nunca commitear); las variables de entorno (p. ej. `DEEPSEEK_API_KEY`) también sirven.

## Licencia y enlaces

- **Licencia**: MIT (úsalo, modifícalo, redistribúyelo; conserva el aviso)
- **Léete esto**: [SECURITY.md](SECURITY.md) · [CHANGELOG.md](CHANGELOG.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [NOTICE](NOTICE)

> ¿Quieres «experiencia cerrada, de caja, casada con un proveedor»? Eso abunda. ¿Quieres **correr con tus propios modelos, mantener el control y poder echarte atrás cuando algo sale mal**? Las llaves están aquí.
