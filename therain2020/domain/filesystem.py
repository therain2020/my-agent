"""Filesystem domain tools — read, write, list, delete."""

from pathlib import Path


def read(path: str) -> str:
    """Read file contents. Auto-detects encoding."""
    p = Path(path).expanduser()
    if not p.is_file():
        raise FileNotFoundError(f"Not a file: {path}")
    try:
        return p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return p.read_text(encoding="latin-1")


def write(path: str, content: str) -> bool:
    """Write content to a file. Creates parent directories."""
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return True


def list_files(dir: str = ".", pattern: str = "*") -> list[str]:
    """List files in a directory matching pattern."""
    p = Path(dir).expanduser()
    if not p.is_dir():
        raise NotADirectoryError(str(dir))
    return sorted(
        str(f.relative_to(p))
        for f in p.glob(pattern)
        if not f.name.startswith(".")
    )


def delete(path: str) -> bool:
    """Delete a file. Fails on non-empty directories."""
    p = Path(path).expanduser()
    if p.is_dir():
        p.rmdir()
    else:
        p.unlink()
    return True


def make_temp(content: str, suffix: str = "") -> str:
    """Create a temporary file and return its path."""
    import tempfile
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=suffix, delete=False, encoding="utf-8",
    ) as f:
        f.write(content)
        return f.name
