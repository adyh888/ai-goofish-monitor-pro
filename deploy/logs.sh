#!/usr/bin/env bash
################################################################################
# 闲鱼监控系统 - 日志查看工具 (在云服务器上运行)
#
# 支持两种模式:
#   1. app 模式 (默认): 查看 Docker 容器主日志 (FastAPI / 调度器 / API 请求等)
#   2. task 模式: 查看爬虫任务运行日志 (logs/*.log 文件)
#
# === app 模式 (默认, 向后兼容) ===
#   bash deploy/logs.sh                 # 实时跟踪日志, Ctrl+C 退出
#   bash deploy/logs.sh --tail 200      # 只看最近 200 行, 不跟踪
#   bash deploy/logs.sh --since 30m     # 看最近 30 分钟内的日志
#
# === task 模式: 查看爬虫任务日志 ===
#   bash deploy/logs.sh task            # 列出所有任务日志文件
#   bash deploy/logs.sh task "MacBook"  # 实时跟踪名称含 MacBook 的任务日志
#   bash deploy/logs.sh task 3          # 实时跟踪 ID=3 的任务日志
#   bash deploy/logs.sh task 3 --tail 100   # 看 ID=3 任务最近 100 行
#   bash deploy/logs.sh task "Mac" --tail 50 # 看名称匹配的任务最近 50 行
#   bash deploy/logs.sh task --grep "推荐"   # 在所有任务日志中搜索关键词
#   bash deploy/logs.sh task 3 --grep "失败" # 在指定任务日志中搜索
#
# 说明: 在项目目录内外均可运行; app 模式无 docker 权限时自动尝试 sudo。
################################################################################
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
APP_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$APP_DIR"

LOGS_DIR="$APP_DIR/logs"

# ─── 帮助信息 ────────────────────────────────────────────────────────────────
print_help() {
  cat <<'EOF'
闲鱼监控系统 - 日志查看工具

用法:
  bash deploy/logs.sh [模式] [参数...]

模式:
  (默认)                查看 Docker 容器主日志 (app 模式)
  task                  查看爬虫任务运行日志
  help / -h / --help    显示此帮助

── app 模式 (默认) ──
  bash deploy/logs.sh                 # 实时跟踪日志, Ctrl+C 退出
  bash deploy/logs.sh --tail 200      # 只看最近 200 行
  bash deploy/logs.sh --since 30m     # 看最近 30 分钟

── task 模式 ──
  bash deploy/logs.sh task                  # 列出所有任务日志文件
  bash deploy/logs.sh task "关键词"         # 实时跟踪匹配的任务日志
  bash deploy/logs.sh task <任务ID>         # 实时跟踪指定 ID 的任务日志
  bash deploy/logs.sh task "关键词" --tail N  # 看最近 N 行 (不跟踪)
  bash deploy/logs.sh task <ID> --tail N      # 看最近 N 行
  bash deploy/logs.sh task --grep "关键词"    # 在所有任务日志中搜索
  bash deploy/logs.sh task <ID> --grep "词"   # 在指定任务日志中搜索

日志文件命名: {任务名}_{任务ID}.log
保留天数: 由 TASK_LOG_RETENTION_DAYS 控制 (默认 7 天)
EOF
}

# ─── task 模式: 列出所有日志文件 ─────────────────────────────────────────────
task_list_logs() {
  if [[ ! -d "$LOGS_DIR" ]]; then
    echo "日志目录不存在: $LOGS_DIR"
    echo "还没有运行过任何任务吗?"
    return 1
  fi

  local count
  count=$(find "$LOGS_DIR" -maxdepth 1 -name "*.log" -type f 2>/dev/null | wc -l | tr -d ' ')

  if [[ "$count" -eq 0 ]]; then
    echo "暂无任务日志文件。"
    echo "运行任务后会在 logs/ 目录下生成 .log 文件。"
    return 0
  fi

  echo "共找到 $count 个任务日志文件 (按修改时间排序, 最新在上):"
  echo "─────────────────────────────────────────────────────────"
  # 按修改时间倒序列出, 显示大小和修改时间
  ls -lht "$LOGS_DIR"/*.log 2>/dev/null | awk '{
    # $5 = 大小, $6$7$8 = 日期时间, $9 = 文件名
    size = $5
    # 人类可读大小
    if (size >= 1048576) {
      hsize = sprintf("%.1fM", size/1048576)
    } else if (size >= 1024) {
      hsize = sprintf("%.1fK", size/1024)
    } else {
      hsize = size "B"
    }
    # 从完整路径提取文件名
    n = split($9, parts, "/")
    fname = parts[n]
    printf "  %-6s  %s %s %s  %s\n", hsize, $6, $7, $8, fname
  }'
  echo "─────────────────────────────────────────────────────────"
  echo "提示: 运行 'bash deploy/logs.sh task <名称或ID>' 查看具体日志"
}

# ─── task 模式: 按关键词/ID 匹配日志文件 ────────────────────────────────────
task_find_log() {
  local query="$1"
  local matched=""

  if [[ ! -d "$LOGS_DIR" ]]; then
    echo "错误: 日志目录不存在: $LOGS_DIR" >&2
    return 1
  fi

  # 如果是纯数字, 优先按任务 ID 精确匹配 (文件名末尾 _数字.log)
  if [[ "$query" =~ ^[0-9]+$ ]]; then
    matched=$(find "$LOGS_DIR" -maxdepth 1 -name "*_${query}.log" -type f 2>/dev/null | head -1)
    if [[ -n "$matched" ]]; then
      echo "$matched"
      return 0
    fi
  fi

  # 按名称模糊匹配 (不区分大小写)
  local matches
  matches=$(find "$LOGS_DIR" -maxdepth 1 -name "*.log" -type f 2>/dev/null \
    | grep -i "$query" 2>/dev/null || true)

  local match_count
  match_count=$(echo "$matches" | grep -c . 2>/dev/null || echo 0)

  if [[ "$match_count" -eq 0 ]]; then
    echo "错误: 未找到匹配 '$query' 的日志文件" >&2
    echo "可用 'bash deploy/logs.sh task' 查看所有日志文件" >&2
    return 1
  elif [[ "$match_count" -gt 1 ]]; then
    echo "错误: 找到 $match_count 个匹配 '$query' 的日志文件, 请更精确:" >&2
    echo "$matches" | while read -r f; do
      basename "$f"
    done >&2
    return 1
  fi

  echo "$matches"
  return 0
}

# ─── task 模式入口 ──────────────────────────────────────────────────────────
task_mode() {
  local query=""
  local mode="follow"     # follow | tail | grep
  local tail_count=50
  local grep_keyword=""

  # 解析参数
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --tail)
        mode="tail"
        if [[ $# -ge 2 && "$2" =~ ^[0-9]+$ ]]; then
          tail_count="$2"
          shift 2
        else
          tail_count=50
          shift
        fi
        ;;
      --grep)
        mode="grep"
        if [[ $# -ge 2 && -n "$2" ]]; then
          grep_keyword="$2"
          shift 2
        else
          echo "错误: --grep 需要指定关键词" >&2
          return 1
        fi
        ;;
      -h|--help|help)
        print_help
        return 0
        ;;
      -*)
        echo "错误: 未知参数 $1" >&2
        echo "使用 'bash deploy/logs.sh task help' 查看帮助" >&2
        return 1
        ;;
      *)
        if [[ -z "$query" ]]; then
          query="$1"
        else
          echo "错误: 多余的参数 '$1'" >&2
          return 1
        fi
        shift
        ;;
    esac
  done

  # 无参数: 列出所有日志文件
  if [[ -z "$query" && "$mode" == "follow" ]]; then
    task_list_logs
    return $?
  fi

  # grep 模式: 无 query 则搜全部文件
  if [[ "$mode" == "grep" ]]; then
    if [[ -z "$query" ]]; then
      # 所有文件中搜索
      if [[ ! -d "$LOGS_DIR" ]]; then
        echo "错误: 日志目录不存在" >&2
        return 1
      fi
      echo "在所有任务日志中搜索: $grep_keyword"
      echo "─────────────────────────────────────────────────────────"
      grep -iHn "$grep_keyword" "$LOGS_DIR"/*.log 2>/dev/null || {
        echo "未找到匹配内容。"
      }
      return 0
    else
      # 指定任务中搜索
      local log_file
      log_file=$(task_find_log "$query") || return 1
      echo "在 $(basename "$log_file") 中搜索: $grep_keyword"
      echo "─────────────────────────────────────────────────────────"
      grep -in "$grep_keyword" "$log_file" 2>/dev/null || {
        echo "未找到匹配内容。"
      }
      return 0
    fi
  fi

  # follow / tail 模式: 需要指定查询
  if [[ -z "$query" ]]; then
    echo "错误: 请指定任务名称或 ID" >&2
    echo "使用 'bash deploy/logs.sh task' 查看所有日志文件" >&2
    return 1
  fi

  local log_file
  log_file=$(task_find_log "$query") || return 1

  local fname
  fname=$(basename "$log_file")

  if [[ "$mode" == "tail" ]]; then
    echo "📄 $fname (最近 $tail_count 行)"
    echo "─────────────────────────────────────────────────────────"
    tail -n "$tail_count" "$log_file"
  else
    echo "📄 实时跟踪: $fname  (Ctrl+C 退出)"
    echo "─────────────────────────────────────────────────────────"
    exec tail -f "$log_file"
  fi
}

# ─── app 模式 (原 docker compose logs) ──────────────────────────────────────
app_mode() {
  # 非 root 且 docker 权限不足时, 自动用 sudo 重跑自己
  if ! docker compose ps >/dev/null 2>&1; then
    exec sudo bash "$SCRIPT_DIR/logs.sh" "$@"
  fi

  if [[ $# -eq 0 ]]; then
    exec docker compose logs -f app
  else
    exec docker compose logs "$@" app
  fi
}

# ─── 主入口 ──────────────────────────────────────────────────────────────────
main() {
  if [[ $# -eq 0 ]]; then
    app_mode
    return
  fi

  case "$1" in
    task)
      shift
      task_mode "$@"
      ;;
    help|-h|--help)
      print_help
      ;;
    app)
      # 显式指定 app 模式
      shift
      app_mode "$@"
      ;;
    -*)
      # 以 - 开头的参数, 视为 app 模式的参数 (保持向后兼容)
      app_mode "$@"
      ;;
    *)
      echo "错误: 未知模式 '$1'" >&2
      echo "使用 'bash deploy/logs.sh help' 查看帮助" >&2
      exit 1
      ;;
  esac
}

main "$@"
