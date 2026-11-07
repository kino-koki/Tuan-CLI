# Tuan-CLI

> **«Model + Harness = Agent.»** — separa o «como pensar» do «como executar com segurança» e entrega as duas chaves pra você.
> Um harness de agentes de IA em Python puro, seguro por padrão e agnóstico de modelo. `v0.3.3` · MIT · Python ≥ 3.10

> ### Posicionamento: um agente safety-first — sem sacrificar a experiência do desenvolvedor
>
> **Segurança é prioridade, não opção** — e **interromper não é substituto de segurança**.
>
> - **Segurança em primeiro lugar**: comandos perigosos são bloqueados *antes* de rodarem (pré-visualização do raio de impacto → linha vermelha dura → confirmação multinível). Cada escrita passa por um livro transacional para um `/undo` exato.
> - **Semântica de segurança**: YOLO/`--yolo` aprova automaticamente operações que normalmente exigiriam confirmação, mas **não** contorna linhas vermelhas duras. `--isolation` oferece isolamento no nível do mecanismo/processo para reduzir o raio de impacto e conter falhas; **não** é um sandbox completo do sistema operacional nem substitui a aprovação de comandos.
> - **Experiência do desenvolvedor preservada**: leituras/escrituras de arquivo, operações `git` rotineiras, instalação de pacotes, rodadas de testes e linters recebem nota `none` — **zero confirmações, zero bloqueios** (`safety_engine.is_benign_dev_command`). Só ações genuinamente perigosas escalam para conselho ou bloqueio.
> - **Medições reproduzíveis**: nosso objetivo é «menos comandos perigosos escapam, menos comandos inofensivos incomodam», e qualquer número que publicarmos **precisa ser reproduzível por um terceiro** — sem promessas absolutas inverificáveis. Os benchmarks vivem em [`bench/`](bench/README.md): 10k amostras adversariais bash/generic + 5k amostras de PowerShell + 2.497 payloads de bypass feitos à mão (com asserções de nível de consequência catastrófica). **Um único comando, `tuan safe bench`, reproduz tudo localmente** (sem rede, sem modelo); `tuan safe report` emite um relatório de segurança HTML autocontido. Código atual medido (2026-10): adversarial 10k → recall de bloqueio 100 % / recall de flag 100 % / falso positivo 0,45 % (5) / bypass 0; PowerShell 5k → precisão 100 % / falhas 0 / falsos positivos 0; matriz de bypass 2.497 payloads → bypass 0 / falso positivo 1 / classes de intenção catastrófica 100 % bloqueadas. Algumas escaladas deliberadamente conservadoras de fail-closed permanecem (ex.: sondagens de porta `nc`, payloads com forma de exfiltração `tar|ssh`) e explicam as cifras de falsos positivos; por favor rode localmente.
> - **Interoperabilidade de ecossistemas**: a gente não reconstrói ecossistemas — **reutilizamos o que o Claude Code / Hermes Agent já acumularam** nesta máquina (skills, agentes nomeados, memória, SOUL persona, configs MCP). `tuan ecosystem` move ativos nos dois sentidos num único comando; `tuan ecosystem link` remonta o tuan neles sobre MCP. Um harness, o equivalente a três ecossistemas em ativos.

**Idioma/Language:** [English](README.md) · [简体中文](README_zh-CN.md) · [繁體中文](README_zh-GAT.md) · [日本語](README_ja.md) · [한국어](README_ko.md) · [Español](README_es.md) · **Português (Brasil)** · [Français](README_fr.md) · [Deutsch](README_de.md) · [Русский](README_ru.md)

**Antes de mexer:** [SECURITY.md](SECURITY.md) · [CHANGELOG.md](CHANGELOG.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · `tuan models list-providers`

**Início rápido:**
- 🚀 **Começar em 3 passos:** `pip install tuan-cli` → `tuan setup` → `tuan "sua tarefa"`
- 📖 **Guia completo:** [docs/QUICKSTART.md](docs/QUICKSTART.md) — inclui árvores de decisão, cenários comuns e FAQ
- 🎯 **Referência rápida:** `tuan help quickstart` — mostra o guia de início direto no terminal

---

## TL;DR

A ideia central: **o modelo pensa; o harness faz esse pensamento rodar com segurança e controle.** O Tuan-CLI desacopla «o modelo» do «host»: hot-swap entre muitos provedores, rodar completamente offline, desfazer erros destrutivos e ver o raio de impacto *antes* do comando disparar. O objetivo é ser um host de agente de terminal razoavelmente neutro, auto-hospedável — não um invólucro refém de um único fornecedor.

**O que NÃO é**: nem um invólucro refém de um modelo (hot-swap / self-host / offline, você escolhe); nem um capacho de IDE (é uma ferramenta de terminal, dirigível via ACP por VSCode/Zed/JetBrains); nem uma única abstração frágil (arquitetura de microkernel pra quem constrói + um `setup` de um único tiro pra todo mundo).

---

## Por que é diferente

| O quê | Detalhes |
|---|---|
| 🛡️ **Segurança em primeiro lugar** | Quatro portões: nota estática de risco, bloqueio prévio por raio de impacto, piso de linhas vermelhas no YOLO, livro transacional com `/undo` exato |
| 🎯 **Experiência do desenvolvedor** | Comandos dev inofensivos passam sem confirmação, `/undo` tem suas costas, 40+ comandos slash, `tuan safe allow` pra opt-outs explícitos, YOLO pra pular confirmações repetidas |
| 🔌 **Agnóstico de modelo** | 58 provedores + Ollama local + hot-swap em runtime + roteamento automático (`router.*`) |
| 🧠 **Três loops principais** | ReAct / Planner-Execute / DevLoop — plugáveis; um único kernel, diferentes «ritmos de pensamento» |
| 🔧 **Microkernel** | `@plugin` de uma linha, registro de serviços, barramento de eventos append-only, middleware de hooks |
| 🗂️ **Memória** | SQLite FTS5 + stream de eventos de sessão; memória de 3 níveis, `/undo`, checkpoint, replay, exportação de Trajectory |
| 🧩 **Ecossistema** | MCP + ACP + **interoperabilidade Claude Code / Hermes Agent**: skills / agentes nomeados / memória / SOUL / configs MCP vão nos dois sentidos (`tuan ecosystem`), de fábrica |
| 🌍 **Dez idiomas** | zh-CN por padrão, localização nativa da interface inteira |
| 🐍 **Python puro** | Grande base de código `.py`, licença MIT |

---

## Respostas diretas

**P: Isso é realmente independente? Quanto é desenvolvido em casa?**
Duas coisas, separadas. **O código é escrito por nós**: o kernel e a grande maioria das capacidades (`core/`, `runtime/`, `arch/`, `tools/`, `ports/`…) são construídos linha a linha em Python, alinhados a protocolos externos só por interoperabilidade. **As ideias e o design são emprestadas** — este projeto fusiona deliberadamente conceitos de projetos de agentes conhecidos, e vale mais dizer isso abertamente do que esconder. A única parte onde até o *estilo* é mantido é a casca de terminal `--tui`, que segue deliberadamente a sensação de interação assinatura do **Kimi Code** (`#4FA8FF` primário, o spinner de fases da lua, a barra de status de duas linhas), creditado no [NOTICE](NOTICE). A lista completa de atribuição está em [Inspiração e atribuição](#inspiração-e-atribuição). **O código é nosso; as ideias são compartilhadas.**

**P: Por que ele me bloqueia antes de eu rodar comandos?**
É feature, não bug. Comandos perigosos pedem primeiro; YOLO respeita linhas vermelhas duras. Tá muito tagarelo? `tuan safe allow <cmd>` pra allowlist — não desligue a segurança.

**P: Então, quando eu fico bloqueado, eu fico preso?**
Não. Cada bloqueio/confirmação traz **alternativas seguras conscientes do comando** (`tuan safe suggest <cmd>` consultável a qualquer momento): `git push --force` → `--force-with-lease`, `rm -rf` → receita pra lixeira/reciclagem, `curl | sh` → «baixe e revise primeiro». A gente não simplesmente para você — leva você pelo caminho seguro pra chegar lá.

**P: O que o `/undo` pode reverter de verdade?**
Toda **escrita** que passa pelo livro: um único arquivo, um único passo, um turno inteiro. Por baixo é o livro transacional + `reverse_transform` de diff + snapshots de checkpoint. Não é cura milagrosa, mas transforma um tropeço de perda garantida em salvamento provável.

**P: Ele vai ler meus arquivos privados?**
O escopo das ferramentas é limitado por uma allow-list de domínios, a saída de rede é gotejada contra exfiltração e os segredos são mascarados na saída. Os padrões e o que você pode ajustar estão em [SECURITY.md](SECURITY.md).

**P: Totalmente offline?**
`tuan models local` pra sondar, `/offline` pra gerenciar Ollama. Sem internet, sem problema.

**P: Eu posso escrever minhas próprias ferramentas/plugins?**
Sim — metadados com `@plugin`, `activate(kernel)` + `kernel.provide(...)` / `kernel.require(...)`. Três passos:

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

## Número de versão

**Por que `0.3.3` e não `1.0`?** Semântica [SemVer](https://semver.org/) honesta: **uma versão `0.x` significa que a API pública (superfície CLI, schema de configuração, protocolo de ferramentas, contrato de plugins) ainda não está congelada** e pode mudar entre releases. O Tuan-CLI já entrega um conjunto amplo de recursos — controle de segurança / rollback transacional, hot-swap agnóstico de modelo (58 provedores + Ollama local), três loops principais, arquitetura de microkernel com plugins, memória de três níveis, interoperabilidade de ecossistemas (MCP / ACP / ponte Claude Code / Hermes), subagentes e Swarm, cron e tarefas em segundo plano, modo Goal e permissões precisas — tudo coberto por testes. Mas **o número de versão reflete a estabilidade da interface, não a completude dos recursos**: um conjunto completo de recursos não significa que a API deva ser congelada. `1.0` fica reservado pra quando a API pública for realmente estável e pudermos prometer retrocompatibilidade. Até lá: mudanças que quebram sobem MINOR dentro de `0.x` (com dicas de migração), recursos compatíveis sobem MINOR, correções sobem PATCH (veja [VERSION_POLICY.md](VERSION_POLICY.md)).

| Semântica de versão | Significado |
|---|---|
| `0.3.3` (atual) | **API ainda não congelada**: `0.x` permite ajustes que quebram, anunciados com dicas de migração; retrocompatibilidade não é prometida |
| `1.0` (reservado) | Ativado quando a API pública for congelada e a retrocompatibilidade for prometida; só então mudanças que quebram sobem MAJOR (`2.0`) |

---

## Inspiração e atribuição

O Tuan-CLI não nasceu do nada: o design se apoia explicitamente nos seguintes projetos e protocolos de agentes conhecidos. A gente lista abertamente (e anota a fonte original nos comentários do código onde faz sentido):

| Fonte | O que tomamos emprestado |
|---|---|
| **DeepSeek Harness / Cordis** | Arquitetura de microkernel + registro de serviços + barramento de eventos append-only (anotado em `core/kernel.py`) |
| **Kimi Code** | A sensação de interação do TUI de terminal e a paleta (ver [NOTICE](NOTICE)) |
| **Claude Code** | Sistema de comandos `/`, agentes nomeados (compatível `.claude/agents`), modo Goal, DevLoop — alinhamento de interface |
| **Hermes Agent** | Memória de três níveis, loop de auto-evolução de skills, identidade SOUL, ferramentas auto-registráveis, semântica cron — alinhado; `tuan ecosystem` sincroniza memória/skills/SOUL bidirecionalmente com ele |
| **ACP (Agent Client Protocol)** | Como client/server, alinhado à semântica de mensagens e handshake pra que um IDE dirija o Tuan-CLI |
| **MCP (Model Context Protocol)** | Como client, alinhado ao protocolo pra plugar no ecosistema de ferramentas |
| **APIs da OpenAI / Anthropic / Google etc.** | Adaptadores de provedor implementados pela semântica REST oficial — só adaptação de protocolo, sem replicar o interior |

> Limite: o **código** é desenvolvido em casa; **protocolos/interfaces** são alinhados; **ideias/designs** são emprestados e fundidos. Onde um detalhe de implementação concreto é referenciado, é declarado nos comentários do código e no [NOTICE](NOTICE).

---

## Início rápido

```bash
# 1) Instalar (—[dev] é o stack completo; caia pra [openai]/[mcp] se você só precisa de APIs)
git clone <este repo> && cd tuan-cli
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# 2) Apontar pra um provedor (14 perfis embutidos: deepseek / groq-free / siliconflow-free / ollama…)
tuan setup
# ou na mão: ~/.tuan/config.yaml
#   model.provider: deepseek
#   model.model: deepseek-chat
#   model.api_key_env: DEEPSEEK_API_KEY      # chaves nunca em texto puro

# 3) Conversar
tuan
# ou um smoke test:
tuan --print run "Oi, descreva-se em uma frase."
```

---

## Superfície de comandos: 51 subcomandos principais + comandos slash

| Comando | Pra quê |
|---|---|
| `tuan` | TUI interativo (skin Kimi Code) |
| `tuan setup` / `tuan models` | Configurar provedor / listar 58 provedores e 1400+ modelos |
| `tuan sessions` / `--continue` / `--resume <id>` / `setup --skip` | Listar/retomar/excluir sessões salvas; retomar direto da CLI; o assistente de configuração roda no primeiro uso (`setup --skip` pula) |
| `tuan models update` | Atualizar o catálogo de modelos/provedores localmente: mesclar as listas embutidas em `~/.tuan/models_catalog.json` (offline, preserva entradas adicionadas pelo usuário; `--check` reporta só diffs, `--background` roda assíncrono) |
| `tuan agent` | Agentes nomeados (compatível `.claude/agents`, descoberta de 3 níveis) |
| `tuan acp` | Sobe um servidor ACP pra VSCode / Zed / JetBrains te dirigirem |
| `tuan ecosystem` | **Interoperabilidade de ecossistemas**: `scan` sondea Claude Code / Hermes; `import` puxa skills/agents/memória/SOUL/configs MCP deles pro tuan; `export` empurra de volta; `link` remonta o tuan neles sobre MCP; `serve` roda o servidor MCP (ver [docs/ecosystem_bridge.md](docs/ecosystem_bridge.md)) |
| `tuan cron` | Tarefas agendadas em segundo plano |
| `tuan doctor [--compact]` | Check-up (adiciona `--compact` pra auto-verificação de sobrevivência à compactação de contexto) |
| `tuan dev codedev ...` | Subsistema de code-dev (recuperação / verificação / decomposição) |

Comandos slash do dia a dia: `/plan`·`/model`·`/undo`·`/impact`·`/swarm`·`/log`·`/stats`·`/cost`·`/budget`·`/goal`·`/sandbox`·`/offline`·`/verify`·`/audit`·`/more`·`/help` — lista completa com `Ctrl-G` no TUI.

---

## Interoperabilidade de ecossistemas: Claude Code / Hermes Agent de fábrica

Além de «segurança em primeiro lugar» e «agnóstico de modelo», a terceira pata é: **não reconstruir ecosistemas — reutilizar o que outros ecossistemas de agentes já acumularam.** Skills (o padrão aberto SKILL.md), agentes nomeados (`.claude/agents`), memória e persona (o `MEMORY.md` / `USER.md` / `SOUL.md` do Hermes), arquivos de contexto (`AGENTS.md` / `CLAUDE.md`) e configs de servidores MCP são estruturalmente quase idênticos entre os três — o tuan faz a ponte:

```bash
tuan ecosystem scan                        # sonda Claude Code / Hermes + seus ativos (somente leitura)
tuan ecosystem import all                  # puxa skills/agents/memória/SOUL/configs MCP dos dois lados pro tuan
tuan ecosystem export skills --to claude   # skills do tuan → .claude/skills (Hermes: --to hermes)
tuan ecosystem link                        # montagem reversa: Claude Code/Hermes chamam o tuan sobre MCP
```

- **Automático na sessão**: skills que o Claude Code ou Hermes já instalou ficam disponíveis no tuan na hora (`~/.claude/skills`, `~/.hermes/skills` estão no caminho de busca); `tuan ecosystem serve` expõe o tuan como servidor MCP pra sessões do Claude Code / Hermes ganharem ferramentas `tuan_*` (busca/escrita de memória, listagem/leitura de skills, despacho headless de tarefas).
- **Delegar, não migrar**: ferramentas `claude_code_run` / `hermes_run` entregam tarefas ao ambiente nativo completo do outro agente (a própria config, memória, skills, MCP dele).
- Doc completo: [`docs/ecosystem_bridge.md`](docs/ecosystem_bridge.md) (mapa de formatos / design de segurança / layout).

---

## Três loops principais, a mesma mão firme

- **ReActLoop** — pensa → age → observa, o ritmo padrão.
- **PlannerExecuteLoop** — um modelo forte planeja, um modelo mais barato executa (`router.*` suporta compartimentar plano/execução). Um padrão que economiza tokens.
- **DevLoop** — escreve-verifica-cura: `/verify` detecta automaticamente o projeto (Python/Node/Rust/Go), infere comandos de teste e se auto-cura até N rodadas.

---

## O modelo de segurança: quatro portões + undo em livro

1. **Nota estática** — todo comando de shell notado de `none→critical` via a fachada `SafetyEngine.score(params)`, com desdobramento de expansões indiretas (IFS, `$VAR`, substituição de comando, escapes ANSI-C/octal/hex, Base64 de PowerShell, NFKC; ≤32 de recursão).
2. **Bloqueio prévio por raio de impacto** — você vê o que ele vai tocar *antes* de disparar (`--impact`).
3. **Piso de linhas vermelhas no YOLO** — YOLO mata as confirmações por passo mas **não pode** tocar nas linhas vermelhas duras (`rm` recursivo, force-push, `chmod -R 000 /`… nunca auto-rodando).
4. **Livro transacional** — cada escrita tem um trilha de auditoria; `/undo` restaura via `reverse_transform` de diff + snapshots.

As regras sempre resolvem `deny > ask > allow`. Use `tuan safe allow <cmd>` pra allowlist; nunca desligue segurança pra economizar clique.

---

## Benchmarks de segurança: reproduzíveis com um único comando

`tuan safe bench` embala as três suítes reproduzíveis num único comando (totalmente local, sem modelo — qualquer terceiro pode rodá-las como estão):

- **Corpus adversarial** `bench/safety_bench_10k.py` — 10.000 comandos bash/generic (semeados 20260906, reproduzíveis); reporta recall de bloqueio / recall de flag / taxa de falsos positivos / bypasses.
- **Corpus de PowerShell** `bench/bench_powershell_safety.py` — 5.000 amostras (2.300 perigosas / 2.700 inofensivas); reporta precisão / falhas / falsos positivos.
- **Matriz de bypass** `bench/bypass_matrix.py` — 2.497 payloads adversariais feitos à mão; além de pattern matching, asserciona **por classe de consequência catastrófica** se cada classe de intenção catastrófica foi realmente bloqueada.

```bash
tuan safe bench                 # rodada completa (~3 min)
tuan safe bench --quick         # auto-verificação rápida (~30 s)
tuan safe bench --check         # compara contra arquivo; exit 1 se regrediu (gate)
tuan safe report                # relatório de segurança HTML autocontido (compartível)
tuan safe report --release      # RELEASE: números + timestamp + commit git amarrados (sem números velhos)
```

Medido no código atual (2026-10-25, reproduzível via `tuan safe bench`):

| Suite | Tamanho | Métrica principal | Bypasses | Falsos positivos |
|---|---|---|---|---|
| Adversarial | 10.000 | recall de bloqueio 100 % · recall de flag 100 % · FP 0,45 % (5) | 0 | — |
| PowerShell | 5.000 | precisão 100 % · falhas 0 | 0 | 0 |
| Matriz de bypass | 2.497 | classes de intenção catastrófica 100 % bloqueadas | 0 | 1 |

Caveat: a matriz de bypass é deliberadamente fail-closed e mantém algumas escaladas conservadoras (sondagens Unicode-variante de `nc`, payloads com forma de exfiltração `tar|ssh`), que produzem falsos positivos «inofensivo mas marcado»; o 0,45 % (5) de FP na suíte adversarial vem do mesmo conservadorismo (5 variantes do mesmo caso benigno `tar|ssh`, todas apenas marcadas, nenhuma bloqueada). Os números são autoritativos como rodados localmente com `tuan safe bench`.

**Gate de números no CI**: o job `safety-benchmarks` no `.github/workflows/security-ci.yml` roda as três suítes a cada push e compara contra o arquivo commitado — qualquer regressão (bypasses, uma classe de desastre não bloqueando completamente mais, uma subida clara de FP) **faz o CI falhar**. O arquivo `bench/security-bench.json` corresponde 1:1 à tabela do README.

---

## Cara a cara vs Claude Code: um único comando

Além das suítes de segurança auto-medidas, `bench/vs_claude.py` roda **o mesmo conjunto de tarefas nos dois agents** e renderiza um lado a lado honesto: mesma `bench/tasks.yaml`, mesmos scripts de aceitação, workspaces isolados, `tuan run -p` vs `claude -p --output-format json`.

```bash
python bench/vs_claude.py --dry --tuan .venv/Scripts/tuan.exe   # só check de framework, sem chamadas de modelo
python bench/vs_claude.py --tuan .venv/Scripts/tuan.exe         # rodada real (precisa de endpoints funcionando dos dois lados)
python bench/vs_claude.py --task fix_bug --model openrouter/deepseek/deepseek-chat
python bench/vs_claude.py --claude "C:\path\claude.cmd" --json
```

Escreve `bench/vs_report.md` / `.json` / `.html` com taxa de aprovação, tempo de parede, custo e contagens de rejeição de permissões por tarefa.

**Contrato de honestidade**: o runner primeiro sonda se `claude -p` pode completar um turno; se a sonda falhar, a coluna do Claude é marcada **N/A com a razão exata** — nunca finge que uma comparação aconteceu. Os números só fazem sentido quando ambos endpoints funcionam na sua máquina; esse é o ponto da medição reproduzível. Nota Windows: `claude` instalado via npm é um shim `.ps1`/`.cmd` — o script resolve o executável real automaticamente, e versões antigas que rejeitam `--no-input` são tratadas via redirecionamento de stdin.

---

## Onde suas ideias rodam

- **Memória** — três níveis (usuário/projeto/sessão) + SQLite FTS5 (trigram), degrada pra texto puro se não tiver.
- **Subagentes** — delegação tipada (general-purpose / explore / plan / coder), subagentes isolados, workers concorrentes e Swarm pra fatiar tarefa longa.
- **Cron e segundo plano** — `tuan cron start --detach`; autonomia headless.
- **Hooks** — `PreToolUse` pode `block` ou reescrever `args` (`hooks.allow_edit_args`) — uma grande emenda pra quem constrói.
- **Observabilidade** — `/stats`·`/audit`·`/impact`·`/bench`·`/cost`; custo na mesa.
- **crypto** — AES-GCM(AEAD) com `cryptography`, senão cifra de fluxo HMAC-SHA256 como respaldo; `open()` com MAC ausente / adulterada sempre vai de fail-closed.

---

## Dev & contrato

```bash
python -m pytest tests/ -q        # suíte grande
python -m mypy tuan_cli       # portão de tipos
tuan --print run "Oi. Uma linha."  # smoke
```

- **Disciplina i18n**: README_zh-CN é o mestre autoritativo; cada idioma é uma localização viva, sem deriva — **nada de tradução mecânica.**
- **Versão**: `v0.3.3` (uma linha `0.x` — a API ainda não está congelada); ajustes que quebram vêm com aviso prévio + notas de migração, e `1.0` fica reservado pra o congelamento da API.
- **A fundo**: assinaturas dos motores e um tour de ferramenta nova moram no apêndice de `README_zh-CN.md`.

---

## Totalmente local e offline · sem login

O Tuan-CLI **não oferece login**: sem vínculo com GitHub / Apple / DeepSeek, sem callback OAuth, sem token em disco. É deliberado — **tudo roda localmente, exceto a API de modelo que você mesmo configura**.

- **Totalmente utilizável sem login**: E/S de arquivos, execução de comandos, memória, skills, subagentes e a barreira de segurança são locais.
- **O único «cloud» é a sua API de modelo**: a chave é sua, enviada apenas a esse endpoint, sem intermediários de terceiros.
- **Pra um fluxo sem rede**: instale Ollama ou llama.cpp — `tuan models local` pra detectar, `tuan models set ollama <modelo>` pra usar.

### Configurar a chave de API do modelo

```bash
tuan models set deepseek deepseek-chat   # escolher provedor e modelo
tuan models                              # configuração interativa (chave em ~/.tuan/.env)
```

As chaves ficam em `~/.tuan/.env` (chmod 600, nunca commitar); variáveis de ambiente (ex.: `DEEPSEEK_API_KEY`) também funcionam.

## Licença & links

- **Licença**: MIT (use, modifique, redistribua; mantenha o aviso)
- **Leia isso**: [SECURITY.md](SECURITY.md) · [CHANGELOG.md](CHANGELOG.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [NOTICE](NOTICE)

> Quer «experiência fechada, de caixa, casada com vendor»? Disso o mercado tá cheio. Quer **rodar com seus próprios modelos, manter o controle e conseguir voltar atrás quando der ruim**? As chaves tão aqui.
