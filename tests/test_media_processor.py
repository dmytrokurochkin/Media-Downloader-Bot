from unittest.mock import AsyncMock

from core.media_processor import process_watermarks, watermark_armed


async def test_process_watermarks_skips_non_max_tier(tmp_path):
    filepath = tmp_path / "video.mp4"
    filepath.touch()
    user = {"telegram_id": 1, "tier": "pro", "watermark_file_id": "abc"}
    watermark_armed.add(1)

    result = await process_watermarks(filepath, user, bot=None, session_dir=tmp_path)
    assert result == filepath


async def test_process_watermarks_skips_when_no_watermark_configured(tmp_path):
    filepath = tmp_path / "video.mp4"
    filepath.touch()
    user = {"telegram_id": 2, "tier": "max", "watermark_file_id": None}
    watermark_armed.add(2)

    result = await process_watermarks(filepath, user, bot=None, session_dir=tmp_path)
    assert result == filepath


async def test_process_watermarks_skips_when_not_armed(tmp_path):
    filepath = tmp_path / "video.mp4"
    filepath.touch()
    user = {"telegram_id": 3, "tier": "max", "watermark_file_id": "wm123"}
    watermark_armed.discard(3)

    result = await process_watermarks(filepath, user, bot=AsyncMock(), session_dir=tmp_path)
    assert result == filepath


async def test_process_watermarks_is_one_shot(tmp_path, monkeypatch):
    filepath = tmp_path / "video.mp4"
    filepath.touch()
    user = {"telegram_id": 4, "tier": "max", "watermark_file_id": "wm123"}
    bot = AsyncMock()

    async def fake_apply_video(input_path, watermark_path, position, output_path):
        output_path.touch()

    monkeypatch.setattr("core.watermark.apply_video_watermark", fake_apply_video)

    watermark_armed.add(4)
    first = await process_watermarks(filepath, user, bot=bot, session_dir=tmp_path)
    assert first.name == "wm_video.mp4"

    # Second call without re-arming should be skipped (one-shot, not automatic).
    filepath2 = tmp_path / "video2.mp4"
    filepath2.touch()
    second = await process_watermarks(filepath2, user, bot=bot, session_dir=tmp_path)
    assert second == filepath2


async def test_process_watermarks_applies_to_video_for_max_tier(tmp_path, monkeypatch):
    filepath = tmp_path / "video.mp4"
    filepath.touch()
    user = {"telegram_id": 5, "tier": "max", "watermark_file_id": "wm123", "watermark_position": "top_left"}

    bot = AsyncMock()

    async def fake_apply_video(input_path, watermark_path, position, output_path):
        output_path.touch()

    monkeypatch.setattr("core.watermark.apply_video_watermark", fake_apply_video)

    watermark_armed.add(5)
    result = await process_watermarks(filepath, user, bot=bot, session_dir=tmp_path)
    assert result.name == "wm_video.mp4"
    bot.download.assert_awaited_once()


async def test_process_watermarks_applies_to_image_for_max_tier(tmp_path, monkeypatch):
    filepath = tmp_path / "photo.jpg"
    filepath.touch()
    user = {"telegram_id": 6, "tier": "max", "watermark_file_id": "wm123"}
    bot = AsyncMock()

    async def fake_apply_image(input_path, watermark_path, position, output_path):
        output_path.touch()

    monkeypatch.setattr("core.watermark.apply_image_watermark", fake_apply_image)

    watermark_armed.add(6)
    result = await process_watermarks(filepath, user, bot=bot, session_dir=tmp_path)
    assert result.name == "wm_photo.jpg"


async def test_process_watermarks_leaves_unsupported_extension_untouched(tmp_path):
    filepath = tmp_path / "doc.pdf"
    filepath.touch()
    user = {"telegram_id": 7, "tier": "max", "watermark_file_id": "wm123"}
    bot = AsyncMock()

    watermark_armed.add(7)
    result = await process_watermarks(filepath, user, bot=bot, session_dir=tmp_path)
    assert result == filepath


async def test_process_watermarks_handles_list_input(tmp_path, monkeypatch):
    video = tmp_path / "a.mp4"
    photo = tmp_path / "b.jpg"
    video.touch()
    photo.touch()
    user = {"telegram_id": 8, "tier": "max", "watermark_file_id": "wm123"}
    bot = AsyncMock()

    async def fake_apply_video(input_path, watermark_path, position, output_path):
        output_path.touch()

    async def fake_apply_image(input_path, watermark_path, position, output_path):
        output_path.touch()

    monkeypatch.setattr("core.watermark.apply_video_watermark", fake_apply_video)
    monkeypatch.setattr("core.watermark.apply_image_watermark", fake_apply_image)

    watermark_armed.add(8)
    result = await process_watermarks([video, photo], user, bot=bot, session_dir=tmp_path)
    assert isinstance(result, list)
    assert {p.name for p in result} == {"wm_a.mp4", "wm_b.jpg"}


async def test_process_watermarks_falls_back_to_original_on_error(tmp_path, monkeypatch):
    filepath = tmp_path / "video.mp4"
    filepath.touch()
    user = {"telegram_id": 9, "tier": "max", "watermark_file_id": "wm123"}

    bot = AsyncMock()
    bot.download.side_effect = RuntimeError("network error")

    watermark_armed.add(9)
    result = await process_watermarks(filepath, user, bot=bot, session_dir=tmp_path)
    assert result == filepath
