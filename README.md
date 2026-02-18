**Wifi setup**
***Raspberry 5*** : 
- Attuned connexion :IP Fixe 192.168.0.7
- Hotspot : SSID : rpi-danse-WIFI password : rpidanse
***Raspberry 4b*** :
- Attuned connexion :IP Fixe 192.168.0.4
- Hotspot : SSID : rpi-danse-WIFI4 password : rpidanse

Be careful to add the IP of the 2nd computer in the .py file for the two case : hotspot and router Attuned, maybe define an ip fix on the client in case the dhcp change the ip at each reboot

**Trial setup**
Once the connection between Pi and PC is set, connect through ssh to the Pi
Run pd_2_haply.py for the first trial then haply_2_pd.py for the second. 
The equivalent .pd files are run on the PC separately. 
