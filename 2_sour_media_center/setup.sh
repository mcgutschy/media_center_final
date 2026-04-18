#!/bin/bash
# === Media Center: Vollständige Installation auf neuem Raspberry Pi ===
#
# Aufruf:
#   chmod +x setup.sh
#   ./setup.sh

set -e

echo ""
echo "============================================="
echo "  📦 Media Center - Setup"
echo "============================================="
echo ""

echo "=== 1. System aktualisieren ==="
sudo apt update && sudo apt upgrade -y

echo ""
echo "=== 2. I2C aktivieren ==="
sudo raspi-config nonint do_i2c 0    # 0 = enable
echo "✅ I2C aktiviert"

echo ""
echo "=== 3. APT-Pakete installieren ==="
sudo apt install -y \
    python3-smbus \
    python3-rpi.gpio \
    python3-gpiozero \
    python3-vlc \
    vlc \
    libttspico-utils \
    alsa-utils \
    i2c-tools
echo "✅ System-Pakete installiert"

echo ""
echo "=== 4. pip-Pakete installieren ==="
pip3 install yt-dlp
echo "✅ pip-Pakete installiert"

echo ""
echo "=== 5. Benutzer in Gruppen aufnehmen ==="
sudo usermod -aG i2c "$USER"
sudo usermod -aG gpio "$USER"
sudo usermod -aG audio "$USER"
echo "✅ Benutzer in i2c, gpio, audio Gruppen"

echo ""
echo "=== 6. Verzeichnisse erstellen ==="
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$SCRIPT_DIR/audiobooks"
mkdir -p "$SCRIPT_DIR/data"
echo "✅ audiobooks/ und data/ erstellt"

echo ""
echo "=== 7. I2C-Bus prüfen ==="
echo "Verbundene I2C-Geräte:"
sudo i2cdetect -y 1 || echo "⚠️  I2C-Scan fehlgeschlagen"

echo ""
echo "============================================="
echo "  ✅ Installation abgeschlossen!"
echo "============================================="
echo ""
echo "Nächste Schritte:"
echo "  1. Neu einloggen oder Reboot (für Gruppen-Mitgliedschaft)"
echo "  2. Audio-Ausgabe prüfen: aplay -l"
echo "  3. Hörbuch-Dateien kopieren nach: $SCRIPT_DIR/audiobooks/"
echo "  4. Starten:"
echo "     cd $SCRIPT_DIR"
echo "     python3 -m media_center"
echo ""
