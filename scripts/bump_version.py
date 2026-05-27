"""Bump project version. Usage: python scripts/bump_version.py [major|minor|patch]"""

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
PYPROJECT = PROJECT_ROOT / "pyproject.toml"
INIT_FILE = PROJECT_ROOT / "agent" / "__init__.py"


def get_current_version() -> tuple[int, int, int]:
    content = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r'version\s*=\s*"(\d+)\.(\d+)\.(\d+)"', content)
    if not match:
        raise ValueError("Version not found in pyproject.toml")
    return int(match[1]), int(match[2]), int(match[3])


def bump(current: tuple[int, int, int], part: str) -> tuple[int, int, int]:
    major, minor, patch = current
    if part == "major":
        return (major + 1, 0, 0)
    elif part == "minor":
        return (major, minor + 1, 0)
    elif part == "patch":
        return (major, minor, patch + 1)
    else:
        raise ValueError(f"Invalid bump part: {part}. Use major/minor/patch")


def update_pyproject(old_ver: str, new_ver: str) -> None:
    content = PYPROJECT.read_text(encoding="utf-8")
    content = content.replace(f'version = "{old_ver}"', f'version = "{new_ver}"')
    PYPROJECT.write_text(content, encoding="utf-8")


def update_init(old_ver: str, new_ver: str) -> None:
    content = INIT_FILE.read_text(encoding="utf-8")
    content = content.replace(f'__version__ = "{old_ver}"', f'__version__ = "{new_ver}"')
    INIT_FILE.write_text(content, encoding="utf-8")


def main():
    part = sys.argv[1] if len(sys.argv) > 1 else "patch"
    current = get_current_version()
    old_ver = f"{current[0]}.{current[1]}.{current[2]}"
    new = bump(current, part)
    new_ver = f"{new[0]}.{new[1]}.{new[2]}"

    update_pyproject(old_ver, new_ver)
    update_init(old_ver, new_ver)

    print(f"Bumped: {old_ver} → {new_ver}")
    print(f"Next steps:")
    print(f"  git add pyproject.toml agent/__init__.py")
    print(f'  git commit -m "Bump version to {new_ver}"')
    print(f"  git tag v{new_ver}")
    print(f"  git push origin master --tags")


if __name__ == "__main__":
    main()
