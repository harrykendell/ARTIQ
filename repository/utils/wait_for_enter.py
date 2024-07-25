#!/usr/bin/env python3
import os
import sys
import select
from artiq.language.types import TBool

if os.name == "nt":
    import msvcrt


def is_enter_pressed() -> TBool:
    if os.name == "nt":
        if msvcrt.kbhit() and msvcrt.getch() == b"\r":
            while msvcrt.kbhit():
                msvcrt.getch()
            print("Enter pressed")
            return True
        else:
            return False
    else:
        if select.select(
            [
                sys.stdin,
            ],
            [],
            [],
            0.0,
        )[0]:
            sys.stdin.read(1)
            return True
        else:
            return False
