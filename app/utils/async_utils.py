import asyncio
import logging
import threading

logger = logging.getLogger(__name__)

_main_loop: asyncio.AbstractEventLoop | None = None
_main_thread_id: int | None = None


def init_event_loop():
    """Must be called once from an async context at application startup."""
    global _main_loop, _main_thread_id
    _main_loop = asyncio.get_running_loop()
    _main_thread_id = threading.current_thread().ident


def fire_and_forget(coro):
    """Schedule a coroutine for execution regardless of the calling thread.

    When called from the event-loop thread, behaves like
    ``asyncio.ensure_future``.  When called from a worker thread (e.g.
    FastAPI's default threadpool for ``def`` handlers), safely schedules
    the coroutine on the main event loop via ``run_coroutine_threadsafe``.
    """
    if _main_loop is None:
        logger.warning("fire_and_forget called before init_event_loop; coroutine dropped")
        return

    if threading.current_thread().ident == _main_thread_id:
        asyncio.ensure_future(coro)
    elif _main_loop.is_running():
        asyncio.run_coroutine_threadsafe(coro, _main_loop)
    else:
        logger.warning("Event loop is not running; coroutine dropped")
