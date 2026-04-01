"""
test_fixed.py  –  Test UDP côté PC "fixed" (IP fixe : 10.42.0.1)
==================================================================

Lance ce script sur le PC à IP fixe AVANT de lancer test_dynamic.py
sur l'autre machine.

Ce que fait ce script (sans robot Haply) :
  1. Écoute le port 5100 en attente du premier paquet du PC "dynamic".
  2. Dès réception, enregistre l'IP du pair et commence à lui envoyer
     des positions simulées (sinusoïdales).
  3. Affiche en console les positions reçues et envoyées.
  4. Affiche des statistiques à la fin (paquets envoyés / reçus, latence).

Usage :
    python test_fixed.py [--duration 30] [--port 5100]
"""

import argparse
import math
import socket
import struct
import threading
import time

# ── Paramètres réseau ──────────────────────────────────────────────────────────
MSG_FORMAT = "!ff"  # 2 floats big-endian (x, y)
MSG_SIZE = struct.calcsize(MSG_FORMAT)  # 8 octets

# ── État partagé ───────────────────────────────────────────────────────────────
_lock = threading.Lock()
remote_addr = None  # (ip, port) du PC dynamic, autodécouvert
received_pos = [0.0, 0.0]  # Dernière position reçue du dynamic
stats_recv = [0]  # Compteur paquets reçus
stats_send = [0]  # Compteur paquets envoyés
latencies_ms = []  # Latences aller-retour (si écho activé)
STOP_FLAG = [False]  # Signal d'arrêt propre


# ── Thread réception ───────────────────────────────────────────────────────────
def receiver(sock: socket.socket) -> None:
    """Reçoit les positions envoyées par le PC dynamic."""
    global remote_addr
    print("[fixed | recv] En attente d'un paquet entrant sur le port de ce socket...")

    while not STOP_FLAG[0]:
        try:
            sock.settimeout(1.0)
            data, addr = sock.recvfrom(256)
        except socket.timeout:
            continue
        except OSError:
            break

        if len(data) < MSG_SIZE:
            continue

        x, y = struct.unpack(MSG_FORMAT, data[:MSG_SIZE])
        now = time.monotonic()

        with _lock:
            received_pos[0] = x
            received_pos[1] = y
            stats_recv[0] += 1

            if remote_addr is None:
                remote_addr = addr
                print(f"[fixed | recv] Pair dynamic enregistré → {addr[0]}:{addr[1]}")

        # Latence : si le paquet transporte un timestamp (12 octets)
        if len(data) == MSG_SIZE + 8:
            (t_sent,) = struct.unpack("!d", data[MSG_SIZE : MSG_SIZE + 8])
            latency = (now - t_sent) * 1000.0
            with _lock:
                latencies_ms.append(latency)


# ── Thread envoi ───────────────────────────────────────────────────────────────
def sender(sock: socket.socket, listen_port: int) -> None:
    """
    Génère des positions sinusoïdales et les envoie au PC dynamic.
    Attend que l'adresse du pair soit connue avant d'émettre.
    """
    print("[fixed | send] En attente de l'enregistrement du pair...")
    t0 = time.monotonic()

    while not STOP_FLAG[0]:
        with _lock:
            peer = remote_addr

        if peer is None:
            time.sleep(0.01)
            continue

        # Position simulée : cercle lent
        t = time.monotonic() - t0
        x = 0.05 * math.sin(2 * math.pi * 0.2 * t)  # 0.2 Hz, ±5 cm
        y = 0.05 * math.cos(2 * math.pi * 0.2 * t)

        now = time.monotonic()
        data = struct.pack(MSG_FORMAT, x, y) + struct.pack("!d", now)
        try:
            sock.sendto(data, (peer[0], listen_port))
            with _lock:
                stats_send[0] += 1
        except OSError:
            break

        time.sleep(0.005)  # ~200 Hz


# ── Affichage console ──────────────────────────────────────────────────────────
def display_loop(duration: float) -> None:
    """Affiche l'état toutes les secondes pendant `duration` secondes."""
    deadline = time.monotonic() + duration
    last_recv = 0

    while time.monotonic() < deadline and not STOP_FLAG[0]:
        time.sleep(1.0)
        with _lock:
            rx = stats_recv[0]
            tx = stats_send[0]
            pos = list(received_pos)
            peer = remote_addr

        rate = rx - last_recv
        last_recv = rx

        if peer:
            print(
                f"[fixed] rx={rx:5d} ({rate:3d}/s)  tx={tx:5d} | "
                f"pos_reçue=({pos[0]:+.4f}, {pos[1]:+.4f})"
            )
        else:
            print("[fixed] En attente du premier paquet du PC dynamic...")

    STOP_FLAG[0] = True


# ── Statistiques finales ───────────────────────────────────────────────────────
def print_stats() -> None:
    with _lock:
        rx = stats_recv[0]
        tx = stats_send[0]
        lats = list(latencies_ms)

    print("\n" + "=" * 55)
    print("  STATISTIQUES FINALES – PC FIXED")
    print("=" * 55)
    print(f"  Paquets envoyés  : {tx}")
    print(f"  Paquets reçus    : {rx}")

    if lats:
        avg = sum(lats) / len(lats)
        mn = min(lats)
        mx = max(lats)
        print(
            f"  Latence (A/R)    : moy={avg:.2f} ms  min={mn:.2f} ms  max={mx:.2f} ms"
        )
    else:
        print("  Latence (A/R)    : non disponible (aucun timestamp reçu)")

    if tx > 0:
        loss = max(0, tx - rx)
        print(f"  Perte estimée    : {loss} paquets ({100*loss/tx:.1f} %)")
    print("=" * 55)


# ── Entrée principale ──────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test UDP côté 'fixed' (sans robot Haply)"
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=30.0,
        help="Durée du test en secondes (défaut : 30)",
    )
    parser.add_argument(
        "--port", type=int, default=5100, help="Port UDP d'écoute (défaut : 5100)"
    )
    args = parser.parse_args()

    print(f"{'='*55}")
    print(f"  TEST FIXED – UDP bidirectionnel")
    print(f"  Écoute sur  : 0.0.0.0:{args.port}")
    print(f"  Durée       : {args.duration} s")
    print(f"{'='*55}\n")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", args.port))

    threads = [
        threading.Thread(target=receiver, args=(sock,), daemon=True),
        threading.Thread(target=sender, args=(sock, args.port), daemon=True),
    ]
    for t in threads:
        t.start()

    try:
        display_loop(args.duration)
    except KeyboardInterrupt:
        print("\n[fixed] Interruption clavier.")
        STOP_FLAG[0] = True

    sock.close()
    print_stats()


if __name__ == "__main__":
    main()
