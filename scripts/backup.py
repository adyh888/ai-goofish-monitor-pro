#!/usr/bin/env python3
"""SaaS 数据备份脚本。

备份内容：
- SQLite 业务库（users/card_keys/tasks/results 等，在线备份 API，不影响运行）
- 登录态目录 state/（含各用户的 Cookie）
- 商品图片目录 images/（跳过任务临时图片，可用 BACKUP_IMAGES=0 关闭）

保留策略：backups/ 下仅保留最近 BACKUP_KEEP 份（默认 7），其余自动删除。

用法：
    .venv/bin/python scripts/backup.py
建议 crontab（每天 03:30）：
    30 3 * * * cd /path/to/ai-goofish-monitor && .venv/bin/python scripts/backup.py >> logs/backup.log 2>&1
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

KEEP = int(os.getenv("BACKUP_KEEP", "7"))
DB_PATH = os.getenv("APP_DATABASE_FILE", "data/app.sqlite3")
STATE_DIR = os.getenv("ACCOUNT_STATE_DIR", "state")
INCLUDE_IMAGES = os.getenv("BACKUP_IMAGES", "1") == "1"
IMAGES_DIR = os.getenv("IMAGE_SAVE_DIR", "images")
BACKUP_ROOT = Path(os.getenv("BACKUP_DIR", "backups"))


def backup_database(target: Path) -> None:
    if not Path(DB_PATH).exists():
        print(f"[backup] 数据库不存在，跳过: {DB_PATH}")
        return
    source = sqlite3.connect(DB_PATH)
    destination = sqlite3.connect(str(target))
    try:
        with destination:
            source.backup(destination)
    finally:
        destination.close()
        source.close()
    print(f"[backup] 数据库已备份: {target}")


def backup_dir(source: str | Path, target: Path, *, skip_task_images: bool = False) -> None:
    source_path = Path(source)
    if not source_path.exists():
        print(f"[backup] 目录不存在，跳过: {source_path}")
        return
    ignore = None
    if skip_task_images:
        ignore = shutil.ignore_patterns("task_images_*")
    shutil.copytree(source_path, target, ignore=ignore, dirs_exist_ok=True)
    print(f"[backup] 目录已备份: {source_path} -> {target}")


def apply_retention() -> None:
    entries = sorted(p for p in BACKUP_ROOT.iterdir() if p.is_dir())
    for stale in entries[:-KEEP] if len(entries) > KEEP else []:
        shutil.rmtree(stale, ignore_errors=True)
        print(f"[backup] 清理过期备份: {stale}")


def main() -> int:
    ts = time.strftime("%Y%m%d_%H%M%S")
    target_root = BACKUP_ROOT / ts
    target_root.mkdir(parents=True, exist_ok=True)

    backup_database(target_root / "app.sqlite3")
    backup_dir(STATE_DIR, target_root / "state")
    if INCLUDE_IMAGES:
        backup_dir(IMAGES_DIR, target_root / "images", skip_task_images=True)

    apply_retention()
    print(f"[backup] 完成: {target_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
