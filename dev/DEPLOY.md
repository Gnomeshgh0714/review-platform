# 审稿协作平台 - 生产部署 runbook（单机同源反代形态）

## 目标形态

一句话：单机同源反代——Caddy 伺服前端构建产物（dist）与后端静态资源（staticfiles/media），`/api/` 与 `/admin/` 反代本机 gunicorn，TLS 证书由 Caddy 自动向 Let's Encrypt 申请与续期。前端与 API 同域名，浏览器侧不发生跨域。

选 Caddy 而非 Nginx + certbot 的原因：证书申请与续期内置，配置文件短一截，少一步 certbot 安装与定时续期维护；对单机演示部署更省事。已熟悉 Nginx 的团队把反代规则翻译过去即可（要点：`/api/` 与 `/admin/` 原样转发 gunicorn、`/static/` 与 `/media/` 指向文件目录、其余路径 try_files 回落 index.html）。

下文以 `/srv/review-platform` 为示例部署根，按实际路径替换。

## 前置条件

- PostgreSQL 15 已安装，可用的库与账号（连接参数按下方 .env 配置）
- Python 3.12+（本地验证环境为 3.14，Django 5.2 可运行）
- Node 18+（仅构建前端用，构建完成后不再需要）
- 一台有公网 IP 的服务器，域名 A 记录已指向该 IP（Let's Encrypt 签发证书的前提）
- 防火墙放行 80 与 443 端口（HTTP-01 验证与日常访问都走 80）

## 步骤

### 1. 拉代码与装依赖

```bash
git clone <仓库地址> /srv/review-platform
cd /srv/review-platform/dev
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

### 2. 填 backend/.env

```bash
cp backend/.env.example backend/.env
```

按下表填写（每键的完整说明见 `.env.example` 注释）：

| 键 | 必填 | 说明 |
|----|------|------|
| DJANGO_SECRET_KEY | 必填 | 换成随机长串：`python -c "import secrets; print(secrets.token_urlsafe(60))"` |
| DJANGO_DEBUG | 保持不设 | 缺省即 False（settings 兜底为安全默认，勿写 True） |
| DJANGO_DB_NAME / USER / PASSWORD / HOST / PORT | 必填 | 生产库连接，勿沿用演示默认口令 |
| DJANGO_ALLOWED_HOSTS | 必填 | 公网域名，如 `review.example.com`（已无 '*' 通配） |
| DJANGO_CSRF_TRUSTED_ORIGINS | 必填 | 含 scheme，如 `https://review.example.com`；不配则浏览器登录 admin 提交即 403 |
| DJANGO_SECURE_PROXY_SSL_HEADER | 必填 | `HTTP_X_FORWARDED_PROTO,https`（反代 TLS 终止，后端才能感知 https） |
| DJANGO_TRUST_X_FORWARDED_FOR | 必填 | `True`（部署在可信反代之后，知识库访问审计取真实 IP） |
| REVIEWER_LLM_API_KEY | 按需 | 不配则 AI 审稿报错，平台其余功能不受影响 |
| REVIEWER_LLM_MODEL | 可选 | AI 审稿模型名，默认 glm-latest，见 .env.example |
| EMAIL_BACKEND / EMAIL_HOST / EMAIL_PORT / EMAIL_HOST_USER / EMAIL_HOST_PASSWORD / EMAIL_USE_TLS / DEFAULT_FROM_EMAIL | 生产必填组 | T-02 通知邮件走 SMTP；不配则邮件只打印到后端日志（console 后端），站内信不受影响 |
| REDIS_URL | 可选 | 多 worker 部署必设（限流计数共享）；单 worker 演示可不设 |
| THROTTLE_LOGIN_MINUTE / THROTTLE_LOGIN_DAILY | 可选 | 默认 10/min、50/day |
| CORS_ALLOWED_ORIGINS | 可选 | 同源反代形态前后端同域名，不跨域，可不配；有独立域名的前端客户端时才需要 |
| BOOTSTRAP_PASSWORD | 可选 | bootstrap_dev 创建演示账号的密码，默认 Demo@2026；仅初始化演示数据时用（第 5 步），自建初始数据可不配 |

### 3. migrate（token_blacklist 两表必须建）

```bash
cd backend
python manage.py migrate
```

注意：`rest_framework_simplejwt.token_blacklist` 会建 OutstandingToken 与 BlacklistedToken 两表。漏建这两表的后果是刷新 token、修改密码、重置密码全部 500（#016 安全项3 的轮换拉黑依赖该表），而且报错发生在运行时，migrate 时不会提醒——部署后务必执行上线检查清单第 3 项确认。

### 4. collectstatic

```bash
python manage.py collectstatic
```

产物在 `backend/staticfiles/`，由反代直接伺服（Django 在 DEBUG=False 下不伺服静态文件，不配反代这一段 admin 会丢样式）。

### 5. 初始数据

```bash
python manage.py bootstrap_dev    # 幂等：演示账号 + 默认模板 + 种子数据
python manage.py createsuperuser  # admin 后台登录用（bootstrap 账号非超管）
```

演示账号密码可用 `BOOTSTRAP_PASSWORD` 覆盖，默认 `Demo@2026`。

### 6. 前端构建

```bash
cd ../frontend
npm install
npm run build    # 产物 dist/
```

### 7. 启动 gunicorn

```bash
cd ../backend
../.venv/bin/gunicorn review_platform.wsgi:application \
    --bind 127.0.0.1:8000 \
    --workers 1
```

- 演示环境用 `--workers 1` 可不配 REDIS_URL（限流计数 locmem 进程内有效）。
- `--workers 2` 及以上必须配 REDIS_URL，否则各进程独立计数会稀释登录限流的效果。
- 建议交给 systemd 等进程托管（`Restart=always`），不要裸 nohup 跑。

### 8. 反代配置（Caddy）

安装 Caddy 后，`/etc/caddy/Caddyfile` 写入以下内容（域名与路径按实际替换）：

```
review.example.com {
    encode gzip

    # Django collectstatic 产物（admin 样式等）
    handle /static/* {
        root * /srv/review-platform/dev/backend/staticfiles
        file_server
    }

    # 上传文件（稿件 PDF 等）
    handle /media/* {
        root * /srv/review-platform/dev/backend/media
        file_server
    }

    # API 与 admin 反代 gunicorn（路径原样转发，Django 侧路由即带 /api/ 前缀）
    handle /api/* {
        reverse_proxy 127.0.0.1:8000
    }
    handle /admin/* {
        reverse_proxy 127.0.0.1:8000
    }

    # 其余路径给前端 SPA：文件存在直接返回，否则回落 index.html
    # （前端为 history 路由，深层路由刷新不能 404）
    try_files {path} /index.html
    root * /srv/review-platform/dev/frontend/dist
    file_server
}
```

```bash
sudo systemctl reload caddy   # 首次启动即自动向 Let's Encrypt 申请证书
```

### 9. cron 定时任务

T-19 定时逻辑与 token 黑名单清理各一条：

```
*/30 * * * * cd /srv/review-platform/dev/backend && /srv/review-platform/dev/.venv/bin/python manage.py process_scheduled >> ../process_scheduled.log 2>&1
0 4 * * * cd /srv/review-platform/dev/backend && /srv/review-platform/dev/.venv/bin/python manage.py flushexpiredtokens >> ../flushexpiredtokens.log 2>&1
```

`process_scheduled` 幂等可重跑（邀请过期 / 截止提醒 / 超时标记 / 分配困难上报四类逻辑，见 README「定时任务」节）；`flushexpiredtokens` 清理 token_blacklist 过期记录，防表膨胀。

## 上线检查清单

逐项过一遍，全部通过再对外提供服务：

1. **证书与域名**：`curl -I https://review.example.com` 返回 200/301 且证书为 Let's Encrypt 签发（Caddy 日志可见签发记录；签发失败先查 80 端口可达与 DNS 解析）。
2. **OPTIONS 预检**：`curl -i -X OPTIONS -H "Origin: https://review.example.com" -H "Access-Control-Request-Method: POST" https://review.example.com/api/users/login/`，响应应带 `access-control-allow-origin: https://review.example.com`（同源形态下浏览器日常不发预检，此项用于确认 CORS 配置对潜在跨域客户端的行为）。
3. **刷新 token（token_blacklist 两表落地验证）**：用演示账号登录拿 refresh，`curl -X POST https://review.example.com/api/users/token/refresh/ -H "Content-Type: application/json" -d '{"refresh":"<上一步的refresh>"}'` 返回 200 且带新 token；500 则说明第 3 步 migrate 没跑全。
4. **限流生效**：连续 11 次错误密码登录，前 10 次返回 401，第 11 次返回 429（限流先于凭据校验，密码正确也会被拦，见 #016 验证记录）。
5. **admin 可登录**：浏览器打开 `https://review.example.com/admin/`，用超管账号登录并做一次保存操作——能保存说明 CSRF_TRUSTED_ORIGINS 配置正确；提交即 403 则检查该键的 scheme 是否为 https。
6. **邮件实测发送一封**：
   ```bash
   cd backend
   ../.venv/bin/python manage.py shell -c "
   from django.core.mail import send_mail
   send_mail('上线检查', '部署验证邮件，收到即通过。', 'webmaster@localhost', ['<你的邮箱>'])
   "
   ```
   到信说明 SMTP 组配置正确；未配 SMTP 时此邮件只会打印到 gunicorn 日志（console 后端），站内信功能不受影响。
7. **深层路由刷新**：浏览器进入平台任意内页（如任务列表）后按 F5，页面正常渲染不 404（try_files 回落生效）。
8. **admin 样式**：admin 页面样式与图片正常加载（`/static/` 由反代伺服，打开浏览器开发者工具 Network 面板确认无 404）。

## 已知边界（部署前知悉）

- 登录限流按 IP 计数，多 worker 部署必须配 REDIS_URL（见第 7 步）。
- AI 审稿为同步调用，LLM 超时 120s 会占住一个 gunicorn worker，小 worker 数下避免多人同时触发（README「已知限制」节同源口径）。
- 单机形态无负载均衡与多实例故障转移，适合演示与小团队使用；用户量上来后再评估拆分。
