# Qingxiaotuan Agent CLI (青小团)

> **«Model + Harness = Agent»** — separa o «pensar» do «rodar em segurança» e entrega as duas chaves pra você.
> Um harness de agentes de IA em Python puro, seguro por padrão e agnóstico de modelo. `v0.2.017` · MIT · Python ≥ 3.10

**Idioma/Language:** [English](README.md) · [简体中文](README_zh-CN.md) · [繁體中文](README_zh-GAT.md) · [日本語](README_ja.md) · [한국어](README_ko.md) · [Español](README_es.md) · **Português (Brasil)** · [Français](README_fr.md) · [Deutsch](README_de.md) · [Русский](README_ru.md)

**Antes de mexer:** [SECURITY.md](SECURITY.md) · [CHANGELOG.md](CHANGELOG.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · `qxt models list-providers`

---

## Em uma frase

A maioria dos CLIs de agente nasce *casada com um fornecedor*. Esse aqui é o oposto: um **chassi sem cérebro fixo**. Troca entre 51 provedores na hora, roda 100 % offline, desfaz suas cagadas e te mostra o raio de impacto **antes** de o comando disparar. **O modelo pensa; ele cuida pra não explodir tudo.**

**O que NÃO é**: nem um invólucro refém de um modelo (hot-swap / self-host / offline, você escolhe); nem um capacho de IDE (é ferramenta de terminal, e ainda dá pra dirigir por ACP via VSCode/Zed/JetBrains); nem uma abstração frágil de uma camada só (arquitetura de microkernel pra quem manja + um `setup` de um clique pro resto).

---

## Por que é diferente

| O que entrega | Até onde vai |
|---|---|
| 🛡️ **Segurança em primeiro lugar** | Quatro portões: nota estática de risco, bloqueio por raio de impacto, piso de linhas vermelhas no YOLO e razão transacional com `/undo` de precisão |
| 🔌 **Agnóstico de modelo** | 51 provedores + Ollama local + hot-swap + roteamento automático (`router.*`) |
| 🧠 **Três loops principais** | ReAct / Planner-Execute / DevLoop — plugáveis: um kernel, vários «ritmos de pensamento» |
| 🔧 **Microkernel** | `@plugin` de uma linha, registro de serviços, barramento de eventos append-only, middleware de hooks |
| 🗂️ **Memória** | SQLite FTS5 + stream de eventos de sessão; memória em 3 níveis, `/undo`, checkpoint, replay, exportação de Trajectory |
| 🧩 **Ecossistema** | MCP + ACP — encaixa ferramentas ou deixa seu IDE te pilotar |
| 🌍 **Dez idiomas** | chinês simplificado por padrão, com localização de verdade da interface |
| 🐍 **Python puro** | ~412 `.py` / ~79 k linhas / 41 pacotes / 36 plugins, MIT |

---

## Sem rodeio

**Q: Isso aí é «feito em casa» de verdade? Tem esqueleto no armário?**
São duas coisas separadas. **O código é nosso**: o kernel e quase todas as capacidades (`core/`, `runtime/`, `arch/`, `tools/`, `ports/`…) são escritos linha a linha em Python, alinhados aos **protocolos** externos só pra interoperar. Mas **as ideias e o design** vêm de projetos de agentes conhecidos, emprestados e fundidos — e isso não é pra esconder, é se apoiar nas costas de gigantes. **O código é nosso; as ideias são compartilhadas.** A única parte que mantém até o *estilo* é a casca do TUI `--tui`, reprise de propósito o estilo e a paleta do **Kimi Code** (`#4FA8FF`, o spinner de fases da lua, a barra de duas linhas); creditado no [NOTICE](NOTICE). A lista completa de atribuição tá em [Inspiração e atribuição](#inspiração-e-atribuição).

**Q: Por que me bloqueia antes de rodar comando?**
É feature, não bug. Comando perigoso pede confirmação primeiro; o YOLO respeita as linhas vermelhas. Tá loco de chato? `qxt safe allow <cmd>` pra allowlist — não desligue a segurança.

**Q: O que `/undo` desfaz de verdade?**
Toda **escrita** que passa pela razão: um arquivo, um passo, um turno inteiro. Por dentro é razão transacional + diff `reverse_transform` + snapshots de checkpoint. Não é milagre, mas transforma «fiz merda» de perda garantida em salvamento provável.

**Q: Ele vai ler meus arquivos privados?**
O escopo das ferramentas é limitado por uma allow-list de domínios, a saída de rede é controlada pra evitar exfiltração e as chaves são mascaradas na saída.

**Q: Total offline?**
`qxt models local` pra sondar, `/offline` pra gerenciar o Ollama. Sem internet, sem problema.

**Q: Dá pra escrever minhas próprias ferramentas/plugins?**
Sim — metadata com `@plugin`, `activate(kernel)` + `kernel.provide(...)` / `kernel.require(...)`. Três passos:

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

## Inspiração e atribuição

Qingxiaotuan não nasceu do nada: o design se apoia explicitamente nos seguintes projetos e protocolos de agentes conhecidos. Listamos sem esconder nada (e anotamos a fonte original nos comentários do código onde fizer sentido):

| Fonte | O que pegamos emprestado |
|---|---|
| **DeepSeek Harness / Cordis** | Arquitetura de microkernel + registro de serviços + barramento de eventos append-only (anotado em `core/kernel.py`) |
| **Kimi Code** | O toque e a paleta do TUI de terminal (ver [NOTICE](NOTICE)) |
| **Claude Code** | Sistema de comandos `/`, agentes nomeados (compatível `.claude/agents`), modo Goal, DevLoop — alinhamento de interface |
| **ACP (Agent Client Protocol)** | Como server/client, alinhado à semântica de mensagens e handshake pra um IDE pilotar o Qingxiaotuan |
| **MCP (Model Context Protocol)** | Como client, alinhado ao protocolo pra plugar no ecossistema de ferramentas |
| **APIs da OpenAI / Anthropic / Google etc.** | Adaptadores de provedor implementados pela semântica REST oficial — só adaptação de protocolo, sem copiar o interior |

> Limite: o **código** é nosso; **protocolos/interfaces** são alinhados; **ideias/designs** são emprestados e fundidos. Onde um detalhe de implementação concreto é referenciado, fica declarado nos comentários do código e no [NOTICE](NOTICE).

---

## Começo rápido

```bash
git clone <este repo> && cd qingxiaotuan-agent-cli
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

qxt setup
# ou na mão: ~/.qingxiaotuan/config.yaml
#   model.provider: deepseek
#   model.model: deepseek-chat
#   model.api_key_env: DEEPSEEK_API_KEY      # chave nunca em texto puro

qxt            # bora conversar
qxt --print run "Oi, se apresenta em uma frase."
```

---

## Superfície de comandos: 105 subcomandos + 46 comandos de barra

| Comando | Pra quê |
|---|---|
| `qxt` | TUI interativo (skin Kimi Code) |
| `qxt setup` / `qxt models` | Configurar provedor / listar 51 provedores e 1100+ modelos |
| `qxt agent` | Agentes nomeados (compatível `.claude/agents`, descoberta de 3 níveis) |
| `qxt acp` | Sobe um server ACP pra VSCode / Zed / JetBrains te pilotar |
| `qxt cron` | Tarefas agendadas em segundo plano |
| `qxt doctor` / `qxt bench` | Checkup / benchmark |
| `qxt arch demo` | Verifica a arquitetura de 5 camadas num comando |

Barras que você vai viver: `/plan`·`/model`·`/undo`·`/impact`·`/swarm`·`/log`·`/stats`·`/cost`·`/budget`·`/goal`·`/sandbox`·`/offline`·`/verify`·`/audit`·`/more`·`/help` — lista completa com `Ctrl-G` no TUI.

---

## Três loops, a mesma mão firme

- **ReActLoop** — pensa → age → observa, o ritmo padrão.
- **PlannerExecuteLoop** — um modelo forte planeja, um barato executa (`router.*` permite compartimentar plano/execução). O economizador de tokens.
- **DevLoop** — escreve-verifica-cura: `/verify` detecta o projeto (Python/Node/Rust/Go), infere os comandos de teste e se auto-cura por até N rodadas.

## O modelo de segurança: quatro portões + desfazer com razão

1. **Nota estática** — todo comando de shell pontuado `none→critical` por `safety_engine.score()`, com expansão de indiretas (IFS, `$VAR`, substituição, escapes ANSI-C/octal/hex, PowerShell Base64, NFKC; ≤32 de recursão).
2. **Bloqueio por raio de impacto** — você vê o que ele vai tocar **antes** de disparar (`--impact`).
3. **Piso de linhas vermelhas no YOLO** — YOLO tira as confirmações passo a passo mas **não** toca nas linhas vermelhas (`rm` recursivo, force-push, `chmod -R 000 /`… nunca em automático).
4. **Razão transacional** — todo write fica auditado; `/undo` restaura com diff `reverse_transform` + snapshots.

As regras sempre resolvem `deny > ask > allow`. Use `qxt safe allow <cmd>` pra allowlist; não desligue segurança pra economizar clique.

---

## Onde suas ideias rodam

- **Memória** — três níveis (usuário/projeto/sessão) + SQLite FTS5 (trigram), degrada pra texto puro se não tiver.
- **Subagentes** — delegação tipada (general-purpose / explore / plan / coder), subagentes isolados, workers concorrentes e Swarm pra fatiar tarefa longa.
- **Cron e segundo plano** — `qxt cron start --detach`; autonomia headless.
- **Hooks** — `PreToolUse` pode `block` ou reescrever `args` (`hooks.allow_edit_args`).
- **Observabilidade** — `/stats`·`/audit`·`/impact`·`/bench`·`/cost`; custo na mesa.
- **crypto** — v2 é sólido: AES-GCM(AEAD) com `cryptography`, senão cifra de fluxo HMAC-SHA256; `open()` com MAC ausente/adulterado sempre vai de fail-closed.

---

## Dev & contrato

```bash
python -m pytest tests/ -q        # 2500+ testes
python -m mypy qingxiaotuan       # portão de tipos
qxt --print run "Oi. Uma linha."  # smoke
```

- **Disciplina i18n**: README_zh-CN é o mestre autoritativo; cada idioma é uma localização viva, sem deriva — **nada de tradução mecânica.**
- **Escala**: ~412 `.py` / ~79 k linhas / 41 pacotes / 36 plugins.
- **Versão**: `v0.2.017` (0.x/Beta); mudanças que quebram avisam na minor + notas de migração.
- **A fundo**: assinaturas dos nove motores e um tutorial de ferramenta nova moram no apêndice de `README_zh-CN.md`.

---

## License & links

- **License**: MIT (usa, modifica, redistribui; mantém o aviso)
- **Lê isso**: [SECURITY.md](SECURITY.md) · [CHANGELOG.md](CHANGELOG.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [NOTICE](NOTICE)

> Quer «experiência fechada, de caixa, casada com vendor»? Disso o mercado tá cheio. Quer **rodar com seus próprios modelos, manter o controle e conseguir voltar atrás quando der ruim**? As chaves tão aqui.