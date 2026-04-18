#!/bin/bash
# === Media Center: systemd-Service installieren ===
#
# Installiert den Media-Center-Service für Autostart beim Booten.
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
echo "  🔧 Media Center - Service installieren"
echo "============================================="
echo ""

if [ ! -f "$SERVICE_FILE" ]; then
    echo "❌ Service-Datei nicht gefunden: $SERVICE_FILE"
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
echo "  ✅ Service installiert und gestartet!"
echo "============================================="
echo ""
echo "Nützliche Befehle:"
echo "  sudo systemctl status media-center    # Status anzeigen"
echo "  sudo systemctl stop media-center      # Stoppen"
echo "  sudo systemctl start media-center     # Starten"
echo "  sudo systemctl restart media-center   # Neustarten"
echo "  sudo systemctl disable media-center   # Autostart deaktivieren"
echo "  journalctl -u media-center -f         # Live-Logs anzeigen"
echo ""
