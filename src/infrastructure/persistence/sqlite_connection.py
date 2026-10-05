"""
SQLite 连接与 schema 初始化。
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from src.infrastructure.persistence.storage_names import DEFAULT_DATABASE_PATH


BUSY_TIMEOUT_MS = 5000

SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS app_metadata (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY,
        task_name TEXT NOT NULL,
        enabled INTEGER NOT NULL,
        keyword TEXT NOT NULL,
        description TEXT,
        analyze_images INTEGER NOT NULL,
        max_pages INTEGER NOT NULL,
        personal_only INTEGER NOT NULL,
        min_price TEXT,
        max_price TEXT,
        cron TEXT,
        ai_prompt_base_file TEXT NOT NULL,
        ai_prompt_criteria_file TEXT NOT NULL,
        account_state_file TEXT,
        account_strategy TEXT NOT NULL,
        free_shipping INTEGER NOT NULL,
        new_publish_option TEXT,
        region TEXT,
        decision_mode TEXT NOT NULL,
        keyword_rules_json TEXT NOT NULL,
        is_running INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS result_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        result_filename TEXT NOT NULL,
        keyword TEXT NOT NULL,
        task_name TEXT NOT NULL,
        crawl_time TEXT NOT NULL,
        publish_time TEXT,
        price REAL,
        price_display TEXT,
        item_id TEXT,
        title TEXT,
        link TEXT,
        link_unique_key TEXT NOT NULL,
        seller_nickname TEXT,
        is_recommended INTEGER NOT NULL,
        analysis_source TEXT,
        keyword_hit_count INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        raw_json TEXT NOT NULL,
        UNIQUE(result_filename, link_unique_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS price_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        keyword_slug TEXT NOT NULL,
        keyword TEXT NOT NULL,
        task_name TEXT NOT NULL,
        snapshot_time TEXT NOT NULL,
        snapshot_day TEXT NOT NULL,
        run_id TEXT NOT NULL,
        item_id TEXT NOT NULL,
        title TEXT,
        price REAL NOT NULL,
        price_display TEXT,
        tags_json TEXT NOT NULL,
        region TEXT,
        seller TEXT,
        publish_time TEXT,
        link TEXT,
        UNIQUE(keyword_slug, run_id, item_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS result_blacklist_rules (
        result_filename TEXT PRIMARY KEY,
        blacklist_keywords_json TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ai_profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        base_url TEXT NOT NULL,
        api_key TEXT NOT NULL DEFAULT '',
        model_name TEXT NOT NULL,
        proxy_url TEXT NOT NULL DEFAULT '',
        enabled INTEGER NOT NULL DEFAULT 1,
        is_active INTEGER NOT NULL DEFAULT 0,
        sort_order INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'user',
        status TEXT NOT NULL DEFAULT 'active',
        expired_at TEXT,
        created_at TEXT NOT NULL,
        last_login_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS card_keys (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT NOT NULL UNIQUE,
        duration_days INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'unused',
        batch_no TEXT NOT NULL DEFAULT '',
        note TEXT NOT NULL DEFAULT '',
        agent_id INTEGER,
        used_by INTEGER,
        used_at TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_notification_configs (
        user_id INTEGER PRIMARY KEY,
        config_json TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_proxy_configs (
        user_id INTEGER PRIMARY KEY,
        config_json TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_tasks_name ON tasks(task_name)",
    "CREATE INDEX IF NOT EXISTS idx_card_keys_status ON card_keys(status)",
    "CREATE INDEX IF NOT EXISTS idx_card_keys_batch ON card_keys(batch_no)",
    "CREATE INDEX IF NOT EXISTS idx_card_keys_used_by ON card_keys(used_by)",
    """
    CREATE INDEX IF NOT EXISTS idx_results_filename_crawl
    ON result_items(result_filename, crawl_time DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_results_filename_publish
    ON result_items(result_filename, publish_time DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_results_filename_price
    ON result_items(result_filename, price DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_results_filename_recommended
    ON result_items(result_filename, is_recommended, analysis_source, crawl_time DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_snapshots_keyword_time
    ON price_snapshots(keyword_slug, snapshot_time DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_snapshots_keyword_item_time
    ON price_snapshots(keyword_slug, item_id, snapshot_time DESC)
    """,
)


def get_database_path() -> str:
    return os.getenv("APP_DATABASE_FILE", DEFAULT_DATABASE_PATH)


def _prepare_database_file(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")


def init_schema(conn: sqlite3.Connection) -> None:
    for statement in SCHEMA_STATEMENTS:
        conn.execute(statement)
    _migrate_result_items_status(conn)
    _migrate_membership_user_scope(conn)
    conn.commit()


def _migrate_result_items_status(conn: sqlite3.Connection) -> None:
    """为 result_items 表添加 status 列（仅执行一次）。"""
    row = conn.execute(
        "SELECT value FROM app_metadata WHERE key = 'migration:result_items_status'"
    ).fetchone()
    if row is not None:
        return
    cols = [r[1] for r in conn.execute("PRAGMA table_info(result_items)").fetchall()]
    if "status" not in cols:
        conn.execute(
            "ALTER TABLE result_items ADD COLUMN status TEXT NOT NULL DEFAULT 'active'"
        )
    conn.execute(
        "INSERT OR REPLACE INTO app_metadata(key, value) VALUES ('migration:result_items_status', 'done')"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_results_filename_status_crawl"
        " ON result_items(result_filename, status, crawl_time DESC)"
    )


MEMBERSHIP_SCOPE_MIGRATION_KEY = "migration:membership_user_scope"


def _migrate_membership_user_scope(conn: sqlite3.Connection) -> None:
    """SaaS 多用户迁移：所有业务表加 user_id（存量数据归管理员 id=1），
    结果/快照/黑名单表重建唯一约束使不同用户互不冲突（仅执行一次）。

    说明：admin 用户在 bootstrap 阶段第一个创建，id 恒为 1，
    因此本迁移可以安全地把存量数据的 user_id 固定为 1。
    """
    row = conn.execute(
        "SELECT value FROM app_metadata WHERE key = ?",
        (MEMBERSHIP_SCOPE_MIGRATION_KEY,),
    ).fetchone()
    if row is not None:
        return

    # 1) tasks / ai_profiles：加列即可（不参与唯一约束）
    task_cols = [r[1] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()]
    if "user_id" not in task_cols:
        conn.execute("ALTER TABLE tasks ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1")
    if "paused_by_membership" not in task_cols:
        conn.execute(
            "ALTER TABLE tasks ADD COLUMN paused_by_membership INTEGER NOT NULL DEFAULT 0"
        )
    conn.execute("UPDATE tasks SET user_id = 1 WHERE user_id IS NULL")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id, enabled)"
    )

    profile_cols = [
        r[1] for r in conn.execute("PRAGMA table_info(ai_profiles)").fetchall()
    ]
    if "user_id" not in profile_cols:
        conn.execute(
            "ALTER TABLE ai_profiles ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1"
        )
    conn.execute("UPDATE ai_profiles SET user_id = 1 WHERE user_id IS NULL")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_profiles_user"
        " ON ai_profiles(user_id, sort_order)"
    )

    # 2) result_items：重建表，唯一键加入 user_id
    conn.execute(
        """
        CREATE TABLE result_items_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            result_filename TEXT NOT NULL,
            keyword TEXT NOT NULL,
            task_name TEXT NOT NULL,
            crawl_time TEXT NOT NULL,
            publish_time TEXT,
            price REAL,
            price_display TEXT,
            item_id TEXT,
            title TEXT,
            link TEXT,
            link_unique_key TEXT NOT NULL,
            seller_nickname TEXT,
            is_recommended INTEGER NOT NULL,
            analysis_source TEXT,
            keyword_hit_count INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            raw_json TEXT NOT NULL,
            user_id INTEGER NOT NULL DEFAULT 1,
            UNIQUE(result_filename, link_unique_key, user_id)
        )
        """
    )
    result_cols = {
        r[1] for r in conn.execute("PRAGMA table_info(result_items)").fetchall()
    }
    result_user_expr = "COALESCE(user_id, 1)" if "user_id" in result_cols else "1"
    conn.execute(
        f"""
        INSERT INTO result_items_new (
            id, result_filename, keyword, task_name, crawl_time, publish_time,
            price, price_display, item_id, title, link, link_unique_key,
            seller_nickname, is_recommended, analysis_source, keyword_hit_count,
            status, raw_json, user_id
        )
        SELECT id, result_filename, keyword, task_name, crawl_time, publish_time,
               price, price_display, item_id, title, link, link_unique_key,
               seller_nickname, is_recommended, analysis_source, keyword_hit_count,
               status, raw_json, {result_user_expr}
        FROM result_items
        """
    )
    conn.execute("DROP TABLE result_items")
    conn.execute("ALTER TABLE result_items_new RENAME TO result_items")

    # 3) price_snapshots：重建表，唯一键加入 user_id
    conn.execute(
        """
        CREATE TABLE price_snapshots_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword_slug TEXT NOT NULL,
            keyword TEXT NOT NULL,
            task_name TEXT NOT NULL,
            snapshot_time TEXT NOT NULL,
            snapshot_day TEXT NOT NULL,
            run_id TEXT NOT NULL,
            item_id TEXT NOT NULL,
            title TEXT,
            price REAL NOT NULL,
            price_display TEXT,
            tags_json TEXT NOT NULL,
            region TEXT,
            seller TEXT,
            publish_time TEXT,
            link TEXT,
            user_id INTEGER NOT NULL DEFAULT 1,
            UNIQUE(keyword_slug, run_id, item_id, user_id)
        )
        """
    )
    snapshot_cols = {
        r[1] for r in conn.execute("PRAGMA table_info(price_snapshots)").fetchall()
    }
    snapshot_user_expr = (
        "COALESCE(user_id, 1)" if "user_id" in snapshot_cols else "1"
    )
    conn.execute(
        f"""
        INSERT INTO price_snapshots_new (
            keyword_slug, keyword, task_name, snapshot_time, snapshot_day,
            run_id, item_id, title, price, price_display, tags_json,
            region, seller, publish_time, link, user_id
        )
        SELECT keyword_slug, keyword, task_name, snapshot_time, snapshot_day,
               run_id, item_id, title, price, price_display, tags_json,
               region, seller, publish_time, link, {snapshot_user_expr}
        FROM price_snapshots
        """
    )
    conn.execute("DROP TABLE price_snapshots")
    conn.execute("ALTER TABLE price_snapshots_new RENAME TO price_snapshots")

    # 4) result_blacklist_rules：主键加入 user_id
    conn.execute(
        """
        CREATE TABLE result_blacklist_rules_new (
            result_filename TEXT NOT NULL,
            user_id INTEGER NOT NULL DEFAULT 1,
            blacklist_keywords_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (result_filename, user_id)
        )
        """
    )
    blacklist_cols = {
        r[1] for r in conn.execute("PRAGMA table_info(result_blacklist_rules)").fetchall()
    }
    blacklist_user_expr = (
        "COALESCE(user_id, 1)" if "user_id" in blacklist_cols else "1"
    )
    conn.execute(
        f"""
        INSERT INTO result_blacklist_rules_new (
            result_filename, user_id, blacklist_keywords_json, updated_at
        )
        SELECT result_filename, {blacklist_user_expr}, blacklist_keywords_json, updated_at
        FROM result_blacklist_rules
        """
    )
    conn.execute("DROP TABLE result_blacklist_rules")
    conn.execute("ALTER TABLE result_blacklist_rules_new RENAME TO result_blacklist_rules")

    # 5) 重建索引（表重建后旧索引已随表删除）
    for statement in _POST_MIGRATION_INDEX_STATEMENTS:
        conn.execute(statement)

    conn.execute(
        "INSERT OR REPLACE INTO app_metadata(key, value) VALUES (?, 'done')",
        (MEMBERSHIP_SCOPE_MIGRATION_KEY,),
    )


_POST_MIGRATION_INDEX_STATEMENTS = (
    "CREATE INDEX IF NOT EXISTS idx_results_filename_crawl ON result_items(result_filename, crawl_time DESC)",
    "CREATE INDEX IF NOT EXISTS idx_results_filename_publish ON result_items(result_filename, publish_time DESC)",
    "CREATE INDEX IF NOT EXISTS idx_results_filename_price ON result_items(result_filename, price DESC)",
    "CREATE INDEX IF NOT EXISTS idx_results_filename_recommended ON result_items(result_filename, is_recommended, analysis_source, crawl_time DESC)",
    "CREATE INDEX IF NOT EXISTS idx_results_filename_status_crawl ON result_items(result_filename, status, crawl_time DESC)",
    "CREATE INDEX IF NOT EXISTS idx_results_user_filename_crawl ON result_items(user_id, result_filename, crawl_time DESC)",
    "CREATE INDEX IF NOT EXISTS idx_results_user_status_crawl ON result_items(user_id, status, crawl_time DESC)",
    "CREATE INDEX IF NOT EXISTS idx_snapshots_keyword_time ON price_snapshots(keyword_slug, snapshot_time DESC)",
    "CREATE INDEX IF NOT EXISTS idx_snapshots_keyword_item_time ON price_snapshots(keyword_slug, item_id, snapshot_time DESC)",
    "CREATE INDEX IF NOT EXISTS idx_snapshots_user_keyword_time ON price_snapshots(user_id, keyword_slug, snapshot_time DESC)",
)


@contextmanager
def sqlite_connection(
    db_path: str | None = None,
) -> Iterator[sqlite3.Connection]:
    path = db_path or get_database_path()
    _prepare_database_file(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        _apply_pragmas(conn)
        yield conn
    finally:
        conn.close()
