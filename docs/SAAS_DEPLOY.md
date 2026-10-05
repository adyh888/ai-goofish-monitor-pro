# 闲鱼监控 SaaS 版部署与运营手册

本版本在开源项目 ai-goofish-monitor 基础上完成了「单实例多用户 + 卡密时间会员 + 全量用户化」改造。

## 一、架构与机制速览

- **一套部署、多个用户**：买家自行注册，凭购买的卡密激活/续期会员；
- **卡密 = 时间**：`新到期时间 = max(当前时间, 原到期时间) + 卡密天数`；到期后任务自动暂停（不删除），续费后自动恢复；
- **全量用户化**：任务、结果、价格历史、日志、闲鱼账号 Cookie、AI 模型配置（多模型 + failover）、通知渠道、Prompt、代理/轮换配置，全部按用户隔离；
- **BYOK**：AI 调用走每个用户自己的 Key（加密落库、永不回显），平台不垫 AI 成本；
- **角色**：`admin`（站长，永不过期，可见全部数据用于运维）与 `user`（买家，只见自己的数据）。
- 首次启动会用 `.env` 的 `WEB_USERNAME/WEB_PASSWORD` 创建管理员账号（仅在用户表为空时）。

## 二、必配环境变量（.env）

| 变量 | 说明 | 建议 |
|---|---|---|
| `JWT_SECRET` | 登录令牌签名密钥 | **必配**（`openssl rand -hex 48`）；不配则自动生成存库，但换库会踢掉所有登录 |
| `MASTER_KEY` | 敏感数据加密主密钥（AI Key / 通知 Token / 代理凭据） | **强烈建议**（`openssl rand -hex 32`）；不配则由 JWT 密钥派生 |
| `WEB_USERNAME` / `WEB_PASSWORD` | 首次启动引导创建 admin 账号 | 部署前改掉默认值 |
| `SERVER_PORT` | 服务端口 | 按需（本机开发用 8001） |
| `REGISTRATION_ENABLED` | 开放注册开关 | 也可在「平台设置」页在线调整 |
| `AI_BASE_URL_WHITELIST` | AI Base URL 域名白名单，逗号分隔，支持 `*.example.com`；留空不限（始终禁止内网地址） | 需要收紧时再配 |
| `PLATFORM_PROXY_POOL_ENABLED` | 用户未填代理时是否回落平台共享池 | 想强制用户自带代理就关掉 |
| `PER_USER_TASK_LIMIT` | 每用户任务数上限（默认 10） | 按机器能力 |
| `PER_USER_CONCURRENT_RUNNING` | 每用户同时运行任务数（默认 1） | 保持 1 |
| `GLOBAL_SPIDER_CONCURRENCY` | 全局爬虫并发上限（默认 5） | 按机器 CPU/内存 |
| `ACCOUNT_STATE_DIR` | 登录态根目录（各用户存于 `state/u{用户ID}/`） | 默认 `state` |

## 三、部署步骤（裸机 + uv）

```bash
# 1. 安装依赖
uv venv .venv --python 3.11
uv pip install -r requirements.txt

# 2. 配置 .env（至少 JWT_SECRET / MASTER_KEY / WEB_USERNAME / WEB_PASSWORD）

# 3. 构建（或直接 dev.sh build）
cd web-ui && npm install && npm run build && cd ..

# 4. 启动（后台）
nohup .venv/bin/python -m src.app > logs/server.log 2>&1 &

# 5. 用 .env 里的账号登录，进「平台设置」完成初始化
```

Docker 部署沿用仓库现有 `Dockerfile` / `docker-compose.yaml`，把上表环境变量加进 compose 即可。

## 三点五、日常重启与更新（重要，改完代码必看）

日常管理统一用 `./dev.sh`（`start.sh` 仅用于首次部署）：

| 你改了什么 | 要执行的命令 | 说明 |
|---|---|---|
| 后端代码（`src/**`、`spider_v2.py`） | `./dev.sh restart` | 后端是常驻进程，**不重启不生效** |
| `.env` 配置 | `./dev.sh restart` | 后端启动时读取 |
| 前端代码（`web-ui/**`，生产模式） | `./dev.sh build` | 重新构建 dist 即生效，**后端无需重启** |
| 前端代码（dev 模式 `./dev.sh all`） | 无需操作 | Vite 自动热更新 |
| 前后端一起重启（开发模式） | `./dev.sh all` 终端 Ctrl+C 后重新 `./dev.sh all` | all 模式前后端同终端管理 |

- `./dev.sh restart` 会**兜底清理端口上游离的旧后端进程**（包括手动 `nohup` 启动、没记录 pid 的），避免"改了代码不生效 / 登录 405"这类新旧不一致问题；
- `./dev.sh status` 随时查看前后端运行状态与端口；
- 服务器上常驻运行建议：`./dev.sh build` 启动后，用 `systemd`/`supervisor` 托管，或 `nohup .venv/bin/python -m src.app &`——但手动 nohup 启动的进程，`./dev.sh restart` 也能识别并接管清理。

## 四、HTTPS（必须）

登录令牌与闲鱼 Cookie 都走网络传输，**必须上 HTTPS**。推荐 Caddy（自动签发续期）：

```
your-domain.com {
    reverse_proxy 127.0.0.1:8001
}
```

## 五、备份

```bash
# 手动
.venv/bin/python scripts/backup.py

# 每日 03:30 自动备份（保留 7 份，BACKUP_KEEP 可调）
crontab -e
30 3 * * * cd /path/to/ai-goofish-monitor && .venv/bin/python scripts/backup.py >> logs/backup.log 2>&1
```

恢复：停服 → 用备份覆盖 `data/app.sqlite3`、`state/`、`images/` → 启动。

## 六、卡密运营流程

1. 管理员登录 → 平台管理 → **卡密管理** → 生成（选天数与数量，建议填批次号）；
2. **导出未使用** 得到 TXT（一行一码），导入发卡平台（独角数卡等）自动发货；
3. 买家注册账号 → 登录后跳转激活页 → 输入卡密即激活/续期；
4. 卡密激活即绑定账号，不退不换；未使用的卡可在后台禁用/恢复；
5. 用户管理与平台设置页可手动调到期时间、禁用账号、重置密码。

## 七、会员与数据策略（重要）

- 到期：任务暂停、接口拦截（仅能激活续费与查看）；**数据默认永久保留**，续费后任务原样恢复；
- 出于安全考虑，v1 **不做**到期自动删除数据（防止误删买家 Cookie 与结果），如需清理由管理员在用户管理中手动处理；
- 管理员账号永不过期，且可在管理视角看到全部用户的数据用于排障。

## 八、买家使用指引（可直接发给买家）

1. 注册账号并用卡密激活会员；
2. 「系统设置 → AI 模型」填自己的 AI Key（支持 DeepSeek/通义/Kimi/硅基流动等 OpenAI 兼容接口，可配多个自动 failover）；
3. 「账号管理」上传闲鱼登录态：用官方 Chrome 扩展在 goofish.com 抓取后复制，再到页面粘贴上传；
4. 「系统设置 → 通知推送」配自己的 Bark/ntfy/企微/TG/Webhook；
5. 「系统设置 → IP 轮换」可选填自己的代理列表（未填时若平台开启共享池则用平台的）；
6. 创建任务（AI 判断或关键词判断），启动后命中会推送到你的通知渠道。

## 九、安全机制清单

- 密码 bcrypt 哈希；JWT 24h；登录/注册/激活按 IP+账号限流（429）；
- 卡密错误提示统一「卡密无效或已被使用」，不泄露存在性；卡密码空间 ≥ 30^12；
- AI Key / 通知配置 / 代理列表 Fernet 加密落库（`MASTER_KEY`），接口永不回显明文；
- AI Base URL：始终拒绝内网/本机地址（SSRF），可选域名白名单；
- WebSocket 握手验 JWT，任务事件只推给归属人（与管理员）；
- API 全量鉴权：未登录 401、过期 403 `MEMBERSHIP_EXPIRED`、越权一律 404。

## 十、已知事项

- 上游测试有 2 个历史失败（`test_frontend_build_paths`、`test_save_to_jsonl`），与本次改造无关；
- `PER_USER_TASK_LIMIT` 等平台设置保存后即时生效，无需重启；
- 改前端后需 `npm run build`（FastAPI 直接伺服 `dist/`），改后端需重启进程。
