---
name: 数据库模式
description: 数据库操作最佳实践：查询优化/索引/迁移/事务/连接池/ORM 使用
tags: [database, sql, migration, orm, query-optimization]
priority: 7
updated_at: 0
use_count: 0
---

# 数据库模式

数据库是应用的地基。地基歪了，上面的楼怎么盖都白搭。

## 查询优化

### N+1 问题 (最常见性能杀手)

```python
# ❌ N+1: 1 次查用户 + N 次查订单
users = User.objects.all()
for user in users:
    orders = Order.objects.filter(user_id=user.id)  # 每个用户一次查询！

# ✅ JOIN 或 prefetch
users = User.objects.prefetch_related('orders').all()  # 只有 2 次查询
# 或
users = User.objects.annotate(order_count=Count('orders')).all()
```

### 索引策略

```sql
-- ✅ 给 WHERE 条件加索引
CREATE INDEX idx_orders_user_id ON orders(user_id);

-- ✅ 复合索引 (注意列顺序: 等值在前, 范围在后)
CREATE INDEX idx_orders_user_status ON orders(user_id, status);

-- ❌ 不要给低选择性列加索引 (如 gender)
CREATE INDEX idx_users_gender ON users(gender);  -- 只有 M/F，索引无意义
```

### 避免 SELECT *

```python
# ❌ 查所有列 (浪费内存和带宽)
cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))

# ✅ 只查需要的列
cursor.execute("SELECT id, name, email FROM users WHERE id = ?", (user_id,))
```

## 事务

```python
# ✅ 原子操作
with db.transaction():
    account_a.balance -= 100
    account_a.save()
    account_b.balance += 100
    account_b.save()
    # 任何异常自动回滚

# ❌ 非原子 (中间失败导致数据不一致)
account_a.balance -= 100
account_a.save()  # 如果这里成功了...
account_b.balance += 100
account_b.save()  # ...但这里失败了，钱就丢了
```

## 连接池

```python
# ✅ 使用连接池
from sqlalchemy import create_engine
engine = create_engine(
    "postgresql://...",
    pool_size=20,        # 保持 20 个连接
    max_overflow=10,     # 最多额外 10 个
    pool_recycle=3600,   # 1 小时回收
)

# ❌ 每次请求创建新连接 (耗尽连接池)
def handle_request():
    conn = create_engine("postgresql://...").connect()  # 每次都新建！
```

## 迁移

```bash
# 生成迁移
alembic revision --autogenerate -m "add users table"

# 应用迁移
alembic upgrade head

# 回滚
alembic downgrade -1
```

迁移规则：
1. **永远不要手动改生产数据库** — 通过迁移脚本
2. **向前兼容** — 新列用默认值，不要 `NOT NULL` 无默认值
3. **测试迁移** — 在 staging 环境先跑一遍
4. **备份** — 大迁移前备份数据

## ORM 使用原则

```python
# ✅ 批量操作
User.objects.bulk_create([User(name=f"user_{i}") for i in range(1000)])

# ❌ 逐条插入
for i in range(1000):
    User.objects.create(name=f"user_{i}")  # 1000 次 INSERT！

# ✅ 更新用 update (绕过 ORM 钩子，直接 SQL)
User.objects.filter(is_active=False).update(is_active=True)

# ❌ 逐条更新
for user in User.objects.filter(is_active=False):
    user.is_active = True
    user.save()  # N 次 UPDATE！
```

## 连接泄漏防护

```python
# ✅ with 语句自动关闭
with db.connection() as conn:
    result = conn.execute(query)
# 连接自动归还池

# ❌ 忘记关闭
conn = db.connection()
result = conn.execute(query)
# conn 永远不会关闭，连接池耗尽
```

## 监控

```sql
-- 查看慢查询
SELECT query, mean_time, calls
FROM pg_stat_statements
ORDER BY mean_time DESC
LIMIT 10;

-- 查看索引使用情况
SELECT indexrelname, idx_scan, idx_tup_read
FROM pg_stat_user_indexes
ORDER BY idx_scan ASC;
```
