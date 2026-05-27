"""Write content to a file on the filesystem."""

from pathlib import Path


async def write_file(path: str, content: str) -> bool:
    """Write content to a file. Creates parent directories if needed."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
    return True
