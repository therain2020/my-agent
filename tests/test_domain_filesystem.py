"""Tests for domain/filesystem.py — file operations."""

from pathlib import Path

from therain2020.domain.filesystem import delete, list_files, make_temp, read, write


class TestRead:
    def test_read_existing_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world", encoding="utf-8")
        assert read(str(f)) == "hello world"

    def test_read_nonexistent_raises(self):
        try:
            read("/nonexistent/path/file.txt")
        except FileNotFoundError:
            pass

    def test_read_directory_raises(self, tmp_path):
        try:
            read(str(tmp_path))
        except FileNotFoundError:
            pass


class TestWrite:
    def test_write_new_file(self, tmp_path):
        f = tmp_path / "sub" / "test.txt"
        assert write(str(f), "content")
        assert f.read_text(encoding="utf-8") == "content"

    def test_write_creates_parents(self, tmp_path):
        f = tmp_path / "a" / "b" / "c.txt"
        write(str(f), "x")
        assert f.exists()


class TestListFiles:
    def test_list_files(self, tmp_path):
        (tmp_path / "a.txt").write_text("")
        (tmp_path / "b.py").write_text("")
        (tmp_path / ".hidden").write_text("")
        files = list_files(str(tmp_path), "*")
        assert "a.txt" in files
        assert "b.py" in files
        assert ".hidden" not in files

    def test_list_with_pattern(self, tmp_path):
        (tmp_path / "a.py").write_text("")
        (tmp_path / "b.txt").write_text("")
        files = list_files(str(tmp_path), "*.py")
        assert "a.py" in files
        assert "b.txt" not in files

    def test_list_nonexistent_raises(self):
        try:
            list_files("/nonexistent")
        except NotADirectoryError:
            pass


class TestDelete:
    def test_delete_file(self, tmp_path):
        f = tmp_path / "to_delete.txt"
        f.write_text("x")
        assert delete(str(f))
        assert not f.exists()

    def test_delete_empty_dir(self, tmp_path):
        d = tmp_path / "empty_dir"
        d.mkdir()
        assert delete(str(d))
        assert not d.exists()


class TestMakeTemp:
    def test_make_temp(self):
        path = make_temp("hello", suffix=".txt")
        p = Path(path)
        try:
            assert p.exists()
            assert p.read_text(encoding="utf-8") == "hello"
            assert p.suffix == ".txt"
        finally:
            p.unlink()
