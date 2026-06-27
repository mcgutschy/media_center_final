# 🎵 Media Center — Raspberry Pi Internetradio

**Headless Media Center für blinde Nutzer — komplett ohne Display bedienbar.**

Ein selbstgebautes Internetradio und Streaming-Media-Center im lasergeschnittenen
MDF-Gehäuse. Zwei Lonpoo-Vollbereichslautsprecher (75 W) liefern Stereoklang,
angetrieben vom **HifiBerry AMP2** auf einem **Raspberry Pi 4**.
Zwei große Drehschalter mit je 11 Positionen — einer wählt das Programm
(Internetradio, YouTube, Hörbuch), der andere die Station bzw. den Kanal.

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Raspberry Pi](https://img.shields.io/badge/Raspberry%20Pi-4B-red.svg)](https://www.raspberrypi.com/)
[![Python](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://python.org)

---

## Hardware

| Komponente | Typ |
|---|---|
| Einplatinencomputer | Raspberry Pi 4 (SSD via USB-SATA-Adapter) |
| Verstärker | HifiBerry AMP2 Class-D HAT (2× 60 W, I²S) |
| Mikrocontroller | 2× Arduino Nano (I²C-Slaves: 0x08, 0x09) |
| Pegelwandler | 3,3 V ↔ 5 V Logic Level Shifter |
| Bedienung | 2× Drehschalter (11 Pos.), Potentiometer (Lautstärke) |
| Audio | 2× Lonpoo 75 W Vollbereich, Kopfhörerausgang |
| Stromversorgung | 20 V / 4 A Netzteil |
| Gehäuse | Lasergeschnittenes MDF, 6 mm (Onshape) |

## Software-Architektur

```
2_sour_media_center/
├── media_center/              ← Python-Paket AMP2 (Soundkarte 3)
│   ├── auswahl.py             ← Programmauswahl
│   ├── radio_player.py        ← mpd + mpc
│   ├── youtube_player.py      ← yt-dlp
│   ├── audiobook_player.py    ← VLC + TTS
│   ├── i2c_reader_program.py  ← I²C → Arduino 2 (0x09, GPIO 17)
│   └── i2c_reader_content.py  ← I²C → Arduino 1 (0x08, GPIO 16)
│
├── kopf_media_center/         ← Python-Paket Kopfhörer (Soundkarte 2)
│   └── (identische Struktur)
│
├── gpio4_selector.py          ← Audio-Umschaltung AMP2/Kopfhörer
├── media-center.service       ← systemd-Service
├── config/                    ← 11 Radio-Stationen + 11 YouTube-Kanäle (JSON)
├── data/                      ← Hörbuch-Spielstände
└── audiobooks/                ← MP3-Hörbücher
```

## Fernzugriff

- **Tailscale Mesh-VPN** (bevorzugt) — Pi ist von überall per `ssh` erreichbar
- **Reverse-SSH-Tunnel** (Fallback) — systemd-Service auf Port 2222
- **FileBrowser-Server** auf [media.b481.de](https://media.b481.de) — Konfiguration per Web-UI, Pi pullt alle 10 Min per Cron

## Schnellstart

```bash
cd 2_sour_media_center
python3 -m media_center
```

Ausführliche Anleitung: [2_sour_media_center/README.md](2_sour_media_center/README.md)

## Infrastruktur

Der komplette Server-Stack ist dokumentiert und reproduzierbar:

- **VPS** (Debian 13): Nginx, FileBrowser, PHP-Admin-Panel
- **Demo-Modus**: [media.b481.de/demo/](https://media.b481.de/demo/) (demo/demo2026)
- **WiFi-Remote**: Poll-basierte Kommandozentrale für Netzwerkwechsel
- **Cron-Sync**: Alle 10 Minuten Konfiguration + Hörbücher synchronisieren

## Projektseite

→ [b481.de/media-center](https://b481.de/media-center/) — Galerie, Schaltplan, Komponenten, Bezugsquellen

## Lizenz

MIT — siehe [LICENSE](LICENSE)

---

*Gebaut von Michael Holz · Entwickelt mit KI-Unterstützung (DeepSeek, GLM, Hermes Agent)*
