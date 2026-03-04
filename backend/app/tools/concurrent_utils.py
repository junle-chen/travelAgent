"""Lightweight helpers for running blocking I/O calls concurrently."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

# Shared pool – keeps threads warm across requests.
_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="travel-io")


def parallel_call(tasks: list[tuple[Callable[..., Any], tuple[Any, ...]]]) -> list[Any]:
    """Execute *tasks* concurrently and return results **in submission order**.

    Each element is ``(callable, args_tuple)``.  If any task raises, the
    exception is propagated **after** all other tasks finish.
    """
    if not tasks:
        return []
    if len(tasks) == 1:
        fn, args = tasks[0]
        return [fn(*args)]

    futures = {_POOL.submit(fn, *args): idx for idx, (fn, args) in enumerate(tasks)}
    results: list[Any] = [None] * len(tasks)
    first_error: Exception | None = None

    for future in as_completed(futures):
        idx = futures[future]
        try:
            results[idx] = future.result()
        except Exception as exc:  # noqa: BLE001
            if first_error is None:
                first_error = exc

    if first_error is not None:
        raise first_error
    return results


def parallel_map(fn: Callable[..., Any], items: list[Any]) -> list[Any]:
    """Apply *fn* to each item concurrently, preserving order."""
    if not items:
        return []
    if len(items) == 1:
        return [fn(items[0])]
    return parallel_call([(fn, (item,)) for item in items])
