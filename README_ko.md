# Tuan-CLI

> **「Model + Harness = Agent」** — "생각"과 "안전하게 굴리기"를 갈라서, 둘 다 열쇠를 손에 쥐여줍니다.
> 안전 우선 · 모델 무관 · 순수 Python AI Agent Harness. `v0.3.0` · MIT · Python ≥ 3.10

**언어/Language:** [English](README.md) · [简体中文](README_zh-CN.md) · [繁體中文](README_zh-GAT.md) · [日本語](README_ja.md) · **한국어** · [Español](README_es.md) · [Português (Brasil)](README_pt-BR.md) · [Français](README_fr.md) · [Deutsch](README_de.md) · [Русский](README_ru.md)

**깔아보기 전에:** [SECURITY.md](SECURITY.md)（위협 모델）· [CHANGELOG.md](CHANGELOG.md)（버전 규율）· [ARCHITECTURE.md](ARCHITECTURE.md)（아키텍처）· `qxt models list-providers`

---

## 한 줄 요약

남들은 "모델 하나에 껍데기 씌우기". 칭샤오퇀은 반대——**뇌 갈아끼우기 가능한 몸통**을 줍니다. 55개 프로바이더 핫스왑, 완전 오프라인, 실수는 되돌리고, 명령 실행**전에** 영향 범위를 보여줍니다. **생각은 모델이, 그걸 받쳐주는 건 이 녀석이.**

**이건 아니다**: 특정 모델 전용 함체 아님(핫스왑·자체호스팅·오프라인 자유); IDE의 수행원 아님(표준 터미널 도구, ACP로 VSCode/Zed/JetBrains가 몰아붙임); 한 겹짜리 취약한 추상체도 아님(개발자용 마이크로커널 + 일반인용 원샷 `setup`).

---

## 뭐가 다르냐

| 이거 | 어디까지 |
|---|---|
| 🛡️ **안전 우선** | 4중 게이트: 정적 리스크 판정, 영향 범위 사전 차단, YOLO 레드라인 바닥, 트랜잭션 원장으로 정밀 `/undo` |
| 🔌 **모델 무관** | 55 프로바이더 + 로컬 Ollama + 핫스왑 + 자동 라우팅（`router.*`） |
| 🧠 **세 가지 메인 루프** | ReAct / Planner-Execute / DevLoop 플러그형 — 하나의 커널, 여러 '사고 리듬' |
| 🔧 **마이크로커널** | 한 줄 `@plugin`, 서비스 레지스트리, append-only 이벤트 버스, hook 미들웨어 |
| 🗂️ **메모리** | SQLite FTS5 + 세션 이벤트 스트림; 3계층 메모리, `/undo`, checkpoint, replay, Trajectory 내보내기 |
| 🧩 **생태계** | MCP + ACP — 도구를 꽂거나, IDE한테 몰아붙여짐 |
| 🌍 **10개 언어** | 기본 중국어 포함 전면 로컬라이즈 |
| 🐍 **순수 Python** | 약 412 `.py` / 약 7.9만 줄 / 41 패키지 / 36 플러그인, MIT |

---

## 솔직히 말해서

**Q: 이거 진짜 '독자 개발'이야? 숨기는 거 없지?**
둘로 나눠서 답합니다. **코드**는 자체 구현: 커널과 대부분의 기능(`core/`·`runtime/`·`arch/`·`tools/`·`ports/` 등)은 Python으로 아키텍처부터 한 줄 한 줄 손으로 썼고, 상호운용을 위해 외부 **프로토콜**에만 인터페이스를 맞췄습니다. 하지만 **아이디어와 설계**는 알려진 에이전트 프로젝트에서 적극적으로 빌리고 섞었습니다——숨길 게 아니라, 기존의 어깨 위에 서는 일이죠. **코드는 우리 것, 아이디어는 빌린 것**, 그렇게 나눠 보세요. 유일하게 '스타일'까지 유지한 건 `--tui` 터미널 UI——Kimi Code의 시그니처 스타일(`#4FA8FF` 메인, 달 모양 스피너, 두 줄 상태바)을 의도적으로 따랐습니다("손맛 좋으면 새로 안 만든다".) 크레딧은 [NOTICE](NOTICE). 전체 목록은 아래 [영감과 출처 표기](#영감과-출처-표기).

**Q: 왜 명령 실행 전에 막는데?**
기능이지 버그 아님. 위험 명령은 원래 확인을 받고, YOLO도 하드 레드라인은 못 어김. 귀찮으면 `qxt safe allow <cmd>`로 허용목록에——안전을 끄는 게 아니라.

**Q: `/undo`로 진짜 뭘 되돌리는데?**
원장에 기록된 모든 **쓰기**: 단일 파일, 단일 step, 턴 전체. 내부는 트랜잭션 원장 + diff `reverse_transform` + checkpoint 스냅샷. 만능은 아니지만, "까먹음 = 확실한 손해"를 "아마 건질 수 있음"으로 바꿉니다.

**Q: 내 개인 파일 읽을까 걱정돼.**
권한 정책은 domain allow-list로 도구 범위를 제한, 유출 방지용 egress 제어, 출력의 키는 마스킹.

**Q: 완전 오프라인은?**
`qxt models local`로 탐지, `/offline`으로 Ollama 관리. 인터넷 없어도 굴러갑니다.

**Q: 내 도구/플러그인 만들 수 있어?**
당연. `@plugin` 메타데이터 선언, `activate(kernel)` 안에서 `kernel.provide(...)` / `kernel.require(...)`. 3스텝:

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

## 버전 번호와 저장소 이력 (투명 공개)

**왜 `1.0`이 아니라 `0.3.0`인가요?** 정직한 [SemVer](https://semver.org/) 의미론: **`0.x` 버전은 공개 API(CLI 인터페이스, 설정 스키마, 도구 프로토콜, 플러그인 계약)가 아직 동결되지 않았음을 의미**하며 릴리스 간에 변경될 수 있습니다. Tuan-CLI는 이미 폭넓은 기능을 제공합니다 — 안전 게이팅/트랜잭션 롤백, 모델 무관 핫스왑(55개 프로바이더 + 로컬 Ollama), 세 가지 메인 루프, 마이크로커널 플러그인 아키텍처, 3계층 메모리, 에코시스템 상호운용(MCP/ACP/Claude Code/Hermes 브리지), 서브에이전트와 Swarm, cron과 백그라운드 작업, Goal 모드와 정밀 권한 — 모두 테스트로 검증되었습니다. 그러나 **버전 번호는 인터페이스 안정성을 반영할 뿐, 기능 완성도를 반영하지 않습니다**: 기능이 완비되었다고 해서 API를 동결해야 하는 것은 아닙니다. `1.0`은 공개 API가 실제로 안정되어 하위 호환을 약속할 수 있을 때를 위해 남겨둡니다. 그때까지는: 파괴적 변경은 `0.x` 내에서 MINOR(마이그레이션 힌트 포함), 호환 기능은 MINOR, 수정은 PATCH를 올립니다([VERSION_POLICY.md](VERSION_POLICY.md) 참조).

| 버전 번호 의미 | 설명 |
|---|---|
| `0.3.0`(현재) | **API 미동결**: `0.x`에서는 파괴적 조정이 가능하며 마이그레이션 힌트와 함께 공지; 하위 호환은 보장하지 않음 |
| `1.0`(예약) | 공개 API가 동결되고 하위 호환이 보장될 때 활성화; 그때부터 파괴적 변경이 MAJOR(`2.0`)를 올림 |

**Git 이력 공지 (오픈소스 투명성):** 본 저장소의 Git 커밋 이력은 **2026-09-26 저자가 의도적으로 재구축(초기 커밋 이력은 저자가 의도적으로 덮어쎈)**되었으며, 그 이전의 커밋별 진화 기록은 더 이상 추적할 수 없습니다(이전 `.git` 객체 소실). 현재 코드는 아키텍처부터 구현까지 완전히 검토 가능합니다. 2026-09-26 이전의 기능 진화는 [CHANGELOG.md](CHANGELOG.md)의 버전 기록을 기준으로 삼아 주세요 (버전 규율에는 영향이 없습니다). 우리는 이 사실을 꾸밈없이 공개합니다.

---

## 영감과 출처 표기

칭샤오퇀은 돌에서 튀어나온 게 아닙니다. 설계는 명시적으로 아래 '알려진 에이전트 프로젝트와 프로토콜'에 기대고 있습니다. 숨기지 않고 나열합니다(가능하면 소스 주석에도 원출처를 명시):

| 참고 대상 | 무엇을 빌렸는가 |
|---|---|
| **DeepSeek Harness / Cordis** | 마이크로커널 + 서비스 레지스트리 + append-only 이벤트 버스 아키텍처（`core/kernel.py`에 주석） |
| **Kimi Code** | 터미널 TUI의 손맛과 색감（[NOTICE](NOTICE) 참조） |
| **Claude Code** | `/` 슬래시 커맨드 체계, 이름 붙은 에이전트（`.claude/agents` 호환）, Goal 모드, DevLoop 등 인터페이스 정합 |
| **ACP（Agent Client Protocol）** | server/client로서 메시지·핸드셰이크 시맨틱 정합, IDE가 칭샤오퇀을 몰 수 있게 |
| **MCP（Model Context Protocol）** | client로서 프로토콜 정합, 도구 생태계 연결 |
| **OpenAI / Anthropic / Google 등 벤더 API** | provider 어댑터를 공식 REST 시맨틱대로 구현, 프로토콜 적응만·내부 구현 복제 안 함 |

> 경계: **코드**는 자체 개발; **프로토콜/인터페이스**는 정합; **아이디어/설계**는 차용과 융합. 구체적 구현 디테일을 참조한 곳은 해당 소스 주석과 [NOTICE](NOTICE)에 명시합니다.

---

## 퀵스타트

```bash
git clone <이 레포> && cd tuan-cli
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

qxt setup
# 수동으로도: ~/.qingxiaotuan/config.yaml
#   model.provider: deepseek
#   model.model: deepseek-chat
#   model.api_key_env: DEEPSEEK_API_KEY      # 키는 절대 평문으로 안 씀

qxt            # 대화
qxt --print run "안녕? 너를 한 줄로 소개해 봐."
```

---

## 커맨드 면: 105 서브커맨드 + 46 슬래시 커맨드

| 커맨드 | 용도 |
|---|---|
| `qxt` | 대화형 TUI (Kimi Code 스킨) |
| `qxt setup` / `qxt models` | 프로바이더 설정 / 55개 프로바이더 & 1100+ 모델 목록 |
| `qxt agent` | 이름 붙은 에이전트 (`.claude/agents` 호환, 3계층 발견) |
| `qxt acp` | ACP server 켜서 VSCode / Zed / JetBrains가 컨트롤하게 |
| `qxt cron` | 정기 백그라운드 작업 |
| `qxt doctor` / `qxt bench` | 건강검진 / 벤치 |
| `qxt arch demo` | 5계층 아키텍처 한 방에 검증 |

애용 슬래시 커맨드: `/plan`·`/model`·`/undo`·`/impact`·`/swarm`·`/log`·`/stats`·`/cost`·`/budget`·`/goal`·`/sandbox`·`/offline`·`/verify`·`/audit`·`/more`·`/help` — 전체는 TUI에서 `Ctrl-G`.

---

## 세 가지 메인 루프, 같은 안정감

- **ReActLoop**: 생각→행동→확인, 기본 리듬.
- **PlannerExecuteLoop**: 강한 모델이 계획, 싼 모델이 실행（`router.*`로 구획 분리 지원）. 토큰 아끼는 장인.
- **DevLoop**: 쓰고→검증하고→자체 치유. `/verify`가 프로젝트 종류(Python/Node/Rust/Go) 자동 판별, 테스트 커맨드 추론 후 최대 N라운드 수리.

## 안전 모델: 4중 게이트 + 원장식 취소

1. **정적 스코어링** — 모든 셸 커맨드를 `safety_engine.score()`로 `none→critical` 판정, 간접 전개 처리(IFS, `$VAR`, 커맨드 치환, ANSI-C/8진/16진 이스케이프, PowerShell Base64, Unicode NFKC; 재귀 ≤32층).
2. **영향 범위 사전 차단** — 실행**전에** 닿을 범위를 보여줌（`--impact`）。
3. **YOLO 레드라인 바닥** — YOLO는 단계별 확인을 없앨 수 있지만 하드 레드라인（재귀 `rm`, force-push, `chmod -R 000 /`…）은 **절대 자동 실행 불가**.
4. **트랜잭션 원장** — 모든 쓰기 기록, `/undo`는 diff `reverse_transform` + 스냅샷으로 정밀 복원.

규칙은 늘 `deny > ask > allow`. `qxt safe allow <cmd>`로 허용목록을 쓰지, 안전을 꺼서 클릭 수를 줄이지 마세요.

---

## 아이디어 굴리는 곳

- **메모리** — 3계층(유저/프로젝트/세션) + SQLite FTS5(trigram), 못 쓰면 일반 텍스트로 자동 강등.
- **서브에이전트** — 타입드 위임(general-purpose / explore / plan / coder), 격리 서브에이전트, 병렬 워커, Swarm으로 긴 작업 분할.
- **Cron & 백그라운드** — `qxt cron start --detach`; 헤드리스로도 자율 가동.
- **Hooks** — `PreToolUse`가 `block`하거나 `args`를 수정（`hooks.allow_edit_args`）。
- **관측성** — `/stats`·`/audit`·`/impact`·`/bench`·`/cost`; 비용을 테이블 위에.
- **crypto** — v2 확실: `cryptography` 있으면 AES-GCM(AEAD), 없으면 HMAC-SHA256 스트림 암호, `open()`은 MAC 누락·변조 시 늘 fail-closed.

---

## 개발 & 계약

```bash
python -m pytest tests/ -q        # 2500+ 테스트
python -m mypy qingxiaotuan       # 타입 게이트
qxt --print run "안녕."            # 스모크
```

- **다국어 문서 규율**: `README_zh-CN.md`가 권위 있는 마스터. 각 언어는 "생생하고, 드리프트 없이" 로컬라이즈, **기계 번역 금지**.
- **규모**: 약 412 `.py` / 약 7.9만 줄 / 41 패키지 / 플러그인 36.
- **버전**: `v0.3.0` (`0.x` 라인 — API는 아직 동결되지 않음); 파괴적 조정은 사전 공지 + 마이그레이션 힌트와 함께, `1.0`은 API 동결을 위해 예약됨.
- **딥다이브**: 9대 엔진 시그니처와 새 도구 워크스루는 `README_zh-CN.md` 부록.

---

## 완전 로컬 오프라인 · 계정 로그인 없음

Tuan-CLI는 **계정 로그인을 제공하지 않습니다**: GitHub / Apple / DeepSeek 연동도, OAuth 콜백도, 로그인 토큰 저장도 없습니다. 이는 의도된 설계입니다 — **직접 설정한 모델 API 외에는 모두 로컬에서 실행됩니다**.

- **로그인 없이 완전히 사용 가능**: 파일 입출력, 명령 실행, 메모리, 스킬, 서브에이전트, 안전 가드 모두 로컬.
- **유일한 "클라우드"는 당신의 모델 API**: 키는 당신 것이며, 해당 엔드포인트 요청에만 쓰이고 제3자를 거치지 않습니다.
- **완전 오프라인으로 쓰려면**: Ollama 또는 llama.cpp 설치 → `qxt models local` 탐지 → `qxt models set ollama <모델>` 연결.

### 모델 API 키 설정

```bash
qxt models set deepseek deepseek-chat   # 프로바이더와 모델 선택
qxt models                              # 대화형 설정 (키는 ~/.qingxiaotuan/.env 에 저장)
```

키는 `~/.qingxiaotuan/.env` 에 모입니다(권한 600 권장·커밋 금지). 환경 변수(예: `DEEPSEEK_API_KEY`)도 가능합니다.

> **투명 공개**: 이전 버전에는 GitHub / Apple / DeepSeek 계정 로그인(웹 세션 토큰 경로 포함)이 있었습니다.
> "완전 로컬 오프라인" 포지셔닝과 충돌하고, 웹 엔드포인트는 비공개·비지원 인터페이스로 리스크 관리에 걸려 **기능 전체를 제거**했습니다. 모델 호출은 공식 API + 본인의 키로 하세요.

## License & 관련

- **License**: MIT（자유 사용·수정·배포, 저작권 표시 유지）
- **필독**: [SECURITY.md](SECURITY.md) · [CHANGELOG.md](CHANGELOG.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [NOTICE](NOTICE)

> "박스깨고 나오자마자 특정 벤더에 묶이고 싶다"는 사람들은 다른 거 고르세요. **내 모델로 돌리고, 통제권을 갖고, 사고 났을 때 되돌릴 수 있는**——열쇠는 여기.