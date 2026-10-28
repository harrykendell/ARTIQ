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
        "Trying to establish connection to Toptica DLCPro at {}...".format(
            args.ip_address
        )
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

    # Read-only DLC telemetry. The browser consumes the cached sipyco
    # publisher on port 3271; hardware commands still go to RPC port 3272.
    # Keep the historical colon-delimited keys for the existing ARTIQ GUI.
    legacy = {
        "emission_button_enabled": dev._dlcpro.emission_button_enabled,
        "emission": dev._dlcpro.emission,
    }
    for laser in ("laser1", "laser2"):
        head = getattr(dev._dlcpro, laser)
        for suffix, decop in (
            ("label", head.label),
            ("enabled", head.enabled),
            ("dl_cc_current_set", head.dl.cc.current_set),
            ("amp_cc_current_set", head.amp.cc.current_set),
            ("dl_lock_lock_enabled", head.dl.lock.lock_enabled),
            ("scan_enabled", head.scan.enabled),
            ("scope_data", head.scope.data),
            ("scope_channel1_signal", head.scope.channel1.signal),
            ("dl_lock_candidates", head.dl.lock.candidates),
            ("dl_lock_background_trace", head.dl.lock.background_trace),
        ):
            legacy[f"{laser}:" + {
                "label": "label",
                "enabled": "enabled",
                "dl_cc_current_set": "dl:cc:current_set",
                "amp_cc_current_set": "amp:cc:current_set",
                "dl_lock_lock_enabled": "dl:lock:lock_enabled",
                "scan_enabled": "scan:enabled",
                "scope_data": "scope:data",
                "scope_channel1_signal": "scope:channel1:signal",
                "dl_lock_candidates": "dl:lock:candidates",
                "dl_lock_background_trace": "dl:lock:background_trace",
            }[suffix]] = decop

    # Controller RPC names flatten SDK paths with underscores. Discover the
    # corresponding Decop nodes without making any hardware reads.
    def resolve(node, flattened):
        parts = flattened.split("_")
        for n in range(len(parts), 0, -1):
            name = "_".join(parts[:n])
            if not hasattr(node, name):
                continue
            value = getattr(node, name)
            if n == len(parts):
                if hasattr(value, "get") and hasattr(value, "subscribe"):
                    return value
                break
            return resolve(value, "_".join(parts[n:]))
        raise AttributeError(f"No subscribable TOPTICA parameter: {flattened}")

    from_fields = (
        "enabled", "dl_cc_enabled", "amp_cc_enabled",
        "dl_cc_current_set", "dl_cc_current_act",
        "dl_cc_current_clip_limit", "dl_cc_current_clip",
        "amp_cc_current_set", "amp_cc_current_act",
        "amp_cc_current_clip_limit", "amp_cc_current_clip",
        "dl_tc_temp_set", "dl_tc_temp_act", "dl_tc_temp_set_min",
        "dl_tc_temp_set_max", "dl_tc_ready",
        "dl_pc_voltage_set", "dl_pc_voltage_act",
        "dl_pc_voltage_min", "dl_pc_voltage_max",
        "scan_enabled", "scan_offset", "scan_amplitude", "scan_frequency",
        "dl_lock_lock_enabled", "dl_lock_state", "dl_lock_state_txt",
        "dl_lock_lockpoint_type", "dl_lock_pid1_regulating_state",
        "dl_lock_pid2_regulating_state", "dl_lock_window_enabled",
        "dl_lock_window_level_low", "dl_lock_window_level_high",
        "health_txt", "dl_lock_candidates", "dl_lock_background_trace",
        "scope_data", "scope_channel1_signal", "label",
    )
    # One SDK subscription per parameter, and one initial get per parameter.
    # Names are canonical and match the flattened RPC getter methods.
    vals = {
        "emission": dev._dlcpro.emission,
        "emission_button_enabled": dev._dlcpro.emission_button_enabled,
    }
    for laser in ("laser1", "laser2"):
        for method in from_fields:
            vals[f"{laser}_{method}"] = resolve(getattr(dev._dlcpro, laser), method)

    def canonical(name: str) -> str:
        # SDK uses hyphenated leaf names on update, e.g. current-set.
        return name.replace(":", "_").replace("-", "_")

    old_names = {}
    for name in legacy:
        old_names.setdefault(canonical(name), []).append(name)

    initial = {}
    for key, decop in vals.items():
        try:
            initial[key] = decop.get()
        except Exception as error:
            logging.warning("DLC initial subscription value %s unavailable: %s", key, error)
            initial[key] = None
    for key, aliases in old_names.items():
        if key in initial:
            for alias in aliases:
                initial[alias] = initial[key]
    # The ARTIQ GUI reads the SDK spelling of this global setting.
    initial["emission-button-enabled"] = initial["emission_button_enabled"]
    notifier = Notifier(initial)

    def callback(subscription: Subscription, time: Timestamp,
                 value: SubscriptionValue):
        key = canonical(subscription.name)
        if key not in vals:
            return
        reading = value.get()
        notifier[key] = reading
        for legacy_name in old_names.get(key, ()):
            if legacy_name != key:
                notifier[legacy_name] = reading
        # Preserve SDK hyphenated keys for older GUI clients.
        if subscription.name != key and subscription.name not in old_names.get(key, ()):
            notifier[subscription.name] = reading

    for key, decop in vals.items():
        try:
            decop.subscribe(callback)
        except Exception as error:
            logging.warning("DLC parameter %s cannot subscribe: %s", key, error)

    # A low-rate heartbeat lets the website fail closed if this controller
    # stops polling the SDK while its publisher TCP connection stays open.
    async def heartbeat():
        while True:
            notifier["_publisher_heartbeat"] = asyncio.get_running_loop().time()
            await asyncio.sleep(2.0)
    heartbeat_task = loop.create_task(heartbeat())
    atexit.register(heartbeat_task.cancel)

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
