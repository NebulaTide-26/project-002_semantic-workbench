from __future__ import annotations

import os
import struct
import subprocess

import pytest

from app.adapters import os_open
from app.core.models import Resource, ResourceKind


def _fake_pe(subsystem: int) -> bytes:
    data = bytearray(512)
    data[0:2] = b"MZ"
    pe_offset = 64
    struct.pack_into("<I", data, 0x3C, pe_offset)
    data[pe_offset : pe_offset + 4] = b"PE\0\0"
    struct.pack_into("<H", data, pe_offset + 24 + 68, subsystem)
    return bytes(data)


def _capture_startfile(monkeypatch) -> list[tuple[str, dict]]:
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        os,
        "startfile",
        lambda target, **kwargs: calls.append((target, kwargs)),
        raising=False,
    )
    return calls


def test_pe_subsystem_console(tmp_path):
    path = tmp_path / "tool.exe"
    path.write_bytes(_fake_pe(3))
    assert os_open.pe_subsystem(path) == 3


def test_pe_subsystem_gui(tmp_path):
    path = tmp_path / "tool.exe"
    path.write_bytes(_fake_pe(2))
    assert os_open.pe_subsystem(path) == 2


def test_pe_subsystem_non_pe(tmp_path):
    path = tmp_path / "note.txt"
    path.write_text("hello", encoding="utf-8")
    assert os_open.pe_subsystem(path) is None


def test_console_app_gets_new_console(tmp_path, monkeypatch):
    path = tmp_path / "tool.exe"
    path.write_bytes(_fake_pe(3))

    calls = []
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda args, **kwargs: calls.append((args, kwargs)),
    )

    os_open.open_resource(
        Resource(kind=ResourceKind.APP, target=str(path), args=["--x"]),
        cwd=str(tmp_path),
    )

    assert calls[0][0] == [str(path), "--x"]
    assert calls[0][1]["creationflags"] == subprocess.CREATE_NEW_CONSOLE
    assert calls[0][1]["cwd"] == str(tmp_path)
    assert calls[0][1]["startupinfo"] is None


def test_gui_app_keeps_default_flags(tmp_path, monkeypatch):
    path = tmp_path / "tool.exe"
    path.write_bytes(_fake_pe(2))

    calls = []
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda args, **kwargs: calls.append((args, kwargs)),
    )

    os_open.open_resource(
        Resource(kind=ResourceKind.APP, target=str(path)),
        cwd=str(tmp_path),
    )

    assert calls[0][1]["creationflags"] == 0


def test_console_app_maximize_sets_startupinfo(tmp_path, monkeypatch):
    path = tmp_path / "tool.exe"
    path.write_bytes(_fake_pe(3))

    calls = []
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda args, **kwargs: calls.append((args, kwargs)),
    )

    os_open.open_resource(
        Resource(kind=ResourceKind.APP, target=str(path)), maximize=True
    )

    assert calls[0][1]["creationflags"] == subprocess.CREATE_NEW_CONSOLE
    startupinfo = calls[0][1]["startupinfo"]
    assert startupinfo is not None
    assert startupinfo.wShowWindow == 3
    assert startupinfo.dwFlags & subprocess.STARTF_USESHOWWINDOW


def test_file_uses_startfile(tmp_path, monkeypatch):
    path = tmp_path / "a.txt"
    path.write_text("x", encoding="utf-8")
    calls = _capture_startfile(monkeypatch)

    os_open.open_resource(Resource(kind=ResourceKind.FILE, target=str(path)))

    assert calls == [(str(path), {"show_cmd": 1})]


def test_file_maximize_sets_show_cmd(tmp_path, monkeypatch):
    path = tmp_path / "a.txt"
    path.write_text("x", encoding="utf-8")
    calls = _capture_startfile(monkeypatch)

    os_open.open_resource(
        Resource(kind=ResourceKind.FILE, target=str(path)), maximize=True
    )

    assert calls == [(str(path), {"show_cmd": 3})]


def test_url_uses_startfile(monkeypatch):
    calls = _capture_startfile(monkeypatch)

    os_open.open_resource(
        Resource(kind=ResourceKind.URL, target="https://example.com")
    )

    assert calls == [("https://example.com", {"show_cmd": 1})]


def test_url_maximize_sets_show_cmd(monkeypatch):
    calls = _capture_startfile(monkeypatch)

    os_open.open_resource(
        Resource(kind=ResourceKind.URL, target="https://example.com"),
        maximize=True,
    )

    assert calls == [("https://example.com", {"show_cmd": 3})]


def test_startfile_failure_raises(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("no association")

    monkeypatch.setattr(os, "startfile", boom, raising=False)

    with pytest.raises(OSError):
        os_open.open_resource(
            Resource(kind=ResourceKind.FILE, target="C:/x.txt")
        )
