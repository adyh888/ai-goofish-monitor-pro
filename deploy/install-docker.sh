#!/usr/bin/env bash
################################################################################
# Docker + Docker Compose 云服务器一键安装脚本
#
# 适用系统: Ubuntu / Debian / CentOS / RHEL / Rocky / AlmaLinux / Fedora
#           Alibaba Cloud Linux / TencentOS / OpenCloudOS
#
# 特性:
#   1. 自动识别系统发行版与 CPU 架构, 选择 apt / dnf / yum 安装
#   2. 自动判断网络环境: 国内自动切换阿里云镜像源, 并配置 Docker Hub 加速器
#   3. 自动配置容器日志轮转, 避免日志撑爆磁盘
#   4. 幂等设计, 重复执行安全
#
# 用法:
#   sudo bash install-docker.sh              # 自动判断国内外网络
#   sudo bash install-docker.sh --cn         # 强制走国内阿里云源
#   sudo bash install-docker.sh --global     # 强制走 Docker 官方源
################################################################################
set -euo pipefail

C_GREEN='\033[0;32m'; C_YELLOW='\033[1;33m'; C_RED='\033[0;31m'; C_RESET='\033[0m'
log()  { echo -e "${C_GREEN}[INFO ]${C_RESET} $*"; }
warn() { echo -e "${C_YELLOW}[WARN ]${C_RESET} $*"; }
err()  { echo -e "${C_RED}[ERROR]${C_RESET} $*" >&2; }

# Docker Hub 加速器(国内环境使用, 可按需增删; 这些公共加速器时效性强, 失效请自行替换)
MIRRORS=(
  "https://docker.1ms.run"
  "https://docker.1panel.live"
  "https://docker.m.daocloud.io"
  "https://dockerproxy.net"
  "https://hub.rat.dev"
)

FORCE_CN=0; FORCE_GLOBAL=0
for arg in "$@"; do
  case "$arg" in
    --cn) FORCE_CN=1 ;;
    --global) FORCE_GLOBAL=1 ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,2\}//'; exit 0 ;;
    *) err "未知参数: $arg"; exit 1 ;;
  esac
done

[[ $EUID -eq 0 ]] || { err "请使用 root 权限运行: sudo bash $0"; exit 1; }

# ---------- 系统识别 ----------
if [[ -r /etc/os-release ]]; then
  . /etc/os-release
else
  err "无法识别系统: 缺少 /etc/os-release"; exit 1
fi
ID_LOWER=$(echo "${ID:-}" | tr '[:upper:]' '[:lower:]')
OS_MAJOR=$(echo "${VERSION_ID:-0}" | cut -d. -f1)
ARCH=$(uname -m)
log "系统: ${PRETTY_NAME:-$ID $VERSION_ID}   架构: $ARCH"

PKG_MGR=""
if command -v apt-get >/dev/null 2>&1; then PKG_MGR=apt-get
elif command -v dnf >/dev/null 2>&1; then PKG_MGR=dnf
elif command -v yum >/dev/null 2>&1; then PKG_MGR=yum
else
  err "不支持的系统: 未找到 apt-get / dnf / yum"; exit 1
fi

# ---------- 网络环境识别 ----------
detect_cn() {
  # 官方源 5 秒内可达 → 视为海外; 否则视为国内
  curl -m 5 -sfI https://download.docker.com/linux/ >/dev/null 2>&1 && return 1
  return 0
}
if   [[ $FORCE_CN -eq 1 ]];     then IS_CN=1
elif [[ $FORCE_GLOBAL -eq 1 ]]; then IS_CN=0
elif detect_cn;                 then IS_CN=1
else                                 IS_CN=0
fi
[[ $IS_CN -eq 1 ]] && log "网络环境: 国内 → 使用阿里云镜像源 + Docker Hub 加速器" \
                  || log "网络环境: 海外 → 使用 Docker 官方源"

# ---------- 已安装检测 ----------
DOCKER_EXISTS=0
if command -v docker >/dev/null 2>&1; then
  DOCKER_EXISTS=1
  log "检测到已安装: $(docker --version 2>/dev/null || echo docker)"
fi

# ---------- Debian / Ubuntu ----------
install_debian() {
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y ca-certificates curl gnupg

  if [[ $IS_CN -eq 1 ]]; then
    local base="https://mirrors.aliyun.com/docker-ce/linux/${ID_LOWER}"
    local codename="${VERSION_CODENAME:-}"
    [[ -z $codename ]] && codename=$(lsb_release -cs 2>/dev/null || true)
    [[ -z $codename ]] && { err "无法确定发行版代号, 请改用: sudo bash $0 --global"; exit 1; }
    install -d -m 0755 /etc/apt/keyrings
    curl -fsSL "$base/gpg" | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] $base $codename stable" \
      > /etc/apt/sources.list.d/docker.list
    apt-get update -y
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  else
    curl -fsSL https://get.docker.com | sh
  fi
}

# ---------- CentOS / RHEL 系 ----------
install_rhel() {
  # EL 兼容发行版的版本映射: 有些系统主版本号与 EL 不同
  local ver="$OS_MAJOR"
  case "$ID_LOWER" in
    alinux|tencentos)  case "$ver" in 2) ver=7 ;; 3) ver=8 ;; 4) ver=9 ;; esac ;;
    opencloudos|ol|rhel|rocky|almalinux|centos|fedora) : ;;  # 主版本号与 EL 一致
  esac
  local repo_dir="centos"
  [[ "$ID_LOWER" == "fedora" && $IS_CN -eq 0 ]] && repo_dir="fedora"

  if [[ $IS_CN -eq 1 ]]; then
    local base="https://mirrors.aliyun.com/docker-ce/linux/${repo_dir}"
    curl -fsSL "$base/docker-ce.repo" -o /etc/yum.repos.d/docker-ce.repo
    sed -i "s/\$releasever/$ver/g" /etc/yum.repos.d/docker-ce.repo
  else
    # 官方源直接交给 get.docker.com 处理, 最省心
    curl -fsSL https://get.docker.com | sh
    return 0
  fi

  if [[ $PKG_MGR == dnf ]]; then
    dnf install -y dnf-plugins-core || true
    dnf makecache || dnf makecache fast || true
    dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  else
    yum install -y yum-utils || true
    yum makecache fast || true
    yum install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  fi
}

# ---------- 安装主体 ----------
if [[ $DOCKER_EXISTS -eq 1 ]]; then
  if docker compose version >/dev/null 2>&1 || command -v docker-compose >/dev/null 2>&1; then
    log "Docker 与 Compose 均已就绪, 跳过安装"
  else
    warn "已安装 Docker 但缺少 Compose 插件, 尝试补装..."
    if [[ $PKG_MGR == apt-get ]]; then
      install_debian
    else
      install_rhel
    fi
  fi
else
  # 清理可能与 docker-ce 冲突的旧版包(仅未安装 Docker 时执行, 安全)
  if [[ $PKG_MGR == apt-get ]]; then
    for pkg in docker.io docker-doc docker-compose docker-compose-v2 podman-docker containerd runc; do
      apt-get remove -y "$pkg" >/dev/null 2>&1 || true
    done
    install_debian
  else
    install_rhel
  fi
fi

# ---------- daemon.json: 加速器 + 日志轮转 ----------
configure_daemon() {
  local f=/etc/docker/daemon.json
  mkdir -p /etc/docker

  if [[ -f $f ]] && grep -qw '"registry-mirrors"' "$f"; then
    log "daemon.json 已配置镜像加速, 保留现有配置"
    return
  fi
  if [[ -f $f ]]; then
    cp "$f" "${f}.bak.$(date +%Y%m%d%H%M%S)"
    if command -v python3 >/dev/null 2>&1; then
      python3 - "$f" "$IS_CN" "${MIRRORS[@]}" <<'PY'
import json, sys
path, is_cn, *mirrors = sys.argv
with open(path) as fp:
    cfg = json.load(fp)
if is_cn == "1" and not cfg.get("registry-mirrors"):
    cfg["registry-mirrors"] = mirrors
cfg.setdefault("log-driver", "json-file")
cfg.setdefault("log-opts", {"max-size": "50m", "max-file": "3"})
with open(path, "w") as fp:
    json.dump(cfg, fp, indent=2, ensure_ascii=False)
PY
      log "已合并写入 $f (原文件已备份)"
      return
    fi
    warn "已备份原 daemon.json; 系统缺少 python3 无法自动合并, 请手动添加 registry-mirrors"
    return
  fi

  local mirror_json
  mirror_json=$(printf '"%s",' "${MIRRORS[@]}"); mirror_json="${mirror_json%,}"
  if [[ $IS_CN -eq 1 ]]; then
    cat > "$f" <<JSON
{
  "registry-mirrors": [$mirror_json],
  "log-driver": "json-file",
  "log-opts": { "max-size": "50m", "max-file": "3" }
}
JSON
  else
    cat > "$f" <<'JSON'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "50m", "max-file": "3" }
}
JSON
  fi
  log "已生成 $f"
}
configure_daemon

# ---------- 启动服务 ----------
if [[ -d /run/systemd/system ]]; then
  systemctl daemon-reload 2>/dev/null || true
  systemctl enable --now docker >/dev/null 2>&1 || true
  systemctl restart docker 2>/dev/null || service docker restart 2>/dev/null || true  # 应用 daemon.json
else
  service docker start || warn "无法通过 service 启动 docker, 请手动启动"
fi

# ---------- 结果验证 ----------
echo ""
docker --version
if docker compose version >/dev/null 2>&1; then
  docker compose version
elif command -v docker-compose >/dev/null 2>&1; then
  docker-compose --version
else
  warn "未检测到 Compose, 可能影响后续部署, 请检查安装日志"
fi
systemctl is-active docker >/dev/null 2>&1 \
  && log "Docker 服务运行中 ✔" \
  || warn "Docker 服务未运行, 请执行: systemctl status docker"

echo ""
log "✅ Docker 安装完成!"
log "   可选: 免 sudo 使用 docker →  usermod -aG docker <你的用户名> 后重新登录"
log "   下一步: 运行同目录 deploy.sh 部署闲鱼监控系统"
