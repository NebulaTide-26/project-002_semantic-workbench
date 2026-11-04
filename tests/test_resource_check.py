from __future__ import annotations

from app.core.models import Resource, ResourceKind
from app.core.resource_check import check_resource, normalize_url


def _resource(kind: ResourceKind, target: str) -> Resource:
    return Resource(kind=kind, target=target)


def test_url_valid():
    assert check_resource(_resource(ResourceKind.URL, "https://example.com/a")) is None


def test_url_without_scheme_rejected():
    reason = check_resource(_resource(ResourceKind.URL, "example.com"))
    assert reason is not None and "http" in reason


def test_url_without_host_rejected():
    assert (
        check_resource(_resource(ResourceKind.URL, "https://"))
        == "URL 缺少域名"
    )


def test_url_invalid_port_rejected():
    assert (
        check_resource(_resource(ResourceKind.URL, "https://example.com:abc"))
        == "URL 端口无效"
    )


def test_empty_target_rejected():
    assert check_resource(_resource(ResourceKind.URL, "   ")) == "目标为空"


def test_file_ok(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("x", encoding="utf-8")
    assert check_resource(_resource(ResourceKind.FILE, str(path))) is None


def test_file_missing(tmp_path):
    assert (
        check_resource(_resource(ResourceKind.FILE, str(tmp_path / "nope.txt")))
        == "文件不存在"
    )


def test_file_but_directory(tmp_path):
    folder = tmp_path / "folder"
    folder.mkdir()
    assert (
        check_resource(_resource(ResourceKind.FILE, str(folder)))
        == "这不是文件"
    )


def test_folder_ok(tmp_path):
    assert check_resource(_resource(ResourceKind.FOLDER, str(tmp_path))) is None


def test_folder_but_file(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("x", encoding="utf-8")
    assert (
        check_resource(_resource(ResourceKind.FOLDER, str(path)))
        == "这不是文件夹"
    )


def test_app_missing(tmp_path):
    assert (
        check_resource(_resource(ResourceKind.APP, str(tmp_path / "app.exe")))
        == "程序不存在"
    )


def test_app_wrong_suffix_rejected(tmp_path):
    path = tmp_path / "script.txt"
    path.write_text("x", encoding="utf-8")
    reason = check_resource(_resource(ResourceKind.APP, str(path)))
    assert reason is not None and ".exe" in reason


def test_app_exe_ok(tmp_path):
    path = tmp_path / "app.exe"
    path.write_text("x", encoding="utf-8")
    assert check_resource(_resource(ResourceKind.APP, str(path))) is None


def test_normalize_url_equivalent_forms():
    assert normalize_url("https://Example.COM") == normalize_url(
        "https://example.com/"
    )
    assert normalize_url("http://example.com:80/a") == normalize_url(
        "http://example.com/a"
    )
    assert normalize_url("https://example.com/a#section") == normalize_url(
        "https://example.com/a"
    )


def test_normalize_url_keeps_path_and_query():
    assert normalize_url("https://example.com/a") != normalize_url(
        "https://example.com/b"
    )
    assert normalize_url("https://example.com/a?x=1") != normalize_url(
        "https://example.com/a?x=2"
    )


def test_relative_path_rejected():
    assert (
        check_resource(_resource(ResourceKind.FILE, "relative.txt"))
        == "请使用绝对路径"
    )
