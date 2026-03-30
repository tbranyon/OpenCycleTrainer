from __future__ import annotations

import asyncio
import threading

import pytest

from opencycletrainer.devices.device_manager import AsyncioRunner


async def _return(value):
    return value


def test_submit_executes_coroutine_and_returns_result():
    runner = AsyncioRunner()
    try:
        future = runner.submit(_return(42))
        assert future.result(timeout=1.0) == 42
    finally:
        runner.shutdown()


def test_shutdown_is_idempotent():
    runner = AsyncioRunner()
    runner.shutdown()
    runner.shutdown()  # must not raise


def test_submit_after_shutdown_raises():
    runner = AsyncioRunner()
    runner.shutdown()
    coro = _return(1)
    try:
        with pytest.raises(RuntimeError, match="closed"):
            runner.submit(coro)
    finally:
        coro.close()  # prevent unawaited-coroutine warning


def test_concurrent_shutdown_does_not_raise():
    """Two threads calling shutdown concurrently must not raise or deadlock."""
    runner = AsyncioRunner()
    errors: list[BaseException] = []

    def _shutdown():
        try:
            runner.shutdown()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    t1 = threading.Thread(target=_shutdown)
    t2 = threading.Thread(target=_shutdown)
    t1.start()
    t2.start()
    t1.join(timeout=5.0)
    t2.join(timeout=5.0)

    assert not errors, f"Concurrent shutdown raised: {errors}"
    assert not t1.is_alive(), "Thread 1 deadlocked"
    assert not t2.is_alive(), "Thread 2 deadlocked"


def test_submit_captures_loop_reference_atomically():
    """submit() must hold a stable loop reference; shutdown mid-submit must not crash."""
    runner = AsyncioRunner()
    errors: list[BaseException] = []

    async def slow():
        await asyncio.sleep(0.05)
        return 99

    def _submit():
        try:
            f = runner.submit(slow())
            f.result(timeout=2.0)
        except Exception as exc:
            # RuntimeError("closed") and CancelledError are acceptable outcomes
            if not isinstance(exc, RuntimeError) and "Cancel" not in type(exc).__name__:
                errors.append(exc)

    t = threading.Thread(target=_submit)
    t.start()
    runner.shutdown()
    t.join(timeout=5.0)

    assert not errors, f"Unexpected errors: {errors}"
    assert not t.is_alive(), "Submit thread deadlocked"
