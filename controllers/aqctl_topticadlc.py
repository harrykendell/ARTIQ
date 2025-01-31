#!/usr/bin/env python3

import asyncio
import argparse
import atexit
import logging

import sipyco.common_args as sca
from sipyco.pc_rpc import Server as RPCServer
from sipyco.sync_struct import Notifier, Publisher
from sipyco.asyncio_tools import atexit_register_coroutine, SignalHandler
from driver_topticadlc import TopticaDLCPro
from toptica.lasersdk.client import (
    Subscription,
    Timestamp,
    SubscriptionValue,
)


def get_argparser():
    parser = argparse.ArgumentParser(description="ARTIQ controller for Toptica DLCPro")
    parser.add_argument(
        "-ip",
        "--ip_address",
        default="192.168.0.4",
        help="IP address of the Toptica DLCPro",
    )

    sca.simple_network_args(parser, 3272)
    sca.verbosity_args(parser)

    return parser


def main():
    args = get_argparser().parse_args()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    atexit.register(loop.close)
    signal_handler = SignalHandler()
    signal_handler.setup()
    atexit.register(signal_handler.teardown)
    signal_handler_task = loop.create_task(signal_handler.wait_terminate())
    bind = sca.bind_address_from_args(args)
    sca.init_logger_from_args(args)

    logging.info(
        "Trying to establish connection "
        "to Toptica DLCPro at {}...".format(args.ip_address)
    )
    dev = TopticaDLCPro(
        ip=args.ip_address,
        rpc=True,
    )
    dev.open()
    logging.info("Established connection.")

    rpc = RPCServer({"TopticaDLCPro": dev}, allow_parallel=True)
    loop.run_until_complete(rpc.start(bind, args.port))
    atexit_register_coroutine(rpc.stop, loop=loop)

    notifier = Notifier(
        {
            "emission-button-enabled": dev._dlcpro.emission_button_enabled.get(),
            "emission": dev._dlcpro.emission.get(),
            "laser1:label": dev._dlcpro.laser1.label.get(),
            "laser1:enabled": dev._dlcpro.laser1.enabled.get(),
            "laser1:dl:cc:current-set": dev._dlcpro.laser1.dl.cc.current_set.get(),
            "laser1:amp:cc:current-set": dev._dlcpro.laser1.amp.cc.current_set.get(),
            "laser1:dl:lock:lock-enabled": dev._dlcpro.laser1.dl.lock.lock_enabled.get(),
            "laser2:label": dev._dlcpro.laser2.label.get(),
            "laser2:enabled": dev._dlcpro.laser2.enabled.get(),
            "laser2:dl:cc:current-set": dev._dlcpro.laser2.dl.cc.current_set.get(),
            "laser2:amp:cc:current-set": dev._dlcpro.laser2.amp.cc.current_set.get(),
            "laser2:dl:lock:lock-enabled": dev._dlcpro.laser2.dl.lock.lock_enabled.get(),
        }
    )

    def callback(subscription: Subscription, time: Timestamp, value: SubscriptionValue):
        logging.debug(f"Callback: {subscription.name} = {value.get()}")
        notifier[subscription.name] = value.get()

    dev._dlcpro.emission_button_enabled.subscribe(callback)
    dev._dlcpro.emission.subscribe(callback)

    dev._dlcpro.laser1.label.subscribe(callback)
    dev._dlcpro.laser1.enabled.subscribe(callback)
    dev._dlcpro.laser1.dl.cc.current_set.subscribe(callback)
    dev._dlcpro.laser1.amp.cc.current_set.subscribe(callback)
    dev._dlcpro.laser1.dl.lock.lock_enabled.subscribe(callback)

    dev._dlcpro.laser2.label.subscribe(callback)
    dev._dlcpro.laser2.enabled.subscribe(callback)
    dev._dlcpro.laser2.dl.cc.current_set.subscribe(callback)
    dev._dlcpro.laser2.amp.cc.current_set.subscribe(callback)
    dev._dlcpro.laser2.dl.lock.lock_enabled.subscribe(callback)

    publisher = Publisher(notifiers={"DLCProState": notifier})
    loop.run_until_complete(publisher.start(bind, args.port - 1))
    atexit_register_coroutine(publisher.stop, loop=loop)

    # .subscribe() allows adding callbacks for value changes of parameters.
    # Subscribing to value changes requires to either regularly call .poll()
    # (which will process all currently queued up callbacks) or .run() (which
    # will continuously process callbacks and block until .stop() is called).
    async def run():
        while True:
            dev._dlcpro.poll()
            await asyncio.sleep(0.1)

    run_task = loop.create_task(run())
    atexit.register(run_task.cancel)

    try:
        loop.run_until_complete(signal_handler_task)
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    main()
