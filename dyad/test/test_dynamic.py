"""
test_dynamic.py  –  Test UDP côté PC "dynamic" (IP dynamique)
==============================================================

Lance ce script sur le PC à IP dynamique, APRÈS que test_fixed.py
tourne déjà sur le PC à IP fixe (10.42.0.1).

Ce que fait ce script (sans robot Haply) :
  1. Envoie immédiatement un paquet vers 10.42.0.1:5100 pour s'enregistrer.
  2. Le PC "fixed" répond → communication bidirectionnelle établie.
  3. Les deux machines s'échangent des positions sinusoïdales simulées.
  4. Affiche en console les positions reçues et envoyées.
  5. Affiche des statistiques à la fin.

Usage :
    python test_dynamic.py [--fixed-ip 10.42.0.1] [--duration 30] [--port 5100]
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
received_pos = [0.0, 0.0]  # Dernière position reçue du fixed
stats_recv = [0]  # Compteur paquets reçus
stats_send = [0]  # Compteur paquets envoyés
latencies_ms = []  # Latences aller-retour
STOP_FLAG = [False]  # Signal d'arrêt propre


# ── Thread réception ───────────────────────────────────────────────────────────
def receiver(sock: socket.socket) -> None:
    """Reçoit les positions envoyées par le PC fixed."""
    print("[dynamic | recv] En attente des réponses du PC fixed...")

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

        # Latence : si le paquet transporte un timestamp (12 octets)
        if len(data) == MSG_SIZE + 8:
            (t_sent,) = struct.unpack("!d", data[MSG_SIZE : MSG_SIZE + 8])
            latency = (now - t_sent) * 1000.0
            with _lock:
                latencies_ms.append(latency)


# ── Thread envoi ───────────────────────────────────────────────────────────────
def sender(sock: socket.socket, fixed_ip: str, listen_port: int) -> None:
    """
    Génère des positions sinusoïdales et les envoie au PC fixed.
    Commence immédiatement (même sans réponse) pour permettre
    l'autodécouverte de ce PC par le fixed.
    """
    dest = (fixed_ip, listen_port)
    print(
        f"[dynamic | send] Envoi vers {fixed_ip}:{listen_port} (enregistrement + données)..."
    )
    t0 = time.monotonic()

    while not STOP_FLAG[0]:
        # Position simulée : figure en 8 (lissajous)
        t = time.monotonic() - t0
        x = 0.04 * math.sin(2 * math.pi * 0.3 * t)  # 0.3 Hz, ±4 cm
        y = 0.04 * math.sin(2 * math.pi * 0.15 * t)  # 0.15 Hz, ±4 cm

        now = time.monotonic()
        data = struct.pack(MSG_FORMAT, x, y) + struct.pack("!d", now)
        try:
            sock.sendto(data, dest)
            with _lock:
                stats_send[0] += 1
        except OSError:
            break

        time.sleep(0.005)  # ~200 Hz


# ── Affichage console ──────────────────────────────────────────────────────────
def display_loop(duration: float, fixed_ip: str) -> None:
    """Affiche l'état toutes les secondes pendant `duration` secondes."""
    deadline = time.monotonic() + duration
    last_recv = 0
    first_rx = False

    while time.monotonic() < deadline and not STOP_FLAG[0]:
        time.sleep(1.0)
        with _lock:
            rx = stats_recv[0]
            tx = stats_send[0]
            pos = list(received_pos)

        rate = rx - last_recv
        last_recv = rx

        if rx == 0:
            print(f"[dynamic] tx={tx:5d} | En attente de la réponse de {fixed_ip}...")
        else:
            if not first_rx:
                first_rx = True
                print(f"[dynamic] ✓ Premier paquet reçu du PC fixed !")
            print(
                f"[dynamic] rx={rx:5d} ({rate:3d}/s)  tx={tx:5d} | "
                f"pos_reçue=({pos[0]:+.4f}, {pos[1]:+.4f})"
            )

    STOP_FLAG[0] = True


# ── Statistiques finales ───────────────────────────────────────────────────────
def print_stats() -> None:
    with _lock:
        rx = stats_recv[0]
        tx = stats_send[0]
        lats = list(latencies_ms)

    print("\n" + "=" * 55)
    print("  STATISTIQUES FINALES – PC DYNAMIC")
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
        description="Test UDP côté 'dynamic' (sans robot Haply)"
    )
    parser.add_argument(
        "--fixed-ip",
        default="10.42.0.1",
        help="IP fixe du PC 'fixed' (défaut : 10.42.0.1)",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=30.0,
        help="Durée du test en secondes (défaut : 30)",
    )
    parser.add_argument(
        "--port", type=int, default=5100, help="Port UDP (défaut : 5100)"
    )
    args = parser.parse_args()

    print(f"{'='*55}")
    print(f"  TEST DYNAMIC – UDP bidirectionnel")
    print(f"  PC fixed cible : {args.fixed_ip}:{args.port}")
    print(f"  Durée          : {args.duration} s")
    print(f"{'='*55}\n")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", args.port))

    threads = [
        threading.Thread(target=receiver, args=(sock,), daemon=True),
        threading.Thread(
            target=sender, args=(sock, args.fixed_ip, args.port), daemon=True
        ),
    ]
    for t in threads:
        t.start()

    try:
        display_loop(args.duration, args.fixed_ip)
    except KeyboardInterrupt:
        print("\n[dynamic] Interruption clavier.")
        STOP_FLAG[0] = True

    sock.close()
    print_stats()


if __name__ == "__main__":
    main()
