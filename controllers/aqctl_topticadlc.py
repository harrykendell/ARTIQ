#!/usr/bin/env python3

import argparse
import logging

import sipyco.common_args as sca
from sipyco.pc_rpc import simple_server_loop
from sipyco.remote_exec import simple_rexec_server_loop

from driver_topticadlc import TopticaDLCPro


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
    )
    dev.open()
    logging.info("Established connection.")

    try:
        logging.info("Starting server at port {}...".format(args.port))
        simple_rexec_server_loop(
            "TopticaDLCPro",dev, sca.bind_address_from_args(args), args.port
        )

    finally:
        dev.close()


if __name__ == "__main__":
    main()
