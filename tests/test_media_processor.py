from unittest.mock import AsyncMock

from core.media_processor import process_watermarks


async def test_process_watermarks_skips_non_max_tier(tmp_path):
    filepath = tmp_path / "video.mp4"
    filepath.touch()
    user = {"tier": "pro", "watermark_file_id": "abc"}

    result = await process_watermarks(filepath, user, bot=None, session_dir=tmp_path)
    assert result == filepath


async def test_process_watermarks_skips_when_no_watermark_configured(tmp_path):
    filepath = tmp_path / "video.mp4"
    filepath.touch()
    user = {"tier": "max", "watermark_file_id": None}

    result = await process_watermarks(filepath, user, bot=None, session_dir=tmp_path)
    assert result == filepath


async def test_process_watermarks_applies_to_video_for_max_tier(tmp_path, monkeypatch):
    filepath = tmp_path / "video.mp4"
    filepath.touch()
    user = {"tier": "max", "watermark_file_id": "wm123", "watermark_position": "top_left"}

    bot = AsyncMock()

    async def fake_apply_video(input_path, watermark_path, position, output_path):
        output_path.touch()

    monkeypatch.setattr("core.watermark.apply_video_watermark", fake_apply_video)

    result = await process_watermarks(filepath, user, bot=bot, session_dir=tmp_path)
    assert result.name == "wm_video.mp4"
    bot.download.assert_awaited_once()


async def test_process_watermarks_applies_to_image_for_max_tier(tmp_path, monkeypatch):
    filepath = tmp_path / "photo.jpg"
    filepath.touch()
    user = {"tier": "max", "watermark_file_id": "wm123"}
    bot = AsyncMock()

    async def fake_apply_image(input_path, watermark_path, position, output_path):
        output_path.touch()

    monkeypatch.setattr("core.watermark.apply_image_watermark", fake_apply_image)

    result = await process_watermarks(filepath, user, bot=bot, session_dir=tmp_path)
    assert result.name == "wm_photo.jpg"


async def test_process_watermarks_leaves_unsupported_extension_untouched(tmp_path):
    filepath = tmp_path / "doc.pdf"
    filepath.touch()
    user = {"tier": "max", "watermark_file_id": "wm123"}
    bot = AsyncMock()

    result = await process_watermarks(filepath, user, bot=bot, session_dir=tmp_path)
    assert result == filepath


async def test_process_watermarks_handles_list_input(tmp_path, monkeypatch):
    video = tmp_path / "a.mp4"
    photo = tmp_path / "b.jpg"
    video.touch()
    photo.touch()
    user = {"tier": "max", "watermark_file_id": "wm123"}
    bot = AsyncMock()

    async def fake_apply_video(input_path, watermark_path, position, output_path):
        output_path.touch()

    async def fake_apply_image(input_path, watermark_path, position, output_path):
        output_path.touch()

    monkeypatch.setattr("core.watermark.apply_video_watermark", fake_apply_video)
    monkeypatch.setattr("core.watermark.apply_image_watermark", fake_apply_image)

    result = await process_watermarks([video, photo], user, bot=bot, session_dir=tmp_path)
    assert isinstance(result, list)
    assert {p.name for p in result} == {"wm_a.mp4", "wm_b.jpg"}


async def test_process_watermarks_falls_back_to_original_on_error(tmp_path, monkeypatch):
    filepath = tmp_path / "video.mp4"
    filepath.touch()
    user = {"tier": "max", "watermark_file_id": "wm123"}

    bot = AsyncMock()
    bot.download.side_effect = RuntimeError("network error")

    result = await process_watermarks(filepath, user, bot=bot, session_dir=tmp_path)
    assert result == filepath
