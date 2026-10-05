import asyncio
from pathlib import Path

import src.ai_handler as ai_handler


def test_download_all_images_runs_with_concurrency(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_handler, "IMAGE_SAVE_DIR", str(tmp_path / "images"))

    active_downloads = 0
    max_active_downloads = 0

    async def fake_download(url, save_path):
        nonlocal active_downloads, max_active_downloads
        active_downloads += 1
        max_active_downloads = max(max_active_downloads, active_downloads)
        await asyncio.sleep(0.02)
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        Path(save_path).write_text("ok", encoding="utf-8")
        active_downloads -= 1
        return save_path

    monkeypatch.setattr(ai_handler, "_download_single_image", fake_download)

    async def run():
        return await ai_handler.download_all_images(
            "product-1",
            [
                "https://example.com/1.jpg",
                "https://example.com/2.jpg",
                "https://example.com/3.jpg",
            ],
            task_name="demo",
            concurrency=3,
        )

    paths = asyncio.run(run())
    assert len(paths) == 3
    assert max_active_downloads == 3


def test_task_image_dir_scoped_by_user_and_task(tmp_path, monkeypatch):
    """图片目录按 用户+任务 隔离：同名任务（跨用户/并发）不再共用同一目录。"""
    monkeypatch.setattr(ai_handler, "IMAGE_SAVE_DIR", str(tmp_path / "images"))
    monkeypatch.setattr(ai_handler, "get_spider_user_id", lambda: 2)

    async def fake_download(url, save_path):
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        Path(save_path).write_text("ok", encoding="utf-8")
        return save_path

    monkeypatch.setattr(ai_handler, "_download_single_image", fake_download)

    async def run():
        return await ai_handler.download_all_images(
            "product-1",
            ["https://example.com/1.jpg"],
            task_name="Same Task",
            task_id=7,
        )

    paths = asyncio.run(run())
    assert len(paths) == 1
    expected_dir = tmp_path / "images" / "task_images_u2_t7_Same_Task"
    assert Path(paths[0]).parent == expected_dir

    ai_handler.cleanup_task_images("Same Task", task_id=7)
    assert not expected_dir.exists()
    # 同用户下另一个任务 ID 的同名目录不受牵连
    other_task_dir = tmp_path / "images" / "task_images_u2_t8_Same_Task"
    other_task_dir.mkdir(parents=True)
    ai_handler.cleanup_task_images("Same Task", task_id=7)
    assert other_task_dir.exists()
