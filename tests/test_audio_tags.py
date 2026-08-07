from core.audio_tags import process_audio_tags


async def test_process_audio_tags_noop_without_state(tmp_path):
    filepath = tmp_path / "song.mp3"
    filepath.touch()
    result = await process_audio_tags(filepath, None)
    assert result == filepath


async def test_process_audio_tags_noop_when_edit_tags_false(tmp_path):
    filepath = tmp_path / "song.mp3"
    filepath.touch()
    result = await process_audio_tags(filepath, {"edit_tags": False})
    assert result == filepath


async def test_process_audio_tags_applies_metadata_for_audio_extension(tmp_path, monkeypatch):
    filepath = tmp_path / "song.mp3"
    filepath.touch()

    async def fake_apply(input_path, output_path, title, artist, album, cover_path=None):
        output_path.touch()
        return output_path

    monkeypatch.setattr("core.audio_tags.apply_audio_metadata", fake_apply)

    state_data = {"edit_tags": True, "title": "T", "artist": "A", "album": "Al"}
    result = await process_audio_tags(filepath, state_data)
    assert result.name == "tagged_song.mp3"


async def test_process_audio_tags_leaves_non_audio_extension_untouched(tmp_path):
    filepath = tmp_path / "video.mp4"
    filepath.touch()
    state_data = {"edit_tags": True, "title": "T", "artist": "A", "album": "Al"}
    result = await process_audio_tags(filepath, state_data)
    assert result == filepath


async def test_process_audio_tags_handles_list_input(tmp_path, monkeypatch):
    mp3 = tmp_path / "a.mp3"
    mp4 = tmp_path / "b.mp4"
    mp3.touch()
    mp4.touch()

    async def fake_apply(input_path, output_path, title, artist, album, cover_path=None):
        output_path.touch()
        return output_path

    monkeypatch.setattr("core.audio_tags.apply_audio_metadata", fake_apply)

    state_data = {"edit_tags": True, "title": "T", "artist": "A", "album": "Al"}
    result = await process_audio_tags([mp3, mp4], state_data)
    names = {p.name for p in result}
    assert names == {"tagged_a.mp3", "b.mp4"}


async def test_process_audio_tags_cleans_up_cover_directory(tmp_path, monkeypatch):
    cover_dir = tmp_path / "cover_session"
    cover_dir.mkdir()
    cover_path = cover_dir / "cover.jpg"
    cover_path.touch()

    filepath = tmp_path / "song.mp3"
    filepath.touch()

    async def fake_apply(input_path, output_path, title, artist, album, cover_path=None):
        output_path.touch()
        return output_path

    monkeypatch.setattr("core.audio_tags.apply_audio_metadata", fake_apply)

    state_data = {"edit_tags": True, "title": "T", "artist": "A", "album": "Al", "cover_path": str(cover_path)}
    await process_audio_tags(filepath, state_data)

    assert not cover_dir.exists()
