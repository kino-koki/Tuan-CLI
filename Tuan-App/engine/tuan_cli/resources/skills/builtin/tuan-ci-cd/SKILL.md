---
name: tuan-ci-cd
description: >
  CI/CD 流水线技能。覆盖 GitHub Actions、GitLab CI、Jenkins、Buildkite、
  流水线设计模式、分支策略 (GitFlow/GitHub Flow)、制品管理、
  环境管理 (dev/staging/prod)、发布策略 (蓝绿/金丝雀/滚动)、
  回滚、基础设施即代码 (Terraform/Pulumi)、安全扫描集成、
  测试金字塔、部署自动化、变更管理。当用户要求 CI/CD、ci cd、
  流水线、pipeline、GitHub Actions、GitLab CI、Jenkins、部署、
  deployment、发布、release、制品、artifact、蓝绿部署、金丝雀、
  回滚、rollback、Terraform、Pulumi、环境管理、变更管理时使用。
activation: proactive
priority: 85
provides:
  - ci-cd
  - pipeline
  - deployment
  - release
  - automation
suggests:
  - tuan-docker
  - tuan-security
  - tuan-observability
triggers:
  - CI/CD
  - ci cd
  - 流水线
  - pipeline
  - GitHub Actions
  - GitLab CI
  - Jenkins
  - 部署
  - deployment
  - 发布
  - release
  - 制品
  - artifact
  - 蓝绿部署
  - 金丝雀
  - 回滚
  - rollback
  - Terraform
  - Pulumi
  - 环境管理
  - 变更管理
  - deploy
  - workflow
license: MIT
metadata:
  version: "1.0.0"
---

# TUAN CI/CD — 流水线与部署自动化

## 流水线设计模式

```
提交 → 构建 → 测试 → 扫描 → 打包 → 部署 → 验证 → 发布
         │       │      │      │      │
         │       │      │      │      └─ dev/staging/prod
         │       │      │      └─ 依赖扫描 (SCA)
         │       │      └─ 安全扫描 (SAST)
         │       └─ 单元/集成测试
         └─ 构建产物
```

## GitHub Actions 模式

### 完整流水线

```yaml
name: CI/CD

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.10", "3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }
      - run: pip install -r requirements.txt
      - run: pytest --cov --cov-report=xml
      - uses: codecov/codecov-action@v4

  security:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: github/codeql-action/analyze@v3
      - name: Dependency scan
        run: pip-audit --fail

  build:
    needs: security
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build Docker image
        run: docker build -t myapp:${{ github.sha }} .
      - name: Push to registry
        run: |
          echo "${{ secrets.REGISTRY_TOKEN }}" | docker login registry.example.com -u bot --password-stdin
          docker push registry.example.com/myapp:${{ github.sha }}

  deploy:
    needs: build
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    environment: production
    steps:
      - name: Deploy
        run: |
          ./deploy.sh --version ${{ github.sha }} --env production
      - name: Verify
        run: |
          curl -f https://api.example.com/health
          curl -f https://api.example.com/version | grep ${{ github.sha }}
```

### 缓存优化

```yaml
- name: Cache dependencies
  uses: actions/cache@v4
  with:
    path: ~/.cache/pip
    key: ${{ runner.os }}-pip-${{ hashFiles('**/requirements.txt') }}

- name: Cache build artifacts
  uses: actions/cache@v4
  with:
    path: |
      node_modules
      target
    key: ${{ runner.os }}-build-${{ hashFiles('**/package-lock.json', '**/Cargo.lock') }}
```

## 发布策略

### 蓝绿部署

```
生产流量 → [Blue 集群 (v1)] ← 切换 → [Green 集群 (v2)]
              ↓
         验证失败? 切回 Blue
```

### 金丝雀部署

```
生产流量 → [金丝雀 (10%) v2] → 监控错误率/延迟
         → [稳定 (90%) v1]

错误率 > 1%? 停止金丝雀，回滚
错误率 < 1%? 逐步扩大: 10% → 25% → 50% → 100%
```

### 滚动部署

```
Pod 1: v1 → 停止 → v2 → 就绪
Pod 2: v1 → 停止 → v2 → 就绪
Pod 3: v1 → 停止 → v2 → 就绪
(逐个替换，始终有 N-1 个 Pod 可用)
```

## 环境管理

| 环境 | 用途 | 配置 | 数据 |
|------|------|------|------|
| dev | 开发 | 最小配置 | 种子数据 |
| test | 测试 | 同 prod | 脱敏数据 |
| staging | 预发 | 同 prod | 脱敏数据 |
| prod | 生产 | 完整配置 | 真实数据 |

### 配置管理

```yaml
# 环境变量分层
dev:     --config config/dev.yaml
test:    --config config/test.yaml --db-url test-db.example.com
staging: --config config/staging.yaml --secret-ref k8s://staging/secrets
prod:    --config config/prod.yaml --secret-ref vault://prod/secrets
```

## 回滚策略

```bash
# 快速回滚 (5 分钟内)
kubectl rollout undo deployment/api-server
kubectl rollout status deployment/api-server

# 版本回滚
kubectl set image deployment/api-server api=myapp:1.2.3  # 从 1.3.0 回到 1.2.3

# 数据库回滚
psql -f migrations/20260101_rollback.sql
```

## 基础设施即代码

### Terraform 基本模式

```hcl
resource "aws_s3_bucket" "app_logs" {
  bucket = "myapp-logs"
  tags   = { Environment = var.environment, Project = "myapp" }
}

resource "aws_s3_bucket_lifecycle_configuration" "app_logs" {
  bucket = aws_s3_bucket.app_logs.id
  rule {
    id     = "explore"
    status = "Enabled"
    transition { days = 30; storage_class = "STANDARD_IA" }
    transition { days = 90; storage_class = "GLACIER" }
    expiration { days = 365 }
  }
}
```

## 检查清单

- [ ] 流水线覆盖: 构建→测试→扫描→打包→部署→验证
- [ ] 分支保护 (PR required, status checks)
- [ ] 环境分离 (dev/staging/prod)
- [ ] 制品版本化 (SHA 标签)
- [ ] 安全扫描集成 (SAST + SCA)
- [ ] 回滚策略已定义和测试
- [ ] 部署验证 (健康检查 + 版本检查)
- [ ] 基础设施即代码 (Terraform/Pulumi)
- [ ] 密钥管理 (不硬编码)
- [ ] 流水线通知 (Slack/Teams/Discord)
- [ ] 变更日志自动生成
```
