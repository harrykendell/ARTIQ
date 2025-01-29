#!/usr/bin/env python3

import argparse
import logging

import sipyco.common_args as sca
from sipyco.pc_rpc import simple_server_loop
from sipyco.sync_struct import Notifier, Publisher
from driver_topticadlc import TopticaDLCPro
from toptica.lasersdk.client import Client, NetworkConnection, DeviceNotFoundError, Subscription, Timestamp, SubscriptionValue


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
    def callback(subscription: Subscription, _: Timestamp, value: SubscriptionValue):
        notifier.set_value(subscription.name, value)

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
                 
    publisher = Publisher(notifiers={"State": notifier})
    publisher.start(
        host=sca.bind_address_from_args(args),
        port=args.port - 1,
    )

    try:
        logging.info("Starting server at port {}...".format(args.port))
        simple_server_loop(
            {"TopticaDLCPro": dev},
            sca.bind_address_from_args(args),
            args.port,
        )
    finally:
        publisher.stop()
        dev.close()


if __name__ == "__main__":
    main()
