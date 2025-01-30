#!/usr/bin/env python3

import argparse
import logging

import asyncio
import sipyco.common_args as sca
from sipyco.pc_rpc import simple_server_loop
from sipyco.sync_struct import Notifier, Publisher
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

    notifier = Notifier(
        {
            "emission-button-enabled": dev._dlcpro.emission_button_enabled.get(),
            "emission": dev._dlcpro.emission.get(),
            "laser1:enabled": dev._dlcpro.laser1.enabled.get(),
            "laser1:dl:cc:current-set": dev._dlcpro.laser1.dl.cc.current_set.get(),
            "laser1:amp:cc:current-set": dev._dlcpro.laser1.amp.cc.current_set.get(),
            "laser1:dl:lock:lock-enabled": dev._dlcpro.laser1.dl.lock.lock_enabled.get(),
            "laser2:enabled": dev._dlcpro.laser2.enabled.get(),
            "laser2:dl:cc:current-set": dev._dlcpro.laser2.dl.cc.current_set.get(),
            "laser2:amp:cc:current-set": dev._dlcpro.laser2.amp.cc.current_set.get(),
            "laser2:dl:lock:lock-enabled": dev._dlcpro.laser2.dl.lock.lock_enabled.get(),
        }
    )

    def callback(subscription: Subscription, time: Timestamp, value: SubscriptionValue):
        notifier[subscription.name] = value.get()

    dev._dlcpro.emission_button_enabled.subscribe(callback)
    dev._dlcpro.emission.subscribe(callback)

    dev._dlcpro.laser1.enabled.subscribe(callback)
    dev._dlcpro.laser1.dl.cc.current_set.subscribe(callback)
    dev._dlcpro.laser1.amp.cc.current_set.subscribe(callback)
    dev._dlcpro.laser1.dl.lock.lock_enabled.subscribe(callback)

    dev._dlcpro.laser2.enabled.subscribe(callback)
    dev._dlcpro.laser2.dl.cc.current_set.subscribe(callback)
    dev._dlcpro.laser2.amp.cc.current_set.subscribe(callback)
    dev._dlcpro.laser2.dl.lock.lock_enabled.subscribe(callback)

    publisher = Publisher(notifiers={"DLCProState": notifier})

    tasks = []
    tasks.append(
        publisher.start(
            host=sca.bind_address_from_args(args),
            port=args.port - 1,
        )
    )

    # .subscribe() allows adding callbacks for value changes of parameters.
    # Subscribing to value changes requires to either regularly call .poll()
    # (which will process all currently queued up callbacks) or .run() (which
    # will continuously process callbacks and block until .stop() is called).
    async def run_dlcpro(dev):
        """Runs dev._dlcpro.run() in a background thread."""
        await dev._dlcpro.run()

    tasks.append(run_dlcpro(dev))

    try:
        logging.info("Starting publisher at port {}...".format(args.port - 1))
        asyncio.gather(*tasks)
        logging.info("Starting server at port {}...".format(args.port))
        simple_server_loop(
            {"TopticaDLCPro": dev},
            sca.bind_address_from_args(args),
            args.port,
        )

    finally:
        dev._dlcpro.stop()
        dev.close()
        # await on publisher.stop()
        asyncio.run(main=publisher.stop())


if __name__ == "__main__":
    main()
