import time
import datetime
import os
import h5py
import numpy as np

from toptica.lasersdk.client import (
    Client,
    NetworkConnection,
    DeviceNotFoundError,
    Subscription,
    Timestamp,
    SubscriptionValue,
)

from toptica.lasersdk.dlcpro.v2_0_3 import (
    DLCpro,
)

from toptica.lasersdk.utils.dlcpro import *


# ---------------- CONFIG ----------------
params = [
    "time",
    "laser2:dl:cc:current-act",
    "laser2:dl:tc:temp-set",
    "laser2:dl:tc:temp-act",
]

interval = 5.00  # seconds
snapshots = {}
# ----------------------------------------


def update_snapshots(
    subscription: Subscription,
    timestamp: Timestamp,
    value: SubscriptionValue,
):
    snapshots[subscription.name] = value.get()


def save_shot_hdf(directory, elapsed_time, dlcpro, shot_index):
    filename = os.path.join(directory, "experiment.h5")

    try:
        scope_data = extract_float_arrays("xyY", dlcpro.laser2.scope.data.get())

        with h5py.File(filename, "a") as hf:
            shot_name = f"shot_{shot_index:06d}"
            grp = hf.create_group(shot_name)

            # Metadata
            grp.attrs["timestamp"] = datetime.datetime.now().isoformat()
            grp.attrs["elapsed_time"] = elapsed_time

            # Save parameters
            param_grp = grp.create_group("params")
            for p in params:
                val = snapshots.get(p, None)
                try:
                    param_grp.attrs[p] = val
                except Exception:
                    param_grp.attrs[p] = str(val)

            # Save scope data
            scope_grp = grp.create_group("scope")
            scope_grp.create_dataset(
                "x",
                data=np.array(scope_data["x"]),
                compression="gzip",
            )
            scope_grp.create_dataset(
                "y",
                data=np.array(scope_data["y"]),
                compression="gzip",
            )
            scope_grp.create_dataset(
                "Y",
                data=np.array(scope_data["Y"]),
                compression="gzip",
            )

    except Exception as e:
        print(f"Scope save failed: {e}")


def main(ip_address, directory=None):
    if directory is None:
        directory = os.getcwd()

    folder_name = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    directory = os.path.join(directory, folder_name)
    os.makedirs(directory, exist_ok=True)

    hdf_filename = os.path.join(directory, "experiment.h5")
    print(f"Saving to: {hdf_filename}")

    try:
        with (
            Client(NetworkConnection(ip_address)) as dlc,
            DLCpro(NetworkConnection(ip_address)) as dlcpro,
        ):
            # Initialize parameters
            for p in params:
                snapshots[p] = dlc.get(p)
                dlc.subscribe(p, update_snapshots)

            start_time = time.time()
            next_sampling_due = start_time
            shot_index = 0

            while True:
                next_sampling_due += interval

                sleep_time = max(0, interval - 0.05)
                time.sleep(sleep_time)

                while time.time() < next_sampling_due:
                    dlc.poll()

                elapsed = time.time() - start_time

                print(
                    f"Shot {shot_index} | "
                    f"Elapsed {elapsed:.2f}s | "
                    f"Current={snapshots.get('laser2:dl:cc:current-act')}"
                )

                save_shot_hdf(directory, elapsed, dlcpro, shot_index)

                shot_index += 1

    except KeyboardInterrupt:
        print("\nFinished logging.")

    except DeviceNotFoundError:
        print("Device not found.")


# if __name__ == "__main__":
#     main(
#         ip_address="192.168.0.4",
#         directory="/home/ae19663/Desktop/toptica_dlc_pro",
#     )
