# 审稿协作平台 - 开发目录

## 技术栈（当前实际部署形态）

- 后端：Django 5.2 + Django REST Framework 3.18 + SimpleJWT + PostgreSQL 15
- 前端：Vue 3 + Element Plus + Pinia + Vue Router 4（Vite 构建）
- 文件存储：本地文件系统（backend/media/）

相对技术实施方案的两处降级（均有据可依，见技术方案 §6.3 技术降级行）：

| 计划 | 实际 | 说明 |
|------|------|------|
| Elasticsearch 8 + IK 分词 | PostgreSQL `icontains` | 单机部署 ES 运维成本高，P0 数据量下 icontains 性能足够 |
| Redis + Celery 定时任务 | Django 管理命令 + cron | T-19 各定时逻辑全部落在 `process_scheduled` 命令中，见下文 |

通知（T-02）目前仅站内信，邮件通道未接线（`.env.example` 中 `CELERY_*` 均为未接线占位）。

## 目录结构

```
dev/
├── backend/               # Django 后端
│   ├── review_platform/   # Django 项目配置（settings.py 从 backend/.env 读环境变量）
│   ├── apps/
│   │   ├── users/         # 用户模块 (T-01)，含 management/commands/bootstrap_dev.py
│   │   ├── notifications/ # 通知模块 (T-02，仅站内信)
│   │   ├── files/         # 文件模块 (T-03)
│   │   ├── tasks/         # 审稿任务管理 (T-10~T-20)，含 state_machine.py
│   │   │   └── management/commands/process_scheduled.py   # T-19 定时任务
│   │   ├── forms/         # 结构化审稿表单 (T-30~T-34)
│   │   ├── summaries/     # 审稿意见汇总与规则引擎 (T-40~T-45)
│   │   └── knowledge/     # 审稿知识库 (T-50~T-56)
│   ├── media/             # 上传文件存储
│   ├── requirements.txt
│   ├── .env.example       # 环境变量模板（复制为 .env 后填写）
│   └── manage.py
├── frontend/              # Vue3 前端（Vite）
├── pgdata/                # PostgreSQL 15 数据目录（本地开发集群）
├── .venv/                 # Python 虚拟环境
└── README.md              # 本文件
```

## 环境搭建（从零到可运行）

```bash
# 1. Python 虚拟环境（Python 3.12+）
cd dev
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt

# 2. PostgreSQL（本仓库自带集群目录 pgdata/）
/opt/homebrew/opt/postgresql@15/bin/pg_ctl -D pgdata -l pgdata/server.log start
# 首次部署需初始化并授权（已做过则跳过）：
#   initdb -D pgdata；createuser review_user；createdb review_platform -O review_user

# 3. 数据库迁移 + 演示数据
cd backend
cp .env.example .env    # 按需填写；默认值即指向本地 pgdata 集群
python manage.py migrate
python manage.py bootstrap_dev   # 幂等：创建演示账号 + 默认模板 + 种子数据

# 4. 启动后端（默认 127.0.0.1:8000）
python manage.py runserver

# 5. 前端
cd ../frontend
npm install
npm run dev            # 开发服务器
npm run build          # 生产构建（输出 dist/）
```

## 演示账号（bootstrap_dev 创建，密码默认 `Demo@2026`，可用 `BOOTSTRAP_PASSWORD` 覆盖）

| 邮箱 | 角色 |
|------|------|
| editor@review.local | 编辑部 |
| reviewer1~3@review.local | 审稿人 |
| author@review.local | 作者 |

## 定时任务（T-19：`process_scheduled`）

一条命令覆盖四类定时逻辑，幂等可重跑：

1. 邀请过期：`INVITED` 超邀请有效期的分配置 `EXPIRED`；任务回落 `PENDING` 并计重试
2. 截止提醒：deadline 剩 7/3/1 天的分配发站内提醒（同日去重）
3. 超时标记：`ACCEPTED/REVIEWING` 超 deadline 置 `OVERDUE`；全员落定后提示编辑部三选一
4. 分配困难上报：`PENDING` 且重试 >3 次的任务通知主编（48h 去重）

cron 接法（示例：每 30 分钟一次）：

```
*/30 * * * * cd <dev绝对路径>/backend && <dev绝对路径>/.venv/bin/python manage.py process_scheduled >> ../process_scheduled.log 2>&1
```

## 测试

```bash
cd backend
python manage.py test apps    # 184 项单元/并发测试（含 AC-T-14 三人并发提交；#018 时点口径）
```

全链路冒烟（需后端已启动、演示账号已就位）：`python scripts/e2e_smoke.py`，
覆盖 建任务→分配→接受→三人提交→自动转 SUBMITTED→Rule-7 汇总→终审→状态日志链 全流程（22 项断言，任一失败退出码非 0）。
加 `--frontend` 可先做经前端构建产物的冒烟（决策 #014 挂账项）：自动 `npx vite build`
产出 dist 后起本地静态服务，断言入口 HTML 及其引用的 JS/CSS 资源可达（5 项断言），再跑上述 API 全链路（合计 27 项）。

前端单元测试：`cd frontend && npm run test`（Vitest + happy-dom，16 项，覆盖 api 层 401 刷新重放/silent404 拦截器/登出并发 401 toast 去重（#018）与 OpinionView 角色分流）。

## 已知限制与待办

- T-02 邮件通知未接线；Celery/Redis 未部署（定时任务走管理命令 + cron）
- 前端暂无用户管理界面（后端 `POST /api/users/` 已可用，仅编辑部权限）
- AI 审稿（`apps/forms/ai_review.py`）为同步调用，LLM 超时 180s 会阻塞请求；需 `REVIEWER_LLM_API_KEY` 环境变量，未配置时接口报错但平台其余功能不受影响
- 前端构建产物 index chunk >1MB（gzip 后 405KB），后续可做 manualChunks 拆分
- 业务 ID 采用「日期前缀 + 当日序号」生成（如 `RO-20261012-0001`），高并发下 `ReviewOpinion` 已用 savepoint+重试兜底，其余模型沿用计数式生成，如遇并发冲突可参照 `ReviewOpinion.save` 的写法
