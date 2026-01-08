from pyhapi import Board, Device
from pantograph import Pantograph
from pythonosc.udp_client import SimpleUDPClient

import time
import serial.tools.list_ports
import signal
import sys
import math

# --------------------
# Constants
# --------------------
CW = 0
CCW = 1
hardware_version = 3

dt = 0.005
stillness_threshold = 0.002
direction_threshold = 0.7

# --------------------
# OSC client (Pure Data / Processing)
# --------------------
pc_ip = "127.0.0.1"   # change to PD IP if needed
pc_port = 5000

client = SimpleUDPClient(pc_ip, pc_port)

# --------------------
# Serial port
# --------------------
com_ports = list(serial.tools.list_ports.comports())

if len(com_ports) == 0:
    print("No Haply board found")
    sys.exit(1)

port = com_ports[0].device
print(f"Using Haply board on {port}")

# --------------------
# Device creation
# --------------------
def create_board(port_name, app_id="app"):
    print(f"Connecting to Haply board on {port_name}")
    haplyBoard = Board(app_id, port_name, 0)
    time.sleep(0.5)

    device = Device(5, haplyBoard)
    pantograph = Pantograph()
    device.set_mechanism(pantograph)

    if hardware_version == 3:
        device.add_actuator(1, CCW, 2)
        device.add_actuator(2, CCW, 1)
        device.add_encoder(1, CCW, 168, 4880, 2)
        device.add_encoder(2, CCW, 12, 4880, 1)

    device.device_set_parameters()
    time.sleep(0.5)
    return device, haplyBoard

device1, haplyBoard1 = create_board(port, "sound_device")

# --------------------
# Safety handler
# --------------------
def signal_handler(sig, frame):
    print("Stopping safely")
    device1.set_device_torques([0.0, 0.0])
    device1.device_write_torques()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

# --------------------
# Main loop
# --------------------
def main():
    print("Starting single-device OSC interaction")

    setOffset = True

    pos = [0.0, 0.0]
    offset = [0.0, 0.0]

    prev_pos = [0.0, 0.0]
    prev_velocity = [0.0, 0.0]

    while True:
        if haplyBoard1.data_available():
            device1.device_read_data()
            angles = device1.get_device_angles()
            raw_pos = device1.get_device_position(angles)

            if setOffset:
                offset = raw_pos[:]
                prev_pos = [0.0, 0.0]
                setOffset = False
                print("Offset set")

            pos = [
                raw_pos[0] - offset[0],
                raw_pos[1] - offset[1]
            ]

            # velocity
            vel = [
                (pos[0] - prev_pos[0]) / dt,
                (pos[1] - prev_pos[1]) / dt
            ]

            speed = math.sqrt(vel[0]**2 + vel[1]**2)

            # stillness
            still = 1 if speed < stillness_threshold else 0

            # direction change
            dot = vel[0]*prev_velocity[0] + vel[1]*prev_velocity[1]
            mag = (math.sqrt(vel[0]**2 + vel[1]**2) *
                   math.sqrt(prev_velocity[0]**2 + prev_velocity[1]**2) + 1e-6)
            direction_change = 1 if (dot / mag) < direction_threshold else 0

            # send OSC messages
            client.send_message("/speed", speed)
            client.send_message("/still", still)
            if direction_change:
                client.send_message("/turn", 1)

            prev_pos = pos[:]
            prev_velocity = vel[:]

        time.sleep(dt)

if __name__ == "__main__":
    main()
