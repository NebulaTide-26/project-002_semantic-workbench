"""启动编排：输入资源列表 + 打开器，输出逐个结果。

这一层不直接调用系统 API：opener 由入口注入。
测试时传一个假的 opener，就不会真的弹出浏览器或窗口。
"""

from __future__ import annotations

import time
from collections.abc import Callable

from app.core.models import LaunchResult, Resource, ResourceKind
from app.core.resource_check import check_resource

Opener = Callable[[Resource], None]
ProgressCallback = Callable[[int, int, Resource], None]


def run(
    resources: list[Resource],
    opener: Opener,
    *,
    url_interval: float = 0.3,
    sleep: Callable[[float], None] = time.sleep,
    progress: ProgressCallback | None = None,
) -> list[LaunchResult]:
    """按顺序启动所有启用的资源，逐个返回结果。

    - 已禁用的资源直接跳过（不产生结果）
    - 启动前逐个校验；无效的目标不调用 opener，直接记为失败
    - 连续两个 URL 之间等待 url_interval 秒（避免浏览器合并标签）
    """
    enabled = [resource for resource in resources if resource.enabled]
    total = len(enabled)
    results: list[LaunchResult] = []
    last_kind: ResourceKind | None = None

    for index, resource in enumerate(enabled, start=1):
        if progress is not None:
            progress(index, total, resource)

        started = time.perf_counter()
        reason = check_resource(resource)
        if reason is not None:
            results.append(
                LaunchResult(
                    resource=resource,
                    ok=False,
                    message=reason,
                    elapsed_ms=_elapsed_ms(started),
                )
            )
            last_kind = resource.kind
            continue

        if (
            resource.kind is ResourceKind.URL
            and last_kind is ResourceKind.URL
        ):
            sleep(url_interval)

        try:
            opener(resource)
        except Exception as exc:  # noqa: BLE001 - 每个资源的失败单独记录
            results.append(
                LaunchResult(
                    resource=resource,
                    ok=False,
                    message=_describe(exc),
                    elapsed_ms=_elapsed_ms(started),
                )
            )
        else:
            results.append(
                LaunchResult(
                    resource=resource,
                    ok=True,
                    message=_success_message(resource.kind),
                    elapsed_ms=_elapsed_ms(started),
                )
            )

        last_kind = resource.kind

    return results


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _success_message(kind: ResourceKind) -> str:
    if kind is ResourceKind.APP:
        return "已启动"
    return "已打开"


def _describe(exc: Exception) -> str:
    if isinstance(exc, FileNotFoundError):
        return "找不到目标"
    if isinstance(exc, PermissionError):
        return "没有权限"
    if isinstance(exc, OSError):
        return f"系统错误：{exc.strerror or exc}"
    return str(exc) or exc.__class__.__name__
