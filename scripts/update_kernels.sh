#! /bin/bash
# this script compiles and flashes the kernels located in ../repository/kernels
SCRIPT_DIR="$(dirname "$(realpath "$0")")"

for TYPE in idle startup; do
    artiq_compile $SCRIPT_DIR"/../repository/kernels/"$TYPE"_kernel.py"
    # artiq_coremgmt config write -f idle_kernel $SCRIPT_DIR/../repository/kernels/idle.elf
done