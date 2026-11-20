#!/usr/bin/env python3
"""ARTIQ-managed Pico USB TC-08 controller (loopback-only Sipyco RPC).

Start/stop is owned by artiq_ctlmgr. The sampler and seven-day SQLite history
are part of this controller, not a website-side background service.
"""
from __future__ import annotations

import argparse
import asyncio
import fcntl
import ipaddress
import logging
import os
import signal
from pathlib import Path

from temperature_logger.acquisition import TemperatureController
from temperature_logger.store import TemperatureStore

log = logging.getLogger(__name__)
DEFAULT_DB = str(Path.home() / ".local" / "state" / "artiq-temperature" / "history.sqlite3")


async def run_controller(db_path, *, bind="127.0.0.1", port=3273, interval=5.0,
                         driver_factory=None):
    """Start one hardware owner and expose recorded data by ARTIQ RPC."""
    from sipyco.pc_rpc import Server as RPCServer

    # Configuration RPC has no independent authentication: never publish it
    # on an externally reachable interface. The Worker authenticates users.
    if not ipaddress.ip_address(bind).is_loopback:
        raise ValueError("TC-08 controller must bind to a loopback address")
    db_directory = Path(db_path).parent
    db_directory.mkdir(parents=True, exist_ok=True)
    owner_fd = os.open(str(db_directory / "owner.lock"),
                       os.O_CREAT | os.O_RDWR, 0o600)
    try:
        # Own the database before running any schema changes or CJC backfill.
        fcntl.flock(owner_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        store = TemperatureStore(db_path)
        stop = asyncio.Event()
        options = {"stop": stop, "interval": interval}
        if driver_factory is not None:
            options["driver_factory"] = driver_factory
        controller = TemperatureController(store, **options)
        server = RPCServer({"temperature_logger": controller}, allow_parallel=True)
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(signum, stop.set)
            except (NotImplementedError, RuntimeError):
                pass
        await server.start(bind, port)
        sample_task = asyncio.create_task(controller._acquisition(), name="tc08-acquisition")
        stop_task = asyncio.create_task(stop.wait(), name="tc08-controller-stop")
        log.info("TC-08 ARTIQ controller listening at %s:%d", bind, port)
        try:
            completed, _ = await asyncio.wait(
                (sample_task, stop_task), return_when=asyncio.FIRST_COMPLETED)
            if sample_task in completed:
                sample_task.result()
                if not stop.is_set():
                    raise RuntimeError("TC-08 acquisition stopped unexpectedly")
        finally:
            controller.terminate()
            stop_task.cancel()
            # Normally finish the in-flight Pico SDK read before closing its
            # handle: cancelling asyncio.to_thread() does not stop the worker.
            try:
                await asyncio.wait_for(sample_task, timeout=15)
            except TimeoutError:
                log.error("TC-08 read did not stop within 15s; forcing shutdown")
            except asyncio.CancelledError:
                pass
            finally:
                await asyncio.gather(stop_task, return_exceptions=True)
                await server.stop()
    finally:
        os.close(owner_fd)


def main():
    parser = argparse.ArgumentParser(description="ARTIQ Pico TC-08 controller")
    parser.add_argument("-p", "--port", type=int, default=3273)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--db", default=os.getenv("ARTIQ_TEMPERATURE_DB", DEFAULT_DB))
    parser.add_argument("--interval", type=float, default=5.0)
    args = parser.parse_args()
    if not 1 <= args.interval <= 60:
        parser.error("--interval must be 1-60 seconds")
    try:
        if not ipaddress.ip_address(args.bind).is_loopback:
            parser.error("--bind must be a loopback IP address")
    except ValueError:
        parser.error("--bind must be a loopback IP address")
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(run_controller(args.db, bind=args.bind, port=args.port,
                               interval=args.interval))


if __name__ == "__main__":
    main()
