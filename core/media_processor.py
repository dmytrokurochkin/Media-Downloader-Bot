import asyncio
from pathlib import Path
from typing import Union, List

async def process_watermarks(filepath: Union[Path, List[Path]], user: dict, bot, session_dir: Path) -> Union[Path, List[Path]]:
    """
    Applies watermarks to videos and images if the user is in the 'Max' tier and has a watermark set.
    Returns the paths to the watermarked files (or original if no watermark applied).
    """
    if user.get('tier') != 'Max' or not user.get('watermark_file_id'):
        return filepath
        
    watermark_file_id = user['watermark_file_id']
    watermark_pos = user.get('watermark_position', 'bottom_right')
    
    watermark_path = session_dir / f"watermark_{watermark_file_id}.png"
    
    try:
        from core.watermark import apply_video_watermark, apply_image_watermark
        await bot.download(watermark_file_id, destination=watermark_path)
        
        files_to_watermark = filepath if isinstance(filepath, list) else [filepath]
        watermarked_files = []
        
        for f in files_to_watermark:
            ext = f.suffix.lower()
            if ext in ['.mp4', '.mkv', '.webm']:
                out_path = f.with_name(f"wm_{f.name}")
                await apply_video_watermark(f, watermark_path, watermark_pos, out_path)
                watermarked_files.append(out_path)
            elif ext in ['.jpg', '.jpeg', '.png', '.webp']:
                out_path = f.with_name(f"wm_{f.name}")
                await apply_image_watermark(f, watermark_path, watermark_pos, out_path)
                watermarked_files.append(out_path)
            else:
                watermarked_files.append(f)
                
        return watermarked_files if isinstance(filepath, list) else watermarked_files[0]
    except Exception as wm_e:
        print(f"Watermark error: {wm_e}")
        return filepath
