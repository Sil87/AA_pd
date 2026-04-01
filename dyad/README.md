# Dyad – Téleopération bidirectionnelle Haply

## Principe

Deux Raspberry Pi, chacun connecté à un robot **Haply**, échangent leurs positions
en temps réel via **UDP** :

```
[Robot A]  -->  position A  -->  [Robot B]  (consigne B = position A)
[Robot B]  -->  position B  -->  [Robot A]  (consigne A = position B)
```

Chaque robot applique une force proportionnelle pour suivre la consigne reçue.

---

## Adressage réseau

| Machine    | IP           | Rôle à passer au script |
|------------|--------------|-------------------------|
| Raspberry 1 | `10.42.0.1` (fixe) | `--role fixed`   |
| Raspberry 2 | dynamique    | `--role dynamic`        |

### Comment fonctionne la découverte d'IP dynamique ?

Le PC _dynamic_ envoie d'abord ses données vers `10.42.0.1:5100`.  
Dès réception, le PC _fixed_ enregistre l'IP source du paquet et commence à
répondre vers cette adresse. La communication bidirectionnelle s'établit ainsi
**sans configuration préalable** de l'IP dynamique.

---

## Lancement

**Sur le Raspberry Pi avec IP fixe (`10.42.0.1`) :**
```bash
python teleop_dyad.py --role fixed
```

**Sur le Raspberry Pi avec IP dynamique :**
```bash
python teleop_dyad.py --role dynamic
```

> Démarrer le PC **dynamic** en premier ou en second, peu importe :
> il envoie continuellement jusqu'à ce que le lien s'établisse.

---

## Paramètres à ajuster dans le code

| Paramètre    | Valeur par défaut | Description                        |
|--------------|-------------------|------------------------------------|
| `FIXED_IP`   | `"10.42.0.1"`     | IP fixe du Raspberry 1             |
| `LISTEN_PORT`| `5100`            | Port UDP (identique sur les deux)  |
| `KP`         | `400.0`           | Gain proportionnel (N/m)           |
| `SATURATION` | `8.0`             | Saturation des forces (N)          |
| `LOOP_DT`    | `0.005`           | Période boucle principale (s)      |

---

## Dépendances

```
pyhapi
pantograph
pyserial
```

---

## Structure du paquet UDP

Chaque paquet fait **8 octets** : deux `float` big-endian (x, y) en mètres.

```
| 4 octets : x [float] | 4 octets : y [float] |
```
