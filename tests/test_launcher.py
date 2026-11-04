from __future__ import annotations

from app.core import launcher
from app.core.models import Resource, ResourceKind


def _resource(
    kind: ResourceKind, target: str, enabled: bool = True
) -> Resource:
    return Resource(kind=kind, target=target, enabled=enabled)


def test_run_skips_disabled(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("x", encoding="utf-8")
    resources = [
        _resource(ResourceKind.URL, "https://example.com"),
        _resource(ResourceKind.FILE, str(path)),
        _resource(ResourceKind.FILE, str(path), enabled=False),
    ]

    calls = []
    results = launcher.run(resources, calls.append, sleep=lambda _: None)

    assert len(results) == 2
    assert [result.ok for result in results] == [True, True]
    assert len(calls) == 2
    assert results[0].resource.kind is ResourceKind.URL
    assert results[0].message == "已打开"


def test_invalid_resource_not_opened(tmp_path):
    resources = [_resource(ResourceKind.FILE, str(tmp_path / "missing.txt"))]

    calls = []
    results = launcher.run(resources, calls.append, sleep=lambda _: None)

    assert len(results) == 1
    assert results[0].ok is False
    assert results[0].message == "文件不存在"
    assert calls == []


def test_opener_exception_is_reported(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("x", encoding="utf-8")

    def boom(_resource: Resource) -> None:
        raise PermissionError("denied")

    results = launcher.run(
        [_resource(ResourceKind.FILE, str(path))], boom, sleep=lambda _: None
    )

    assert results[0].ok is False
    assert results[0].message == "没有权限"


def test_url_interval_between_consecutive_urls(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("x", encoding="utf-8")
    resources = [
        _resource(ResourceKind.URL, "https://a.example"),
        _resource(ResourceKind.URL, "https://b.example"),
        _resource(ResourceKind.FILE, str(path)),
        _resource(ResourceKind.URL, "https://c.example"),
    ]

    sleeps: list[float] = []
    launcher.run(resources, lambda _: None, sleep=sleeps.append)

    # 只有连续两个 URL 之间等待；文件打断后不再等待
    assert sleeps == [0.3]


def test_progress_callback_order(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("x", encoding="utf-8")
    resources = [
        _resource(ResourceKind.FILE, str(path)),
        _resource(ResourceKind.FILE, str(path), enabled=False),
        _resource(ResourceKind.URL, "https://a.example"),
    ]

    seen: list[tuple[int, int, str]] = []
    launcher.run(
        resources,
        lambda _: None,
        sleep=lambda _: None,
        progress=lambda index, total, resource: seen.append(
            (index, total, resource.target)
        ),
    )

    assert seen == [
        (1, 2, str(path)),
        (2, 2, "https://a.example"),
    ]


def test_elapsed_ms_is_recorded(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("x", encoding="utf-8")

    results = launcher.run(
        [_resource(ResourceKind.FILE, str(path))],
        lambda _: None,
        sleep=lambda _: None,
    )

    assert results[0].elapsed_ms >= 0
