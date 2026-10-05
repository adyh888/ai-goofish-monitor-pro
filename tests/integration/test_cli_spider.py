import asyncio
import importlib
import json
import sys
import types


def test_cli_runs_single_task_with_prompt(tmp_path, load_json_fixture, monkeypatch):
    fake_scraper = types.ModuleType("src.scraper")

    async def placeholder_scrape(task_config, debug_limit):
        return 0

    fake_scraper.scrape_xianyu = placeholder_scrape
    monkeypatch.setitem(sys.modules, "src.scraper", fake_scraper)
    sys.modules.pop("spider_v2", None)

    spider_v2 = importlib.import_module("spider_v2")
    config_data = load_json_fixture("config.sample.json")

    base_prompt = "Base prompt. " + ("x" * 120) + " {{CRITERIA_SECTION}}"
    criteria_prompt = "Criteria text for A7M4."

    base_path = tmp_path / "base_prompt.txt"
    criteria_path = tmp_path / "criteria_prompt.txt"
    base_path.write_text(base_prompt, encoding="utf-8")
    criteria_path.write_text(criteria_prompt, encoding="utf-8")

    config_data[0]["ai_prompt_base_file"] = str(base_path)
    config_data[0]["ai_prompt_criteria_file"] = str(criteria_path)

    config_data[1]["ai_prompt_base_file"] = str(base_path)
    config_data[1]["ai_prompt_criteria_file"] = str(criteria_path)

    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config_data, ensure_ascii=False), encoding="utf-8")

    state_path = tmp_path / "state.json"
    state_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(spider_v2, "STATE_FILE", str(state_path))

    called = []

    async def fake_scrape_xianyu(task_config, debug_limit):
        called.append(task_config["task_name"])
        assert "{{CRITERIA_SECTION}}" not in task_config["ai_prompt_text"]
        assert "Criteria text for A7M4." in task_config["ai_prompt_text"]
        return 1

    monkeypatch.setattr(spider_v2, "scrape_xianyu", fake_scrape_xianyu)
    monkeypatch.setattr(sys, "argv", ["spider_v2.py", "--config", str(config_path), "--task-name", "Sony A7M4"])

    asyncio.run(spider_v2.main())

    assert called == ["Sony A7M4"]


def test_cli_runs_keyword_mode_without_prompt_files(tmp_path, load_json_fixture, monkeypatch):
    fake_scraper = types.ModuleType("src.scraper")

    async def placeholder_scrape(task_config, debug_limit):
        return 0

    fake_scraper.scrape_xianyu = placeholder_scrape
    monkeypatch.setitem(sys.modules, "src.scraper", fake_scraper)
    sys.modules.pop("spider_v2", None)

    spider_v2 = importlib.import_module("spider_v2")
    config_data = load_json_fixture("config.sample.json")
    config_data[0]["enabled"] = True
    config_data[0]["decision_mode"] = "keyword"
    config_data[0]["keyword_rules"] = ["a7m4", "验货宝"]
    config_data[0]["ai_prompt_base_file"] = "missing_base.txt"
    config_data[0]["ai_prompt_criteria_file"] = "missing_criteria.txt"

    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config_data, ensure_ascii=False), encoding="utf-8")

    state_path = tmp_path / "state.json"
    state_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(spider_v2, "STATE_FILE", str(state_path))

    captured = []

    async def fake_scrape_xianyu(task_config, debug_limit):
        captured.append(task_config)
        return 1

    monkeypatch.setattr(spider_v2, "scrape_xianyu", fake_scrape_xianyu)
    monkeypatch.setattr(sys, "argv", ["spider_v2.py", "--config", str(config_path), "--task-name", "Sony A7M4"])

    asyncio.run(spider_v2.main())

    assert len(captured) == 1
    assert captured[0]["decision_mode"] == "keyword"
    assert captured[0]["ai_prompt_text"] == ""


class _FakeTask:
    def __init__(self, **kwargs):
        data = {
            "id": 0,
            "user_id": 1,
            "task_name": "Same Task",
            "enabled": True,
            "keyword": "kw",
            "decision_mode": "keyword",
            "keyword_rules": ["kw"],
            "ai_prompt_base_file": "",
            "ai_prompt_criteria_file": "",
        }
        data.update(kwargs)
        self._data = data

    def dict(self):
        return dict(self._data)


def test_cli_task_id_beats_same_name_task(tmp_path, monkeypatch):
    """回归：同名任务必须按 --task-id 精确匹配，且按用户过滤加载，避免串配置。"""
    fake_scraper = types.ModuleType("src.scraper")

    async def placeholder_scrape(task_config, debug_limit):
        return 0

    fake_scraper.scrape_xianyu = placeholder_scrape
    monkeypatch.setitem(sys.modules, "src.scraper", fake_scraper)
    sys.modules.pop("spider_v2", None)

    spider_v2 = importlib.import_module("spider_v2")

    # 同一用户（user_id=2）下两个同名任务：id=1 是 AI 模式旧配置，id=7 是用户要跑的
    task_old = _FakeTask(id=1, user_id=2, task_name="Same Task", keyword="old-keyword", decision_mode="ai")
    task_new = _FakeTask(id=7, user_id=2, task_name="Same Task", keyword="new-keyword", decision_mode="keyword")

    seen_scopes = []

    class FakeRepo:
        async def find_all(self, user_id=None):
            seen_scopes.append(user_id)
            return [task_old, task_new]

    monkeypatch.setattr(spider_v2, "SqliteTaskRepository", lambda: FakeRepo())

    state_path = tmp_path / "state.json"
    state_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(spider_v2, "STATE_FILE", str(state_path))

    captured = []

    async def fake_scrape(task_config, debug_limit):
        captured.append(task_config)
        return 1

    monkeypatch.setattr(spider_v2, "scrape_xianyu", fake_scrape)
    monkeypatch.setattr(
        sys,
        "argv",
        ["spider_v2.py", "--task-id", "7", "--task-name", "Same Task", "--user-id", "2"],
    )

    asyncio.run(spider_v2.main())

    assert seen_scopes == [2]
    assert len(captured) == 1
    assert captured[0]["id"] == 7
    assert captured[0]["keyword"] == "new-keyword"


def test_cli_task_id_from_other_user_not_found(tmp_path, monkeypatch):
    """跨用户保护：目标用户的任务列表里没有该 ID 时不执行任何任务。"""
    fake_scraper = types.ModuleType("src.scraper")

    async def placeholder_scrape(task_config, debug_limit):
        return 0

    fake_scraper.scrape_xianyu = placeholder_scrape
    monkeypatch.setitem(sys.modules, "src.scraper", fake_scraper)
    sys.modules.pop("spider_v2", None)

    spider_v2 = importlib.import_module("spider_v2")

    class FakeRepo:
        async def find_all(self, user_id=None):
            return []  # 用户 2 名下没有任务（任务属于其他用户）

    monkeypatch.setattr(spider_v2, "SqliteTaskRepository", lambda: FakeRepo())

    state_path = tmp_path / "state.json"
    state_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(spider_v2, "STATE_FILE", str(state_path))

    captured = []

    async def fake_scrape(task_config, debug_limit):
        captured.append(task_config)
        return 1

    monkeypatch.setattr(spider_v2, "scrape_xianyu", fake_scrape)
    monkeypatch.setattr(
        sys,
        "argv",
        ["spider_v2.py", "--task-id", "9", "--user-id", "2"],
    )

    asyncio.run(spider_v2.main())

    assert captured == []
