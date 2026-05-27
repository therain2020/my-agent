"""Tests for package publishing."""

import tempfile
from pathlib import Path

from agent.publish import (
    build_package,
    init_package,
    install_package,
    validate_package,
)


class TestPublish:
    def test_init_creates_files(self):
        d = tempfile.mkdtemp()
        try:
            pkg = init_package("my-tool", package_type="tool", directory=d)
            assert (pkg / "therain2020-package.yaml").exists()
            assert (pkg / "tool.md").exists()
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def test_validate_valid_package(self):
        d = tempfile.mkdtemp()
        try:
            pkg = init_package("test-pkg", directory=d)
            issues = validate_package(pkg)
            assert issues == []
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def test_validate_missing_manifest(self):
        d = tempfile.mkdtemp()
        try:
            pkg_dir = Path(d)
            issues = validate_package(pkg_dir)
            assert len(issues) > 0
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def test_build_and_install(self):
        d = tempfile.mkdtemp()
        try:
            pkg = init_package("my-pkg", directory=d)
            archive = build_package(pkg, output_dir=d)
            assert archive.exists()
            assert archive.name.endswith(".tar.gz")

            # Install
            installed = install_package(archive, target_dir=d)
            assert installed == "my-pkg"
            assert (Path(d) / "my-pkg" / "tool.md").exists()
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    def test_build_rejects_invalid(self):
        d = tempfile.mkdtemp()
        try:
            pkg_dir = Path(d)
            (pkg_dir / "therain2020-package.yaml").write_text(
                "name: bad\nversion: 1", encoding="utf-8"
            )
            import pytest
            with pytest.raises(ValueError, match="Missing required field"):
                build_package(pkg_dir)
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)
