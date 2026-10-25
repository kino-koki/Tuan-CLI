# Tuan-CLI

> **« Model + Harness = Agent. »** — on sépare « comment penser » de « comment l'exécuter en sécurité », et on vous remet les deux clés.
> Un harness d'agents IA en pur Python, sécurité d'abord, agnostique du modèle. `v0.3.3` · MIT · Python ≥ 3.10

> ### Positionnement : un agent sécurité d'abord — sans sacrifier l'expérience développeur
>
> **La sécurité est une priorité, pas une option** — et **interrompre n'est pas un substitut de la sécurité**.
>
> - **Sécurité d'abord** : les commandes dangereuses sont bloquées *avant* qu'elles s'exécutent (aperçu du rayon d'impact → ligne rouge dure → confirmation multi-étapes). Chaque écriture est journalisée dans un livre transactionnel pour un `/undo` exact.
> - **Sémantique de sécurité** : YOLO/`--yolo` approuve automatiquement les opérations qui nécessitent normalement une confirmation, mais ne contourne **pas** les lignes rouges dures. `--isolation` fournit une isolation au niveau du moteur/processus pour réduire le rayon d'impact et contenir les défaillances ; ce n'est **pas** un bac à sable complet du système d'exploitation et cela ne remplace pas l'approbation des commandes.
> - **Expérience développeur préservée** : lectures/écritures de fichiers, opérations `git` courantes, installations de paquets, exécutions de tests et linters sont notées `none` — **zéro confirmation, zéro blocage** (`safety_engine.is_benign_dev_command`). Seules les actions réellement dangereuses escaladent vers conseil ou blocage.
> - **Mesures reproductibles** : notre objectif est « moins de commandes dangereuses s'échappent, moins de commandes bénignes harcèlent », et tout nombre que nous publions **doit être reproductible par un tiers** — aucune promesse absolue invérifiable. Les benchmarks vivent dans [`bench/`](bench/README.md) : 10k échantillons adversariaux bash/generic + 5k échantillons PowerShell + 2.321 payloads de bypass faits main (avec assertions au niveau de conséquences catastrophiques). **Une seule commande, `tuan safe bench`, reproduit tout localement** (sans réseau, sans modèle) ; `tuan safe report` émet un rapport de sécurité HTML autonome. Code actuel mesuré (2026-10) : adversarial 10k → rappel de blocage 100 % / rappel de flag 100 % / faux positif 0,09 % (1) / bypass 0 ; PowerShell 5k → précision 100 % / ratés 0 / faux positifs 0 ; matrice de bypass 2.321 payloads → bypass 0 / faux positif 1 / classes d'intention catastrophique 100 % bloquées. Quelques escalades délibérément conservatrices de fail-closed restent (p. ex. sondages de port `nc`, payloads de forme exfiltration `tar|ssh`) et expliquent les chiffres de faux positifs ; veuillez relancer localement.
> - **Interopérabilité d'écosystèmes** : on ne reconstruit pas les écosystèmes — on **réutilise ce que Claude Code / Hermes Agent ont déjà accumulé** sur cette machine (skills, agents nommés, mémoire, persona SOUL, configs MCP). `tuan ecosystem` déplace les actifs dans les deux sens en une seule commande ; `tuan ecosystem link` remonte tuan en eux via MCP. Un seul harness, la valeur de trois écosystèmes en actifs.

**Langue/Language:** [English](README.md) · [简体中文](README_zh-CN.md) · [繁體中文](README_zh-GAT.md) · [日本語](README_ja.md) · [한국어](README_ko.md) · [Español](README_es.md) · [Português (Brasil)](README_pt-BR.md) · **Français** · [Deutsch](README_de.md) · [Русский](README_ru.md)

**À lire avant de plonger :** [SECURITY.md](SECURITY.md) · [CHANGELOG.md](CHANGELOG.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · `tuan models list-providers`

**Démarrage rapide :**
- 🚀 **Commencer en 3 étapes :** `pip install tuan-cli` → `tuan setup` → `tuan "votre tâche"`
- 📖 **Guide complet :** [docs/QUICKSTART.md](docs/QUICKSTART.md) — avec arbres de décision, scénarios courants et FAQ
- 🎯 **Référence rapide：** `tuan help quickstart` — affiche le guide de démarrage directement dans le terminal

---

## TL;DR

L'idée centrale : **le modèle pense ; le harness fait que cette réflexion tourne de façon sûre et contrôlable.** Tuan-CLI découple « le modèle » de l'« hôte » : hot-swap entre plusieurs fournisseurs, tourner complètement hors ligne, annuler les erreurs destructives, et voir le rayon d'impact *avant* que la commande ne parte. Le but est d'être un hôte d'agent de terminal raisonnablement neutre, auto-hébergeable — pas un emballage captif autour d'un seul fournisseur.

**Ce que ce n'est pas** : ni un emballage captif d'un modèle (hot-swap / auto-hébergement / hors ligne, vous choisissez) ; ni un sous-fifre d'IDE (c'est un outil de terminal, pilotable via ACP par VSCode/Zed/JetBrains) ; ni une seule abstraction fuible (architecture micro-noyau pour les constructeurs, plus un `setup` d'un coup pour les autres).

---

## Pourquoi c'est différent

| Le truc | Détails |
|---|---|
| 🛡️ **Sécurité d'abord** | Quatre barrières : score de risque statique, blocage préalable par rayon d'impact, plancher de lignes rouges en YOLO, livre transactionnel avec `/undo` exact |
| 🎯 **Expérience développeur** | Les commandes dev bénignes passent sans confirmation, `/undo` vous a le dos, 40+ commandes slash, `tuan safe allow` pour des opt-outs explicites, YOLO pour sauter les confirmations répétées |
| 🔌 **Agnostique modèle** | 58 fournisseurs + Ollama local + hot-swap à l'exécution + routage automatique (`router.*`) |
| 🧠 **Trois boucles principales** | ReAct / Planner-Execute / DevLoop — débranchables ; un seul noyau, différents « rythmes de pensée » |
| 🔧 **Microkernel** | `@plugin` en une ligne, registre de services, bus d'événements append-only, middleware de hooks |
| 🗂️ **Mémoire** | SQLite FTS5 + flux d'événements de session ; mémoire à trois niveaux, `/undo`, checkpoint, replay, export Trajectory |
| 🧩 **Écosystème** | MCP + ACP + **interopérabilité Claude Code / Hermes Agent** : skills / agents nommés / mémoire / SOUL / configs MCP vont dans les deux sens (`tuan ecosystem`), dès la sortie de boîte |
| 🌍 **Dix langues** | zh-CN par défaut, localisation native de toute l'interface |
| 🐍 **Python pur** | Grande base de code `.py`, licence MIT |

---

## Réponses directes

**Q : C'est vraiment indépendant ? Combien est-ce développé en interne ?**
Deux choses, gardées séparées. **Le code est écrit par nous** : le noyau et l'immense majorité des capacités (`core/`, `runtime/`, `arch/`, `tools/`, `ports/`…) sont construits ligne par ligne en Python, alignés sur les **protocoles** externes uniquement pour interopérer. **Les idées et le design sont empruntés** — ce projet fusionne délibérément des concepts de projets d'agents connus, et c'est mieux de le dire franchement que de le cacher. La seule partie où même le *style* est conservé, c'est la peau de terminal `--tui`, qui suit délibérément le ressenti d'interaction signature de **Kimi Code** (`#4FA8FF` primaire, le spinner des phases de lune, la barre d'état sur deux lignes), crédité dans [NOTICE](NOTICE). La liste complète est dans [Inspiration et attribution](#inspiration-et-attribution). **Le code est à nous ; les idées sont partagées.**

**Q : Pourquoi ça me bloque avant que j'exécute des commandes ?**
C'est une fonctionnalité, pas un bug. Les commandes dangereuses demandent d'abord ; YOLO respecte les lignes rouges dures. Si c'est trop bavard, `tuan safe allow <cmd>` pour la liste blanche — ne désactivez pas la sécurité.

**Q : Donc quand je suis bloqué, je suis coincé ?**
Non. Chaque blocage/confirmation apporte des **alternatives sûres conscientes de la commande** (`tuan safe suggest <cmd>` consultable à tout moment) : `git push --force` → `--force-with-lease`, `rm -rf` → recette corbeille/recyclage, `curl | sh` → « télécharger et revoir d'abord ». On ne vous arrête pas tout court — on vous mène sur le chemin sûr pour y arriver.

**Q : Que peut vraiment annuler `/undo` ?**
Chaque **écriture** qui passe par le livre : un fichier, un pas, un tour complet. Sous le capot, c'est le livre transactionnel + `reverse_transform` de diff + snapshots de checkpoint. Ce n'est pas un remède miracle, mais ça transforme une erreur de perte garantie en sauvetage probable.

**Q : Est-ce que ça va lire mes fichiers privés ?**
Le périmètre des outils est borné par une allow-list de domaines, la sortie réseau est bridée contre l'exfiltration et les secrets sont masqués dans la sortie. Les valeurs par défaut et ce que vous pouvez régler sont dans [SECURITY.md](SECURITY.md).

**Q : Totalement hors ligne ?**
`tuan models local` pour sonder, `/offline` pour gérer Ollama. Pas d'internet, pas de souci.

**Q : Puis-je écrire mes propres outils/plugins ?**
Oui — métadonnées via `@plugin`, `activate(kernel)` + `kernel.provide(...)` / `kernel.require(...)`. Trois étapes :

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

## Numéro de version et historique du dépôt (divulgation transparente)

**Pourquoi `0.3.1` et non `1.0` ?** Sémantique [SemVer](https://semver.org/) honnête : **une version `0.x` signifie que l'API publique (surface CLI, schéma de config, protocole d'outils, contrat de plugins) n'est pas encore gelée** et peut encore changer entre les releases. Tuan-CLI livre déjà un large ensemble de fonctionnalités — contrôle de sécurité / rollback transactionnel, hot-swap modèle-neutre (58 fournisseurs + Ollama local), trois boucles principales, architecture micro-noyau à plugins, mémoire à trois niveaux, interopérabilité d'écosystèmes (MCP / ACP / pont Claude Code / Hermes), sous-agents et Swarm, cron et tâches d'arrière-plan, mode Goal et permissions précises — le tout couvert par des tests. Mais **le numéro de version reflète la stabilité de l'interface, pas l'exhaustivité des fonctionnalités** : un ensemble complet de fonctionnalités ne signifie pas que l'API doit être gelée. `1.0` est réservé au moment où l'API publique sera réellement stable et où nous pourrons promettre la rétrocompatibilité. D'ici là : les changements cassants montent MINOR dans `0.x` (avec pistes de migration), les fonctions compatibles montent MINOR, les correctifs montent PATCH (voir [VERSION_POLICY.md](VERSION_POLICY.md)).

| Sémantique de version | Signification |
|---|---|
| `0.3.3` (actuel) | **API pas encore gelée** : `0.x` autorise des ajustements cassants, annoncés avec des pistes de migration ; rétrocompatibilité non promise |
| `1.0` (réservé) | Activé lorsque l'API publique sera gelée et la rétrocompatibilité promise ; c'est seulement alors que les changements cassants montent MAJOR (`2.0`) |

**Note sur l'historique Git (transparence open source) :** l'historique des commits de ce dépôt a été **volontairement reconstruit le 2026-09-26 — l'historique initial des commits a été délibérément écrasé par l'auteur** ; l'évolution commit par commit antérieure à cette date n'est plus conservée. Le code actuel est entièrement revoyable, de l'architecture à l'implémentation ; pour l'évolution des fonctionnalités antérieure à 2026-09-26, fiez-vous aux enregistrements de version de [CHANGELOG.md](CHANGELOG.md) (la discipline de version n'est pas affectée). Nous choisissons de le divulguer franchement — sans fard, sans rien cacher.

---

## Inspiration et attribution

Tuan-CLI n'est pas né de rien : sa conception s'appuie explicitement sur les projets et protocoles d'agents connus suivants. Nous les listons ouvertement (et annotons la source originale dans les commentaires du code le cas échéant) :

| Source | Ce que nous avons emprunté |
|---|---|
| **DeepSeek Harness / Cordis** | Architecture micro-noyau + registre de services + bus d'événements append-only (annotée dans `core/kernel.py`) |
| **Kimi Code** | Le ressenti d'interaction du TUI terminal et la palette (voir [NOTICE](NOTICE)) |
| **Claude Code** | Système de commandes `/`, agents nommés (compatible `.claude/agents`), mode Goal, DevLoop — alignement d'interface |
| **Hermes Agent** | Mémoire à trois niveaux, boucle d'auto-évolution de skills, identité SOUL, outils auto-enregistrés, sémantique cron — aligné ; `tuan ecosystem` synchronise mémoire/skills/SOUL bidirectionnellement avec lui |
| **ACP (Agent Client Protocol)** | Comme client/serveur, aligné sur la sémantique des messages et du handshake pour qu'un IDE pilote Tuan-CLI |
| **MCP (Model Context Protocol)** | Comme client, aligné sur le protocole pour se brancher sur l'écosystème d'outils |
| **APIs OpenAI / Anthropic / Google, etc.** | Adaptateurs de fournisseur implémentés selon la sémantique REST officielle — adaptation de protocole seulement, sans répliquer l'intérieur |

> Limite : le **code** est développé en interne ; les **protocoles/interfaces** sont alignés ; les **idées/designs** sont empruntés et fusionnés. Là où un détail d'implémentation est cité, c'est déclaré dans les commentaires du code et dans [NOTICE](NOTICE).

---

## Démarrage rapide

```bash
# 1) Installer (—[dev] est le stack complet ; passez à [openai]/[mcp] si vous ne voulez que les APIs)
git clone <ce dépôt> && cd tuan-cli
python -m venv .venv && source .venv/bin/activate    # Windows : .venv\Scripts\activate
pip install -e ".[dev]"

# 2) Pointer vers un fournisseur (14 profils intégrés : deepseek / groq-free / siliconflow-free / ollama…)
tuan setup
# ou à la main : ~/.tuan/config.yaml
#   model.provider: deepseek
#   model.model: deepseek-chat
#   model.api_key_env: DEEPSEEK_API_KEY      # les clés jamais en clair

# 3) Discuter
tuan
# ou un smoke test :
tuan --print run "Salut, décris-toi en une phrase."
```

---

## Surface de commandes : 38 sous-commandes principales + commandes slash

| Commande | À quoi ça sert |
|---|---|
| `tuan` | TUI interactif (skin Kimi Code) |
| `tuan setup` / `tuan models` | Configurer les fournisseurs / lister 58 fournisseurs et 1400+ modèles |
| `tuan sessions` / `--continue` / `--resume <id>` / `setup --skip` | Lister/reprendre/supprimer les sessions enregistrées ; reprendre directement depuis la CLI ; l’assistant de configuration s’exécute au premier lancement (`setup --skip` pour ignorer) |
| `tuan models update` | Mettre à jour le catalogue de modèles/fournisseurs localement : fusionner les listes intégrées dans `~/.tuan/models_catalog.json` (hors ligne, préserve les entrées ajoutées par l'utilisateur ; `--check` rapporte seulement les diffs, `--background` tourne de façon asynchrone) |
| `tuan agent` | Agents nommés (compatible `.claude/agents`, découverte en 3 niveaux) |
| `tuan acp` | Démarre un serveur ACP pour que VSCode / Zed / JetBrains puisse vous piloter |
| `tuan ecosystem` | **Interopérabilité d'écosystèmes** : `scan` sonde Claude Code / Hermes ; `import` tire leurs skills/agents/mémoire/SOUL/configs MCP vers tuan ; `export` pousse en retour ; `link` monte tuan en eux via MCP ; `serve` fait tourner le serveur MCP (voir [docs/ecosystem_bridge.md](docs/ecosystem_bridge.md)) |
| `tuan cron` | Tâches planifiées en arrière-plan |
| `tuan doctor [--compact]` | Vérification de santé (ajoutez `--compact` pour l'auto-contrôle de survie face à la compaction de contexte) |
| `tuan dev codedev ...` | Sous-système de code-dev (récupération / vérification / décomposition) |

Commandes slash du quotidien : `/plan`·`/model`·`/undo`·`/impact`·`/swarm`·`/log`·`/stats`·`/cost`·`/budget`·`/goal`·`/sandbox`·`/offline`·`/verify`·`/audit`·`/more`·`/help` — liste complète via `Ctrl-G` dans le TUI.

---

## Interopérabilité d'écosystèmes : Claude Code / Hermes Agent dès la sortie de boîte

Au-delà de « sécurité d'abord » et « agnostique modèle », la troisième jambe est : **ne pas reconstruire les écosystèmes — réutiliser ce que les autres écosystèmes d'agents ont déjà accumulé.** Les skills (le standard ouvert SKILL.md), les agents nommés (`.claude/agents`), la mémoire et la persona (les `MEMORY.md` / `USER.md` / `SOUL.md` de Hermes), les fichiers de contexte (`AGENTS.md` / `CLAUDE.md`) et les configs de serveurs MCP sont structurellement quasi identiques entre les trois — tuan les pont :

```bash
tuan ecosystem scan                        # sonder Claude Code / Hermes + leurs actifs (lecture seule)
tuan ecosystem import all                  # tirer les skills/agents/mémoire/SOUL/configs MCP des deux côtés vers tuan
tuan ecosystem export skills --to claude   # skills de tuan → .claude/skills (Hermes : --to hermes)
tuan ecosystem link                        # montage inverse : Claude Code/Hermes appellent tuan via MCP
```

- **Automatique dans la session** : les skills déjà installées par Claude Code ou Hermes sont utilisables immédiatement dans tuan (`~/.claude/skills`, `~/.hermes/skills` sont dans le chemin de recherche) ; `tuan ecosystem serve` expose tuan comme serveur MCP pour que les sessions Claude Code / Hermes gagnent des outils `tuan_*` (recherche/écriture de mémoire, listage/lecture de skills, déploiement de tâches headless).
- **Déléguer, ne pas migrer** : les outils `claude_code_run` / `hermes_run` confient les tâches à l'environnement natif complet de l'autre agent (sa propre config, mémoire, skills, MCP).
- Doc complet : [`docs/ecosystem_bridge.md`](docs/ecosystem_bridge.md) (carte de formats / conception sécurité / disposition).

---

## Trois boucles principales, une main ferme

- **ReActLoop** — pense → agit → observe, le rythme par défaut.
- **PlannerExecuteLoop** — un modèle fort planifie, un modèle moins cher exécute (`router.*` supporte la compartimentation plan/exécution). Un motif qui économise les tokens.
- **DevLoop** — écris-vérifie-soigne : `/verify` détecte automatiquement le projet (Python/Node/Rust/Go), infère les commandes de test et se soigne lui-même pendant N tours au maximum.

---

## Le modèle de sécurité : quatre barrières + undo en livre

1. **Score statique** — chaque commande shell notée de `none→critical` via la façade `SafetyEngine.score(params)`, avec déploiement des expansions indirectes (IFS, `$VAR`, substitution de commande, échappements ANSI-C/octal/hex, Base64 PowerShell, NFKC ; ≤32 de récursion).
2. **Blocage préalable par rayon d'impact** — vous voyez ce que ça touchera *avant* que ça parte (`--impact`).
3. **Plancher de lignes rouges en YOLO** — YOLO tue les confirmations par étape mais **ne peut pas** toucher les lignes rouges dures (`rm` récursif, force-push, `chmod -R 000 /`… jamais auto-exécuté).
4. **Livre transactionnel** — chaque écriture a une piste d'audit ; `/undo` restaure via `reverse_transform` de diff + snapshots.

Les règles résolvent toujours `deny > ask > allow`. Blanchez avec `tuan safe allow <cmd>` ; ne désactivez jamais la sécurité pour gagner des clics.

---

## Benchmarks de sécurité : reproductibles avec une seule commande

`tuan safe bench` embarque les trois suites reproductibles dans une seule commande (entièrement local, sans modèle — n'importe quel tiers peut les relancer telles quelles) :

- **Corpus adversarial** `bench/safety_bench_10k.py` — 10.000 commandes bash/generic (ensemencées 20260906, reproductibles) ; rapporte rappel de blocage / rappel de flag / taux de faux positifs / bypasses.
- **Corpus PowerShell** `bench/bench_powershell_safety.py` — 5.000 échantillons (2.300 dangereux / 2.700 bénins) ; rapporte précision / ratés / faux positifs.
- **Matrice de bypass** `bench/bypass_matrix.py` — 2.321 payloads adversariaux faits main ; au-delà de la correspondance de motifs, elle vérifie **par classe de conséquence catastrophique** si chaque classe d'intention catastrophique a été réellement bloquée.

```bash
tuan safe bench                 # exécution complète (~3 min)
tuan safe bench --quick         # auto-vérification rapide (~30 s)
tuan safe bench --check         # compare à l'archive ; exit 1 si régression (gate)
tuan safe report                # rapport de sécurité HTML autonome (partageable)
tuan safe report --release      # RELEASE : chiffres + horodatage + commit git liés (pas de chiffres périmés)
```

Mesuré sur le code actuel (2026-10-25, reproductible via `tuan safe bench`) :

| Suite | Taille | Métrique clé | Bypasses | Faux positifs |
|---|---|---|---|---|
| Adversarial | 10.000 | rappel de blocage 100 % · rappel de flag 100 % · FP 0,09 % (1) | 0 | — |
| PowerShell | 5.000 | précision 100 % · ratés 0 | 0 | 0 |
| Matrice de bypass | 2.321 | classes d'intention catastrophique 100 % bloquées | 0 | 1 |

Avis : la matrice de bypass est délibérément fail-closed et conserve quelques escalades conservatrices (sondages Unicode-variante de `nc`, payloads de forme exfiltration `tar|ssh`), qui produisent des faux positifs « bénin mais marqué » ; le 0,09 % (1) de FP dans la suite adversarial vient du même conservatisme. Les chiffres sont autoritatifs comme relancés localement avec `tuan safe bench`.

**Gate de chiffres en CI** : le job `safety-benchmarks` dans `.github/workflows/security-ci.yml` relance les trois suites à chaque push et les compare à l'archive commitée — toute régression (bypasses, une classe de désastre ne se bloque plus complètement, une hausse claire de FP) **fait échouer la CI**. L'archive `bench/security-bench.json` correspond 1:1 au tableau du README.

---

## Face-à-face vs Claude Code : une seule commande

Au-delà des suites de sécurité auto-mesurées, `bench/vs_claude.py` exécute **le même set de tâches sur les deux agents** et rend un face-à-face honnête : même `bench/tasks.yaml`, mêmes scripts d'acceptation, workspaces isolés, `tuan run -p` contre `claude -p --output-format json`.

```bash
python bench/vs_claude.py --dry --tuan .venv/Scripts/tuan.exe   # vérification framework seulement, sans appels de modèle
python bench/vs_claude.py --tuan .venv/Scripts/tuan.exe         # vraie exécution (nécessite des endpoints fonctionnels des deux côtés)
python bench/vs_claude.py --task fix_bug --model openrouter/deepseek/deepseek-chat
python bench/vs_claude.py --claude "C:\path\claude.cmd" --json
```

Écrit `bench/vs_report.md` / `.json` / `.html` avec taux de passage, temps réel, coût et comptes de refus de permissions par tâche.

**Contrat d'honnêteté** : l'exécuteur sonde d'abord si `claude -p` peut compléter un tour ; si la sonde échoue, la colonne Claude est marquée **N/A avec la raison exacte** — on ne donne jamais pour acquis qu'une comparaison a eu lieu. Les chiffres ne deviennent significatifs que lorsque les deux endpoints fonctionnent sur votre machine ; c'est le point de la mesure reproductible. Note Windows : `claude` installé par npm est un shim `.ps1`/`.cmd` — le script résout l'exécutable réel automatiquement, et les vieilles versions qui rejettent `--no-input` sont gérées via redirection de stdin.

---

## Là où vos idées tournent

- **Mémoire** — trois niveaux (utilisateur/projet/session) + SQLite FTS5 (trigramme), dégrade en texte brut si indisponible.
- **Sous-agents** — délégation typée (general-purpose / explore / plan / coder), sous-agents isolés, workers concurrents et Swarm pour démembrer les longues tâches.
- **Cron et arrière-plan** — `tuan cron start --detach` ; autonomie headless.
- **Hooks** — `PreToolUse` peut `block` ou réécrire `args` (`hooks.allow_edit_args`) — une grande couture pour les constructeurs.
- **Observabilité** — `/stats`·`/audit`·`/impact`·`/bench`·`/cost` ; le coût sur la table.
- **crypto** — AES-GCM(AEAD) avec `cryptography`, sinon chiffrement de flux HMAC-SHA256 en repli ; `open()` avec MAC manquante / altérée échoue toujours fail-closed.

---

## Dev & contrat

```bash
python -m pytest tests/ -q        # grande suite
python -m mypy tuan_cli       # porte des types
tuan --print run "Salut, une ligne." # smoke
```

- **Discipline i18n** : README_zh-CN est le maître de référence ; chaque langue est une localisation vivante, zéro dérive — **aucune traduction mécanique.**
- **Version** : `v0.3.3` (une lignée `0.x` — l'API n'est pas encore gelée) ; les ajustements cassants arrivent avec préavis + notes de migration, et `1.0` est réservé au gel de l'API.
- **En profondeur** : signatures des moteurs et un tour de vis de nouvel outil vivent dans l'appendice de `README_zh-CN.md`.

---

## Entièrement local et hors ligne · aucune connexion

Tuan-CLI **ne propose aucune connexion** : pas de liaison GitHub / Apple / DeepSeek, pas de callback OAuth, aucun jeton sur disque. C'est délibéré — **tout tourne en local sauf l'API de modèle que vous configurez**.

- **Pleinement utilisable sans se connecter** : E/S de fichiers, exécution de commandes, mémoire, skills, sous-agents et le garde-fou de sécurité sont locaux.
- **Le seul « cloud » c'est votre API de modèle** : la clé est la vôtre, envoyée uniquement à ce point de terminaison, sans relais tiers.
- **Pour un pipeline sans réseau** : installez Ollama ou llama.cpp — `tuan models local` pour détecter, `tuan models set ollama <modèle>` pour l'utiliser.

### Configurer la clé d'API du modèle

```bash
tuan models set deepseek deepseek-chat   # choisir fournisseur et modèle
tuan models                              # configuration interactive (clé dans ~/.tuan/.env)
```

Les clés résident dans `~/.tuan/.env` (chmod 600, jamais commitées) ; les variables d'environnement (p. ex. `DEEPSEEK_API_KEY`) fonctionnent aussi.

> **Transparence** : les versions précédentes proposaient une connexion GitHub / Apple / DeepSeek (avec une voie par jeton de session web). Cela contredisait le positionnement « entièrement local et hors ligne », et le point de terminaison web était une interface privée non prise en charge déclenchant des contrôles de risque — la capacité a donc été **entièrement retirée**. Les appels de modèle passent par les APIs officielles avec votre propre clé.

## Licence & liens

- **Licence** : MIT (utilisez, modifiez, redistribuez ; gardez l'avis)
- **À lire** : [SECURITY.md](SECURITY.md) · [CHANGELOG.md](CHANGELOG.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [NOTICE](NOTICE)

> Vous voulez « une expérience clé en main, fermée, mariée à un fournisseur » ? Ça ne manque pas. Vous voulez **tourner sur vos propres modèles, garder le contrôle et pouvoir revenir en arrière** ? Les clés sont ici.
