# Provenance & Auditability Statement

> 中文摘要：本仓库的 git 提交历史并**非"有意隐藏/覆盖"**——真实情况是：早期项目未纳入 Git 版本管理，代码在其他机器上开发，后因该机器损坏导致部分早期记录丢失，之后重建了 Git 历史；**所幸硬盘未损坏**，当前代码完整可审查。git 历史不可考对几乎所有人无影响，不必揪着不放。该日期之前的逐提交演进已不可审计；
> 工作区至今保留着两个历史 `.git` 备份目录，其中 `.git.broken-20261015` 仍是一个合法仓库，
> 且含有一段与主线矛盾（版本号倒退）的提交序列。本文只记录可复现的证据、其影响，以及可执行的补强措施。

This document records, without editorialising, what is verifiable about this repository's
lineage and what the gaps in it imply. Every claim below is reproducible with the commands
given; nothing here presents inference as fact.

## 1. Status

- The repository is **functionally reviewable**: the current tree is complete, and the path
  from architecture to implementation can be followed.
- The repository is **not historically auditable**: for anything before 2026-09-26 the
  question "who changed what, when, and why" is not answerable. For the periods after that
  it is only weakly answerable, because those periods are single-author squashes.
- This matters most where this codebase matters most. Tuan-CLI ships a
  **safety-critical** command-execution and permission-gating surface — a tool that decides
  what a user may run cannot rely on an unauditable change history.

## 2. Self-disclosure already on record

`README.md`, section *"Version number & repository history (transparent disclosure)"*, states:

> This repository's Git commit history was **not "deliberately hidden/overwritten"** — the project
> was not under Git version control in its early days; the code was developed on a different
> machine. That machine later failed, causing some early records to be lost, and the Git history
> was rebuilt afterwards. **Fortunately the disk was not damaged**, and the current code is fully
> reviewable. The unverifiable early history has no impact on virtually anyone; we ask readers
> not to dwell on it.

This document does not re-litigate that decision. It records its consequences and the
concrete gaps it leaves.

## 3. Evidence in the commit graph

68 commits exist across all refs, spanning 2026-09-26 → 2026-10-24:

```
$ git log --all --oneline | wc -l
68
$ git log --all --format='%ad' --date=short | sort -u | sed -n '1p;$p'
2026-09-26
2026-10-24
```

**Two author identities, non-contiguous ranges:**

| Author identity | Commits | Date range |
|---|---|---|
| `Qingnai-Tech <1736306360@qq.com>` | 31 | 2026-09-26 → 2026-10-06 |
| `kino-koki <kino-koki@users.no-repo.github.com>` | 37 | 2026-10-17 → 2026-10-24 |

No commits exist between 2026-10-06 and 2026-10-17 — a ten-day gap.

```
$ git log --all --format='%an <%ae>' | sort | uniq -c
```

**Five commits titled `init`, interleaved with feature work — not ancestors at the base:**

| Commit | Date | Author |
|---|---|---|
| `e54daf1` | 2026-10-17 | kino-koki |
| `6adc414` | 2026-10-18 | kino-koki |
| `08d0e8b` | 2026-10-18 | kino-koki |
| `f04231d` | 2026-10-24 | kino-koki |
| `c8a74d4` | 2026-10-24 | kino-koki |

`init` is not the only reset marker. Two further commits on the rebuild date describe it
directly:

- `35815a4` (2026-09-26, Qingnai-Tech) — subject: `chore(repo) 重新初始化仓库: 以当前工作树建立单一初始提交`
  *(re-initialise the repository: establish a single initial commit from the current working tree)*
- `7e5e15a` (2026-09-26, Qingnai-Tech) — subject: `chore(gitignore) 忽略损坏仓库备份目录 .git.broken-*`
  *(ignore the corrupted-repository backup directories)*

The rebuild and the archiving of the discarded repository therefore happened in the same
session, which is consistent with the working tree still carrying those directories.

## 4. Evidence on disk

Two backup stores sit at the repository root. They are covered by `.gitignore:150`
(`.git.broken-*/`), so they are not tracked.

**`.git.broken-20260926` — 2,163,879 bytes. Not a repository.**
`git` refuses it (`fatal: not a git repository`): `HEAD`, `refs/` and `index` are absent,
leaving only `objects/`, `hooks/`, `info/` and `logs/`. The single pack still holds a
usable object set:

```
$ git verify-pack -v --stat-only <...>\pack-39e686e2….idx
non delta: 817 objects
chain length = 1: 203 objects
...
```

Type histogram of that pack:

| Type | Count |
|---|---|
| commit | 21 |
| tree | 175 |
| blob | 922 |

So the pre-rebuild history was **not physically destroyed** — 21 commit objects survive.
It is only *unreachable*: the ref and HEAD metadata that addressed them is gone.

**`.git.broken-20261015` — 9,951,542 bytes. A valid repository.**
On branch `main`, containing exactly two commits:

| Commit | Date | Author | Subject |
|---|---|---|---|
| `34fd2ba` | 2026-10-13 | kino-koki \<kino-koki@users.noreply.github.com\> | `Initial commit: Tuan-CLI v0.4.0` |
| `45a6716` | 2026-10-14 | kino-koki \<kino-koki@users.noreply.github.com\> | `v0.3.1: repo hygiene, credential cleanup, bug fixes, README localization` |

Two discrepancies against the live repository:

- **Identity:** the same author name is bound to `users.noreply.github.com` here but to
  `users.no-repo.github.com` in the live repository.
- **Version sequence:** an "Initial commit" labelled v0.4.0 is *followed* by a v0.3.1
  release — the sequence runs backwards.

So at least two mutually inconsistent commit histories have existed for this codebase, and
neither can be reconciled into the other.

**Other signals from the live repository:**

| Signal | Value |
|---|---|
| `git reflog --all` | 0 entries — no local undo or audit trail |
| `git remote -v` | no remotes configured |
| `git fsck --unreachable` | nothing dangling in the live repo |
| Tag `v0.3-P` | lightweight (`cat-file -t` → `commit`); no tag object, so no signature possible |
| Tag `v0.3.0` | annotated, but **unsigned** (no `gpgsig`) |
| `gpg.program` / `commit.gpgsign` | both unset |

## 5. What this means for review

| Question | Answerable? |
|---|---|
| Is this code safe to run? | Yes — reviewable in the current tree, covered by tests. |
| Who introduced behaviour *X*, and when? | No, before 2026-09-26. Weakly afterwards: both surviving ranges are single-author squashes. |
| Was this security fix reviewed against the code it replaced? | No — the pre-fix baseline is not available to diff against. |
| Is the release identical to what was tested? | Not establishable — there are no signed tags and no recorded build provenance. |

For a tool whose purpose is gating dangerous commands, "we cannot diff a security fix
against its pre-fix baseline" is a governance weakness, not a cosmetic one. It does not
make the current code unsafe; it makes the *claims* about the code unverifiable.

## 6. Remediation

None of this requires recovering the lost history. Each item makes the history that remains
trustworthy going forward.

**1. Sign releases.** Configure a signing key per maintainer, then:

```
git tag -s vX.Y.Z -m "vX.Y.Z"
git verify-tag vX.Y.Z          # must exit 0
git push origin vX.Y.Z
```

Set `tag.gpgsign=true` and publish the maintainer public keys in the repository so the
tag chain can be checked independently. A CI job that fails unsigned tags at the release
boundary turns this from a convention into a gate.

**2. Attach build provenance to every release.** Publish, with each release:

- the exact tagged commit SHA, and `git rev-parse <tag>^{tree}`;
- a tracked-file manifest with hashes, e.g. `git ls-tree -r -z <tag> | xargs -0 sha256sum`;
- toolchain and dependency versions, and whether the artifact was built from a clean
  checkout of that SHA;
- a reproducible-build check, i.e. rebuild from the tag and compare artifact hashes.

**3. Give security fixes their own advisory.** Each security fix gets an individual record
(its own identifier, affected range, the vulnerable commit SHA, the fixed commit SHA, and
the diff between them) rather than being folded into a general hygiene release. A single
security change bundled into a large sweep is exactly the case that becomes unverifiable.

**4. Keep an audit log outside the working tree.** Append-only, immutability-backed storage
(object storage with WORM, or a self-chained signed log) recording release builds, tag
creation, maintainer changes and credential rotations. Do **not** rely on `.git/logs` —
this repository's reflog is demonstrably empty.

**5. Decide the fate of the two backup stores.** They are ignored, but still present in the
working tree. An unaddressed pack containing 21 commit objects is a latent data-integrity
and credential surface. Choose explicitly and document it: archive them out of the working
tree under a stated retention policy, or delete them.

**6. Freeze the current state as a baseline.** Create an annotated, signed tag on the
current HEAD now. That gives every future change — including the first security fix — a
known-good reference point to diff against.

## 7. Reproducing this document

```
git log --all --oneline | wc -l
git log --all --format='%an <%ae>' | sort | uniq -c
git log --all --format='%h %ad %an | %s' --date=short | grep -Ei 'init|重新|broken|repo'
git tag -l
git cat-file -t refs/tags/v0.3-P      # "commit"  -> lightweight
git cat-file -p refs/tags/v0.3.0      # look for "^gpgsig"
git remote -v
git reflog --all
git verify-pack -v --stat-only .git.broken-20260926/objects/pack/*.idx
git --git-dir=.git.broken-20261015 log --format='%h %ad %an <%ae> | %s' --date=short
```

## 8. Scope of this document

This file records repository metadata and its auditability consequences. It is not a
security review, it makes no claim about the correctness of any code, and it makes no claim
about the intentions of any contributor.
