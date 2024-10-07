#!/bin/bash

set -e
set -x

XC3SPROG=xc3sprog
CABLE=jtaghs2
JED_FILE=mirny_v0_3_1.jed


echo $CABLE
$XC3SPROG -c $CABLE -m data/map_files/ -v data/binaries/$JED_FILE:w
