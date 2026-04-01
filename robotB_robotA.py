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
robotA_ip = "10.42.0.1"  # IP de Robot qui modifie le son sur le réseau local
robotA_port = 6000            # port pour recevoir la force
client = udp_client.SimpleUDPClient(robotA_ip, robotA_port)

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

device1, haplyBoard1 = create_board(port1, "RobotB")

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

prev_position1 = [0.0, 0.0]

# -------------------
# Thread pour envoyer la force à Robot A
# -------------------
def osc_sender_thread():
    global device_position1, prev_position1, forces1
    while True:
        try:
            # Calculer variation de position (vitesse)
            dx = device_position1[0] - prev_position1[0]
            dy = device_position1[1] - prev_position1[1]

            # Calcul force simple
            force_value = device_position1[0] * kp1  # ou dx+dy si tu veux dynamique
            if force_value > saturation:
                force_value = saturation
            elif force_value < -saturation:
                force_value = -saturation

            # Envoi au Robot A via OSC
            client.send_message("/interaction/force_AB", force_value)

            prev_position1 = device_position1.copy()
            time.sleep(0.005)

        except Exception as e:
            print("OSC send error:", e)
            time.sleep(0.1)

threading.Thread(target=osc_sender_thread, daemon=True).start()

# -------------------
# Main loop robot B
# -------------------
def main_loop():
    global device_position1, device_position_offset1, setOffset1, forces1
    print("Starting Robot B main loop...")
    while True:
        try:
            if haplyBoard1.data_available():
                device1.device_read_data()
                motorAngle = device1.get_device_angles()
                device_position1 = device1.get_device_position(motorAngle)

                # Offset initial
                if setOffset1:
                    device_position_offset1 = device_position1
                    setOffset1 = False

                # Position relative
                device_position1 = [
                    device_position1[0] - device_position_offset1[0],
                    device_position1[1] - device_position_offset1[1]
                ]

                # Optionnel: appliquer un retour haptique léger
                forces1[0] = 0.0
                forces1[1] = 0.0
                device1.set_device_torques(forces1)
                device1.device_write_torques()

            time.sleep(0.005)

        except Exception as e:
            print("Error in Robot B loop:", e)
            forces1 = [0.0, 0.0]
            device1.set_device_torques(forces1)
            device1.device_write_torques()
            time.sleep(0.1)

if __name__ == "__main__":
    main_loop()