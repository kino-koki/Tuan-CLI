# Tuan-CLI

> **« Model + Harness = Agent »** — on sépare « penser » de « tourner en sécurité », et on te remet les deux clés.
> Un harness d'agents IA en pur Python, sécurité d'abord, agnostique du modèle. `v0.2.018` · MIT · Python ≥ 3.10

**Langue/Language:** [English](README.md) · [简体中文](README_zh-CN.md) · [繁體中文](README_zh-GAT.md) · [日本語](README_ja.md) · [한국어](README_ko.md) · [Español](README_es.md) · [Português (Brasil)](README_pt-BR.md) · **Français** · [Deutsch](README_de.md) · [Русский](README_ru.md)

**À lire avant de plonger :** [SECURITY.md](SECURITY.md) · [CHANGELOG.md](CHANGELOG.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · `qxt models list-providers`

---

## En une phrase

La plupart des CLIs d'agents naissent *mariés à un fournisseur*. Ici, c'est l'inverse : un **châssis sans cerveau imposé**. Change de fournisseur à chaud parmi 51, tourne 100 % hors ligne, défais tes bêtises et vois le rayon d'impact **avant** que la commande ne parte. **Le modèle pense ; lui, il fait en sorte que rien n'explose.**

**Ce que ce n'est pas** : ni un emballage captif d'un modèle (hot-swap / auto-hébergement / offline, tu choisis) ; ni un sous-fifre d'IDE (c'est un outil de terminal, en plus pilotable via ACP par VSCode/Zed/JetBrains) ; ni une abstraction fragile sur une seule couche (architecture microkernel pour ceux qui bricolent + un `setup` d'un clic pour les autres).

---

## Pourquoi c'est différent

| Ce qu'il donne | Jusqu'où ça va |
|---|---|
| 🛡️ **La sécurité d'abord** | Quatre barrières : score de risque statique, blocage par rayon d'impact, plancher de lignes rouges en YOLO, et livre de comptes transactionnel avec `/undo` de précision |
| 🔌 **Agnostique modèle** | 51 fournisseurs + Ollama local + hot-swap + routage auto (`router.*`) |
| 🧠 **Trois boucles principales** | ReAct / Planner-Execute / DevLoop — enfichables : un noyau, plusieurs « rythmes de pensée » |
| 🔧 **Microkernel** | Un `@plugin` d'une ligne, registre de services, bus d'événements append-only, middleware de hooks |
| 🗂️ **Mémoire** | SQLite FTS5 + flux d'événements de session ; mémoire à 3 niveaux, `/undo`, checkpoint, replay, export Trajectory |
| 🧩 **Écosystème** | MCP + ACP — branche des outils ou laisse ton IDE te piloter |
| 🌍 **Dix langues** | simplifié par défaut, avec une vraie localisation de l'interface |
| 🐍 **Python pur** | ~412 `.py` / ~79 k lignes / 41 paquets / 36 plugins, MIT |

---

## Sans détour

**Q : C'est vraiment « fait maison » ? Un cadavre dans le placard ?**
Deux choses, séparées. **Le code est nôtre** : le noyau et l'immense majorité des capacités (`core/`, `runtime/`, `arch/`, `tools/`, `ports/`…) sont écrits ligne par ligne en Python, alignés sur les **protocoles** externes uniquement pour interopérer. Mais **les idées et le design** sont empruntés et fusionnés à des projets d'agents connus — et ce n'est pas à cacher, c'est justement se tenir sur les épaules de géants. **Le code est à nous ; les idées sont partagées.** La seule partie où même le *style* est conservé, c'est la peau du TUI `--tui`, qui reprend volontairement le style et la palette de **Kimi Code** (`#4FA8FF`, le spinner des phases de lune, la barre à deux lignes), crédité dans [NOTICE](NOTICE). La liste complète est dans [Inspiration et attribution](#inspiration-et-attribution).

**Q : Pourquoi il me bloque avant d'exécuter des commandes ?**
C'est une fonctionnalité, pas un bug. Les commandes dangereuses demandent d'abord ; YOLO respecte les lignes rouges. Trop bavard ? `qxt safe allow <cmd>` pour la liste blanche — ne désactive pas la sécurité.

**Q : Que peut vraiment défaire `/undo` ?**
Toute **écriture** qui passe par le livre de comptes : un fichier, un pas, un tour complet. Derrière : livre transactionnel + diff `reverse_transform` + snapshots de checkpoint. Pas miraculeux, mais ça transforme « j'ai merdé » d'une perte garantie en un sauvetage probable.

**Q : Il va lire mes fichiers privés ?**
Le périmètre des outils est borné par une allow-list de domaines, la sortie réseau est bridée contre l'exfiltration et les clés sont masquées dans la sortie.

**Q : Offline total ?**
`qxt models local` pour sonder, `/offline` pour gérer Ollama. Pas d'internet, pas de souci.

**Q : On peut écrire ses propres outils/plugins ?**
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

**Pourquoi la version reste-t-elle en `0.x` ?** Tuan-CLI suit [SemVer](https://semver.org/) : `0.x` signifie que **l'API n'est pas encore figée** — les changements cassants sont annoncés à l'avance avec des pistes de migration (voir [VERSION_POLICY.md](VERSION_POLICY.md)). **Le numéro de version reflète la stabilité de l'interface, pas l'exhaustivité des fonctionnalités.** En capacité, le `0.2.x` actuel offre ce que les produits comparables d'Agent CLI appellent un **ensemble de fonctionnalités de niveau 2.x** — contrôle de sécurité / rollback transactionnel, changement à chaud indépendant du modèle (51 fournisseurs + Ollama local), trois boucles principales, architecture micro-noyau à plugins, mémoire à trois niveaux, interopérabilité d'écosystèmes (pont MCP/ACP/Claude Code/Hermes), sous-agents et Swarm, cron et tâches d'arrière-plan, mode Goal et permissions précises — le tout livré et couvert par des tests. En une phrase : **la maturité fonctionnelle est à « 2.x » ; la version reste en « 0.x » parce que nous tenons le principe que 1.0 n'arrive qu'après le gel de l'API** — pas par manque de capacités.

| Sémantique de version | Signification |
|---|---|
| `0.x` (actuel) | API non figée : changements cassants annoncés + pistes de migration ; exhaustivité fonctionnelle au niveau des concurrents 2.x |
| `1.0` (prévu) | Publié une fois l'API figée ; ensuite le numéro reflète directement la stabilité de l'interface |

**Note sur l'historique Git (transparence open source) :** L'historique des commits de ce dépôt a été **reconstruit le 2026-09-26 après corruption du dépôt local** ; l'évolution commit par commit antérieure à cette date n'est plus récupérable (les anciens objets `.git` ont été perdus). Le code actuel est entièrement revoyable, de l'architecture à l'implémentation ; pour l'évolution des fonctionnalités antérieure à 2026-09-26, fiez-vous aux enregistrements de version de [CHANGELOG.md](CHANGELOG.md) (la discipline de version n'est pas affectée). Nous choisissons de le divulguer clairement — sans fard, sans rien cacher.

---

## Inspiration et attribution

Tuan-CLI n'est pas né de rien : sa conception s'appuie explicitement sur les projets et protocoles d'agents connus suivants. On les liste sans rien cacher (et on annote la source originale dans les commentaires du code le cas échéant) :

| Source | Ce qu'on a emprunté |
|---|---|
| **DeepSeek Harness / Cordis** | Architecture microkernel + registre de services + bus d'événements append-only (annotée dans `core/kernel.py`) |
| **Kimi Code** | Le ressenti et la palette du TUI terminal (voir [NOTICE](NOTICE)) |
| **Claude Code** | Système de commandes `/`, agents nommés (compatible `.claude/agents`), mode Goal, DevLoop — alignement d'interface |
| **ACP (Agent Client Protocol)** | En tant que server/client, aligné sur la sémantique des messages et du handshake pour qu'un IDE pilote Tuan-CLI |
| **MCP (Model Context Protocol)** | En tant que client, aligné sur le protocole pour se brancher sur l'écosystème d'outils |
| **API OpenAI / Anthropic / Google, etc.** | Adaptateurs de provider implémentés selon la sémantique REST officielle — adaptation de protocole seulement, sans répliquer l'intérieur |

> Limite : le **code** est notre ; les **protocoles/interfaces** sont alignés ; les **idées/designs** sont empruntées et fusionnées. Là où un détail d'implémentation est cité, on le déclare dans les commentaires du code et dans [NOTICE](NOTICE).

---

## Démarrage rapide

```bash
git clone <ce dépôt> && cd tuan-cli
python -m venv .venv && source .venv/bin/activate    # Windows : .venv\Scripts\activate
pip install -e ".[dev]"

qxt setup
# ou à la main : ~/.qingxiaotuan/config.yaml
#   model.provider: deepseek
#   model.model: deepseek-chat
#   model.api_key_env: DEEPSEEK_API_KEY      # jamais de clé en clair

qxt            # on discute
qxt --print run "Salut, présente-toi en une phrase."
```

---

## Surface de commandes : 105 sous-commandes + 46 commandes slash

| Commande | À quoi ça sert |
|---|---|
| `qxt` | TUI interactif (skin Kimi Code) |
| `qxt setup` / `qxt models` | Configurer le fournisseur / lister 51 fournisseurs et 1100+ modèles |
| `qxt agent` | Agents nommés (compatible `.claude/agents`, découverte en 3 niveaux) |
| `qxt acp` | Lance un serveur ACP pour que VSCode / Zed / JetBrains te pilote |
| `qxt cron` | Tâches planifiées en arrière-plan |
| `qxt doctor` / `qxt bench` | Check-up santé / benchmark |
| `qxt arch demo` | Vérifie l'architecture en 5 couches d'une commande |

Les slash au quotidien : `/plan`·`/model`·`/undo`·`/impact`·`/swarm`·`/log`·`/stats`·`/cost`·`/budget`·`/goal`·`/sandbox`·`/offline`·`/verify`·`/audit`·`/more`·`/help` — liste complète via `Ctrl-G` dans le TUI.

---

## Trois boucles, une main ferme

- **ReActLoop** — pense → agit → observe, le rythme par défaut.
- **PlannerExecuteLoop** — un modèle fort planifie, un modèle pas cher exécute (`router.*` permet de compartimenter plan/exécution). Le roi des économies de tokens.
- **DevLoop** — écris-vérifie-soigne : `/verify` détecte le projet (Python/Node/Rust/Go), infère les commandes de test et se soigne jusqu'à N tours.

## Le modèle de sécurité : quatre barrières + défaire à livre ouvert

1. **Score statique** — chaque commande shell notée `none→critical` par `safety_engine.score()`, avec dépliage des indirections (IFS, `$VAR`, substitution, échappements ANSI-C/octal/hex, PowerShell Base64, NFKC ; ≤32 de récursion).
2. **Blocage par rayon d'impact** — tu vois ce que ça touchera **avant** que ça parte (`--impact`).
3. **Plancher de lignes rouges en YOLO** — YOLO supprime les confirmations par étape mais **ne** touche **pas** aux lignes rouges (`rm` récursif, force-push, `chmod -R 000 /`… jamais en auto).
4. **Livre de comptes** — chaque écriture est auditée ; `/undo` restaure via diff `reverse_transform` + snapshots.

Les règles résolvent toujours `deny > ask > allow`. Utilise `qxt safe allow <cmd>` pour la liste blanche ; ne désactive pas la sécu pour gagner des clics.

---

## Là où tes idées tournent

- **Mémoire** — trois niveaux (utilisateur/projet/session) + SQLite FTS5 (trigram), dégrade en texte brut si indisponible.
- **Sous-agents** — délégation typée (general-purpose / explore / plan / coder), sous-agents isolés, workers concurrents et Swarm pour découper les longues tâches.
- **Cron et arrière-plan** — `qxt cron start --detach` ; autonomie en headless.
- **Hooks** — `PreToolUse` peut `block` ou réécrire `args` (`hooks.allow_edit_args`).
- **Observabilité** — `/stats`·`/audit`·`/impact`·`/bench`·`/cost` ; le coût sur la table.
- **crypto** — v2 solide : AES-GCM(AEAD) avec `cryptography`, sinon chiffrement de flux HMAC-SHA256 ; `open()` sans MAC / altéré fait toujours fail-closed.

---

## Dev & contrat

```bash
python -m pytest tests/ -q        # 2500+ tests
python -m mypy qingxiaotuan       # porte des types
qxt --print run "Salut, une ligne." # smoke
```

- **Discipline i18n** : README_zh-CN est le maître de référence ; chaque langue est une localisation vivante, zéro dérive — **aucune traduction mécanique.**
- **Échelle** : ~412 `.py` / ~79 k lignes / 41 paquets / 36 plugins.
- **Version** : `v0.2.018` (0.x/Beta) ; les changements qui cassent préviennent en version mineure + notes de migration.
- **En profondeur** : signatures des neuf moteurs et un tutoriel de nouvelle outil vivent dans l'appendice de `README_zh-CN.md`.

---

## Connexion : GitHub / Apple / DeepSeek (optionnel · hors ligne par défaut)

- Tuan-CLI fonctionne hors ligne sans aucun compte. La connexion est une couche optionnelle.
- `qxt login` / `qxt login github` / `qxt logout` / `qxt whoami`.
- Identifiants dans `~/.qingxiaotuan/auth-config.toml` ou variables d'environnement `QXT_GITHUB_*` / `QXT_APPLE_*` / `QXT_DEEPSEEK_*` (variables prioritaires).
- Callback OAuth par défaut `http://127.0.0.1:8765/callback` ; `auth.json` stocke les jetons en clair — protégez votre répertoire personnel et déconnectez-vous sur les machines partagées.
- Détails dans README_zh-CN.md (maître) et README.md.

---

## License & liens

- **License** : MIT (utilise, modifie, redistribue ; garde l'avis)
- **À lire** : [SECURITY.md](SECURITY.md) · [CHANGELOG.md](CHANGELOG.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [NOTICE](NOTICE)

> Tu veux « une expérience clé en main, fermée, mariée à un fournisseur » ? Ça ne manque pas. Tu veux **tourner sur tes propres modèles, garder le contrôle et pouvoir revenir en arrière** ? Les clés sont ici.