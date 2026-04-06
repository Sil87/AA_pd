# Instruction de connection wifi suivies

## 1. Configurer la connexion WiFi cliente

```bash
# Ajouter le profil WiFi (remplacer MOT_DE_PASSE par votre clé WPA2)
sudo nmcli con add type wifi ifname wlan0 con-name "Rpi-danse-Wifi4" ssid "Rpi-danse-Wifi4"
sudo nmcli con modify "Rpi-danse-Wifi4" wifi-sec.key-mgmt wpa-psk wifi-sec.psk "MOT_DE_PASSE"
sudo nmcli con modify "Rpi-danse-Wifi4" connection.autoconnect no
```

## 2. Configurer le hotspot

```bash
# Ajouter le profil hotspot
sudo nmcli con add type wifi ifname wlan0 con-name "Rpi-danse-Hotspot" ssid "Rpi-danse-Wifi" mode ap
sudo nmcli con modify "Rpi-danse-Hotspot" wifi-sec.key-mgmt wpa-psk wifi-sec.psk "MOT_DE_PASSE_HOTSPOT"
sudo nmcli con modify "Rpi-danse-Hotspot" ipv4.method shared ipv4.addresses "192.168.4.1/24"
sudo nmcli con modify "Rpi-danse-Hotspot" connection.autoconnect no
```

## 3. Créer le script de décision

```bash
sudo nano /usr/local/bin/wifi-autoconnect.sh
```

Contenu du script :

```bash
#!/bin/bash
TARGET_SSID="Rpi-danse-Wifi4"
TARGET_CON="Rpi-danse-Wifi4"
HOTSPOT_CON="hotspot"
IFACE="wlan0"

# Attendre que l'interface soit prête
sleep 10

# Scanner les réseaux disponibles
nmcli dev wifi rescan ifname "$IFACE" 2>/dev/null
sleep 5

# Vérifier si le SSID cible est visible
if nmcli -t -f SSID dev wifi list ifname "$IFACE" | grep -qx "$TARGET_SSID"; then
    echo "SSID $TARGET_SSID trouvé, connexion en cours..."
    nmcli con up "$TARGET_CON" ifname "$IFACE"
else
    echo "SSID $TARGET_SSID introuvable, démarrage du hotspot..."
    nmcli con up "$HOTSPOT_CON" ifname "$IFACE"
fi
```

```bash
sudo chmod +x /usr/local/bin/wifi-autoconnect.sh
```

## 4. Créer le service systemd

```bash
sudo nano /etc/systemd/system/wifi-autoconnect.service
```

Contenu :

```ini
[Unit]
Description=WiFi auto-connect ou hotspot
After=NetworkManager.service
Wants=NetworkManager.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/wifi-autoconnect.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable wifi-autoconnect.service
```

## 5. Tester sans redémarrer

```bash
sudo systemctl start wifi-autoconnect.service
sudo journalctl -u wifi-autoconnect.service -f
```

---

**Notes importantes :**
- Le `sleep 10` laisse le temps à NetworkManager de démarrer — ajustez si nécessaire
- Le hotspot partagera la connexion internet via `ipv4.method shared` (pratique si la Pi a une connexion ethernet en plus)
- Pour voir l'état : `nmcli con show` et `nmcli dev status`
- Si votre interface n'est pas `wlan0`, vérifiez avec `nmcli dev`
