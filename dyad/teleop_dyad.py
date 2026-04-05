"""
teleop_dyad.py  –  Téleopération bidirectionnelle entre deux robots Haply
=========================================================================

Deux Raspberry Pi ont exactement la même configuration matérielle.
    - PC "fixed"   : IP fixe  10.42.0.1
    - PC "dynamic" : IP dynamique (inconnue à l'avance)

Principe de communication UDP :
    1. Le PC "dynamic" envoie un paquet vers le PC "fixed" dès le démarrage
       ➜ le PC "fixed" découvre ainsi l'IP et le port du PC "dynamic".
    2. Les deux machines échangent ensuite en continu leurs positions
       dans les deux sens (bidirectionnel).

Lancement :
    PC fixe    →  python teleop_dyad.py --role fixed
    PC dynamique →  python teleop_dyad.py --role dynamic

Logique de téleopération :
    • Chaque robot mesure ses angles articulaires (th1, th2).
    • Il envoie ces angles à l'autre machine par UDP.
    • Il reçoit les angles de l'autre robot et les utilise comme consigne.
    • Un couple proportionnel-dérivé (PD) articulaire ramène le robot local vers la consigne.
"""

import time
import signal
import sys
import threading
import socket
import struct
import argparse
import serial.tools.list_ports

# from pyhapi import Board, Device, Mechanisms
# from pantograph import Pantograph
from HaplyHAPI import Board, Device, Mechanisms, Pantograph


# ============================================================
# Paramètres réseau
# ============================================================
# FIXED_IP défini par argument de ligne de commande (voir main())
LISTEN_PORT = 5100  # Port d'écoute (identique sur les deux machines)

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
remote_angles = [0.0, 0.0]  # Angles reçus du robot distant (= consigne)
remote_addr = None  # (ip, port) du pair distant


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
# Thread UDP – réception
# ============================================================
def udp_receiver(sock: socket.socket) -> None:
    """
    Reçoit les angles UDP du robot distant.
    Enregistre automatiquement l'adresse du pair lors du premier paquet reçu
    (mécanisme d'enregistrement dynamique).
    """
    global remote_addr

    print(f"[UDP] Écoute sur le port {LISTEN_PORT}...")
    while True:
        try:
            data, addr = sock.recvfrom(256)
            if len(data) == MSG_SIZE:
                x, y = struct.unpack(MSG_FORMAT, data)
                with _lock:
                    remote_angles[0] = x
                    remote_angles[1] = y
                    # Enregistrement du pair (IP dynamique autodécouverte)
                    if remote_addr is None:
                        remote_addr = addr
                        print(f"[UDP] Pair enregistré : {addr[0]}:{addr[1]}")
        except OSError:
            break
        except Exception as exc:
            print(f"[UDP recv] Erreur : {exc}")


# ============================================================
# Thread UDP – envoi
# ============================================================
def udp_sender(sock: socket.socket, role: str) -> None:
    """
    Envoie en continu les angles locaux au pair distant.

    Stratégie d'adressage :
    - "fixed"   : attend que le pair dynamic s'enregistre, puis répond.
    - "dynamic" : envoie d'abord vers FIXED_IP pour s'enregistrer,
                  puis continue vers l'adresse enregistrée.
    """
    print(f"[UDP] Émetteur démarré (rôle : {role}).")
    if role == "dynamic":
        print(f"[UDP] Enregistrement auprès de {FIXED_IP}:{LISTEN_PORT}...")

    while True:
        try:
            with _lock:
                ang = local_angles[:]
                peer = remote_addr

            # Le PC dynamic envoie vers l'IP fixe tant qu'aucun pair n'est connu
            if peer is None:
                if role == "dynamic":
                    dest = (FIXED_IP, LISTEN_PORT)
                else:
                    # PC fixed : pas encore de pair, on attend
                    time.sleep(0.01)
                    continue
            else:
                dest = (peer[0], LISTEN_PORT)

            data = struct.pack(MSG_FORMAT, ang[0], ang[1])
            sock.sendto(data, dest)

        except Exception as exc:
            print(f"[UDP send] Erreur : {exc}")

        time.sleep(LOOP_DT)


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
    global local_angles, FIXED_IP

    # --- Arguments de ligne de commande ---
    parser = argparse.ArgumentParser(
        description="Téleopération Haply bidirectionnelle par UDP"
    )
    parser.add_argument(
        "--role",
        choices=["fixed", "dynamic"],
        required=True,
        help=(
            "'fixed'   si cette machine a l'IP fixe\n"
            "'dynamic' si cette machine a une IP dynamique"
        ),
    )
    parser.add_argument(
        "--fixed-ip",
        type=str,
        default="10.42.0.1",
        help="Adresse IP du Raspberry ayant le rôle 'fixed' (défaut: 10.42.0.1)",
    )
    args = parser.parse_args()
    FIXED_IP = args.fixed_ip

    # --- Initialisation robot ---
    port = select_port()
    device, haplyBoard = create_board(port)

    # --- Socket UDP partagée (envoi + réception) ---
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", LISTEN_PORT))

    # --- Threads UDP ---
    threading.Thread(target=udp_receiver, args=(sock,), daemon=True).start()
    threading.Thread(target=udp_sender, args=(sock, args.role), daemon=True).start()

    # --- Gestionnaire Ctrl+C ---
    signal.signal(signal.SIGINT, make_signal_handler(device, sock))

    # --- Variables de boucle ---
    offset = [0.0, 0.0]
    offset_ok = False
    joint_torques = [0.0, 0.0]
    prev_error = [0.0, 0.0]
    prev_error_ok = False

    role_label = f"IP fixe ({FIXED_IP})" if args.role == "fixed" else "IP dynamique"
    print(f"\n[Téléop] Boucle démarrée – rôle : {role_label}")
    if args.role == "fixed":
        print("[Téléop] En attente du pair distant...")
    else:
        print(f"[Téléop] Connexion vers {FIXED_IP}:{LISTEN_PORT}...")

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
                joint_torques[0] = max(min(tau1, SATURATION_TORQUE), -SATURATION_TORQUE)
                joint_torques[1] = max(min(tau2, SATURATION_TORQUE), -SATURATION_TORQUE)
                prev_error[0] = error[0]
                prev_error[1] = error[1]

                print(
                    f"ang_local=({angles_rel[0]:+.4f}, {angles_rel[1]:+.4f})  "
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
