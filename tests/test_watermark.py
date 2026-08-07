from PIL import Image

from core.watermark import _get_overlay_coords, apply_image_watermark_sync, apply_image_watermark


def test_overlay_coords_top_left():
    assert _get_overlay_coords("top_left", padding=10) == "10:10"


def test_overlay_coords_top_right():
    assert _get_overlay_coords("top_right", padding=10) == "W-w-10:10"


def test_overlay_coords_bottom_left():
    assert _get_overlay_coords("bottom_left", padding=10) == "10:H-h-10"


def test_overlay_coords_bottom_right():
    assert _get_overlay_coords("bottom_right", padding=10) == "W-w-10:H-h-10"


def test_overlay_coords_unknown_defaults_to_bottom_right():
    assert _get_overlay_coords("nonsense", padding=10) == "W-w-10:H-h-10"


def _make_png(path, size, color):
    Image.new("RGBA", size, color).save(path)


def test_apply_image_watermark_sync_produces_correctly_sized_output(tmp_path):
    base_path = tmp_path / "base.png"
    wm_path = tmp_path / "wm.png"
    out_path = tmp_path / "out.png"

    _make_png(base_path, (400, 300), (255, 0, 0, 255))
    _make_png(wm_path, (100, 50), (0, 255, 0, 255))

    apply_image_watermark_sync(base_path, wm_path, "bottom_right", out_path)

    assert out_path.exists()
    with Image.open(out_path) as result:
        assert result.size == (400, 300)


def test_apply_image_watermark_sync_converts_jpeg_to_rgb(tmp_path):
    base_path = tmp_path / "base.jpg"
    wm_path = tmp_path / "wm.png"
    out_path = tmp_path / "out.jpg"

    Image.new("RGB", (200, 200), (10, 20, 30)).save(base_path)
    _make_png(wm_path, (50, 50), (0, 255, 0, 255))

    apply_image_watermark_sync(base_path, wm_path, "top_left", out_path)

    with Image.open(out_path) as result:
        assert result.mode == "RGB"


def test_apply_image_watermark_sync_places_watermark_pixels_in_expected_corner(tmp_path):
    base_path = tmp_path / "base.png"
    wm_path = tmp_path / "wm.png"
    out_path = tmp_path / "out.png"

    # Solid blue background, solid opaque green watermark (fully covers its own area).
    _make_png(base_path, (200, 200), (0, 0, 255, 255))
    _make_png(wm_path, (50, 50), (0, 255, 0, 255))

    apply_image_watermark_sync(base_path, wm_path, "top_left", out_path)

    with Image.open(out_path) as result:
        # top-left padding is 10px, watermark scaled to 15% of 200 = 30px wide.
        pixel_inside_watermark = result.getpixel((15, 15))
        pixel_outside_watermark = result.getpixel((190, 190))

    assert pixel_inside_watermark[:3] == (0, 255, 0)
    assert pixel_outside_watermark[:3] == (0, 0, 255)


async def test_apply_image_watermark_async_wrapper(tmp_path):
    base_path = tmp_path / "base.png"
    wm_path = tmp_path / "wm.png"
    out_path = tmp_path / "out.png"

    _make_png(base_path, (120, 80), (255, 255, 0, 255))
    _make_png(wm_path, (30, 30), (0, 0, 0, 255))

    await apply_image_watermark(base_path, wm_path, "bottom_right", out_path)
    assert out_path.exists()
