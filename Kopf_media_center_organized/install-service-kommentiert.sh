#!/bin/bash
# Shebang: Teilt dem System mit, dass dieses Skript mit der Bash-Shell ausgeführt werden soll.

# === Media Center: systemd-Service installieren ===
# Hauptbeschreibung: Dieses Skript installiert den Media-Center-Service für den Autostart beim Booten.

# Aufruf:
#   chmod +x install-service.sh    # Macht das Skript ausführbar
#   ./install-service.sh           # Führt das Skript aus

set -e
# Fehlerbehandlung: Beendet das Skript sofort, wenn ein Befehl fehlschlägt (Exit-Code ≠ 0).

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# Ermittelt das Verzeichnis, in dem dieses Skript liegt, als absoluten Pfad.
# $0 ist der Pfad, wie das Skript aufgerufen wurde (relativ oder absolut).
# dirname extrahiert das Verzeichnis aus diesem Pfad.
# cd wechselt in dieses Verzeichnis, pwd gibt den absoluten Pfad zurück.
# Das garantiert, dass SCRIPT_DIR immer korrekt ist, egal von wo das Skript aufgerufen wird.

SERVICE_FILE="$SCRIPT_DIR/media-center.service"
# Definiert den Pfad zur Service-Datei im Projektverzeichnis.
# Nutzt SCRIPT_DIR, um den absoluten Pfad zu erhalten.

TARGET="/etc/systemd/system/media-center.service"
# Definiert den Zielpfad für die Service-Datei im System.
# /etc/systemd/system/ ist der Standardort für benutzerdefinierte systemd-Services.

echo ""
# Gibt eine leere Zeile für bessere Lesbarkeit aus.

echo "============================================="
# Gibt eine Trennzeile für die Überschrift aus.

echo "  🔧 Media Center - Service installieren"
# Gibt den Titel des Skripts mit Emoji für bessere Übersichtlichkeit aus.

echo "============================================="
# Schließt die Überschrift mit einer Trennzeile ab.

echo ""
# Gibt eine weitere leere Zeile für Abstand aus.

if [ ! -f "$SERVICE_FILE" ]; then
    # Prüft, ob die Service-Datei NICHT existiert (-f testet auf reguläre Datei, ! negiert).
    # Anführungszeichen um $SERVICE_FILE verhindern Probleme mit Leerzeichen im Pfad.
    
    echo "❌ Service-Datei nicht gefunden: $SERVICE_FILE"
    # Gibt eine Fehlermeldung mit dem erwarteten Pfad aus, wenn die Datei fehlt.
    
    exit 1
    # Beendet das Skript mit Exit-Code 1 (allgemeiner Fehler).
    # Das verhindert, dass das Skript ohne die nötige Datei weiterläuft.
fi
# Beendet den if-Block.

echo "📁 Projektverzeichnis: $SCRIPT_DIR"
# Informiert den Benutzer über das gefundene Projektverzeichnis für Transparenz.

echo "👤 Benutzer: $(whoami)"
# Zeigt den aktuellen Benutzernamen an, der das Skript ausführt.
# whoami gibt den Benutzernamen zurück, $(...) führt den Befehl aus und setzt die Ausgabe ein.

echo ""
# Leere Zeile für bessere Formatierung vor dem ersten Arbeitsschritt.

# Service-Datei kopieren
echo "=== 1. Service-Datei kopieren ==="
# Überschrift für den ersten Arbeitsschritt: Service-Datei kopieren.

sudo cp "$SERVICE_FILE" "$TARGET"
# Kopiert die Service-Datei von Quelle nach Ziel.
# sudo ist nötig, weil /etc/systemd/system/ Root-Rechte erfordert.
# cp (copy) kopiert Dateien; Anführungszeichen schützen vor Leerzeichenproblemen.

echo "✅ Kopiert nach $TARGET"
# Bestätigt dem Benutzer, dass der Kopiervorgang erfolgreich war.

# Pfade in der Service-Datei an aktuelle Installation anpassen
echo ""
# Leere Zeile zwischen den Schritten.

echo "=== 2. Pfade aktualisieren ==="
# Überschrift für den zweiten Arbeitsschritt: Pfade anpassen.

sudo sed -i "s|User=.*|User=$(whoami)|" "$TARGET"
# sed (stream editor) ändert Text in der Datei.
# -i: Ändert die Datei direkt (in-place), nicht nur Anzeige.
# s|...|...|: Sucht und ersetzt (substitute).
# User=.*: Sucht "User=" gefolgt von allem (.*) bis Zeilenende.
# Ersetzt durch "User=" + aktueller Benutzername (whoami).

sudo sed -i "s|WorkingDirectory=.*|WorkingDirectory=$SCRIPT_DIR|" "$TARGET"
# Ersetzt WorkingDirectory durch das aktuelle Skript-Verzeichnis.
# Das stellt sicher, dass der Service im richtigen Verzeichnis arbeitet.

sudo sed -i "s|Environment=HOME=.*|Environment=HOME=$HOME|" "$TARGET"
# Ersetzt HOME-Umgebungsvariable durch das HOME des aktuellen Benutzers.
# $HOME ist automatisch gesetzt (z.B. /home/sinnie).

echo "✅ Pfade angepasst für Benutzer '$(whoami)' in '$SCRIPT_DIR'"
# Bestätigt die Anpassungen mit Details für den Benutzer.

# systemd neu laden
echo ""
# Leere Zeile vor dem nächsten Schritt.

echo "=== 3. systemd neu laden ==="
# Überschrift für den dritten Schritt: systemd-Konfiguration neu laden.

sudo systemctl daemon-reload
# Lädt die systemd-Konfiguration neu, damit systemd die neue Service-Datei erkennt.
# Notwendig nach jeder Änderung an Service-Dateien.

echo "✅ systemd-Konfiguration neu geladen"
# Bestätigt, dass systemd die neue Konfiguration geladen hat.

# Service aktivieren (Autostart)
echo ""
# Leere Zeile für Formatierung.

echo "=== 4. Service aktivieren ==="
# Überschrift für den vierten Schritt: Autostart aktivieren.

sudo systemctl enable media-center.service
# Aktiviert den Service für den Autostart beim Booten.
# Erstellt Symlinks in den systemd-Target-Verzeichnissen.

echo "✅ Autostart aktiviert"
# Bestätigt, dass der Service beim nächsten Booten automatisch startet.

# Service starten
echo ""
# Leere Zeile vor dem Start-Befehl.

echo "=== 5. Service jetzt starten ==="
# Überschrift für den fünften Schritt: Service sofort starten.

sudo systemctl start media-center.service
# Startet den Service sofort, ohne auf einen Neustart zu warten.

sleep 2
# Wartet 2 Sekunden, damit der Service Zeit zum Starten hat.
# Das gibt dem Service Zeit, Status zu melden.

# Status anzeigen
echo ""
# Leere Zeile vor der Statusanzeige.

echo "=== Status ==="
# Überschrift für die Statusanzeige.

sudo systemctl status media-center.service --no-pager || true
# Zeigt den aktuellen Status des Services an.
# --no-pager: Verhindert, dass less/more für die Ausgabe genutzt werden.
# || true: Ignoriert Fehler, falls der Service nicht läuft (set -e umgehen).

echo ""
# Leere Zeile für Abschlussnachricht.

echo "============================================="
# Trennzeile für Abschlussbox.

echo "  ✅ Service installiert und gestartet!"
# Erfolgsmeldung: Der Service wurde erfolgreich installiert und gestartet.

echo "============================================="
# Abschluss der Box.

echo ""
# Leere Zeile vor den nützlichen Befehlen.

echo "Nützliche Befehle:"
# Einleitung für die Liste nützlicher Befehle.

echo "  sudo systemctl status media-center    # Status anzeigen"
# Zeigt den aktuellen Status des Services an (läuft, gestoppt, Fehler).

echo "  sudo systemctl stop media-center      # Stoppen"
# Stoppt den laufenden Service sofort.

echo "  sudo systemctl start media-center     # Starten"
# Startet den Service manuell (falls er gestoppt wurde).

echo "  sudo systemctl restart media-center   # Neustarten"
# Startet den Service neu (stopp + start in einem).

echo "  sudo systemctl disable media-center   # Autostart deaktivieren"
# Deaktiviert den Autostart - Service startet nicht mehr beim Booten.

echo "  journalctl -u media-center -f         # Live-Logs anzeigen"
# Zeigt die Logs des Services in Echtzeit an (-f = follow, wie tail -f).

echo ""
# Letzte leere Zeile zum Abschluss.
