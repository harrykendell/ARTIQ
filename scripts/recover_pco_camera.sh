#!/usr/bin/env bash
# Recover the PCO SDK after a camera process wedges in PCO_CloseCamera or
# PCO_OpenCameraDevice.
#
# The Linux PCO SDK keeps cross-process device state in
# /dev/shm/pco_device_shmem. A worker killed while the SDK is wedged can leave
# that state unusable even after the USB device handle has been released.
#
# This script:
#   1. finds processes that are genuinely using the PCO SDK/device state,
#      including repository/gui/pco_camera.py;
#   2. terminates those processes (TERM, then KILL if required);
#   3. removes the stale PCO shared-memory object once no users remain.
#
# It deliberately does not restart artiq_master or reset unrelated USB devices.

set -euo pipefail

SHMEM="/dev/shm/pco_device_shmem"
PCO_USB_VENDOR="1cb2"
YES=0
DRY_RUN=0

usage() {
    cat <<'EOF'
Usage: scripts/recover_pco_camera.sh [--yes] [--dry-run]

Recover a wedged PCO camera/SDK without restarting the whole ARTIQ stack.

  --yes      Do not ask for confirmation before terminating PCO users.
  --dry-run  Show what would be terminated/removed, but change nothing.
  -h, --help Show this help.
EOF
}

while (($#)); do
    case "$1" in
        --yes|-y)
            YES=1
            ;;
        --dry-run|-n)
            DRY_RUN=1
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
    shift
done

declare -A TARGET_PIDS=()

add_pid() {
    local pid="${1:-}"
    [[ "$pid" =~ ^[0-9]+$ ]] || return 0
    [[ "$pid" -ne "$$" ]] || return 0
    [[ -d "/proc/$pid" ]] || return 0
    TARGET_PIDS["$pid"]=1
}

add_fuser_pids() {
    local path="$1"
    [[ -e "$path" ]] || return 0

    local pid
    for pid in $(fuser "$path" 2>/dev/null || true); do
        add_pid "$pid"
    done
}

# 1. Anything with the PCO cross-process state mapped/open.
add_fuser_pids "$SHMEM"

# 2. Any process with the PCO device-manager library mapped. This catches
# workers/GUI processes even when they currently have no USB file descriptor.
for maps in /proc/[0-9]*/maps; do
    [[ -r "$maps" ]] || continue
    if grep -q '/libpcodevmgr\.so' "$maps" 2>/dev/null; then
        pid="${maps#/proc/}"
        pid="${pid%/maps}"
        add_pid "$pid"
    fi
done

# 3. Explicitly include the standalone PCO GUI in case it is starting up but
# has not mapped the device manager yet.
while read -r pid; do
    add_pid "$pid"
done < <(pgrep -f 'repository/gui/pco_camera\.py([[:space:]]|$)' || true)

# 4. Include owners of any currently enumerated PCO USB device.
for sysdev in /sys/bus/usb/devices/*; do
    [[ -r "$sysdev/idVendor" && -r "$sysdev/busnum" && -r "$sysdev/devnum" ]] || continue
    [[ "$(cat "$sysdev/idVendor")" == "$PCO_USB_VENDOR" ]] || continue

    bus="$(cat "$sysdev/busnum")"
    dev="$(cat "$sysdev/devnum")"
    node="$(printf '/dev/bus/usb/%03d/%03d' "$bus" "$dev")"
    add_fuser_pids "$node"
done

PIDS=()
if ((${#TARGET_PIDS[@]})); then
    mapfile -t PIDS < <(printf '%s\\n' "${!TARGET_PIDS[@]}" | sort -n)
fi

echo "PCO recovery"
echo "============"

if ((${#PIDS[@]})); then
    echo "Processes using the PCO SDK/device state:"
    for pid in "${PIDS[@]}"; do
        ps -p "$pid" -o pid=,user=,stat=,etime=,args= || true
    done
else
    echo "No live PCO SDK/device users found."
fi

if [[ -e "$SHMEM" ]]; then
    echo "Shared PCO device state: $SHMEM"
else
    echo "Shared PCO device state is already absent."
fi

if ((DRY_RUN)); then
    echo
    echo "Dry run: no processes were terminated and no shared memory was removed."
    exit 0
fi

if ((${#PIDS[@]})) && ((YES == 0)); then
    echo
    read -r -p "Terminate these PCO users and clear SDK shared state? [y/N] " answer
    case "$answer" in
        y|Y|yes|YES)
            ;;
        *)
            echo "Cancelled."
            exit 1
            ;;
    esac
fi

if ((${#PIDS[@]})); then
    echo
    echo "Sending SIGTERM to PCO users..."
    kill -TERM "${PIDS[@]}" 2>/dev/null || true

    # Give well-behaved processes a short chance to shut down. A process stuck
    # inside the native PCO SDK may never handle SIGTERM, so do not wait long.
    for _ in {1..20}; do
        remaining=()
        for pid in "${PIDS[@]}"; do
            [[ -d "/proc/$pid" ]] && remaining+=("$pid")
        done
        ((${#remaining[@]} == 0)) && break
        sleep 0.1
    done

    remaining=()
    for pid in "${PIDS[@]}"; do
        [[ -d "/proc/$pid" ]] && remaining+=("$pid")
    done

    if ((${#remaining[@]})); then
        echo "Forcing stuck PCO users to exit: ${remaining[*]}"
        kill -KILL "${remaining[@]}" 2>/dev/null || true
        sleep 0.2
    fi
fi

# Do not unlink the shared state while any process still has it open/mapped.
owners=()
if [[ -e "$SHMEM" ]]; then
    for pid in $(fuser "$SHMEM" 2>/dev/null || true); do
        [[ "$pid" =~ ^[0-9]+$ ]] && owners+=("$pid")
    done
fi

if ((${#owners[@]})); then
    echo "ERROR: refusing to remove $SHMEM; still owned by: ${owners[*]}" >&2
    exit 1
fi

if [[ -e "$SHMEM" ]]; then
    echo "Removing stale PCO SDK shared state..."
    rm -f -- "$SHMEM"
fi

if [[ -e "$SHMEM" ]]; then
    echo "ERROR: $SHMEM still exists after removal attempt." >&2
    exit 1
fi

echo
echo "PCO SDK recovery state cleared."
echo "PCO USB devices currently visible:"
lsusb | grep -Ei '1cb2|PCO|Excelitas' || echo "  (none found)"
echo
echo "Retry the camera/absorption image now. No ARTIQ master restart was performed."
