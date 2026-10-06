# 版本迭代策略 / Version Iteration Policy

> **⚠️ 必读 / MANDATORY** — 本文件对 kino-koki 所有开发者、内部人员、PR提交者具有强制约束力。违反本策略的PR将被拒绝。
> **This document is mandatory for all developers, contributors, and PR submitters. PRs violating this policy will be rejected.**

**Language / 语言:** [English](#english) · [简体中文](#简体中文) · [繁體中文](#繁體中文) · [日本語](#日本語) · [한국어](#한국어) · [Español](#español) · [Português](#português) · [Français](#français) · [Deutsch](#deutsch) · [Русский](#русский)

---

## English

### Core Principle: Semantic Versioning

Tuan-CLI follows [SemVer](https://semver.org/). The project is currently in its **`0.x` line — the public API is not yet frozen**. Version numbers communicate interface stability, not effort or pride:

- Breaking changes within `0.x` bump **MINOR** (e.g. `0.3.0` → `0.4.0`) and MUST be announced with migration hints
- New backward-compatible features bump **MINOR** (e.g. `0.3.0` → `0.4.0`)
- Bug fixes / docs / internal refactors bump **PATCH** (e.g. `0.3.0` → `0.3.1`)

The previous "small-steps / annual-lock" policy (max bump +0.0.001, no jump to 0.3 before Chinese New Year 2027) is **abolished**. Version bumps are decided by the SemVer nature of the change — not by the calendar, not by how impressive the work looks.

### Version Bump Rules

| Level | When | Example |
|-------|------|---------|
| **MAJOR** | Breaking changes — **only after the API freeze** (from `1.0` on) | `1.0` → `2.0` |
| **MINOR** | New features; also breaking adjustments while in `0.x` | `0.3.0` → `0.4.0` |
| **PATCH** | Bug fixes, docs, internal refactors, security patches without behavior change | `0.3.0` → `0.3.1` |

Breaking changes MUST be announced in advance with migration hints; the version number itself is the signal (a MINOR bump while in `0.x`, a MAJOR bump only past `1.0`). Releases pass the full test suite and the CHANGELOG gate before publishing.

### PR/Commit Checklist

Each PR must confirm before submission:
- [ ] Version in `pyproject.toml` and `qingxiaotuan/__init__.py` are identical
- [ ] CHANGELOG.md top entry matches the current version
- [ ] Version is not lower than the previous release (no downgrade)
- [ ] Version bump level matches the SemVer nature of the change

**Any PR violating the above will be closed immediately without review.**

---

## 简体中文

### 核心原则：语义化版本

青小团遵循 [SemVer](https://semver.org/)。当前处于 **`0.x` 阶段——公共 API 尚未冻结**。版本号表达的是接口稳定度，不是工作量，也不是“面子”：

- `0.x` 内的破坏性变更 → 升 **MINOR**（如 `0.3.0` → `0.4.0`），须提前公告并给出迁移提示
- 向后兼容的新功能 → 升 **MINOR**（如 `0.3.0` → `0.4.0`）
- Bug 修复 / 文档 / 内部重构 → 升 **PATCH**（如 `0.3.0` → `0.3.1`）

旧的「小步快跑 / 年度锁定」策略（版本号最多 +0.0.001、2027 年春节前不得跃迁至 0.3 及以上）**已废除**。版本号由变更的 SemVer 语义决定——不由日历决定，也不由"看起来是否 NB"决定。

### 版本号递增规则

| 级别 | 触发条件 | 示例 |
|------|---------|------|
| **MAJOR** | 不兼容变更 —— **仅在 API 冻结后**（`1.0` 起） | `1.0` → `2.0` |
| **MINOR** | 新增功能；`0.x` 阶段的破坏性调整亦升此级 | `0.3.0` → `0.4.0` |
| **PATCH** | Bug 修复、文档、内部重构、无行为变化的安全补丁 | `0.3.0` → `0.3.1` |

破坏性变更必须提前公告并提供迁移提示；版本号本身即信号（`0.x` 阶段为 MINOR 升级，`1.0` 之后才为 MAJOR）。发版前必须跑通全量测试与 CHANGELOG 门禁。

### PR/提交检查清单

每个 PR 提交前必须确认：
- [ ] `pyproject.toml` 与 `qingxiaotuan/__init__.py` 中的版本号一致
- [ ] CHANGELOG.md 顶层条目与当前版本一致
- [ ] 版本号不低于上一发布（禁止回退）
- [ ] 版本递增级别与变更的 SemVer 性质相符

**违反以上任何一条的PR将被直接关闭，不进入评审流程。**

---

## 繁體中文

### 核心原則：語義化版本

青小團遵循 [SemVer](https://semver.org/)。當前處於 **`0.x` 階段——公共 API 尚未凍結**。版本號表達的是介面穩定度，不是工作量，也不是“面子”：

- `0.x` 內的破壞性變更 → 升 **MINOR**（如 `0.3.0` → `0.4.0`），須提前公告並給出遷移提示
- 向後相容的新功能 → 升 **MINOR**（如 `0.3.0` → `0.4.0`）
- Bug 修復 / 文件 / 內部重構 → 升 **PATCH**（如 `0.3.0` → `0.3.1`）

舊的「小步快跑 / 年度鎖定」策略（版本號最多 +0.0.001、2027 年春節前不得躍遷至 0.3 及以上）**已廢除**。版本號由變更的 SemVer 語義決定——不由日曆決定，也不由"看起來是否 NB"決定。

### 版本號遞增規則

| 級別 | 觸發條件 | 示例 |
|------|---------|------|
| **MAJOR** | 不相容變更 —— **僅在 API 凍結後**（`1.0` 起） | `1.0` → `2.0` |
| **MINOR** | 新增功能；`0.x` 階段的破壞性調整亦升此級 | `0.3.0` → `0.4.0` |
| **PATCH** | Bug 修復、文件、內部重構、無行為變化的安全修補 | `0.3.0` → `0.3.1` |

破壞性變更必須提前公告並提供遷移提示；版本號本身即信號（`0.x` 階段為 MINOR 升級，`1.0` 之後才為 MAJOR）。發版前必須跑通全量測試與 CHANGELOG 門禁。

### PR/提交檢查清單

每個 PR 提交前必須確認：
- [ ] `pyproject.toml` 與 `qingxiaotuan/__init__.py` 中的版本號一致
- [ ] CHANGELOG.md 頂層條目與目前版本一致
- [ ] 版本號不低於上一發布（禁止回退）
- [ ] 版本遞增級別與變更的 SemVer 性質相符

**違反以上任何一條的PR將被直接關閉，不進入評審流程。**

---

## 日本語

### 核心理念：セマンティックバージョニング

Tuan-CLI は [SemVer](https://semver.org/) に従います。現在は **`0.x` 系——公開 API はまだ凍結されていません**。バージョン番号はインターフェースの安定度を表すものであり、作業量や「格好よさ」ではありません：

- `0.x` 内の破壊的変更 → **MINOR** アップ（例：`0.3.0` → `0.4.0`）、事前告知と移行ヒントが必須
- 後方互換な新機能 → **MINOR** アップ（例：`0.3.0` → `0.4.0`）
- Bug修正 / ドキュメント / 内部リファクタリング → **PATCH** アップ（例：`0.3.0` → `0.3.1`）

旧「小刻み・年度ロック」方針（最大 +0.0.001、2027年旧正月まで 0.3 以上へのジャンプ禁止）は**廃止**されました。バージョンは変更の SemVer 意味論で決まります——暦や「見た目の凄さ」とは無関係です。

### バージョン増分規則

| レベル | 条件 | 例 |
|--------|------|----|
| **MAJOR** | 非互換変更 —— **API 凍結後のみ**（`1.0` 以降） | `1.0` → `2.0` |
| **MINOR** | 新機能；`0.x` 段階の破壊的調整もこのレベル | `0.3.0` → `0.4.0` |
| **PATCH** | Bug修正、ドキュメント、内部リファクタリング、動作変更のないセキュリティパッチ | `0.3.0` → `0.3.1` |

破壊的変更は事前に告知し、移行ヒントを提供します。バージョン番号自体がシグナルです（`0.x` 段階は MINOR アップ、`1.0` 以降のみ MAJOR）。リリース前に全テストと CHANGELOG ゲートを通過する必要があります。

### PR/コミットチェックリスト

各 PR は提出前に確認すること：
- [ ] `pyproject.toml` と `qingxiaotuan/__init__.py` のバージョンが一致
- [ ] CHANGELOG.md の最上位エントリが現在のバージョンと一致
- [ ] バージョンが前リリースより低くない（ダウングレード禁止）
- [ ] バージョン増分レベルが変更の SemVer 性質と一致

**上記に違反するPRはレビューなしで即クローズされます。**

---

## 한국어

### 핵심 원칙: 시맨틱 버저닝

Tuan-CLI는 [SemVer](https://semver.org/)를 따릅니다. 현재 **`0.x` 라인——공개 API는 아직 동결되지 않았습니다**. 버전 번호는 인터페이스 안정성을 나타내며, 작업량이나 "보기 좋음"과는 무관합니다:

- `0.x` 내의 파괴적 변경 → **MINOR** 상향(예: `0.3.0` → `0.4.0`), 사전 공지와 마이그레이션 힌트 필수
- 하위 호환 신기능 → **MINOR** 상향(예: `0.3.0` → `0.4.0`)
- 버그 수정 / 문서 / 내부 리팩터링 → **PATCH** 상향(예: `0.3.0` → `0.3.1`)

기존 "소폭 증분·연도 고정" 정책(최대 +0.0.001, 2027년 설날까지 0.3 이상 점프 금지)은 **폐지**되었습니다. 버전은 변경의 SemVer 의미로 결정됩니다——달력이나 "인상적인 숫자"와는 무관합니다.

### 버전 증분 규칙

| 레벨 | 조건 | 예 |
|------|------|----|
| **MAJOR** | 비호환 변경 —— **API 동결 이후에만**(`1.0`부터) | `1.0` → `2.0` |
| **MINOR** | 신기능; `0.x` 단계의 파괴적 조정도 이 급 | `0.3.0` → `0.4.0` |
| **PATCH** | 버그 수정, 문서, 내부 리팩터링, 동작 변화 없는 보안 패치 | `0.3.0` → `0.3.1` |

파괴적 변경은 사전에 공지하고 마이그레이션 힌트를 제공합니다. 버전 번호 자체가 신호입니다(`0.x` 단계는 MINOR 상향, `1.0` 이후에만 MAJOR). 릴리스 전 전체 테스트와 CHANGELOG 게이트를 통과해야 합니다.

### PR/커밋 체크리스트

각 PR은 제출 전에 확인해야 합니다:
- [ ] `pyproject.toml`과 `qingxiaotuan/__init__.py`의 버전이 일치
- [ ] CHANGELOG.md 최상위 항목이 현재 버전과 일치
- [ ] 버전이 이전 릴리스보다 낮지 않음(다운그레이드 금지)
- [ ] 버전 증분 수준이 변경의 SemVer 특성과 일치

**위 규칙을 위반한 PR은 리뷰 없이 즉시 닫힙니다.**

---

## Español

### Principio central: Versionado Semántico

Tuan-CLI sigue [SemVer](https://semver.org/). El proyecto está actualmente en su **línea `0.x`: la API pública aún no está congelada**. El número de versión refleja la estabilidad de la interfaz, no la cantidad de trabajo ni la apariencia:

- Cambios disruptivos dentro de `0.x` → subir **MINOR** (p. ej. `0.3.0` → `0.4.0`), con aviso previo y notas de migración
- Funciones nuevas compatibles hacia atrás → subir **MINOR** (p. ej. `0.3.0` → `0.4.0`)
- Correcciones de bugs / documentación / refactor interno → subir **PATCH** (p. ej. `0.3.0` → `0.3.1`)

La antigua política de «pasos pequeños / bloqueo anual» (máx. +0.0.001, sin saltar a 0.3 antes del Año Nuevo Chino 2027) queda **derogada**. La versión la decide la semántica SemVer del cambio — no el calendario ni «lo impresionante que parezca».

### Reglas de incremento de versión

| Nivel | Cuándo | Ejemplo |
|-------|--------|---------|
| **MAJOR** | Cambios incompatibles —— **solo tras el congelamiento de la API** (desde `1.0`) | `1.0` → `2.0` |
| **MINOR** | Nuevas funciones; también ajustes disruptivos en la línea `0.x` | `0.3.0` → `0.4.0` |
| **PATCH** | Correcciones de bugs, documentación, refactor interno, parches de seguridad sin cambio de comportamiento | `0.3.0` → `0.3.1` |

Los cambios disruptivos se anuncian con antelación y se ofrecen pistas de migración; el número de versión es en sí la señal (un salto MINOR en `0.x`, MAJOR solo a partir de `1.0`). Los lanzamientos pasan el suite completo de pruebas y la compuerta de CHANGELOG antes de publicarse.

### Lista de verificación de PR/commits

Cada PR debe confirmar antes de enviarse:
- [ ] La versión en `pyproject.toml` y `qingxiaotuan/__init__.py` es idéntica
- [ ] La entrada superior de CHANGELOG.md coincide con la versión actual
- [ ] La versión no es menor que la anterior (sin degradaciones)
- [ ] El nivel de incremento coincide con la naturaleza SemVer del cambio

**Cualquier PR que viole lo anterior se cerrará de inmediato sin revisión.**

---

## Português

### Princípio central: Versionamento Semântico

O Tuan-CLI segue [SemVer](https://semver.org/). O projeto está atualmente na sua **linha `0.x`: a API pública ainda não está congelada**. O número de versão reflete a estabilidade da interface, não a quantidade de trabalho nem a aparência:

- Mudanças que quebram dentro de `0.x` → subir **MINOR** (ex.: `0.3.0` → `0.4.0`), com aviso prévio e notas de migração
- Novos recursos retrocompatíveis → subir **MINOR** (ex.: `0.3.0` → `0.4.0`)
- Correções de bugs / documentação / refatoração interna → subir **PATCH** (ex.: `0.3.0` → `0.3.1`)

A antiga política de «pequenos passos / trava anual» (máx. +0.0.001, sem saltar para 0.3 antes do Ano Novo Chinês 2027) está **revogada**. A versão é decidida pela semântica SemVer da mudança — não pelo calendário nem por «parecer impressionante».

### Regras de incremento de versão

| Nível | Quando | Exemplo |
|-------|--------|---------|
| **MAJOR** | Mudanças incompatíveis —— **somente após o congelamento da API** (a partir de `1.0`) | `1.0` → `2.0` |
| **MINOR** | Novos recursos; também ajustes que quebram na linha `0.x` | `0.3.0` → `0.4.0` |
| **PATCH** | Correções de bugs, documentação, refatoração interna, patches de segurança sem mudança de comportamento | `0.3.0` → `0.3.1` |

Mudanças que quebram são anunciadas com antecedência com dicas de migração; o próprio número de versão é o sinal (um salto MINOR em `0.x`, MAJOR apenas a partir de `1.0`). Lançamentos passam o conjunto completo de testes e a porta de CHANGELOG antes de publicar.

### Lista de verificação de PR/commits

Cada PR deve confirmar antes do envio:
- [ ] A versão em `pyproject.toml` e `qingxiaotuan/__init__.py` é idêntica
- [ ] A entrada superior de CHANGELOG.md coincide com a versão atual
- [ ] A versão não é inferior à anterior (sem downgrade)
- [ ] O nível de incremento coincide com a natureza SemVer da mudança

**Qualquer PR que viole o acima será fechado imediatamente sem revisão.**

---

## Français

### Principe central : Versionnage sémantique

Tuan-CLI suit [SemVer](https://semver.org/). Le projet est actuellement sur sa **lignée `0.x` : l'API publique n'est pas encore figée**. Le numéro de version reflète la stabilité de l'interface, pas la quantité de travail ni l'apparence :

- Changements cassants dans `0.x` → monter **MINOR** (ex. `0.3.0` → `0.4.0`), avec préavis et notes de migration
- Nouvelles fonctions rétrocompatibles → monter **MINOR** (ex. `0.3.0` → `0.4.0`)
- Corrections de bugs / documentation / refactor interne → monter **PATCH** (ex. `0.3.0` → `0.3.1`)

L'ancienne politique « petits pas / verrou annuel » (max +0.0.001, pas de passage à 0.3 avant le Nouvel An chinois 2027) est **abolie**. La version est décidée par la sémantique SemVer du changement — pas par le calendrier ni par « l'impressionnant ».

### Règles d'incrémentation

| Niveau | Quand | Exemple |
|--------|-------|---------|
| **MAJOR** | Changements incompatibles —— **uniquement après le gel de l'API** (à partir de `1.0`) | `1.0` → `2.0` |
| **MINOR** | Nouvelles fonctions ; aussi les ajustements cassants en `0.x` | `0.3.0` → `0.4.0` |
| **PATCH** | Corrections de bugs, documentation, refactor interne, correctifs de sécurité sans changement de comportement | `0.3.0` → `0.3.1` |

Les changements cassants sont annoncés à l'avance avec des pistes de migration ; le numéro de version est lui-même le signal (un saut MINOR en `0.x`, MAJOR seulement à partir de `1.0`). Les versions passent la suite complète de tests et la porte CHANGELOG avant publication.

### Liste de vérification PR/commit

Chaque PR doit confirmer avant soumission :
- [ ] La version dans `pyproject.toml` et `qingxiaotuan/__init__.py` est identique
- [ ] L'entrée supérieure de CHANGELOG.md correspond à la version actuelle
- [ ] La version n'est pas inférieure à la précédente (pas de downgrade)
- [ ] Le niveau d'incrément correspond à la nature SemVer du changement

**Tout PR violant ce qui précède sera fermé immédiatement sans revue.**

---

## Deutsch

### Kernprinzip: Semantische Versionierung

Tuan-CLI folgt [SemVer](https://semver.org/). Das Projekt befindet sich derzeit in seiner **`0.x`-Linie — die öffentliche API ist noch nicht eingefroren**. Versionsnummern drücken die Stabilität der Schnittstelle aus, nicht den Aufwand und nicht das Ansehen:

- Breaking Changes innerhalb von `0.x` → **MINOR** anheben (z. B. `0.3.0` → `0.4.0`), mit Vorankündigung und Migrationshinweisen
- Neue rückwärtskompatible Funktionen → **MINOR** anheben (z. B. `0.3.0` → `0.4.0`)
- Bugfixes / Doku / interne Refactorings → **PATCH** anheben (z. B. `0.3.0` → `0.3.1`)

Die alte Politik «kleine Schritte / Jahres-Sperre» (max. +0.0.001, kein Sprung auf 0.3 vor dem chinesischen Neujahr 2027) ist **abgeschafft**. Die Version richtet sich nach der SemVer-Semantik der Änderung — nicht nach dem Kalender oder «wie beeindruckend es aussieht».

### Versionsinkrement-Regeln

| Ebene | Wann | Beispiel |
|-------|------|----------|
| **MAJOR** | Inkompatible Änderungen —— **erst nach dem API-Freeze** (ab `1.0`) | `1.0` → `2.0` |
| **MINOR** | Neue Funktionen; auch Breaking-Anpassungen in der `0.x`-Linie | `0.3.0` → `0.4.0` |
| **PATCH** | Bugfixes, Doku, interne Refactorings, Sicherheitspatches ohne Verhaltensänderung | `0.3.0` → `0.3.1` |

Breaking Changes werden im Voraus mit Migrationshinweisen angekündigt; die Versionsnummer selbst ist das Signal (ein MINOR-Sprung in `0.x`, MAJOR erst ab `1.0`). Releases bestehen die vollständige Testsuite und das CHANGELOG-Gate vor der Veröffentlichung.

### PR/Commit-Checkliste

Jeder PR muss vor dem Einreichen bestätigen:
- [ ] Die Version in `pyproject.toml` und `qingxiaotuan/__init__.py` ist identisch
- [ ] Der oberste Eintrag in CHANGELOG.md entspricht der aktuellen Version
- [ ] Die Version ist nicht niedriger als das vorherige Release (kein Downgrade)
- [ ] Das Inkrement-Niveau entspricht der SemVer-Natur der Änderung

**Jeder PR, der das oben Genannte verletzt, wird ohne Review sofort geschlossen.**

---

## Русский

### Основной принцип: семантическое версионирование

Tuan-CLI следует [SemVer](https://semver.org/). Проект сейчас находится на **линии `0.x` — публичный API ещё не заморожен**. Номер версии отражает стабильность интерфейса, а не объём работы и не «внешний блеск»:

- Ломающие изменения внутри `0.x` → поднять **MINOR** (например, `0.3.0` → `0.4.0`), с предварительным анонсом и подсказками по миграции
- Новые обратно совместимые функции → поднять **MINOR** (например, `0.3.0` → `0.4.0`)
- Исправления ошибок / документация / внутренний рефакторинг → поднять **PATCH** (например, `0.3.0` → `0.3.1`)

Прежняя политика «маленькие шаги / годовое ограничение» (макс. +0.0.001, запрет перехода на 0.3 до китайского Нового года 2027) **отменена**. Версия определяется семантикой SemVer изменения — не календарём и не «впечатляющим видом».

### Правила инкремента версии

| Уровень | Когда | Пример |
|---------|-------|--------|
| **MAJOR** | Несовместимые изменения —— **только после заморозки API** (начиная с `1.0`) | `1.0` → `2.0` |
| **MINOR** | Новые функции; также ломающие правки на линии `0.x` | `0.3.0` → `0.4.0` |
| **PATCH** | Исправления ошибок, документация, внутренний рефакторинг, патчи безопасности без изменения поведения | `0.3.0` → `0.3.1` |

Ломающие изменения анонсируются заранее с подсказками по миграции; сам номер версии является сигналом (MINOR внутри `0.x`, MAJOR только начиная с `1.0`). Релизы проходят полный набор тестов и порог CHANGELOG перед публикацией.

### Контрольный список PR/коммитов

Каждый PR должен подтвердить перед отправкой:
- [ ] Версия в `pyproject.toml` и `qingxiaotuan/__init__.py` идентична
- [ ] Верхняя запись CHANGELOG.md соответствует текущей версии
- [ ] Версия не ниже предыдущего релиза (запрет даунгрейда)
- [ ] Уровень инкремента соответствует семантике SemVer изменения

**Любой PR, нарушающий вышеуказанное, будет закрыт немедленно без ревью.**
