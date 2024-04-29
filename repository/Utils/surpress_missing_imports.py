#!/usr/bin/env python3
from artiq.experiment import *
from artiq.language.core import delay, now_mu, parallel, sequential
from artiq.language.units import us, ms, MHz, dB, s
from artiq.language.types import TInt32, TFloat, TList, TTuple, TStr, TNone