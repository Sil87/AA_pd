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
    • Le MASTER mesure sa position et l'envoie par UDP au SLAVE.
    • Le SLAVE reçoit cette position et applique une force pour la suivre.
    • Le MASTER n'a aucune retro-action (force de retour).
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

KP = 400.0  # Gain proportionnel [N/m]
SATURATION = 8.0  # Saturation des forces [N]
LOOP_DT = 0.005  # Période de la boucle principale [s]  ~200 Hz


# ============================================================
# État partagé (protégé par un verrou)
# ============================================================
_lock = threading.Lock()
local_position = [0.0, 0.0]  # Position mesurée du robot local
remote_position = [0.0, 0.0]  # Position reçue du robot distant (= consigne pour SLAVE)


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
    MASTER : envoie en continu sa position au SLAVE.
    """
    slave_addr = (slave_ip, LISTEN_PORT)
    print(f"[UDP] MASTER prêt à envoyer vers {slave_ip}:{LISTEN_PORT}")

    while True:
        try:
            with _lock:
                pos = local_position[:]

            data = struct.pack(MSG_FORMAT, pos[0], pos[1])
            sock.sendto(data, slave_addr)

        except Exception as exc:
            print(f"[UDP send] Erreur : {exc}")

        time.sleep(LOOP_DT)


# ============================================================
# Thread UDP – SLAVE (réception uniquement)
# ============================================================
def udp_receiver_slave(sock: socket.socket) -> None:
    """
    SLAVE : reçoit la position du MASTER et la met à jour.
    """
    print(f"[UDP] SLAVE en écoute sur le port {LISTEN_PORT}...")
    while True:
        try:
            data, addr = sock.recvfrom(256)
            if len(data) == MSG_SIZE:
                x, y = struct.unpack(MSG_FORMAT, data)
                with _lock:
                    remote_position[0] = x
                    remote_position[1] = y
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
        device.set_device_torques([0.0, 0.0])
        device.device_write_torques()
        sock.close()
        time.sleep(0.1)
        sys.exit(0)

    return handler


# ============================================================
# Boucle principale
# ============================================================
def main():
    global local_position, remote_position

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
        default="10.42.0.254",
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
    forces = [0.0, 0.0]

    print(f"\n[Téléop] Boucle démarrée – rôle : {role_label}")

    # ---- Boucle temps-réel ----
    while True:
        try:
            if haplyBoard.data_available():
                device.device_read_data()
                angles = device.get_device_angles()
                pos = device.get_device_position(angles)

                # Calibration : offset positionnel au premier passage
                if not offset_ok:
                    offset = list(pos)
                    offset_ok = True
                    print("[Robot] Offset de position enregistré.")

                pos_rel = [
                    pos[0] - offset[0],
                    pos[1] - offset[1],
                ]

                # Mise à jour de la position locale partagée
                with _lock:
                    local_position[0] = pos_rel[0]
                    local_position[1] = pos_rel[1]

                if args.role == "master":
                    # ========== MASTER ==========
                    # Le master ne fait rien, juste envoie sa position par UDP
                    print(
                        f"[MASTER] pos=({pos_rel[0]:+.4f}, {pos_rel[1]:+.4f})  "
                        f"F=(0.00, 0.00) N"
                    )
                    forces = [0.0, 0.0]

                else:
                    # ========== SLAVE ==========
                    # Le slave suit la position reçue du master
                    with _lock:
                        target = remote_position[:]

                    # Loi de commande proportionnelle
                    fx = (target[0] - pos_rel[0]) * KP
                    fy = (target[1] - pos_rel[1]) * KP
                    forces[0] = max(min(fx, SATURATION), -SATURATION)
                    forces[1] = max(min(fy, SATURATION), -SATURATION)

                    print(
                        f"[SLAVE]  pos=({pos_rel[0]:+.4f}, {pos_rel[1]:+.4f})  "
                        f"cible=({target[0]:+.4f}, {target[1]:+.4f})  "
                        f"F=({forces[0]:+.2f}, {forces[1]:+.2f}) N"
                    )

            device.set_device_torques(forces)
            device.device_write_torques()
            time.sleep(LOOP_DT)

        except Exception as exc:
            print(f"[Boucle] Erreur : {exc}")
            forces = [0.0, 0.0]
            device.set_device_torques(forces)
            device.device_write_torques()
            time.sleep(0.1)


if __name__ == "__main__":
    main()
