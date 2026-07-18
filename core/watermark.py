import asyncio
import os
from pathlib import Path
from PIL import Image

def _get_overlay_coords(position: str, padding: int = 10) -> str:
    if position == 'top_left':
        return f"{padding}:{padding}"
    elif position == 'top_right':
        return f"W-w-{padding}:{padding}"
    elif position == 'bottom_left':
        return f"{padding}:H-h-{padding}"
    elif position == 'bottom_right':
        return f"W-w-{padding}:H-h-{padding}"
    else:
        return f"W-w-{padding}:H-h-{padding}"

async def apply_video_watermark(input_video_path: Path, watermark_path: Path, position: str, output_path: Path):
    padding = 10
    coords = _get_overlay_coords(position, padding)
    # Using scale2ref to scale the watermark to 15% of the video width
    filter_complex = f"[1:v][0:v]scale2ref=w='max(main_w*0.15,10)':h='ow/a'[wm][vid];[vid][wm]overlay={coords}"

    from core.config import FFMPEG_WIN_PATH
    ffmpeg_bin = "ffmpeg"
    if Path(FFMPEG_WIN_PATH).exists():
        ffmpeg_bin = FFMPEG_WIN_PATH

    cmd = [
        str(ffmpeg_bin), "-y",
        "-i", str(input_video_path),
        "-i", str(watermark_path),
        "-filter_complex", filter_complex,
        "-c:a", "copy",
        str(output_path)
    ]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    
    if process.returncode != 0:
        raise Exception(f"FFmpeg watermark error: {stderr.decode()}")

def apply_image_watermark_sync(input_image_path: Path, watermark_path: Path, position: str, output_path: Path):
    with Image.open(input_image_path) as base_img:
        base_img = base_img.convert("RGBA")
        with Image.open(watermark_path) as wm_img:
            wm_img = wm_img.convert("RGBA")
            
            target_wm_width = max(int(base_img.width * 0.15), 10)
            wm_ratio = target_wm_width / wm_img.width
            target_wm_height = int(wm_img.height * wm_ratio)
            
            wm_resized = wm_img.resize((target_wm_width, target_wm_height), Image.Resampling.LANCZOS)
            
            padding = 10
            
            if position == 'top_left':
                x, y = padding, padding
            elif position == 'top_right':
                x, y = base_img.width - target_wm_width - padding, padding
            elif position == 'bottom_left':
                x, y = padding, base_img.height - target_wm_height - padding
            elif position == 'bottom_right':
                x, y = base_img.width - target_wm_width - padding, base_img.height - target_wm_height - padding
            else:
                x, y = base_img.width - target_wm_width - padding, base_img.height - target_wm_height - padding
                
            transparent = Image.new("RGBA", base_img.size, (0, 0, 0, 0))
            transparent.paste(wm_resized, (x, y), wm_resized)
            
            result = Image.alpha_composite(base_img, transparent)
            
            if input_image_path.suffix.lower() in ['.jpg', '.jpeg']:
                result = result.convert("RGB")
            
            result.save(output_path, quality=95)

async def apply_image_watermark(input_image_path: Path, watermark_path: Path, position: str, output_path: Path):
    await asyncio.to_thread(apply_image_watermark_sync, input_image_path, watermark_path, position, output_path)
