"""Run untrusted-file parsing in a child process with a wall-clock timeout and memory cap."""

import multiprocessing as mp
import resource
import sys
from collections.abc import Callable
from multiprocessing.connection import Connection
from typing import Any

from backend.core.errors import InvalidFile

_ctx = mp.get_context("spawn")


def _child(conn: Connection, mem_mb: int, fn: Callable[..., Any], args: tuple[Any, ...]) -> None:
    try:
        # shortcut: macOS ignores RLIMIT_AS; the timeout is the only hard guard there. Linux (Docker) enforces it.
        if sys.platform != "darwin":
            limit = mem_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
        conn.send(("ok", fn(*args)))
    except InvalidFile as e:
        conn.send(("invalid", (e.code, e.message)))
    except MemoryError:
        conn.send(("invalid", ("too_complex", "This file needs more memory to read than allowed.")))
    except Exception as e:  # noqa: BLE001 - any parser crash on untrusted input is a file problem
        conn.send(("invalid", ("parse_failed", f"The file couldn't be read ({type(e).__name__}).")))
    finally:
        conn.close()


def run_sandboxed(fn: Callable[..., Any], *args: Any, timeout_s: float, mem_mb: int) -> Any:
    """Call fn(*args) in a fresh process. fn and its result must be picklable."""
    parent, child = _ctx.Pipe(duplex=False)
    proc = _ctx.Process(target=_child, args=(child, mem_mb, fn, args), daemon=True)
    proc.start()
    child.close()
    try:
        if not parent.poll(timeout_s):
            raise InvalidFile("parse_timeout", f"Reading this file took longer than {int(timeout_s)} s.")
        try:
            kind, payload = parent.recv()
        except EOFError:
            raise InvalidFile("parse_crashed", "The file crashed the reader. It may be damaged.") from None
    finally:
        parent.close()
        if proc.is_alive():
            proc.kill()
        proc.join(5)
    if kind == "invalid":
        raise InvalidFile(*payload)
    return payload
