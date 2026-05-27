"""Read a file from the filesystem."""

from pathlib import Path


async def read_file(path: str, encoding: str = "utf-8") -> str:
    """Read file content."""
    file_path = Path(path)
    if not file_path.exists():
        return f"Error: File not found: {path}"
    return file_path.read_text(encoding=encoding)
