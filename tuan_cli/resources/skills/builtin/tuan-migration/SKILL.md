---
name: tuan-migration
description: >
  代码迁移与版本升级技能。覆盖语言版本升级 (Python 2→3、Java 8→17、
  Node 16→20)、框架迁移 (Django→FastAPI、Express→Next.js、jQuery→React、
  Redux→Zustand)、数据库迁移 (MySQL→PostgreSQL、MongoDB→PostgreSQL、
  Elasticsearch→OpenSearch)、构建工具迁移 (Webpack→Vite、Maven→Gradle、
  npm→pnpm)、ORM 迁移、认证迁移、部署迁移、单体→微服务拆分、
  迁移策略 (大爆炸/增量/绞杀者)、回滚方案、兼容性测试、
  数据迁移脚本、双写模式、灰度迁移。当用户要求迁移、migration、
  升级、upgrade、版本升级、框架迁移、数据库迁移、语言升级、
  重构迁移、迁移方案、回滚方案、兼容性测试、数据迁移、双写、
  灰度迁移、单体拆分、微服务拆分时使用。
activation: proactive
priority: 85
provides:
  - migration
  - upgrade
  - refactoring
  - version-upgrade
suggests:
  - code-architect
  - safe-refactor
  - database-patterns
  - test-driven-dev
triggers:
  - 迁移
  - migration
  - 升级
  - upgrade
  - 版本升级
  - 框架迁移
  - 数据库迁移
  - 语言升级
  - 重构迁移
  - 迁移方案
  - 回滚方案
  - 兼容性测试
  - 数据迁移
  - 双写
  - 灰度迁移
  - 单体拆分
  - 微服务拆分
  - upgrade
  - refactor
license: MIT
metadata:
  version: "1.0.0"
---

# TUAN Migration — 代码迁移与版本升级

## 迁移策略矩阵

| 策略 | 风险 | 速度 | 适用场景 | 回滚难度 |
|------|------|------|----------|----------|
| 大爆炸 (Big Bang) | 高 | 快 | 小项目、紧急升级 | 中 |
| 绞杀者 (Strangler Fig) | 中 | 中 | 大系统重构 | 低 |
| 增量迁移 (Incremental) | 低 | 慢 | 核心业务系统 | 低 |
| 双写 (Dual Write) | 中 | 中 | 数据库迁移 | 中 |
| 并行运行 (Parallel Run) | 低 | 慢 | 关键路径迁移 | 低 |

## 迁移四步法

```
1. 评估 (Assess) → 2. 规划 (Plan) → 3. 执行 (Execute) → 4. 验证 (Verify)
```

### Step 1: 评估

```
[现状扫描]
- 代码扫描: 版本、依赖、技术债务
- 依赖分析: 直接/间接依赖、版本冲突
- 兼容性检查: 破坏性变更、废弃 API
- 测试覆盖: 现有测试能否保护迁移

[影响分析]
- 受影响模块清单
- 破坏性变更列表
- 迁移工作量估算
- 回滚方案
```

### Step 2: 规划

```
[阶段划分]
Phase 1: 基础准备 (依赖升级、环境配置)
Phase 2: 核心迁移 (核心逻辑、数据层)
Phase 3: 外围迁移 (UI、集成、部署)
Phase 4: 清理验证 (移除旧代码、性能验证)

[兼容性策略]
- 抽象层: 迁移期间新旧接口共存
- 特性开关: Feature Flag 控制新旧路径
- 灰度发布: 10% → 50% → 100%
```

### Step 3: 执行

```
[迁移原则]
1. 一次只迁移一个关注点 (不混入重构)
2. 每个阶段有独立可运行的状态
3. 迁移脚本可重入 (幂等)
4. 保留回滚点

[CI/CD 集成]
- 迁移 PR 必须通过所有现有测试
- 新增迁移相关测试
- 迁移脚本自动运行
- 数据备份在迁移前自动执行
```

### Step 4: 验证

```
[功能验证]
- 现有测试全部通过
- 新增边界用例测试
- 性能基准对比 (迁移前后)

[数据验证]
- 数据完整性检查 (行数、checksum)
- 数据一致性检查 (跨表关联)
- 数据迁移回滚测试

[监控验证]
- 错误率对比
- 延迟对比
- 资源使用对比
```

## 语言版本升级

### Python 2 → 3

```python
# 常见变更
# 1. print 函数
print("hello")  # 不是 print "hello"

# 2. Unicode 默认
s = "hello"  # 不是 s = u"hello"

# 3. 整数除法
result = 10 / 3  # 3.333... 不是 3

# 4. range
for i in range(10):  # 不是 xrange(10)

# 5. input 是 str
name = input("Name: ")  # 不是 raw_input

# 工具: 2to3、futurize
# 检查: python -W error -c "import sys; sys.exit(0 if sys.version_info >= (3, 0) else 1)"
```

### Node.js 版本升级

```javascript
// Node 16 → 20 常见变更
// 1. 模块系统 (CommonJS → ESM)
import { foo } from './bar.js';  // 不是 require

// 2. 异步迭代
for await (const line of fs.createReadStream('file.txt')) { }

// 3. 测试内置 (Node 20+)
import { test } from 'node:test';
test('works', () => { assert.ok(true); });

// 工具: node --check, npx semantic-release
```

## 数据库迁移

### MySQL → PostgreSQL

```sql
-- 常见类型映射
-- MySQL        → PostgreSQL
-- VARCHAR      → VARCHAR
-- INT          → INTEGER
-- BIGINT       → BIGINT
-- DECIMAL      → NUMERIC
-- DATETIME     → TIMESTAMP
-- TIMESTAMP    → TIMESTAMPTZ
-- JSON         → JSONB
-- ENUM         → CREATE TYPE ... AS ENUM

-- MySQL AUTO_INCREMENT → PostgreSQL SERIAL / GENERATED ALWAYS AS IDENTITY
-- MySQL DATETIME DEFAULT CURRENT_TIMESTAMP → GENERATED DEFAULT AS CURRENT_TIMESTAMP
-- MySQL CHECK → PostgreSQL CHECK (语法相似)
-- MySQL ENGINE=InnoDB → 不需要 (PostgreSQL 默认)
-- MySQL INDEX name ON → CREATE INDEX idx_name ON table (column)
```

### 数据迁移脚本 (幂等)

```python
def migrate_data():
    """幂等数据迁移: 可安全重复运行。"""
    conn = get_connection()
    with conn.cursor() as cur:
        # 1. 创建目标表 (IF NOT EXISTS)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users_new (
                id BIGSERIAL PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                name VARCHAR(100) NOT NULL,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 2. 迁移数据 (去重)
        cur.execute("""
            INSERT INTO users_new (email, name, created_at)
            SELECT email, name, created_at
            FROM users_old
            WHERE NOT EXISTS (
                SELECT 1 FROM users_new WHERE email = users_old.email
            )
        """)
        
        # 3. 验证
        old_count = cur.execute("SELECT COUNT(*) FROM users_old").fetchone()[0]
        new_count = cur.execute("SELECT COUNT(*) FROM users_new").fetchone()[0]
        assert old_count == new_count, f"数据不一致: old={old_count} new={new_count}"
        
        conn.commit()
```

## 框架迁移

### 绞杀者模式 (Strangler Fig)

```
[阶段 1] 建立代理层
    旧系统 ← 代理层 (新) → 新系统 (部分)
    
[阶段 2] 逐步迁移
    旧系统 ← 代理层 → 新系统 (大部分)
    
[阶段 3] 完成迁移
    旧系统 (移除) ← 代理层 → 新系统 (全部)
```

```python
# 代理层示例 (兼容新旧接口)
class UserServiceProxy:
    def get_user(self, user_id):
        if self.should_use_new(user_id):
            return self.new_service.get_user(user_id)
        return self.old_service.get_user(user_id)
    
    def should_use_new(self, user_id):
        """特性开关: 逐步扩大迁移范围"""
        return user_id in self.feature_flags.enabled_users
```

## 检查清单

### 评估阶段
- [ ] 现有代码扫描完成
- [ ] 依赖版本分析完成
- [ ] 破坏性变更列表完成
- [ ] 工作量估算完成
- [ ] 回滚方案完成

### 执行阶段
- [ ] 特性开关就位
- [ ] 抽象层就位 (新旧共存)
- [ ] 迁移脚本幂等
- [ ] 数据备份完成
- [ ] CI/CD 通过

### 验证阶段
- [ ] 所有测试通过
- [ ] 性能基准对比完成
- [ ] 数据完整性验证完成
- [ ] 监控确认无误
- [ ] 回滚点保留

### 清理阶段
- [ ] 旧代码移除
- [ ] 旧依赖移除
- [ ] 文档更新
- [ ] 团队培训完成
```
