#!/usr/bin/env bash
################################################################################
# 闲鱼监控系统 - 服务器端一键部署/更新 (在云服务器上运行)
#
# 用法:
#   bash deploy/update.sh /root/xianyu-deploy.tar.gz  # 推荐: 解包+构建+启动一条龙
#   bash deploy/update.sh                             # 已手动解压过代码时, 直接构建+启动
#   xupdate                                           # 首次部署成功后自动可用的最短命令
#
# 说明: 需要 root 权限, 以普通用户运行时会自动 sudo;
#       不带包路径时, 默认你已把代码手动解压到项目目录。
#
# 数据保护: 服务器的 .env(密码/Key)、扫码登录状态、数据库、日志等永不覆盖;
#           已有部署时, config.json(任务) 与 prompts/(AI标准) 默认也不覆盖,
#           除非加 --force-config。
################################################################################
set -euo pipefail

C_GREEN='\033[0;32m'; C_YELLOW='\033[1;33m'; C_RED='\033[0;31m'; C_RESET='\033[0m'
log()  { echo -e "${C_GREEN}[INFO ]${C_RESET} $*"; }
warn() { echo -e "${C_YELLOW}[WARN ]${C_RESET} $*"; }
err()  { echo -e "${C_RED}[ERROR]${C_RESET} $*" >&2; }

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
APP_DIR=$(cd "$SCRIPT_DIR/.." && pwd)

TGZ=""
FORCE_CONFIG=0
for arg in "$@"; do
  case "$arg" in
    --force-config) FORCE_CONFIG=1 ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,2\}//'; exit 0 ;;
    *) TGZ="$arg" ;;
  esac
done

# 非 root 时自动用 sudo 重跑自己
if [[ $EUID -ne 0 ]]; then
  log "需要 root 权限, 自动尝试 sudo (可能要求输入一次密码)..."
  exec sudo bash "$SCRIPT_DIR/update.sh" "$@"
fi

# ---------- 解包(如提供了代码包) ----------
if [[ -n $TGZ ]]; then
  [[ -f $TGZ ]] || { err "找不到代码包: $TGZ"; exit 1; }

  # ---------- 更新前自动备份用户数据(保留最近 7 份) ----------
  BK_DIR="$APP_DIR/backups"
  BK_ITEMS=()
  if [[ -f $APP_DIR/.env ]]; then BK_ITEMS+=(.env); fi
  if [[ -f $APP_DIR/config.json ]]; then BK_ITEMS+=(config.json); fi
  for d in data state prompts price_history; do
    if [[ -d $APP_DIR/$d ]]; then BK_ITEMS+=("$d"); fi
  done
  if [[ ${#BK_ITEMS[@]} -gt 0 ]]; then
    mkdir -p "$BK_DIR"
    BK_FILE="$BK_DIR/pre-update-$(date +%Y%m%d-%H%M%S).tar.gz"
    tar -czf "$BK_FILE" -C "$APP_DIR" ${BK_ITEMS[@]+"${BK_ITEMS[@]}"}
    log "已自动备份用户数据 → $BK_FILE ($(du -h "$BK_FILE" | cut -f1))"
    ls -1t "$BK_DIR"/pre-update-*.tar.gz 2>/dev/null | tail -n +8 | xargs -r rm -f
    log "回滚方法: 解压对应备份到 $APP_DIR 即可 (tar xzf <备份文件> -C $APP_DIR)"
  fi

  if [[ -f $APP_DIR/docker-compose.yaml ]]; then
    log "检测到已有部署, 保护服务器数据不被覆盖 (.env / config.json / prompts / 运行数据)..."
    EXCLUDES=(--exclude=deploy/update.sh --exclude=.env)
    if [[ $FORCE_CONFIG -eq 1 ]]; then
      log "已启用 --force-config: 将用代码包里的 config.json 和 prompts/ 覆盖服务器"
    else
      EXCLUDES+=(--exclude=config.json --exclude=prompts)
    fi
    tar -xzf "$TGZ" -C "$APP_DIR" "${EXCLUDES[@]}"
  else
    log "全新部署, 解压代码包到 $APP_DIR ..."
    tar -xzf "$TGZ" -C "$APP_DIR" --exclude=deploy/update.sh
  fi
  log "代码已更新 ✔"
else
  if [[ -f $APP_DIR/docker-compose.yaml ]]; then
    log "未提供代码包: 视为你已手动更新代码, 直接构建部署"
  else
    log "未提供代码包: 视为手动解压的全新部署, 直接构建部署"
  fi
fi

# ---------- 交给 deploy.sh --build: 检查 Docker → .env → 构建 → 启动 → 健康检查 ----------
[[ -f $APP_DIR/deploy/deploy.sh ]] || { err "未找到 $APP_DIR/deploy/deploy.sh"; exit 1; }

# ---------- 安装/刷新全局短命令 xupdate (幂等) ----------
# 装好后, 以后更新只需: 把新包拖到服务器, 然后输 xupdate 回车
cat > /usr/local/bin/xupdate <<'XUPD'
#!/usr/bin/env bash
# 闲鱼监控系统一键更新入口 (由 deploy/update.sh 自动维护)
# 用法: xupdate [代码包路径] [额外参数如 --force-config]; 不带路径时自动在常见位置找包
APP_DIR="__APP_DIR__"
if [ $# -gt 0 ]; then
  exec bash "$APP_DIR/deploy/update.sh" "$@"
fi
TGZ=$(ls "$APP_DIR/xianyu-deploy.tar.gz" /root/xianyu-deploy.tar.gz /tmp/xianyu-deploy.tar.gz 2>/dev/null | head -1)
if [ -z "$TGZ" ]; then
  echo "未找到 xianyu-deploy.tar.gz, 请先把新包拖到服务器(/opt/ai-goofish-monitor/、/root 或 /tmp 任一位置)" >&2
  exit 1
fi
exec bash "$APP_DIR/deploy/update.sh" "$TGZ"
XUPD
sed -i "s|__APP_DIR__|$APP_DIR|" /usr/local/bin/xupdate
chmod +x /usr/local/bin/xupdate
log "已安装/刷新全局更新命令: xupdate (以后拖入新包后直接输 xupdate 即可)"

cd "$APP_DIR"
exec bash deploy/deploy.sh --build
