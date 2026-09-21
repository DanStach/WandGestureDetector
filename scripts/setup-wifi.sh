#!/usr/bin/env bash
# Connect the Pi to a Wi-Fi network (default SSID: Pan) via NetworkManager.
# Run on the Pi: ./scripts/setup-wifi.sh [SSID]
# The password is prompted for (not stored in the repo or shell history).
set -euo pipefail

SSID="${1:-Pan}"

# Unblock the radio (Wi-Fi country must be set on first boot or it stays blocked)
sudo rfkill unblock wifi
if ! iw reg get 2>/dev/null | grep -q '^country [A-Z][A-Z]'; then
  sudo raspi-config nonint do_wifi_country US
fi

read -rsp "Password for '$SSID': " PSK
echo

# autoconnect is on by default, so the profile persists across reboots
sudo nmcli device wifi rescan || true
sudo nmcli device wifi connect "$SSID" password "$PSK"
unset PSK

nmcli -f GENERAL.CONNECTION,IP4.ADDRESS device show wlan0
echo "Connected. Web UI: http://$(hostname -I | awk '{print $1}'):8000"
