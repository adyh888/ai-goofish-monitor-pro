# 云服务器部署指南(拖拽部署 · 傻瓜式)

你的使用方式:**打包 → 拖文件上服务器 → 服务器执行一条命令**。部署和更新用的是**同一套动作**。

## 日常就记两个命令

| 位置 | 命令 | 干什么 |
|---|---|---|
| 本机(Mac) | `bash deploy/pack.sh` | 打包项目到桌面,生成 `xianyu-deploy.tar.gz` + 命令小抄 |
| 云服务器 | `bash /opt/ai-goofish-monitor/deploy/update.sh /root/xianyu-deploy.tar.gz` | 解包 → 构建 → 启动 → 健康检查 |

---

## 首次部署(3 步)

```bash
# ① 本机(项目目录 ai-goofish-monitor/ 下)打包
bash deploy/pack.sh
```
桌面会生成两样东西:`xianyu-deploy.tar.gz`(3M 左右,已排除 .venv/node_modules/日志等)和 `服务器部署命令.txt`。

```bash
# ② 把桌面的 xianyu-deploy.tar.gz 拖到服务器 /root 目录(用你的 SFTP 工具拖拽)
```

### ③ 部署(两种方式任选)

**方式一 · 万能命令**(推荐, 复制粘贴一次搞定, 包和解压状态都不用管):

```bash
sudo bash -c 'D=/opt/ai-goofish-monitor; T=$(ls $D/xianyu-deploy.tar.gz /root/xianyu-deploy.tar.gz /tmp/xianyu-deploy.tar.gz 2>/dev/null | head -1); [ -n "$T" ] || { echo "未找到 xianyu-deploy.tar.gz, 请先把包拖到服务器"; exit 1; }; mkdir -p $D; tar xzf "$T" -C $D && bash $D/deploy/update.sh "$T"'
```

**方式二 · 手动解压**(更直观): 在 1Panel 文件管理里进入 `/opt/ai-goofish-monitor`, 把包**解压到当前目录**, 然后终端执行:

```bash
cd /opt/ai-goofish-monitor/deploy && bash update.sh
```

> 用 `bash update.sh` 而不是 `./update.sh`, 避免解压工具丢失可执行权限; 脚本会自动 sudo。
> 注意解压位置: 包内文件在根层级, 要解压**进** `/opt/ai-goofish-monitor`, 不要解压到家目录。

脚本自动完成:检查 Docker → 生成 `.env` → 构建 Docker 镜像(首次 5-15 分钟)→ 启动 → 健康检查 → 打印访问地址。

> Docker 已装好会自动跳过;没装会自动调用 install-docker.sh 安装(国内自动换源)。

部署完**必做两件事**(只有你能做):

1. `vim /opt/ai-goofish-monitor/.env`:填 `OPENAI_API_KEY`、改 `WEB_PASSWORD`(默认 admin123),然后 `docker compose up -d`
2. 云控制台【安全组】放行 **TCP 8000**,否则外网打不开

## 以后更新代码(拖包 + 两个字)

```bash
# ① 本机重新打包
bash deploy/pack.sh

# ② 把新的 xianyu-deploy.tar.gz 拖到服务器(/opt/ai-goofish-monitor、/root、/tmp 均可)

# ③ 服务器上直接输(首次部署成功后 update.sh 自动装好了这个命令)
xupdate
```

只重建变化的部分, 通常几分钟。`xupdate` 会自动在常见位置找包; 也可以显式指定: `xupdate /root/xianyu-deploy.tar.gz`。
若提示找不到 `xupdate` 命令(说明还没用过新版 update.sh), 用上面③的万能命令跑一次即可。

## 数据安全(更新不会丢用户数据)

用户数据全部存在服务器项目目录下, 更新代码动不到它们——三重保护:

1. **代码包里没有数据**: `pack.sh` 打包时排除了 `data/`(数据库)、`state/`(扫码登录态)、`.env`、`config.json`、`prompts/`、`backups/` 等, 包里只有代码
2. **更新前自动备份**: `update.sh` 每次更新前会自动把 `.env`、`config.json`、`data/`、`state/`、`prompts/`、`price_history/` 打包快照到服务器 `backups/` 目录, 自动保留最近 7 份
3. **Docker 架构隔离**: 代码在镜像里, 数据在宿主机目录挂载进容器; 重建容器/换镜像不碰宿主机数据

万一需要回滚:

```bash
# 查看有哪些备份
ls -lht /opt/ai-goofish-monitor/backups/

# 恢复某份备份(会覆盖当前数据, 恢复后 bash deploy/restart.sh)
tar xzf /opt/ai-goofish-monitor/backups/pre-update-YYYYMMDD-HHMMSS.tar.gz -C /opt/ai-goofish-monitor
```

手动备份(做危险操作前建议先跑一次):

```bash
sudo tar czf /root/manual-backup-$(date +%m%d-%H%M).tar.gz -C /opt/ai-goofish-monitor data state .env config.json prompts price_history
```

> ⚠️ 唯一会丢数据的操作是手动删除项目目录(如 `rm -rf /opt/ai-goofish-monitor`)。更新代码永远不需要删目录。

特殊情况: 你在**网页端**改过任务/AI 标准, 现在想**以本地改的为准**推上去:

```bash
xupdate --force-config
```

> 如果你是手动拖**文件夹/零散文件**覆盖(而不是拖 tar.gz 包),就跳过解包直接:
> `bash /opt/ai-goofish-monitor/deploy/update.sh`(不带参数 = 仅重建+启动)。
> 不推荐:手动拖整文件夹容易把本地 `.env`、`config.json` 一起覆盖上去,也容易漏传隐藏文件。

---

## deploy/ 目录脚本一览

| 脚本 | 运行位置 | 作用 |
|---|---|---|
| `pack.sh` | 本机 | 打包项目为单个部署包到桌面(自动排除无用文件) |
| `update.sh` | 云服务器 | 一键更新:解包(带数据保护)→ 构建 → 启动 |
| `logs.sh` | 云服务器 | 看日志:`bash deploy/logs.sh`(实时),`--tail 200` 看最近 200 行 |
| `restart.sh` | 云服务器 | 改 `.env`(端口/密码/Key)后重建容器生效,并打印新访问地址 |
| `deploy.sh` | 云服务器 | 被 update.sh 调用;也可单独用(官方镜像模式 `bash deploy.sh`) |
| `install-docker.sh` | 云服务器 | 安装 Docker + Compose(update.sh 会自动调,一般不用手动跑) |
| `push.sh` | 本机 | 备选方案:本机一条命令自动 rsync 推送+部署(不想手动拖文件时用) |

## 常用运维命令(服务器 /opt/ai-goofish-monitor 下)

```bash
docker compose logs -f app     # 跟踪日志
docker compose restart         # 重启
docker compose down            # 停止(数据在挂载目录, 不丢失)
docker compose up -d           # 启动
vim .env && docker compose up -d   # 改配置后生效
```

## 常见问题

- **外网访问不了**: 九成是云安全组没放行 TCP 8000; 其次检查 `ufw status` / `firewall-cmd --list-ports`。
- **首次构建卡住/拉不动基础镜像**: 确认跑过 `install-docker.sh`(配了加速器); 公共加速器失效时可编辑该脚本顶部 `MIRRORS` 数组换新。
- **内存小(1G/2G)构建失败**: 先加 2G swap:
  `fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile`
- **update.sh 报找不到代码包**: 检查拖到的路径, 命令里的 `/root/xianyu-deploy.tar.gz` 要和实际位置一致。
- **本地删过文件**: tar 包只覆盖不删除, 个别删除的文件会残留在服务器; 一般无影响, 若行为异常可 `rm -rf /opt/ai-goofish-monitor/src /opt/ai-goofish-monitor/web-ui` 后重新执行 update.sh。
- **换端口**: `vim .env` 改 `SERVER_PORT` → `bash deploy/restart.sh`(几秒生效)→ 防火墙/安全组放行新端口。端口映射已参数化为 `${SERVER_PORT:-8000}`, 更新代码也不会丢。
