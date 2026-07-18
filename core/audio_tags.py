import asyncio
import subprocess
from pathlib import Path
from typing import Union, List

async def apply_audio_metadata(input_path: Path, output_path: Path, title: str, artist: str, album: str, cover_path: Path = None) -> Path:
    """
    Applies ID3 metadata and optional cover art to an audio file using FFmpeg.
    """
    from core.config import FFMPEG_WIN_PATH
    ffmpeg_winget = Path(FFMPEG_WIN_PATH)
    ffmpeg_bin = str(ffmpeg_winget) if ffmpeg_winget.exists() else "ffmpeg"
    
    cmd = [ffmpeg_bin, "-y", "-i", str(input_path)]
    
    if cover_path and cover_path.exists():
        cmd.extend(["-i", str(cover_path), "-map", "0:a", "-map", "1:0", "-c", "copy", "-id3v2_version", "3"])
        cmd.extend(["-metadata:s:v", "title=Album cover", "-metadata:s:v", "comment=Cover (front)"])
    else:
        cmd.extend(["-c", "copy", "-id3v2_version", "3"])
        
    if title: cmd.extend(["-metadata", f"title={title}"])
    if artist: cmd.extend(["-metadata", f"artist={artist}"])
    if album: cmd.extend(["-metadata", f"album={album}"])
    
    cmd.append(str(output_path))
    
    try:
        await asyncio.to_thread(subprocess.run, cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        print(f"FFmpeg tag error: {e.stderr}")
        import shutil
        shutil.copy(input_path, output_path)
        
    return output_path

async def process_audio_tags(filepath: Union[Path, List[Path]], state_data: dict) -> Union[Path, List[Path]]:
    """
    Processes audio tags for single or multiple files based on the FSM state data.
    """
    if not state_data or not state_data.get('edit_tags'):
        return filepath
        
    audio_title = state_data.get('title')
    audio_performer = state_data.get('artist')
    audio_album = state_data.get('album')
    cover_path_str = state_data.get('cover_path')
    cover_path = Path(cover_path_str) if cover_path_str else None
    
    files_to_tag = filepath if isinstance(filepath, list) else [filepath]
    tagged_files = []
    
    for f in files_to_tag:
        ext = f.suffix.lower()
        if ext in ['.mp3', '.m4a', '.wav', '.opus', '.flac']:
            out_path = f.with_name(f"tagged_{f.name}")
            await apply_audio_metadata(f, out_path, audio_title, audio_performer, audio_album, cover_path)
            tagged_files.append(out_path)
        else:
            tagged_files.append(f)
            
    if cover_path and cover_path.exists():
        try:
            import shutil
            shutil.rmtree(cover_path.parent, ignore_errors=True)
        except Exception: pass
            
    return tagged_files if isinstance(filepath, list) else tagged_files[0]
