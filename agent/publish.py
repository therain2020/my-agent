"""Package publisher. 类比: dpkg-buildpackage + PPA.

Publishes tools/roles/dont-do as standard packages to GitHub Releases.
"""

import json
import tarfile
from pathlib import Path

import structlog
import yaml

logger = structlog.get_logger()

PACKAGE_FILE = "therain2020-package.yaml"

PACKAGE_TEMPLATE = """\
# therain2020-package.yaml
name: {name}
version: "0.1.0"
type: tool              # tool | role | dont-do | bundle
description: "TODO: describe your {name}"
author: "TODO: your name"
license: MIT
dependencies:
  tools: []
entry: tool.md          # or role.md or dont-do.md
"""


def init_package(name: str, package_type: str = "tool", directory: str = "") -> Path:
    """Initialize a new package directory. 类比: dh_make."""
    pkg_dir = Path(directory) if directory else Path(name)
    pkg_dir.mkdir(parents=True, exist_ok=True)

    # Write package manifest
    manifest = PACKAGE_TEMPLATE.format(name=name)
    (pkg_dir / PACKAGE_FILE).write_text(manifest, encoding="utf-8")

    # Write stub tool.md
    entry_file = f"{package_type.rstrip('s')}.md"
    (pkg_dir / entry_file).write_text(
        f"# {name}\n\nTODO: describe your {package_type}.\n", encoding="utf-8"
    )

    logger.info("package_init", name=name, dir=str(pkg_dir), type=package_type)
    return pkg_dir


def validate_package(pkg_dir: Path) -> list[str]:
    """Validate a package directory. Returns list of issues (empty = valid)."""
    issues = []

    manifest_path = pkg_dir / PACKAGE_FILE
    if not manifest_path.exists():
        issues.append(f"Missing {PACKAGE_FILE}")
        return issues

    try:
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        issues.append(f"Invalid YAML in {PACKAGE_FILE}: {e}")
        return issues

    required = ["name", "version", "type"]
    for key in required:
        if key not in data:
            issues.append(f"Missing required field: {key}")

    entry = data.get("entry", "")
    if entry and not (pkg_dir / entry).exists():
        issues.append(f"Entry file not found: {entry}")

    return issues


def build_package(pkg_dir: Path, output_dir: str = "dist") -> Path:
    """Build a .tar.gz package. 类比: dpkg-buildpackage."""
    issues = validate_package(pkg_dir)
    if issues:
        raise ValueError("Package validation failed:\n" + "\n".join(f"  - {i}" for i in issues))

    data = yaml.safe_load((pkg_dir / PACKAGE_FILE).read_text(encoding="utf-8"))
    name = data["name"]
    version = data["version"]

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    archive_path = output_path / f"{name}-{version}.tar.gz"

    with tarfile.open(archive_path, "w:gz") as tar:
        for f in pkg_dir.iterdir():
            tar.add(f, arcname=f"{name}/{f.name}")

    logger.info("package_built", name=name, version=version, path=str(archive_path))
    return archive_path


def install_package(archive_path: Path, target_dir: str = "tools/.generated") -> str:
    """Install a .tar.gz package. 类比: dpkg -i."""
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)

    with tarfile.open(archive_path, "r:gz") as tar:
        # Get package name from root dir in archive
        root = tar.getnames()[0].split("/")[0]
        tar.extractall(target)

    installed = target / root
    logger.info("package_installed", name=root, path=str(installed))
    return root


def install_from_github(repo: str, target_dir: str = "tools/.generated") -> str | None:
    """Download and install from GitHub Releases. 类比: apt-get install.

    Usage: install_from_github("therain2020/deploy-k8s")
    Downloads latest release asset .tar.gz.
    """
    import tempfile
    import urllib.request

    api_url = f"https://api.github.com/repos/{repo}/releases/latest"
    try:
        req = urllib.request.Request(api_url)
        req.add_header("Accept", "application/vnd.github+json")
        with urllib.request.urlopen(req, timeout=15) as resp:
            release = json.loads(resp.read())

        # Find .tar.gz asset
        asset = None
        for a in release.get("assets", []):
            if a["name"].endswith(".tar.gz"):
                asset = a
                break

        if not asset:
            logger.warning("no_tarball_asset", repo=repo)
            return None

        # Download
        tmp = Path(tempfile.mkdtemp()) / asset["name"]
        urllib.request.urlretrieve(asset["browser_download_url"], tmp)

        return install_package(tmp, target_dir)
    except Exception as e:
        logger.error("github_install_failed", repo=repo, error=str(e))
        return None
