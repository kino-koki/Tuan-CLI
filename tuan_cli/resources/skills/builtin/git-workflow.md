---
name: Git 工作流
description: Git 版本控制最佳实践：提交规范/分支策略/合并冲突/rebase/cherry-pick
tags: [git, version-control, commit, branch, merge, rebase]
priority: 6
updated_at: 0
use_count: 0
---

# Git 工作流

Git 不只是版本控制，是团队协作的语言。

## 提交规范

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Type
- `feat`: 新功能
- `fix`: 修复 bug
- `refactor`: 重构 (不改行为)
- `perf`: 性能优化
- `test`: 补测试
- `docs`: 文档
- `chore`: 构建/工具/依赖
- `style`: 格式 (不影响逻辑)

### 示例

```bash
# ✅ 好的提交
git commit -m "feat(auth): add JWT refresh token support

Implement automatic token refresh when access token expires.
Refresh token is stored in httpOnly cookie for security.

Closes #123"

# ❌ 差的提交
git commit -m "fix bug"  # 什么 bug？怎么修的？
git commit -m "update"   # 更新了什么？
git commit -m "wip"      # 工作中的提交不应该进主分支
```

## 分支策略

```
main (生产)
├── develop (开发)
│   ├── feature/user-auth
│   ├── feature/payment
│   └── fix/login-error
├── release/v1.2
└── hotfix/critical-bug
```

### 规则
1. **main 永远可部署** — 不直接提交
2. **feature 分支从 develop 拉** — 完成后 PR 合回
3. **hotfix 从 main 拉** — 修完同时合回 main 和 develop
4. **删除已合并的分支** — 保持仓库整洁

## 合并 vs Rebase

```bash
# merge: 保留完整历史，但可能有合并提交
git merge feature-branch

# rebase: 线性历史，但改写了提交历史
git rebase main
```

### 选择指南
| 场景 | 用 merge | 用 rebase |
|---|---|---|
| 公共分支 (已推送) | ✅ | ❌ (危险) |
| 本地 feature 分支 | ✅ | ✅ |
| 想保留合并记录 | ✅ | ❌ |
| 想要线性历史 | ❌ | ✅ |

## 合并冲突解决

```bash
# 1. 拉取最新
git fetch origin
git rebase origin/main

# 2. 解决冲突
# 编辑冲突文件, 选择保留哪部分

# 3. 标记已解决
git add <conflicted-file>
git rebase --continue

# 4. 放弃 rebase (搞砸了)
git rebase --abort
```

## Cherry-pick (移植提交)

```bash
# 把某个提交移植到当前分支
git cherry-pick <commit-hash>

# 移植多个
git cherry-pick <hash1> <hash2> <hash3>

# 移植范围
git cherry-pick <start>..<end>
```

## .gitignore 规则

```gitignore
# 依赖目录
node_modules/
venv/
.venv/

# 构建产物
dist/
build/
*.pyc

# 环境变量 (密钥！)
.env
.env.local

# IDE
.vscode/
.idea/

# OS
.DS_Store
Thumbs.db

# 测试临时目录
.pytest_cache/
```

## 常用命令

```bash
# 查看谁改了某行 (blame)
git blame file.py

# 查看某个提交的详细改动
git show <commit>

# 搜索提交内容
git log --grep="keyword"

# 搜索代码改动
git log -S "function_name"

# 交互式暂存 (只暂存部分改动)
git add -p

# 撤销工作区改动
git checkout -- file.py

# 撤销已暂存
git reset HEAD file.py

# 修改最近一次提交
git commit --amend -m "new message"
```

## 安全

- **不要提交密钥** — 用 `.gitignore` 排除 `.env`
- **已经提交了密钥** — 立即轮换密钥，用 `git filter-branch` 从历史中删除
- **强制推送前** — 三思，再三思，确保不会丢失别人的工作
