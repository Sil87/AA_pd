from pyhapi import Board, Device, Mechanisms
from pantograph import Pantograph
import time
import serial.tools.list_ports
import signal
import sys
import threading
import socket

# -------------------
# Constants
# -------------------
CW = 0
CCW = 1
hardware_version = 3

# Robot variables
kp1 = 50.0  #10
saturation = 4.0 #4
forces1 = [0.0, 0.0]

# UDP variables
x_target = 0.0
UDP_IP = "0.0.0.0"   # listen on all interfaces
UDP_PORT = 3000     # port to receive pitch

# -------------------
# Functions
# -------------------
def create_board(port_name, app_id="app"):
    print("Connection to the robot, port:", port_name)
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
    else:
        device.add_actuator(1, CCW, 2)
        device.add_actuator(2, CW, 1)
        device.add_encoder(1, CCW, 241, 10752, 2)
        device.add_encoder(2, CW, -61, 10752, 1)

    device.device_set_parameters()
    time.sleep(0.5)
    return device, haplyBoard

# -------------------
# UDP listener
# -------------------
def udp_listener():
    global x_target

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((UDP_IP, UDP_PORT))
    print(f"UDP server listening on {UDP_IP}:{UDP_PORT}")

    while True:
        data, addr = sock.recvfrom(1024) #max 1024 bytes so 1024 strings or 256 integers once

        try:
            text = data.decode("utf-8").strip()
            if not text:
                continue

            # Remove semicolons
            text = text.replace(";", "")
            
            # Convert to float
            dx = float(text)
            x_target = dx
            print("UDP x_target =", x_target)

        except Exception as e:
            print("Error decoding UDP:", repr(data), e) #repr(data) to print in raw form

# -------------------
# Signal handler
# -------------------
def signal_handler(sig, frame, device):
    print("Stopping robot...")
    device.set_device_torques([0.0, 0.0])
    device.device_write_torques()
    sys.exit(0)

# -------------------
# Main function
# -------------------
def main():
    global x_target

    # --- Select COM port ---
    com_ports = list(serial.tools.list_ports.comports())
    if len(com_ports) == 1:
        port1 = "/dev/ttyACM0"
    else:
        print("Select COM port for Haply board:")
        for i, p in enumerate(com_ports):
            print(f"{i}: {p.device}")
        port1 = com_ports[int(input())].device

    # --- Initialize robot ---
    device1, haplyBoard1 = create_board(port1)

    # --- Start UDP listener thread ---
    threading.Thread(target=udp_listener, daemon=True).start()

    # --- Clean exit ---
    signal.signal(signal.SIGINT,
                  lambda sig, frame: signal_handler(sig, frame, device1))

    # --- Loop variables ---
    device_position_offset1 = [0.0, 0.0]
    setOffset1 = True

    print("Starting robot loop... Move the robot by hand to see angles!")

    # --- Main loop ---
    while True:
        if haplyBoard1.data_available():
            device1.device_read_data()
            motorAngle = device1.get_device_angles()
            device_position1 = device1.get_device_position(motorAngle)

            if setOffset1:
                device_position_offset1 = device_position1
                setOffset1 = False
                print("Setting offset1")

            device_position1 = [
                device_position1[0] - device_position_offset1[0],
                device_position1[1] - device_position_offset1[1]
            ]

            # --- Force computation ---
            f_x = (x_target - device_position1[0]) * kp1
            forces1[0] = max(min(f_x, saturation), -saturation)
            forces1[1] = forces1[0]

            # Debug
            print(
                "x_target:", x_target,
                "x_pos:", device_position1[0],
                "fx:", forces1[0]
            )

        device1.set_device_torques(forces1)
        device1.device_write_torques()

        time.sleep(0.005)

# -------------------
# Run
# -------------------
if __name__ == "__main__":
    main()
