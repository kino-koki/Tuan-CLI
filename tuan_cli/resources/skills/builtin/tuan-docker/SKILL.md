---
name: tuan-docker
description: >
  Docker 与容器化技能。覆盖 Dockerfile 最佳实践、多阶段构建、镜像优化、
  Docker Compose、容器编排、Kubernetes 基础、镜像安全扫描、CI/CD 集成。
  当用户要求 Docker、容器化、Dockerfile、Compose、镜像、Kubernetes、
  容器部署、镜像优化、Docker 构建、容器安全时使用。
activation: proactive
priority: 82
provides:
  - docker
  - containerization
  - compose
  - kubernetes
suggests:
  - tuan-ci-cd
  - tuan-security
  - code-architect
triggers:
  - Docker
  - docker
  - Dockerfile
  - 容器化
  - 容器
  - Compose
  - compose
  - 镜像
  - image
  - Kubernetes
  - k8s
  - 容器部署
  - 镜像优化
  - Docker 构建
  - 容器安全
  - container
  - podman
license: MIT
metadata:
  version: "1.0.0"
---

# TUAN Docker — 容器化与编排

## Dockerfile 最佳实践

### 基础镜像选择

| 运行时 | 推荐基础镜像 | 大小 |
|--------|-------------|------|
| Python | `python:3.12-slim` | ~150MB |
| Node.js | `node:20-alpine` | ~50MB |
| Go | `golang:1.22-alpine` (build) + `alpine` (runtime) | ~10MB |
| Rust | `rust:slim` (build) + `debian:bookworm-slim` (runtime) | ~50MB |
| Java | `eclipse-temurin:21-jre-alpine` | ~100MB |

### 多阶段构建 (关键)

```dockerfile
# 阶段 1: 构建
FROM golang:1.22-alpine AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o /server .

# 阶段 2: 运行
FROM alpine:3.20
RUN apk add --no-cache ca-certificates tzdata
COPY --from=builder /server /server
EXPOSE 8080
USER 1001:1001  # 非 root 运行
ENTRYPOINT ["/server"]
```

### 层缓存优化

```dockerfile
# 好: 依赖先复制 (变化少，缓存命中)
COPY go.mod go.sum ./
RUN go mod download
COPY . .

# 坏: 源码先复制 (每次变化，缓存失效)
COPY . .
RUN go mod download
```

### 安全加固

```dockerfile
# 非 root 用户
RUN addgroup -S appgroup && adduser -S appuser -G appgroup
USER appuser

# 只读文件系统 (运行时)
# docker run --read-only --tmpfs /tmp -v /app:/app:ro myapp

# 无敏感信息 (构建时)
# 不要 COPY .env、不要 COPY credentials
```

## Docker Compose 模式

```yaml
version: "3.9"

services:
  api:
    build: .
    ports:
      - "8080:8080"
    environment:
      - DATABASE_URL=postgresql://app:app@db:5432/app
    depends_on:
      db:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: app
      POSTGRES_PASSWORD: app
      POSTGRES_DB: app
    volumes:
      - dbdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "app"]
      interval: 10s
      retries: 5

volumes:
  dbdata:
```

## 镜像优化检查清单

```bash
# 1. 镜像大小
docker images --format "table {{.Repository}}:{{.Tag}}\t{{.Size}}"

# 2. 层分析
docker history myapp

# 3. 安全扫描
docker scout quickview myapp

# 4. 构建时间
docker build --progress=plain . 2>&1 | grep -E "^STEP"

# 5. 运行时检查
docker run --rm myapp sh -c 'id && which server && cat /etc/passwd | tail -1'
```

## Kubernetes 基础

### Pod 规范

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api-server
spec:
  replicas: 3
  selector:
    matchLabels:
      app: api-server
  template:
    metadata:
      labels:
        app: api-server
    spec:
      containers:
        - name: api
          image: myapp:latest
          ports:
            - containerPort: 8080
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: 500m
              memory: 512Mi
          livenessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 30
          readinessProbe:
            httpGet:
              path: /ready
              port: 8080
            initialDelaySeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: api-service
spec:
  selector:
    app: api-server
  ports:
    - port: 80
      targetPort: 8080
  type: LoadBalancer
```

## 检查清单

- [ ] 多阶段构建，运行时镜像最小化
- [ ] 非 root 用户运行
- [ ] 依赖文件先复制 (缓存优化)
- [ ] 无敏感信息 (.env, credentials)
- [ ] 健康检查 (liveness + readiness)
- [ ] 资源限制 (CPU + memory)
- [ ] 镜像标签 (不是 latest)
- [ ] Compose 用于本地开发
- [ ] .dockerignore 排除无关文件
- [ ] 安全扫描通过
```
