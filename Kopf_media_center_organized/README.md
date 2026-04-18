# 🎵 Media Center — Organisierte Projektstruktur

Ein Media Center für Raspberry Pi mit Radio, YouTube und Hörbuch-Player,
gesteuert über zwei Arduino Nanos (I2C) und GPIO-Taster.

## Projektstruktur

```
media_center_organized/
├── README.md                          ← Diese Datei
├── ABHÄNGIGKEITEN.md                  ← Vollständige Abhängigkeitsliste
├── setup.sh                           ← Installationsskript für neuen Raspberry Pi
│
├── config/                            ← Konfigurationsdateien
│   ├── radio_stations.json            ← 11 Radio-Sender (Pos 0–10)
│   └── youtube_channels.json          ← 11 YouTube-Kanäle (Pos 0–10)
│
├── data/                              ← Laufzeitdaten (auto-generiert)
│   └── audiobook_progress.json        ← Hörbuch-Spielstände
│
├── audiobooks/                        ← Hörbuch-Dateien hierhin kopieren
│   └── (*.mp3, *.m4a, *.ogg, ...)
│
└── media_center/                      ← Python-Paket
    ├── __init__.py                    ← Paket-Initialisierung
    ├── __main__.py                    ← Entry-Point: python3 -m media_center
    ├── auswahl.py                     ← ⭐ Programmauswahl (Subprozess-Steuerung)
    ├── radio_player.py                ← Radio-Modul (VLC-Streams)
    ├── youtube_player.py              ← YouTube-Modul (yt-dlp + VLC)
    ├── audiobook_player.py            ← Hörbuch-Modul (VLC + Spielstand + TTS)
    ├── i2c_reader_program.py          ← I2C Reader: Arduino 2 (0x09, GPIO 17)
    ├── i2c_reader_content.py          ← I2C Reader: Arduino 1 (0x08, GPIO 16)
    └── core.py                        ← Monolithischer Kern (Legacy/Alternative)
```

## Schnellstart

```bash
# 1. In das Projektverzeichnis wechseln
cd media_center_organized

# 2. Media Center starten (Programmauswahl)
python3 -m media_center

# Alternativ direkt einen bestimmten Player starten:
python3 -m media_center.radio_player
python3 -m media_center.youtube_player
python3 -m media_center.audiobook_player
```

## Installation (neuer Raspberry Pi)

```bash
cd media_center_organized
chmod +x setup.sh
./setup.sh
# Dann Reboot und starten
```

Oder manuell — siehe [ABHÄNGIGKEITEN.md](ABHÄNGIGKEITEN.md).

## Hardware

### Arduinos (I2C)

| Arduino | I2C-Adresse | Funktion | Interrupt-GPIO | I2C Reader |
|---------|-------------|----------|----------------|------------|
| Arduino 1 | `0x08` | Inhaltswahl + Lautstärke | GPIO 16 | `i2c_reader_content.py` |
| Arduino 2 | `0x09` | Programmwahl + Tonhöhe | GPIO 17 | `i2c_reader_program.py` |

### GPIO-Taster

| GPIO | Pin | Funktion |
|------|-----|----------|
| 22 | Pin 15 | Play/Pause |
| 23 | Pin 16 | Vorwärts / +30s / +2min (lang) |
| 24 | Pin 18 | Rückwärts / -30s / -2min (lang) |

### Drehschalter-Belegung (Arduino 2 → Programmwahl)

| Position | Programm |
|----------|----------|
| 0 | Radio |
| 1 | YouTube |
| 2 | Hörbuch |
| 3–10 | (erweiterbar) |

## Architektur

```
auswahl.py  (Hauptprozess)
│
├── Liest Arduino 2 (i2c_reader_program.py)
│   → Drehschalter = Programmwahl
│
└── Startet Subprozess je nach Programm:
    ├── radio_player.py     → VLC-Streams, I2C Arduino 1
    ├── youtube_player.py   → yt-dlp + VLC, I2C Arduino 1, Taster
    └── audiobook_player.py → VLC lokal, I2C Arduino 1, Taster, Spielstand
```

Jeder Player läuft als eigenständiger Subprozess und wird beim
Programmwechsel sauber beendet (SIGTERM). So gibt es keine Konflikte
zwischen GPIO, VLC oder I2C.

## Änderungen gegenüber Original

| Original | Organisiert | Änderung |
|----------|-------------|----------|
| `i2c_reader_grün.py` | `i2c_reader_program.py` | Umlaut entfernt, im Paket |
| `i2c_reader_simple.py` (in `src/`) | `i2c_reader_content.py` | Ins Paket verschoben |
| `audiobook_player_V4c.py` | `audiobook_player.py` | Versions-Suffix entfernt |
| `media_center.py` | `core.py` | Umbenannt (vermeidet Paket-Namenskonflikt) |
| `media_center_fixed.py` | (entfernt) | War nur Wrapper |
| `main.py` | `__main__.py` | Standard Python-Konvention |
| JSON-Dateien im Paket | `config/` | Konfiguration vom Code getrennt |
| `audiobook_progress.json` in `raspberry/` | `data/` | Laufzeitdaten zentral |
| `~/MediaCenter/audiobooks/` | `audiobooks/` | Im Projektverzeichnis |
| `sys.path`-Hacks + `importlib` | Saubere Paket-Imports | Keine Pfad-Manipulation mehr |

## Lizenz

MIT License — frei für persönliche und kommerzielle Nutzung.
