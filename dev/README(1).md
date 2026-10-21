# 审稿协作平台 - 开发目录

## 技术栈
- 后端：Django 5 + Django REST Framework + PostgreSQL 15 + Redis + Celery
- 前端：Vue 3 + Element Plus + Pinia + Vue Router 4
- 检索：Elasticsearch 8 + IK分词
- 文件存储：本地文件系统

## 目录结构
```
dev/
├── backend/               # Django后端
│   ├── config/            # Django项目配置
│   ├── apps/              # 业务应用
│   │   ├── users/         # 用户模块 (T-01)
│   │   ├── notifications/ # 通知模块 (T-02)
│   │   ├── files/         # 文件模块 (T-03)
│   │   ├── tasks/         # 审稿任务管理 (T-10~T-20)
│   │   ├── forms/         # 结构化审稿表单 (T-30~T-34)
│   │   ├── summaries/     # 审稿意见汇总 (T-40~T-45)
│   │   └── knowledge/     # 审稿知识库 (T-50~T-56)
│   ├── manage.py
│   ├── requirements.txt
│   └── .env.example
├── frontend/              # Vue3前端
│   ├── src/
│   │   ├── views/         # 页面视图
│   │   ├── components/    # 通用组件
│   │   ├── stores/        # Pinia状态管理
│   │   ├── router/        # 路由配置
│   │   ├── api/           # API调用封装
│   │   └── utils/         # 工具函数
│   ├── package.json
│   └── vite.config.js
├── .venv/                 # Python虚拟环境
└── README.md              # 本文件
```

## 开发任务对照
任务编号对照技术实施方案：T-00~T-56，共34个任务，预估77人天。
