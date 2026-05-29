# import pco
# import matplotlib.pyplot as plt
# import logging


# FIRST = 19701804
# SECOND = 61011464

# ms = 1e-3

# cam = pco.Camera(serial=SECOND)
# cam.default_configuration()

# cam.sdk.set_shutter_mode("global reset")

# cam.sdk.arm_camera()

# print(cam.sdk.get_shutter_mode())
# import socket
# from datetime import datetime
# from pathlib import Path
# import time

# IP = "192.168.0.5"

# # Create screenshot
# s = socket.create_connection((IP, 4000))
# s.settimeout(10)

# s.sendall(b'SAVE:IMAGE "C:/latest.png"\n')
# s.sendall(b"*OPC?\n")

# print("OPC =", s.recv(1024))

# s.close()

# time.sleep(1)

# # Download screenshot
# s = socket.create_connection((IP, 4000))
# s.settimeout(10)

# s.sendall(b'FILESystem:READFile "C:/latest.png"\n')

# data = b""

# while True:
#     try:
#         chunk = s.recv(65536)

#         if not chunk:
#             break

#         data += chunk

#     except TimeoutError:
#         break

# s.close()

# print("Received", len(data), "bytes")

# timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

# outfile = Path(f"/home/ae19663/Desktop/MSO24_{timestamp}.png")

# with open(outfile, "wb") as f:
#     f.write(data)

# print("Saved:", outfile)
