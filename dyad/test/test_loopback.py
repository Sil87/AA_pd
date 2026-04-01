"""
test_loopback.py  –  Test de la communication UDP en boucle locale
===================================================================

Simule les deux rôles ("fixed" et "dynamic") sur UNE SEULE machine,
en utilisant deux ports distincts sur localhost. Utile pour valider
l'intégralité de la logique de communication SANS avoir besoin d'un
second Raspberry Pi.

Architecture :
    Nœud A ("fixed")   écoute sur localhost:5200, envoie vers localhost:5201
    Nœud B ("dynamic") écoute sur localhost:5201, envoie vers localhost:5200

Séquence testée :
    ┌───────────────────────────────────────────────────────────────┐
    │  B→A  : premier paquet (simule la découverte de l'IP dynamic) │
    │  A→B  : réponse après enregistrement de B                     │
    │  ...  : échange bidirectionnel continu                        │
    └───────────────────────────────────────────────────────────────┘

Indicateurs vérifiés :
    - Paquets envoyés / reçus dans chaque sens
    - Latence aller-retour (round-trip) sur un écho de timestamp
    - Débit effectif (Hz)
    - Perte de paquets estimée

Usage :
    python test_loopback.py [--duration 10] [--hz 200]
"""

import argparse
import math
import socket
import struct
import threading
import time
from statistics import mean, median, stdev

MSG_FORMAT = "!ff"  # 2 floats big-endian (x, y)
MSG_SIZE = struct.calcsize(MSG_FORMAT)  # 8 octets
TS_FORMAT = "!d"  # timestamp (8 octets)
TS_SIZE = struct.calcsize(TS_FORMAT)  # 8 octets
PKT_SIZE = MSG_SIZE + TS_SIZE  # 16 octets total


# ─────────────────────────────────────────────────────────────────────────────
# Classe représentant un nœud de communication
# ─────────────────────────────────────────────────────────────────────────────


class Node:
    """
    Simule un participant à la téleopération :
      - génère des positions sinusoïdales locales
      - les envoie à l'adresse distante
      - reçoit les positions de l'autre nœud
    """

    def __init__(
        self,
        name: str,
        listen_port: int,
        send_port: int,
        freq_hz: float = 0.2,
        amplitude: float = 0.05,
    ):
        self.name = name
        self.listen_port = listen_port
        self.send_port = send_port
        self.freq_hz = freq_hz
        self.amplitude = amplitude

        self._lock = threading.Lock()
        self._received = [0.0, 0.0]
        self._sent_count = 0
        self._recv_count = 0
        self._latencies = []  # latences en ms (timestamps aller-retour)
        self._stop = False

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", listen_port))
        self._sock.settimeout(0.05)

    # ── Démarrage des threads ──────────────────────────────────────────────────
    def start(self, loop_dt: float) -> None:
        self._loop_dt = loop_dt
        self._t0 = time.monotonic()
        threading.Thread(target=self._recv_loop, daemon=True).start()
        threading.Thread(target=self._send_loop, daemon=True).start()

    def stop(self) -> None:
        self._stop = True
        self._sock.close()

    # ── Thread réception ───────────────────────────────────────────────────────
    def _recv_loop(self) -> None:
        while not self._stop:
            try:
                data, _ = self._sock.recvfrom(256)
            except socket.timeout:
                continue
            except OSError:
                break

            if len(data) < PKT_SIZE:
                continue

            x, y = struct.unpack(MSG_FORMAT, data[:MSG_SIZE])
            (t_sent,) = struct.unpack(TS_FORMAT, data[MSG_SIZE : MSG_SIZE + TS_SIZE])
            latency_ms = (time.monotonic() - t_sent) * 1000.0

            with self._lock:
                self._received[0] = x
                self._received[1] = y
                self._recv_count += 1
                self._latencies.append(latency_ms)

    # ── Thread envoi ──────────────────────────────────────────────────────────
    def _send_loop(self) -> None:
        dest = ("127.0.0.1", self.send_port)
        while not self._stop:
            t = time.monotonic() - self._t0
            x = self.amplitude * math.sin(2 * math.pi * self.freq_hz * t)
            y = self.amplitude * math.cos(2 * math.pi * self.freq_hz * t)
            now = time.monotonic()

            data = struct.pack(MSG_FORMAT, x, y) + struct.pack(TS_FORMAT, now)
            try:
                self._sock.sendto(data, dest)
                with self._lock:
                    self._sent_count += 1
            except OSError:
                break

            time.sleep(self._loop_dt)

    # ── Lecture des statistiques ───────────────────────────────────────────────
    @property
    def stats(self) -> dict:
        with self._lock:
            return {
                "sent": self._sent_count,
                "recv": self._recv_count,
                "latencies": list(self._latencies),
                "pos": list(self._received),
            }


# ─────────────────────────────────────────────────────────────────────────────
# Boucle d'affichage
# ─────────────────────────────────────────────────────────────────────────────


def display_loop(node_a: Node, node_b: Node, duration: float) -> None:
    HEADER = (
        f"{'':>8} {'sent':>7} {'recv':>7} {'rate/s':>7} "
        f"{'lat_avg':>9} {'lat_min':>9} {'lat_max':>9} {'pos_reçue':>20}"
    )
    print(HEADER)
    print("-" * len(HEADER))

    deadline = time.monotonic() + duration
    prev = {"A": 0, "B": 0}

    while time.monotonic() < deadline:
        time.sleep(1.0)
        for label, node in [("A [fixed]", node_a), ("B [dynami]", node_b)]:
            s = node.stats
            key = label[0]
            rate = s["recv"] - prev[key]
            prev[key] = s["recv"]

            lats = s["latencies"]
            if lats:
                avg = mean(lats)
                mn = min(lats)
                mx = max(lats)
                lat_str = f"{avg:7.2f}ms  {mn:7.2f}ms  {mx:7.2f}ms"
            else:
                lat_str = " " * 30 + "n/a"

            pos = s["pos"]
            print(
                f"  {label:>10} {s['sent']:>7} {s['recv']:>7} {rate:>7} "
                f" {lat_str}  ({pos[0]:+.4f}, {pos[1]:+.4f})"
            )
        print()


# ─────────────────────────────────────────────────────────────────────────────
# Rapport final
# ─────────────────────────────────────────────────────────────────────────────


def print_report(node_a: Node, node_b: Node, duration: float, hz: float) -> None:
    print("\n" + "=" * 60)
    print("  RAPPORT DE TEST LOOPBACK")
    print("=" * 60)

    for label, node in [("A [fixed]", node_a), ("B [dynamic]", node_b)]:
        s = node.stats
        tx = s["sent"]
        rx = s["recv"]
        lats = s["latencies"]

        print(f"\n  Nœud {label}")
        print(f"    Paquets envoyés  : {tx}")
        print(f"    Paquets reçus    : {rx}")

        expected = int(duration * hz)
        if expected > 0:
            eff = 100.0 * rx / expected
            print(
                f"    Débit effectif   : {rx/duration:.1f} Hz  (cible : {hz:.0f} Hz, {eff:.1f} %)"
            )

        if tx > 0:
            loss = max(0, tx - rx)
            print(f"    Perte estimée    : {loss} ({100*loss/tx:.1f} %)")

        if lats:
            avg = mean(lats)
            mn = min(lats)
            mx = max(lats)
            sd = stdev(lats) if len(lats) > 1 else 0.0
            med = median(lats)
            print(
                f"    Latence (A/R)    : moy={avg:.3f} ms  med={med:.3f} ms  "
                f"min={mn:.3f} ms  max={mx:.3f} ms  σ={sd:.3f} ms"
            )
        else:
            print("    Latence          : aucune mesure disponible")

    # Verdict global
    s_a = node_a.stats
    s_b = node_b.stats
    ok_ab = s_a["recv"] > 0 and s_b["recv"] > 0
    print("\n" + "=" * 60)
    if ok_ab:
        print("  RÉSULTAT : OK – communication bidirectionnelle vérifiée")
    else:
        print("  RÉSULTAT : ÉCHEC – au moins un sens de communication est vide")
    print("=" * 60)


# ─────────────────────────────────────────────────────────────────────────────
# Entrée principale
# ─────────────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test loopback UDP (deux rôles sur une seule machine)"
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=10.0,
        help="Durée du test en secondes (défaut : 10)",
    )
    parser.add_argument(
        "--hz", type=float, default=200.0, help="Fréquence d'envoi en Hz (défaut : 200)"
    )
    parser.add_argument(
        "--port-a",
        type=int,
        default=5200,
        help="Port d'écoute du nœud A / fixed (défaut : 5200)",
    )
    parser.add_argument(
        "--port-b",
        type=int,
        default=5201,
        help="Port d'écoute du nœud B / dynamic (défaut : 5201)",
    )
    args = parser.parse_args()

    loop_dt = 1.0 / args.hz

    print(f"{'='*60}")
    print(f"  TEST LOOPBACK – bidirectionnel sur localhost")
    print(f"  Nœud A [fixed]   : écoute={args.port_a}  envoie→{args.port_b}")
    print(f"  Nœud B [dynamic] : écoute={args.port_b}  envoie→{args.port_a}")
    print(f"  Fréquence        : {args.hz} Hz")
    print(f"  Durée            : {args.duration} s")
    print(f"{'='*60}\n")

    # Instanciation et démarrage des deux nœuds
    # A (fixed) : fréquence 0.2 Hz, amplitude 5 cm  – cercle
    # B (dynamic) : fréquence 0.3 Hz, amplitude 4 cm – figure en 8 (approx)
    node_a = Node(
        "A", listen_port=args.port_a, send_port=args.port_b, freq_hz=0.2, amplitude=0.05
    )
    node_b = Node(
        "B", listen_port=args.port_b, send_port=args.port_a, freq_hz=0.3, amplitude=0.04
    )

    node_a.start(loop_dt)
    node_b.start(loop_dt)

    try:
        display_loop(node_a, node_b, args.duration)
    except KeyboardInterrupt:
        print("\n[loopback] Interruption clavier.")

    node_a.stop()
    node_b.stop()

    print_report(node_a, node_b, args.duration, args.hz)


if __name__ == "__main__":
    main()
