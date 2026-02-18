import time
import signal
import sys
import serial.tools.list_ports
import threading
from pyhapi import Board, Device, Mechanisms
from pantograph import Pantograph
from pythonosc import udp_client

# -------------------
# Robot & UDP settings
# -------------------
pc_ip = "192.168.0.130"  # IP of the computer receiving OSC
pc_port = 5000
client = udp_client.SimpleUDPClient(pc_ip, pc_port)

CW = 0
CCW = 1
hardware_version = 3
kp1 = 400.0
saturation = 8.0

# -------------------
# Select COM port
# -------------------
com_ports = list(serial.tools.list_ports.comports())
if len(com_ports) == 1:
    port1 = "/dev/ttyACM0"
else:
    print("Select the COM port for the Haply board:")
    for i, port in enumerate(com_ports):
        print(f"{i}: {port.device}")
    port1 = com_ports[int(input())].device

# -------------------
# Create robot board
# -------------------
def create_board(port_name, app_id="app"):
    print("Connecting to robot on port:", port_name)
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

device1, haplyBoard1 = create_board(port1, "test1")

# -------------------
# Handle Ctrl+C safely
# -------------------
def signal_handler(sig, frame):
    print('You pressed Ctrl+C!')
    device1.set_device_torques([0.0, 0.0])
    device1.device_write_torques()
    time.sleep(0.1)

    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)

# -------------------
# Shared robot position
# -------------------
device_position1 = [0.0, 0.0]
device_position_offset1 = [0.0, 0.0]
setOffset1 = True
forces1 = [0.0, 0.0]

# -------------------
# Thread for sending OSC
# -------------------
def osc_sender_thread():
    global device_position1
    while True:
        try:
            client.send_message("/haply", [device_position1[0], device_position1[1]])
            time.sleep(0.005)
        except Exception as e:
            print("OSC send error:", e)
            time.sleep(0.1)  # wait a bit and retry

threading.Thread(target=osc_sender_thread, daemon=True).start()

# -------------------
# Main robot loop
# -------------------
def main_loop():
    global device_position1, device_position_offset1, setOffset1, forces1
    print("Starting main robot loop...")
    while True:
        try:
            if haplyBoard1.data_available():
                # --- Read robot ---
                device1.device_read_data()
                motorAngle = device1.get_device_angles()
                device_position1 = device1.get_device_position(motorAngle)

                # --- Set offset once ---
                if setOffset1:
                    device_position_offset1 = device_position1
                    setOffset1 = False
                    print("Setting offset1")

                # --- Make position relative ---
                device_position1 = [
                    device_position1[0] - device_position_offset1[0],
                    device_position1[1] - device_position_offset1[1]
                ]

                # --- Compute forces ---
                f1 = device_position1[0] * kp1
                if f1 > saturation:
                    forces1[0] = saturation
                elif f1 < -saturation:
                    forces1[0] = -saturation
                else:
                    forces1[0] = f1
                forces1[1] = 0.0  # y-axis not used

                # --- Debug ---
                print("Device1 position:", device_position1, "Device Angle1:", motorAngle)

            # --- Apply torques ---
            device1.set_device_torques(forces1)
            device1.device_write_torques()

            time.sleep(0.005)

        except Exception as e:
            # Catch any unexpected error, stop robot safely
            print("Error in main loop:", e)
            forces1 = [0.0, 0.0]
            device1.set_device_torques(forces1)
            device1.device_write_torques()
            time.sleep(0.1)

# -------------------
# Run
# -------------------
if __name__ == "__main__":
    main_loop()
