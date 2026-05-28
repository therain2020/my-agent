"""Tests for _ipc.py — browser-harness IPC helpers."""


from therain2020._ipc import _read_port_file, _sock_path


def test_sock_path_posix():
    path = _sock_path("default")
    assert "bu-default" in str(path)


def test_read_port_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("therain2020._ipc._RUNTIME", tmp_path)
    port, token = _read_port_file("test")
    assert port is None
    assert token is None
