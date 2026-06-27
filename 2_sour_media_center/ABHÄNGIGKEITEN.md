# 📦 Abhängigkeiten & Installationsanleitung — Media Center

> **Ziel:** Alle Abhängigkeiten dokumentieren, die für einen Umzug auf einen neuen Raspberry Pi
> oder eine Neuinstallation benötigt werden.
>
> **Haupteinstieg:** `cd media_center_organized && python3 -m media_center`

---

## 1️⃣ Systemvoraussetzungen

| Komponente | Minimum | Empfohlen |
|---|---|---|
| Raspberry Pi | Pi 3B | Pi 4B / Pi 5 |
| OS | Raspberry Pi OS (Bookworm) | Raspberry Pi OS (64-bit) |
| Python | 3.9+ | 3.11+ |
| Audio-Ausgang | 3,5 mm Klinke / USB-Soundkarte | USB-Soundkarte (Karte 2) |
| I2C | aktiviert | aktiviert |

---

## 2️⃣ Raspberry Pi Konfiguration

### I2C aktivieren

```bash
sudo raspi-config
# → Interface Options → I2C → Enable
```

### Benutzer in Gruppen aufnehmen

```bash
sudo usermod -aG i2c $USER
sudo usermod -aG gpio $USER
sudo usermod -aG audio $USER
# Danach neu einloggen oder Reboot
```

---

## 3️⃣ APT-Pakete (System-Ebene)

```bash
sudo apt update
sudo apt install -y \
    python3-smbus \
    python3-rpi.gpio \
    python3-gpiozero \
    python3-vlc \
    vlc \
    libttspico-utils \
    alsa-utils \
    i2c-tools
```

| APT-Paket | Python-Modul | Verwendet in | Zweck |
|---|---|---|---|
| `python3-smbus` | `smbus` | `i2c_reader_program.py`, `i2c_reader_content.py`, `core.py` | I2C-Kommunikation |
| `python3-rpi.gpio` | `RPi.GPIO` | `core.py`, `youtube_player.py`, `audiobook_player.py` | GPIO-Steuerung |
| `python3-gpiozero` | `gpiozero` | `i2c_reader_program.py`, `i2c_reader_content.py` | GPIO-Interrupts |
| `python3-vlc` | `vlc` | `radio_player.py`, `youtube_player.py`, `audiobook_player.py` | VLC-Bindings |
| `vlc` | — | (von `python3-vlc` benötigt) | VLC Media Player |
| `libttspico-utils` | — (`pico2wave`) | `auswahl.py`, `youtube_player.py`, `audiobook_player.py` | Text-to-Speech |
| `alsa-utils` | — (`aplay`, `amixer`, `speaker-test`) | `auswahl.py`, `youtube_player.py`, `audiobook_player.py` | Audio-Werkzeuge |
| `i2c-tools` | — (`i2cdetect`) | Diagnose | I2C-Bus scannen |

---

## 4️⃣ pip-Pakete

```bash
sudo pip3 install yt-dlp --break-system-packages
```

| pip-Paket | Verwendet in | Zweck |
|---|---|---|
| `yt-dlp` | `youtube_player.py` | YouTube-Videos abrufen (CLI-Tool) |

> **Hinweis:** Regelmäßig aktualisieren: `sudo pip3 install -U yt-dlp --break-system-packages`
>
> **Automatisches Update per Cron (empfohlen):**
> ```bash
> sudo crontab -e
> # Zeile einfügen:
> # 0 4 * * * pip3 install -U yt-dlp --break-system-packages -q
> ```

---

## 5️⃣ Python Standard-Bibliothek (keine Installation nötig)

`os`, `sys`, `time`, `signal`, `subprocess`, `json`, `re`, `threading`,
`pathlib`, `importlib`, `traceback`, `urllib.request`, `urllib.error`

---

## 6️⃣ Externe CLI-Tools (via subprocess)

| Tool | APT-Paket | Verwendet in |
|---|---|---|
| `pico2wave` | `libttspico-utils` | TTS-Ansage |
| `aplay` | `alsa-utils` | WAV-Wiedergabe |
| `amixer` | `alsa-utils` | Lautstärke-Regelung |
| `speaker-test` | `alsa-utils` | Piepton-Feedback |
| `yt-dlp` | pip: `yt-dlp` | YouTube-Audio-URLs |

---

## 7️⃣ Audio-Konfiguration

VLC wird mit ALSA-Gerät `plughw:2,0` gestartet. Falls sich die Soundkarten-Nummer
ändert, anpassen in:
- `radio_player.py` — Zeile mit `audio_options`
- `youtube_player.py` — Zeile mit `options`
- `audiobook_player.py` — Zeile mit `options`

```bash
# Soundkarten auflisten:
aplay -l
```

---

## 8️⃣ Daten- und Konfigurationsdateien

| Datei | Ort | Manuell pflegen? |
|---|---|---|
| `radio_stations.json` | `config/` | ✅ Ja |
| `youtube_channels.json` | `config/` | ✅ Ja |
| `audiobook_progress.json` | `data/` | ❌ Auto-generiert |

### Hörbuch-Verzeichnis

```bash
# Unterstützte Formate: .mp3, .mp4, .m4a, .ogg, .wav, .flac, .aac
# Dateien kopieren nach:
media_center_organized/audiobooks/
```

---

## 🚀 Komplettes Setup

```bash
cd media_center_organized
chmod +x setup.sh
./setup.sh
```

---

## 🔍 Diagnose

```bash
sudo i2cdetect -y 1                                    # I2C prüfen
aplay -l                                                # Audio-Geräte
pico2wave -l de-DE -w /tmp/test.wav "Hallo" && aplay /tmp/test.wav  # TTS
yt-dlp --version                                        # yt-dlp
python3 -c "import smbus, RPi.GPIO, gpiozero, vlc; print('OK')"    # Module
groups | grep -E "(gpio|i2c|audio)"                     # Berechtigungen
cd media_center_organized && python3 -m media_center    # Starten
```

---

## 📋 Zusammenfassung

| # | Was | Installationsbefehl | Typ |
|---|---|---|---|
| 1 | `python3-smbus` | `sudo apt install python3-smbus` | APT |
| 2 | `python3-rpi.gpio` | `sudo apt install python3-rpi.gpio` | APT |
| 3 | `python3-gpiozero` | `sudo apt install python3-gpiozero` | APT |
| 4 | `python3-vlc` | `sudo apt install python3-vlc` | APT |
| 5 | `vlc` | `sudo apt install vlc` | APT |
| 6 | `libttspico-utils` | `sudo apt install libttspico-utils` | APT |
| 7 | `alsa-utils` | `sudo apt install alsa-utils` | APT |
| 8 | `i2c-tools` | `sudo apt install i2c-tools` | APT |
| 9 | `yt-dlp` | `sudo pip3 install yt-dlp --break-system-packages` | pip |

---

*Erstellt am 20.03.2026 — basierend auf Quellcode-Analyse aller Module.*
