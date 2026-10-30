---
name: 安全提交与 PR 流程
description: 从工作区到可合入 PR 的完整流程，覆盖提交规范、自测、变更范围控制与审查准备
activation: auto
triggers: 提交, commit, PR, 合并, pull request, 提交流程
provides: git-flow
suggests: code-review-checklist, git-workflow
priority: 70
updated_at: 0
use_count: 0
---
# 安全提交与 PR 流程

提交不是「git add . 然后 commit」，是把变更安全地送进主干的过程。

## 提交前自检
- 先 git_status / git_diff 看真实变更集：有没有误改、调试残留、大文件、密钥。
- 跑一遍相关测试：目标路径的测试全绿再提交；红就说明行为变了。
- 拆提交：一个逻辑变更一个 commit，别把重构和功能混在一个提交里。

## 提交规范
- 用 Conventional Commits：`type(scope): 描述`（feat / fix / refactor / docs / test ...）。
- 描述聚焦「为什么」：修了什么、影响什么、怎么验证的。
- 不把生成物/缓存/机密放进版本库（检查 .gitignore）。

## 推送与分支
- 功能分支命名清晰：`feat/xxx`、`fix/xxx`，从最新主干切出，别从旧提交上长。
- 推送前先同步远端主干（rebase，非 merge），避免历史分叉难合入。

## PR 准备
- PR 描述写清：动机、改动点、影响面、测试方式、截图/日志证据。
- 控制 PR 范围：一个 PR 一个主题，过大就拆分。
- 自查一遍再提：自己先 review，别把脏活丢给 reviewer。

## 合入后
- 合入后验证主干（跑 CI / 冒烟）。
- 清理已合并分支，保持仓库整洁。
