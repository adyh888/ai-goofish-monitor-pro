#!/usr/bin/env bash
################################################################################
# 打包项目为单个部署包 (在自己电脑上运行)
#
# 用法:  bash deploy/pack.sh
#
# 产物(在桌面):
#   1. xianyu-deploy.tar.gz   干净的代码包(已排除 .venv/node_modules/日志/数据等)
#   2. 服务器部署命令.txt      复制粘贴到服务器执行即可
#
# 流程: 本机跑本脚本 → 把桌面的 tar.gz 拖到服务器(如 /root) → 服务器粘贴执行命令
################################################################################
set -euo pipefail

C_GREEN='\033[0;32m'; C_YELLOW='\033[1;33m'; C_RED='\033[0;31m'; C_RESET='\033[0m'
log()  { echo -e "${C_GREEN}[INFO ]${C_RESET} $*"; }
warn() { echo -e "${C_YELLOW}[WARN ]${C_RESET} $*"; }
err()  { echo -e "${C_RED}[ERROR]${C_RESET} $*" >&2; }

# ---------- 定位项目根目录(向上查找 docker-compose.yaml) ----------
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=""
d=$SCRIPT_DIR
while [[ $d != "/" ]]; do
  [[ -f "$d/docker-compose.yaml" ]] && { PROJECT_ROOT=$d; break; }
  d=$(dirname "$d")
done
[[ -n $PROJECT_ROOT ]] || { err "请在项目目录内运行本脚本"; exit 1; }

OUT="$HOME/Desktop/xianyu-deploy.tar.gz"
CMD_TXT="$HOME/Desktop/服务器部署命令.txt"

cd "$PROJECT_ROOT"

# ---------- 生成打包清单: 只要代码与配置, 排除本地运行产物 ----------
# 注意: data/logs 等运行数据目录只在项目根目录精确排除(-path),
#       否则会误伤 web-ui/src/data 这类同名源码目录!
LIST=$(mktemp)
trap 'rm -f "$LIST"' EXIT
find . \
  \( -name .git -o -name .venv -o -name node_modules -o -name __pycache__ \
       -o -name .idea -o -name .serena \) -prune -o \
  \( -path ./data -o -path ./logs -o -path ./images -o -path ./jsonl \
       -o -path ./state -o -path ./price_history -o -path ./dist \
       -o -path ./backups -o -path ./chrome-extension -o -path ./web-ui/dist \) -prune -o \
  \( -type f ! -name '.DS_Store' ! -name '*.pyc' ! -name '.env' ! -name '.aider*' \
       ! -name '.backend.pid' ! -name 'xianyu_state.json' \
       ! -path './deploy/server.conf' -print \) > "$LIST"

# ---------- 完整性自检: 关键文件必须在内 ----------
for f in ./docker-compose.yaml ./Dockerfile ./deploy/deploy.sh ./config.json ./src ./web-ui/src/data; do
  if ! grep -qF "$f" "$LIST"; then
    err "打包清单缺少关键内容: $f, 打包中止"; exit 1
  fi
done

log "打包中(排除本地虚拟环境/依赖/日志/数据)..."
# --no-xattrs: 去掉 macOS 扩展属性, 避免 Linux 解包时刷屏警告
tar --no-xattrs -czf "$OUT" -T "$LIST"

SIZE=$(du -h "$OUT" | cut -f1 | tr -d ' ')

# ---------- 生成服务器命令小抄 ----------
cat > "$CMD_TXT" <<EOF
==============================================
 闲鱼监控系统 · 服务器部署/更新命令
 (把桌面上的 xianyu-deploy.tar.gz 拖到服务器后, ssh 到服务器粘贴执行)
 包放在 /opt/ai-goofish-monitor、/root 或 /tmp 任意位置均可, 命令自动查找
==============================================

【万能命令 · 首次部署/解压与否都能用】复制整行执行:
sudo bash -c 'D=/opt/ai-goofish-monitor; T=\$(ls \$D/xianyu-deploy.tar.gz /root/xianyu-deploy.tar.gz /tmp/xianyu-deploy.tar.gz 2>/dev/null | head -1); [ -n "\$T" ] || { echo "未找到 xianyu-deploy.tar.gz, 请先把包拖到服务器"; exit 1; }; mkdir -p \$D; tar xzf "\$T" -C \$D && bash \$D/deploy/update.sh "\$T"'

【方式二 · 手动解压版】1Panel 文件管理进入 /opt/ai-goofish-monitor, 把包解压到当前目录, 然后终端执行:
cd /opt/ai-goofish-monitor/deploy && bash update.sh
(用 bash 运行最稳, 不依赖文件的可执行权限; 脚本会自动 sudo)

【以后更新 · 最简方式】拖入新包后, 服务器上直接输(首次部署成功后自动可用):
xupdate

【可选】连任务配置/AI标准也用本地版本覆盖:
xupdate --force-config

----------------------------------------------
提示:
· xupdate 是首次部署成功后自动安装的短命令; 若提示找不到命令, 用上面万能命令跑一次即可
· 服务器的 .env(密码/Key)、扫码登录状态、数据库不会被代码包覆盖
· 部署完成后记得: vim /opt/ai-goofish-monitor/.env 填 OPENAI_API_KEY、改 WEB_PASSWORD, 然后 bash deploy/restart.sh
· 外网访问: 云控制台【安全组】放行 TCP 8000(或你在 .env 改过的端口)
EOF

echo ""
log "✅ 打包完成!"
log "   部署包:  $OUT  ($SIZE)"
log "   命令小抄: $CMD_TXT"
echo ""
echo -e "${C_GREEN}下一步:${C_RESET}"
echo "  1. 把桌面的 xianyu-deploy.tar.gz 拖到服务器 /root 目录"
echo "  2. ssh 到服务器, 打开桌面的『服务器部署命令.txt』, 复制对应命令粘贴执行"
echo "  3. 以后更新代码: 重跑本脚本 → 再拖一次 → 服务器执行『以后更新』那条命令"
