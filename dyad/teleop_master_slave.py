"""
teleop_master_slave.py  –  Téleopération unidirectionnelle (Master → Slave)
===========================================================================

Un seul robot (MASTER) envoie sa position.
L'autre robot (SLAVE) la reçoit et la suit.
Il n'y a pas de retour d'information du slave vers le master.

Lancement :
    Robot MASTER →  python teleop_master_slave.py --role master --slave-ip <IP_SLAVE>
    Robot SLAVE  →  python teleop_master_slave.py --role slave

Logique :
    • Le MASTER mesure ses angles articulaires et les envoie au SLAVE.
    • Le SLAVE reçoit ces angles et applique un couple PD articulaire pour les suivre.
    • Le MASTER n'a aucune retro-action (couple de retour).
"""

import time
import signal
import sys
import threading
import socket
import struct
import argparse
import serial.tools.list_ports

from HaplyHAPI import Board, Device, Mechanisms, Pantograph


# ============================================================
# Paramètres réseau
# ============================================================
LISTEN_PORT = 5101  # Port d'écoute (identique sur les deux machines)

# Format du message UDP : deux floats little-endian (x, y) = 8 octets
MSG_FORMAT = "!ff"
MSG_SIZE = struct.calcsize(MSG_FORMAT)  # 8 octets

# ============================================================
# Paramètres robot
# ============================================================
CW = 0
CCW = 1
HARDWARE_VERSION = 3

KP_ANGLE = 0.08  # Gain proportionnel articulaire [N.m/deg]
KD_ANGLE = 0.002  # Gain dérivé articulaire [N.m.s/deg]
SATURATION_TORQUE = 0.7  # Saturation des couples [N.m]
LOOP_DT = 0.005  # Période de la boucle principale [s]  ~200 Hz


# ============================================================
# État partagé (protégé par un verrou)
# ============================================================
_lock = threading.Lock()
local_angles = [0.0, 0.0]  # Angles mesurés du robot local
remote_angles = [0.0, 0.0]  # Angles reçus du robot distant (= consigne pour SLAVE)


# ============================================================
# Initialisation du robot Haply
# ============================================================
def create_board(port_name: str, app_id: str = "app"):
    """Initialise la carte Haply et retourne (device, haplyBoard)."""
    print(f"[Robot] Connexion sur le port : {port_name}")
    haplyBoard = Board(app_id, port_name, 0)
    time.sleep(0.5)

    device = Device(5, haplyBoard)
    pantograph = Pantograph()
    device.set_mechanism(pantograph)

    if HARDWARE_VERSION == 3:
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


def select_port() -> str:
    """Sélectionne automatiquement le port COM ou demande à l'utilisateur."""
    com_ports = list(serial.tools.list_ports.comports())
    if len(com_ports) == 1:
        return "/dev/ttyACM0"
    print("Sélectionnez le port COM de la carte Haply :")
    for i, p in enumerate(com_ports):
        print(f"  {i}: {p.device}")
    return com_ports[int(input("> "))].device


# ============================================================
# Thread UDP – MASTER (envoi uniquement)
# ============================================================
def udp_sender_master(sock: socket.socket, slave_ip: str) -> None:
    """
    MASTER : envoie en continu ses angles au SLAVE.
    """
    slave_addr = (slave_ip, LISTEN_PORT)
    print(f"[UDP] MASTER prêt à envoyer vers {slave_ip}:{LISTEN_PORT}")

    while True:
        try:
            with _lock:
                ang = local_angles[:]

            data = struct.pack(MSG_FORMAT, ang[0], ang[1])
            sock.sendto(data, slave_addr)

        except Exception as exc:
            print(f"[UDP send] Erreur : {exc}")

        time.sleep(LOOP_DT)


# ============================================================
# Thread UDP – SLAVE (réception uniquement)
# ============================================================
def udp_receiver_slave(sock: socket.socket) -> None:
    """
    SLAVE : reçoit les angles du MASTER et les met à jour.
    """
    print(f"[UDP] SLAVE en écoute sur le port {LISTEN_PORT}...")
    while True:
        try:
            data, addr = sock.recvfrom(256)
            if len(data) == MSG_SIZE:
                x, y = struct.unpack(MSG_FORMAT, data)
                with _lock:
                    remote_angles[0] = x
                    remote_angles[1] = y
                # Affichage occasionnel de la position reçue
                # (optionnel, peut ralentir le système)

        except OSError:
            break
        except Exception as exc:
            print(f"[UDP recv] Erreur : {exc}")


# ============================================================
# Gestionnaire d'arrêt propre (Ctrl+C)
# ============================================================
def make_signal_handler(device, sock):
    def handler(sig, frame):
        print("\n[Info] Arrêt demandé – mise à zéro des forces...")
        device.set_device_joint_torques([0.0, 0.0])
        device.device_write_torques()
        sock.close()
        time.sleep(0.1)
        sys.exit(0)

    return handler


# ============================================================
# Boucle principale
# ============================================================
def main():
    global local_angles, remote_angles

    # --- Arguments de ligne de commande ---
    parser = argparse.ArgumentParser(
        description="Téleopération Haply unidirectionnelle (Master → Slave)"
    )
    parser.add_argument(
        "--role",
        choices=["master", "slave"],
        required=True,
        help="'master' = envoie sa position | 'slave' = suit la position reçue",
    )
    parser.add_argument(
        "--slave-ip",
        type=str,
        default="10.42.0.42",
        help="Adresse IP du SLAVE (requis si --role=master)",
    )
    args = parser.parse_args()

    # --- Initialisation robot ---
    port = select_port()
    device, haplyBoard = create_board(port)

    # --- Socket UDP ---
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", LISTEN_PORT))

    # --- Démarrage du thread réseau selon le rôle ---
    if args.role == "master":
        threading.Thread(
            target=udp_sender_master, args=(sock, args.slave_ip), daemon=True
        ).start()
        role_label = f"MASTER (envoie vers {args.slave_ip})"
    else:
        threading.Thread(target=udp_receiver_slave, args=(sock,), daemon=True).start()
        role_label = "SLAVE (suit la position reçue)"

    # --- Gestionnaire Ctrl+C ---
    signal.signal(signal.SIGINT, make_signal_handler(device, sock))

    # --- Variables de boucle ---
    offset = [0.0, 0.0]
    offset_ok = False
    joint_torques = [0.0, 0.0]
    prev_error = [0.0, 0.0]
    prev_error_ok = False

    print(f"\n[Téléop] Boucle démarrée – rôle : {role_label}")

    # ---- Boucle temps-réel ----
    while True:
        try:
            if haplyBoard.data_available():
                device.device_read_data()
                angles = device.get_device_angles()
                a0 = angles[0]
                a1 = angles[1]
                if a0 is None or a1 is None:
                    continue
                angles_meas = [float(a0), float(a1)]

                # Calibration : offset angulaire au premier passage
                if not offset_ok:
                    offset = list(angles_meas)
                    offset_ok = True
                    prev_error_ok = False
                    print("[Robot] Offset angulaire enregistré.")

                angles_rel = [
                    angles_meas[0] - offset[0],
                    angles_meas[1] - offset[1],
                ]

                # Mise à jour des angles locaux partagés
                with _lock:
                    local_angles[0] = angles_rel[0]
                    local_angles[1] = angles_rel[1]

                if args.role == "master":
                    # ========== MASTER ==========
                    # Le master ne fait rien, il envoie seulement ses angles par UDP
                    print(
                        f"[MASTER] ang=({angles_rel[0]:+.4f}, {angles_rel[1]:+.4f})  "
                        f"tau=(0.000, 0.000) N.m"
                    )
                    joint_torques = [0.0, 0.0]
                    prev_error_ok = False

                else:
                    # ========== SLAVE ==========
                    # Le slave suit les angles reçus du master
                    with _lock:
                        target = remote_angles[:]

                    # Loi de commande PD en espace articulaire
                    error = [target[0] - angles_rel[0], target[1] - angles_rel[1]]
                    if prev_error_ok:
                        d_error = [
                            (error[0] - prev_error[0]) / LOOP_DT,
                            (error[1] - prev_error[1]) / LOOP_DT,
                        ]
                    else:
                        d_error = [0.0, 0.0]
                        prev_error_ok = True

                    tau1 = KP_ANGLE * error[0] + KD_ANGLE * d_error[0]
                    tau2 = KP_ANGLE * error[1] + KD_ANGLE * d_error[1]
                    joint_torques[0] = max(
                        min(tau1, SATURATION_TORQUE), -SATURATION_TORQUE
                    )
                    joint_torques[1] = max(
                        min(tau2, SATURATION_TORQUE), -SATURATION_TORQUE
                    )
                    prev_error[0] = error[0]
                    prev_error[1] = error[1]

                    print(
                        f"[SLAVE]  ang=({angles_rel[0]:+.4f}, {angles_rel[1]:+.4f})  "
                        f"cible=({target[0]:+.4f}, {target[1]:+.4f})  "
                        f"tau=({joint_torques[0]:+.3f}, {joint_torques[1]:+.3f}) N.m"
                    )

            device.set_device_joint_torques(joint_torques)
            device.device_write_torques()
            time.sleep(LOOP_DT)

        except Exception as exc:
            print(f"[Boucle] Erreur : {exc}")
            joint_torques = [0.0, 0.0]
            device.set_device_joint_torques(joint_torques)
            device.device_write_torques()
            time.sleep(0.1)


if __name__ == "__main__":
    main()
