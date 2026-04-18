#!/bin/bash
# === Media Center GPIO4 Selector: systemd-Service installieren ===
#
# Installiert den GPIO4-Selector-Service für Autostart beim Booten.
# Der Selector überwacht GPIO 4 und schaltet zwischen
# media_center (AMP2/Lautsprecher) und kopf_media_center (3.5mm/Kopfhörer) um.
#
# Aufruf:
#   chmod +x install-service.sh
#   ./install-service.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_FILE="$SCRIPT_DIR/media-center.service"
TARGET="/etc/systemd/system/media-center.service"

echo ""
echo "============================================="
echo "  🔧 Media Center GPIO4 Selector - Service installieren"
echo "============================================="
echo ""

if [ ! -f "$SERVICE_FILE" ]; then
    echo "❌ Service-Datei nicht gefunden: $SERVICE_FILE"
    exit 1
fi

if [ ! -f "$SCRIPT_DIR/gpio4_selector.py" ]; then
    echo "❌ gpio4_selector.py nicht gefunden: $SCRIPT_DIR/gpio4_selector.py"
    exit 1
fi

echo "📁 Projektverzeichnis: $SCRIPT_DIR"
echo "👤 Benutzer: $(whoami)"
echo ""

# Service-Datei kopieren
echo "=== 1. Service-Datei kopieren ==="
sudo cp "$SERVICE_FILE" "$TARGET"
echo "✅ Kopiert nach $TARGET"

# Pfade in der Service-Datei an aktuelle Installation anpassen
echo ""
echo "=== 2. Pfade aktualisieren ==="
sudo sed -i "s|User=.*|User=$(whoami)|" "$TARGET"
sudo sed -i "s|WorkingDirectory=.*|WorkingDirectory=$SCRIPT_DIR|" "$TARGET"
sudo sed -i "s|ExecStart=.*|ExecStart=/usr/bin/python3 $SCRIPT_DIR/gpio4_selector.py|" "$TARGET"
sudo sed -i "s|Environment=HOME=.*|Environment=HOME=$HOME|" "$TARGET"
echo "✅ Pfade angepasst für Benutzer '$(whoami)' in '$SCRIPT_DIR'"

# systemd neu laden
echo ""
echo "=== 3. systemd neu laden ==="
sudo systemctl daemon-reload
echo "✅ systemd-Konfiguration neu geladen"

# Service aktivieren (Autostart)
echo ""
echo "=== 4. Service aktivieren ==="
sudo systemctl enable media-center.service
echo "✅ Autostart aktiviert"

# Service starten
echo ""
echo "=== 5. Service jetzt starten ==="
sudo systemctl start media-center.service
sleep 2

# Status anzeigen
echo ""
echo "=== Status ==="
sudo systemctl status media-center.service --no-pager || true

echo ""
echo "============================================="
echo "  ✅ GPIO4 Selector-Service installiert und gestartet!"
echo "============================================="
echo ""
echo "GPIO 4 Steuerung:"
echo "  HIGH (offen)  → media_center (HifiBerry AMP2)"
echo "  LOW (Masse)   → kopf_media_center (3.5mm Klinke)"
echo ""
echo "Nützliche Befehle:"
echo "  sudo systemctl status media-center    # Status anzeigen"
echo "  sudo systemctl stop media-center      # Stoppen"
echo "  sudo systemctl start media-center     # Starten"
echo "  sudo systemctl restart media-center   # Neustarten"
echo "  sudo systemctl disable media-center   # Autostart deaktivieren"
echo "  journalctl -u media-center -f         # Live-Logs anzeigen"
echo ""
