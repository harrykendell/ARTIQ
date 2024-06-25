#!/usr/bin/python3
"""
Author: Vertigo Designs, Ryan Summers

Description: Basic functional testing of Booster hardware
"""
import argparse
import asyncio
import contextlib
import sys
import time

from booster import BoosterApi, TelemetryReader

# The default bias current to tune to.
DEFAULT_BIAS_CURRENT = 0.05


async def periodic_check(awaitable, timeout: float):
    """ Periodically check a condition for a predefined amount of time until it evaluates true. """
    start = time.time()

    while (time.time() - start) < timeout:
        result = await awaitable()
        if result:
            return

    raise Exception('Condition did not occur within expected timeout')


@contextlib.asynccontextmanager
async def channel_on(booster, channel, initial_state='Enabled'):
    """ Context manager to ensure a channel is disabled upon exit.

    Args:
        booster: The BoosterApi objct.
        channel: The channel to configure.
        initial_state: The state to configure the channel into.
    """
    try:
        print(f'Commanding channel {channel} into {initial_state}')
        await booster.settings_interface.set(f'/channel/{channel}/state', initial_state)
        yield
    finally:
        print(f'Commanding channel {channel} off')
        await booster.settings_interface.set(f'/channel/{channel}/state', 'Off')


async def test_channel(booster, channel, prefix, broker):
    """ Basic testing of a single RF channel.

    Args:
        booster: The BoosterApi.
        channel: The channel index to test.
        prefix: Booster's miniconf prefix.
        broker: The broker IP address.
    """
    print(f'-> Conducting self-test on channel {channel}')

    # Start receiving telemetry for the channel under test.
    telemetry = await TelemetryReader.create(prefix, broker, channel)

    # Tune the bias current on the channel
    async with channel_on(booster, channel, 'Powered'):
        vgs, ids = await booster.tune_bias(channel, DEFAULT_BIAS_CURRENT)
        print(f'Channel {channel} bias tuning: Vgs = {vgs}, Ids = {ids}')

    # Disable the channel.
    await booster.settings_interface.set(f'/channel/{channel}/state', 'Off')

    # Check that telemetry indicates channel is powered off.
    async def is_off() -> bool:
        _, tlm = await telemetry.get_next_telemetry()
        return tlm['state'] == 'Off'

    await periodic_check(is_off, timeout=5)

    # Set the interlock threshold so that it won't trip.
    print('Setting output interlock threshold to 30 dB')
    await booster.settings_interface.set(f'/channel/{channel}/output_interlock_threshold', 30)

    # Enable the channel, verify telemetry indicates it is now enabled.
    async with channel_on(booster, channel):
        async def is_enabled() -> bool:
            _, tlm = await telemetry.get_next_telemetry()
            return tlm['state'] == 'Enabled'

        await periodic_check(is_enabled, timeout=5)

        # Lower the interlock threshold so it trips.
        print('Setting output interlock threshold to -5 dB, verifying interlock trips')
        await booster.settings_interface.set(f'/channel/{channel}/output_interlock_threshold', -5.7)

        async def is_tripped() -> bool:
            _, tlm = await telemetry.get_next_telemetry()
            return tlm['state'] == 'Tripped(Output)'

        # Verify the channel is now tripped.
        await periodic_check(is_tripped, timeout=5)

    print(f'Channel {channel}: PASS')
    print('')


def main():
    """ Main program entry point. """
    parser = argparse.ArgumentParser(description='Loopback tests for Stabilizer HITL testing',)
    parser.add_argument('--prefix', type=str, help='The MQTT prefix of the target')
    parser.add_argument('--broker', '-b', default='mqtt', type=str,
                        help='The MQTT broker address')
    parser.add_argument('--channels', '-c', nargs='+', help='Channels indices to test',
                        default=list(range(8)))

    args = parser.parse_args()

    async def test():
        """ The actual testing being completed. """
        booster = await BoosterApi.create(args.prefix, args.broker)

        # Disable configure the telemetry rate.
        await booster.settings_interface.set('/telemetry_period', 1, retain=False)

        # Test operation of an RF channel
        for channel in args.channels:
            await test_channel(booster, channel, booster.prefix, args.broker)

    loop = asyncio.get_event_loop()
    sys.exit(loop.run_until_complete(test()))


if __name__ == '__main__':
    main()

# #!/usr/bin/python
# """
# Author: Vertigo Designs, Ryan Summers

# Description: Provides an API for controlling Booster NGFW over MQTT.
# """
# import argparse
# import asyncio

# import sys
# sys.path.append(
#     __file__.split("repository")[0] + "repository"
# )  # link to repository root
# from utils.booster import BoosterApi, Action


# # A dictionary of all the available commands, their number of arguments, argument type, and help
# # information about the command.
# CMDS = {
#     'save': {
#         'nargs': 0,
#         'help': 'Save channel configuration',
#     },
#     'tune': {
#         'nargs': 1,
#         'type': float,
#         'help': 'Tune the channel RF drain current to the specified amps',
#     },
# }

# def parse_command(entry):
#     """ Parse a command string into a command and arguments. """
#     try:
#         pieces = entry.split('=')
#         assert 1 <= len(pieces) <= 2, 'Invalid command format'

#         cmd = pieces[0]
#         tail = pieces[1] if len(pieces) > 1 else None
#         args = tail.split(',') if tail else []

#         assert cmd in CMDS, f'Unknown command specified: {cmd}'
#         assert CMDS[cmd]['nargs'] == len(args), \
#             f'Invalid args specified. Expected {CMDS[cmd]["nargs"]}, but found {len(args)}'
#         return (cmd, [CMDS[cmd]['type'](x) for x in args])

#     except Exception as exception:
#         raise Exception(f'Failed to parse command "{entry}": {exception}')


# def main():
#     """ Main program entry point. """
#     parser = argparse.ArgumentParser(
#         formatter_class=argparse.RawTextHelpFormatter,
#         description='Modify booster RF channel configuration')
#     parser.add_argument('--prefix', type=str, help='The prefix of the booster to configure')
#     parser.add_argument('--channel', required=True, type=int, choices=range(8),
#                         help='The RF channel index to control')
#     parser.add_argument('--broker', default='mqtt', type=str, help='The MQTT broker address')

#     command_help = 'Individual commands. Options:\n'
#     for cmd, info in CMDS.items():
#         line = f'{cmd}'
#         if info['nargs'] == 1:
#             line += '=x'
#         if info['nargs'] == 2:
#             line += '=x,y'

#         command_help += f'{line:<30} | {info["help"]}\n'

#     parser.add_argument('commands', nargs='+', help=command_help)

#     async def channel_configuration(args):
#         """ Configure an RF channel. """

#         # Establish a communication interface with Booster.
#         interface = await BoosterApi.create(args.prefix, args.broker)

#         for command in args.commands:
#             command, cmd_args = parse_command(command)
#             if command == 'save':
#                 await interface.perform_action(Action.Save, args.channel)
#                 print(f'Channel {args.channel} configuration saved')
#             elif command == 'tune':
#                 vgs, ids = await interface.tune_bias(args.channel, cmd_args[0])
#                 print(f'Channel {args.channel}: Vgs = {vgs:.3f} V, Ids = {ids * 1000:.2f} mA')

#     loop = asyncio.get_event_loop()
#     loop.run_until_complete(channel_configuration(parser.parse_args()))


# if __name__ == '__main__':
#     main()