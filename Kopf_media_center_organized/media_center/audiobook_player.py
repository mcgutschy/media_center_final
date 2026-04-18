#!/usr/bin/env python3
"""
Hörbuch-Player - Optimiert

Bedienung:
  - GPIO 22 (Pin 15): Play/Pause
  - GPIO 23 (Pin 16): +30s vorspulen  (lang gedrückt: +2 Minuten, wiederholend)
  - GPIO 24 (Pin 18): -30s zurückspulen (lang gedrückt: -2 Minuten, wiederholend)
  - Arduino Nano I2C: Drehschalter für Dateiauswahl, Poti für Lautstärke

Features:
  - Speichert die Wiedergabeposition für jedes Hörbuch
  - Beim Wechsel zu einem anderen Hörbuch wird die letzte Position wiederhergestellt
  - Vorlesen des Dateinamens beim Wechsel (TTS mit pico2wave)

Installation:
  sudo apt install libttspico-utils alsa-utils python3-vlc vlc

Anschluss: Taster zwischen GPIO-Pin und GND

Umbenannt von: audiobook_player_V4c.py → audiobook_player.py

Starten:
  cd media_center_organized
  python3 -m media_center.audiobook_player
"""

import os
import time
import signal
import sys
import json
import subprocess
import re
import threading
from pathlib import Path

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    print("⚠️  RPi.GPIO nicht verfügbar - Simulation ohne Hardware")
    GPIO_AVAILABLE = False

try:
    import vlc
    VLC_AVAILABLE = True
except ImportError:
    print("⚠️  python-vlc nicht installiert: sudo apt install python3-vlc vlc")
    VLC_AVAILABLE = False

# I2C Reader importieren
try:
    from media_center.i2c_reader_content import SimpleI2CReader
    I2C_AVAILABLE = True
except ImportError:
    print("⚠️  i2c_reader_content.py nicht gefunden - keine Nano-Steuerung")
    I2C_AVAILABLE = False


def _check_tts_available():
    """Prüft ob pico2wave und aplay verfügbar sind"""
    try:
        subprocess.run(['which', 'pico2wave'], check=True, capture_output=True)
        subprocess.run(['which', 'aplay'], check=True, capture_output=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


TTS_AVAILABLE = _check_tts_available()
if not TTS_AVAILABLE:
    print("⚠️  pico2wave oder aplay nicht gefunden - keine TTS-Ansage")
    print("    Installieren mit: sudo apt install libttspico-utils alsa-utils")

# ── Konfiguration ────────────────────────────────────────────────────

BUTTON_PLAY_PAUSE = 22   # GPIO 22, Pin 15
BUTTON_FORWARD = 23      # GPIO 23, Pin 16
BUTTON_BACKWARD = 24     # GPIO 24, Pin 18

SKIP_SECONDS = 30
LONG_PRESS_THRESHOLD = 1.0   # Sekunden bis langes Spulen
LONG_SKIP_MINUTES = 2
LONG_SKIP_MS = LONG_SKIP_MINUTES * 60 * 1000

BEEP_FREQUENCY = 800
BEEP_DURATION = 0.012

AUDIO_EXTENSIONS = frozenset(('.mp3', '.mp4', '.m4a', '.ogg', '.wav', '.flac', '.aac'))
SAVE_INTERVAL = 10  # Sekunden zwischen automatischen Speicherungen

# Richtungs-Konstanten
FORWARD = 1
BACKWARD = -1

# Verzeichnisse (relativ zum Projekt-Root)
MODULE_DIR = Path(__file__).parent
PROJECT_DIR = MODULE_DIR.parent
AUDIOBOOKS_DIR = PROJECT_DIR / "audiobooks"
PROGRESS_FILE = PROJECT_DIR / "data" / "audiobook_progress.json"


class AudiobookPlayer:
    """Hörbuch-Player mit Spielstand-Speicherung, TTS-Ansage und I2C-Steuerung"""

    def __init__(self):
        self.running = True
        self.player = None
        self.instance = None
        self.current_file = None
        self.is_paused = False
        self.current_volume = 50

        # Hörbuch-Liste und aktueller Index
        self.audiobook_files = []
        self.current_index = -1
        self.last_switch_position = -1

        # I2C Reader
        self.i2c_reader = None

        # Spielstand-Speicherung: {dateipfad: position_in_ms}
        self.playback_positions = {}
        self._load_progress()

        # Button-Zustand: Play/Pause Flanken-Erkennung
        self._play_btn_was_pressed = False

        # Button-Zustand: Forward/Backward (langes Spulen)
        self._btn_state = {
            FORWARD:  {'press_start': None, 'long_active': False, 'last_skip': 0},
            BACKWARD: {'press_start': None, 'long_active': False, 'last_skip': 0},
        }
        self._was_playing_before_skip = False

        # Zeitstempel für periodisches Speichern
        self._last_save_time = 0.0

        # Hardware-Initialisierung
        if GPIO_AVAILABLE:
            self._setup_gpio()
        if VLC_AVAILABLE:
            self._init_vlc()

        AUDIOBOOKS_DIR.mkdir(parents=True, exist_ok=True)
        self._load_audiobook_list()

        if I2C_AVAILABLE:
            try:
                self.i2c_reader = SimpleI2CReader()
                print("✅ I2C Reader initialisiert")
            except Exception as e:
                print(f"⚠️  I2C Fehler: {e}")

        self._print_startup_info()

    # ── Initialisierung ──────────────────────────────────────────────

    def _setup_gpio(self):
        """GPIO konfigurieren"""
        try:
            GPIO.setmode(GPIO.BCM)
            for pin in (BUTTON_PLAY_PAUSE, BUTTON_FORWARD, BUTTON_BACKWARD):
                GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            print("✅ GPIO konfiguriert")
        except Exception as e:
            print(f"⚠️  GPIO Fehler: {e}")

    def _init_vlc(self):
        """VLC initialisieren"""
        options = [
            '--no-video',
            '--aout=alsa',
            '--alsa-audio-device=plughw:2,0',
            '--file-caching=2000',
            '--network-caching=2000',
            '--clock-jitter=0',
            '--clock-synchro=0',
        ]
        try:
            self.instance = vlc.Instance(*options)
        except Exception as e:
            print(f"⚠️  VLC ALSA-Optionen fehlgeschlagen: {e}")
            self.instance = vlc.Instance('--no-video')
        self.player = self.instance.media_player_new()
        print("✅ VLC initialisiert")

    def _print_startup_info(self):
        """Zeigt Startinformationen an"""
        tts_status = "✅ TTS-Ansage aktiviert" if TTS_AVAILABLE else "⚠️  TTS nicht verfügbar"
        sep = "=" * 50
        print(f"\n{sep}")
        print("📚 HÖRBUCH-PLAYER (Mit Spielstand + TTS)")
        print(sep)
        print(f"Verzeichnis: {AUDIOBOOKS_DIR}")
        print(f"{len(self.audiobook_files)} Hörbuch-Dateien gefunden")
        print("Taster:")
        print(f"  GPIO {BUTTON_PLAY_PAUSE} (Pin 15): Play/Pause")
        print(f"  GPIO {BUTTON_FORWARD} (Pin 16): +{SKIP_SECONDS}s / +{LONG_SKIP_MINUTES}min (lang)")
        print(f"  GPIO {BUTTON_BACKWARD} (Pin 18): -{SKIP_SECONDS}s / -{LONG_SKIP_MINUTES}min (lang)")
        print("Nano 1 I2C: Drehschalter (Datei), Poti (Lautstärke)")
        print(tts_status)
        print(f"\n💾 Spielstände werden in: {PROGRESS_FILE}")
        print(f"{sep}\n")
        self._list_audiobooks()

    # ── Hörbuch-Verwaltung ───────────────────────────────────────────

    def _load_audiobook_list(self):
        """Lädt alle Hörbuch-Dateien in eine sortierte Liste"""
        if not AUDIOBOOKS_DIR.exists():
            self.audiobook_files = []
            return
        self.audiobook_files = sorted(
            str(f) for f in AUDIOBOOKS_DIR.iterdir()
            if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS
        )

    def _list_audiobooks(self):
        """Zeigt verfügbare Hörbücher mit Index an"""
        if not self.audiobook_files:
            print("⚠️  Keine Hörbücher gefunden")
            print(f"   Kopiere MP3-Dateien nach: {AUDIOBOOKS_DIR}")
            return

        print(f"📁 {len(self.audiobook_files)} Hörbücher verfügbar:")
        print("   (Drehschalter-Position → Hörbuch)")
        max_display = min(11, len(self.audiobook_files))
        for i in range(max_display):
            filepath = self.audiobook_files[i]
            filename = os.path.basename(filepath)
            marker = " ← aktuell" if i == self.current_index else ""
            saved = self.playback_positions.get(filepath)
            saved_pos = f" [⏱️ {self._format_time(saved)}]" if saved else ""
            print(f"   Pos {i:2d}: {filename}{saved_pos}{marker}")

        remaining = len(self.audiobook_files) - 11
        if remaining > 0:
            print(f"   ... und {remaining} weitere")
        print()

    def _find_audiobook(self):
        """Gibt die erste verfügbare Hörbuch-Datei zurück"""
        return self.audiobook_files[0] if self.audiobook_files else None

    # ── Spielstand-Verwaltung ────────────────────────────────────────

    def _load_progress(self):
        """Lädt gespeicherte Spielstände aus JSON-Datei"""
        if not PROGRESS_FILE.exists():
            return
        try:
            with open(PROGRESS_FILE, 'r') as f:
                self.playback_positions = json.load(f)
            print(f"💾 {len(self.playback_positions)} Spielstände geladen")
        except Exception as e:
            print(f"⚠️  Fehler beim Laden der Spielstände: {e}")
            self.playback_positions = {}

    def _save_progress(self):
        """Speichert Spielstände in JSON-Datei"""
        try:
            PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(PROGRESS_FILE, 'w') as f:
                json.dump(self.playback_positions, f, indent=2)
        except Exception as e:
            print(f"⚠️  Fehler beim Speichern der Spielstände: {e}")

    def _save_current_position(self):
        """Speichert die aktuelle Position des laufenden Hörbuchs"""
        if not self.current_file or not self.player:
            return
        position = self.player.get_time()
        if position > 0:
            self.playback_positions[self.current_file] = position
            self._save_progress()
            print(f"💾 Position gespeichert: {self._format_time(position)}")

    def _update_position(self, pos_ms):
        """Aktualisiert und speichert die Position für die aktuelle Datei"""
        if self.current_file:
            self.playback_positions[self.current_file] = pos_ms
            self._save_progress()

    def _save_position_throttled(self):
        """Speichert Position höchstens alle SAVE_INTERVAL Sekunden"""
        now = time.time()
        if now - self._last_save_time < SAVE_INTERVAL:
            return
        self._last_save_time = now
        if self.player and self.player.is_playing() and self.current_file:
            pos = self.player.get_time()
            if pos > 0:
                self.playback_positions[self.current_file] = pos
                self._save_progress()
                self._print_status()

    # ── VLC-Hilfsmethoden ────────────────────────────────────────────

    def _is_vlc_ended(self):
        """Prüft ob VLC im Ended- oder Stopped-Zustand ist"""
        if not self.player:
            return False
        return self.player.get_state() in (vlc.State.Ended, vlc.State.Stopped)

    def _wait_for_vlc_ready(self, max_wait=3.0):
        """Wartet bis VLC bereit ist (max max_wait Sekunden)"""
        waited = 0.0
        while not self.player.is_playing() and waited < max_wait:
            time.sleep(0.1)
            waited += 0.1
        time.sleep(0.3)  # Extra-Warten für stabile Wiedergabe

    def _get_current_position(self):
        """Ermittelt die aktuelle Position, auch wenn VLC gestoppt ist"""
        pos = self.player.get_time() if self.player else 0
        if pos <= 0 and self.current_file:
            pos = self.playback_positions.get(self.current_file, 0)
        return pos

    def _reload_and_play(self, target_pos=None):
        """Lädt die aktuelle Datei neu und spielt ab der gewünschten Position"""
        if not self.player or not self.current_file:
            return

        print("🔄 Datei wird neu geladen...")
        resume_pos = target_pos if target_pos is not None else self.player.get_time()

        media = self.instance.media_new(self.current_file)
        self.player.set_media(media)
        self.player.audio_set_volume(self.current_volume)
        self.player.play()
        self._wait_for_vlc_ready()

        if resume_pos > 0:
            self.player.set_time(int(resume_pos))
        self.is_paused = False
        print(f"▶️  Wiedergabe fortgesetzt bei {self._format_time(resume_pos)}")

    # ── Audio-Feedback ───────────────────────────────────────────────

    def _play_beep(self, frequency=BEEP_FREQUENCY, duration=BEEP_DURATION):
        """Spielt einen kurzen Piepton über den Lautsprecher (USB-Soundkarte 2)

        Verwendet Popen + terminate statt run mit -l 1, da speaker-test
        mit -l 1 immer ~1 Sekunde spielt unabhängig vom timeout.
        """
        try:
            subprocess.run(
                ['amixer', '-c', '2', '-q', 'set', 'PCM', '15%'],
                capture_output=True, timeout=2,
            )
            time.sleep(0.02)

            proc = subprocess.Popen(
                ['speaker-test', '-D', 'plughw:2,0', '-t', 'sine',
                 '-f', str(frequency), '-s', '1'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            time.sleep(duration)
            proc.terminate()
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                proc.kill()

            time.sleep(0.02)
            subprocess.run(
                ['amixer', '-c', '2', '-q', 'set', 'PCM', '100%'],
                capture_output=True, timeout=2,
            )
        except Exception:
            pass  # Stille als Fallback

    def _play_skip_beep(self):
        """Kurzer asynchroner Piepton beim Spulen"""
        threading.Thread(target=self._play_beep, daemon=True).start()

    # ── TTS ──────────────────────────────────────────────────────────

    def _run_tts(self, text):
        """Gemeinsame TTS-Logik: Text mit pico2wave vorlesen"""
        if not TTS_AVAILABLE or not text or not text.strip():
            return
        try:
            print(f"🔊 Sage: '{text}'")
            temp_wav = "/tmp/tts_announcement.wav"
            subprocess.run(
                ['pico2wave', '-l', 'de-DE', '-w', temp_wav, text],
                check=True, capture_output=True,
            )
            subprocess.run(['aplay', temp_wav], check=True, capture_output=True)
            if os.path.exists(temp_wav):
                os.remove(temp_wav)
        except Exception as e:
            print(f"⚠️  TTS-Fehler: {e}")

    @staticmethod
    def _sanitize_filename_for_tts(filename):
        """Bereinigt den Dateinamen für TTS-Ausgabe

        Entfernt Dateiendung, Bindestriche, Unterstriche, Zahlen und
        Sonderzeichen für bessere Verständlichkeit.
        """
        name = os.path.splitext(filename)[0]
        name = name.replace('-', ' ').replace('_', ' ')
        name = re.sub(r'[^a-zA-ZäöüÄÖÜß\s]', '', name)
        name = ' '.join(name.split())
        return name.strip() or "Hörbuch"

    def speak_filename(self, filename):
        """Liest den bereinigten Dateinamen per TTS vor"""
        text = self._sanitize_filename_for_tts(filename)
        if text != "Hörbuch":
            self._run_tts(text)

    def speak_text(self, text):
        """Liest einen beliebigen Text per TTS vor"""
        self._run_tts(text)

    # ── Formatierung ─────────────────────────────────────────────────

    @staticmethod
    def _format_time(ms):
        """Formatiert Millisekunden als mm:ss"""
        seconds = ms // 1000
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    def _print_status(self):
        """Zeigt aktuelle Wiedergabe-Position"""
        if not self.player:
            return
        time.sleep(0.2)
        current = self.player.get_time()
        duration = self.player.get_length()
        if duration > 0:
            print(f"   ⏱️  {self._format_time(current)} / {self._format_time(duration)}")

    # ── Wiedergabe-Steuerung ─────────────────────────────────────────

    def select_audiobook_by_index(self, index):
        """Wählt ein Hörbuch per Index (0-10 vom Drehschalter)"""
        if not self.audiobook_files:
            print("⚠️  Keine Hörbücher verfügbar")
            return False

        index = max(0, min(index, len(self.audiobook_files) - 1))
        if index == self.current_index:
            return True

        # Aktuelles Hörbuch pausieren und Position speichern
        if self.current_file and self.player:
            self._save_current_position()
            self.player.pause()
            self.is_paused = True
            print(f"⏸️  '{os.path.basename(self.current_file)}' pausiert")

        self.current_index = index
        filepath = self.audiobook_files[index]
        filename = os.path.basename(filepath)

        print(f"📖 Drehschalter Pos {index} → {filename}")
        self.speak_filename(filename)

        resume_position = self.playback_positions.get(filepath, 0)
        self.play_audiobook(filepath, resume_position=resume_position, start_paused=True)
        return True

    def play_audiobook(self, filepath=None, resume_position=0, start_paused=False):
        """Spielt ein Hörbuch ab

        Args:
            filepath: Pfad zur Audiodatei (None = erstes verfügbare)
            resume_position: Position in Millisekunden zum Fortsetzen
            start_paused: Wenn True, wird das Hörbuch pausiert gestartet
        """
        if not self.player:
            print("❌ VLC nicht verfügbar")
            return

        if filepath is None:
            filepath = self._find_audiobook()
        if not filepath or not os.path.exists(filepath):
            print(f"⚠️  Datei nicht gefunden: {filepath}")
            return

        # Index aktualisieren wenn Datei in Liste
        if filepath in self.audiobook_files:
            self.current_index = self.audiobook_files.index(filepath)

        self.current_file = filepath
        media = self.instance.media_new(filepath)
        self.player.set_media(media)
        self.player.audio_set_volume(self.current_volume)
        self.player.play()
        self._wait_for_vlc_ready()

        # Zur gespeicherten Position springen wenn vorhanden
        if resume_position > 0:
            duration = self.player.get_length()
            if duration > 0 and resume_position < duration - 5000:
                self.player.set_time(int(resume_position))
                time.sleep(0.2)
                print(f"⏱️  Fortsetzen bei: {self._format_time(resume_position)}")
            else:
                print("⏱️  Datei zu Ende oder fast zu Ende - starte von Anfang")

        # Pausieren wenn gewünscht (z.B. beim Wechsel)
        if start_paused:
            time.sleep(0.3)
            self.player.pause()
            self.is_paused = True
            print(f"⏸️  '{os.path.basename(filepath)}' bereit (pausiert)")
        else:
            self.is_paused = False

        if self.player.is_playing() or start_paused:
            if not start_paused:
                print(f"▶️  Spiele: {os.path.basename(filepath)}")
            self._print_status()
        else:
            print(f"⚠️  Konnte nicht abspielen: {filepath}")

    def toggle_pause(self):
        """Play/Pause umschalten"""
        if not self.player or not self.current_file:
            print("⚠️  Kein Hörbuch geladen")
            return

        # Wenn VLC im Ended/Stopped-Zustand ist, Datei neu laden
        if self._is_vlc_ended():
            current_pos = self._get_current_position()
            print(f"🔄 VLC war gestoppt - lade neu bei {self._format_time(current_pos)}")
            self._reload_and_play(target_pos=current_pos)
            self._print_status()
            return

        self.player.pause()
        self.is_paused = not self.is_paused
        if self.is_paused:
            self._save_current_position()
            print("⏸️  Pausiert")
        else:
            print("▶️  Weiter")
            self._print_status()

    def set_volume(self, volume):
        """Setzt die Lautstärke (0-100)"""
        volume = max(0, min(100, volume))
        if volume != self.current_volume:
            self.current_volume = volume
            if self.player:
                self.player.audio_set_volume(volume)
            print(f"🔊 Lautstärke: {volume}%")

    # ── Spulen (vereinheitlicht) ─────────────────────────────────────

    def _skip(self, direction):
        """Kurzes Spulen: ±SKIP_SECONDS

        Args:
            direction: FORWARD (1) oder BACKWARD (-1)
        """
        if not self.player:
            return

        delta_ms = direction * SKIP_SECONDS * 1000
        icon = "⏩" if direction == FORWARD else "⏪"
        label = f"+{SKIP_SECONDS}s" if direction == FORWARD else f"-{SKIP_SECONDS}s"

        # Wenn VLC am Ende ist und zurückgespult werden soll → neu laden
        if self._is_vlc_ended() and direction == BACKWARD:
            current = self._get_current_position()
            new_pos = max(0, current + delta_ms)
            print(f"{icon} {label} (Position: {self._format_time(new_pos)})")
            self._update_position(new_pos)
            self._reload_and_play(target_pos=new_pos)
            return

        current = self.player.get_time()
        new_pos = current + delta_ms
        duration = self.player.get_length()

        new_pos = max(0, new_pos)
        if duration > 0:
            new_pos = min(new_pos, duration)

        self.player.set_time(int(new_pos))
        print(f"{icon} {label} (Position: {self._format_time(new_pos)})")
        self._update_position(new_pos)

    def _perform_long_skip(self, direction):
        """Langes Spulen: ±LONG_SKIP_MINUTES Minuten mit Piepton

        Args:
            direction: FORWARD (1) oder BACKWARD (-1)
        """
        if not self.player:
            return

        icon = "⏩" if direction == FORWARD else "⏪"
        label = f"{'+' if direction == FORWARD else '-'}{LONG_SKIP_MINUTES} Minuten"

        was_ended = self._is_vlc_ended()
        current = self._get_current_position()
        new_pos = current + (direction * LONG_SKIP_MS)
        reached_end = False

        if direction == FORWARD:
            duration = self.player.get_length()
            if duration > 0 and new_pos >= duration - 5000:
                new_pos = duration - 3000
                reached_end = True
        else:
            new_pos = max(0, new_pos)

        if was_ended and direction == BACKWARD:
            self._reload_and_play(target_pos=new_pos)
        else:
            self.player.set_time(int(new_pos))

        print(f"{icon} {label} (Position: {self._format_time(new_pos)})")
        self._update_position(new_pos)
        self._play_skip_beep()

        # Ansage wenn Ende erreicht
        if reached_end and self.current_file:
            name = self._sanitize_filename_for_tts(os.path.basename(self.current_file))
            self.speak_text(f"{name} Ende")

    # ── Button-Handling (vereinheitlicht) ────────────────────────────

    def _handle_skip_button(self, direction, is_pressed, current_time):
        """Verarbeitet einen Spul-Button (Forward oder Backward)

        Erkennt kurzen Druck (→ ±30s) vs. langen Druck (→ ±2min wiederholend).
        """
        state = self._btn_state[direction]
        dir_name = "Spulen" if direction == FORWARD else "Zurückspulen"
        icon = "⏩" if direction == FORWARD else "⏪"

        if is_pressed:
            # Button gerade gedrückt
            if state['press_start'] is None:
                state['press_start'] = current_time
                state['long_active'] = False
                state['last_skip'] = 0
                self._was_playing_before_skip = (
                    self.player is not None and self.player.is_playing()
                )

            press_duration = current_time - state['press_start']

            if not state['long_active'] and press_duration >= LONG_PRESS_THRESHOLD:
                # Langes Spulen aktivieren
                state['long_active'] = True
                print(f"{icon} Langes {dir_name} aktiviert ({LONG_SKIP_MINUTES} Minuten)")
                self._perform_long_skip(direction)
                state['last_skip'] = current_time

            elif state['long_active']:
                # Bereits im langen Spulmodus - nächster Sprung fällig?
                if current_time - state['last_skip'] >= LONG_PRESS_THRESHOLD:
                    self._perform_long_skip(direction)
                    state['last_skip'] = current_time

        elif state['press_start'] is not None:
            # Button losgelassen
            if not state['long_active']:
                # Kurzer Druck → normales ±30s Spulen
                self._skip(direction)
            else:
                # Langes Spulen beendet → Wiedergabe fortsetzen
                print(f"▶️  {dir_name} beendet - setze Wiedergabe fort")
                if self.player:
                    if self._is_vlc_ended():
                        current_pos = self.playback_positions.get(self.current_file, 0)
                        self._reload_and_play(target_pos=current_pos)
                    elif self._was_playing_before_skip:
                        self.player.play()
                        self.is_paused = False

            # Reset
            state['press_start'] = None
            state['long_active'] = False
            state['last_skip'] = 0

    def _check_buttons(self):
        """Prüft alle Taster-Zustände (Polling)"""
        if not GPIO_AVAILABLE:
            return

        # Play/Pause - Flanken-Erkennung (nur auf fallende Flanke reagieren)
        play_pressed = not GPIO.input(BUTTON_PLAY_PAUSE)
        if play_pressed and not self._play_btn_was_pressed:
            self.toggle_pause()
            time.sleep(0.3)  # Entprellen
        self._play_btn_was_pressed = play_pressed

        # Vorspulen & Zurückspulen
        current_time = time.time()
        self._handle_skip_button(FORWARD, not GPIO.input(BUTTON_FORWARD), current_time)
        self._handle_skip_button(BACKWARD, not GPIO.input(BUTTON_BACKWARD), current_time)

    # ── I2C-Handling ─────────────────────────────────────────────────

    def _check_i2c(self):
        """Prüft I2C-Daten vom Arduino Nano"""
        if not self.i2c_reader:
            return

        if self.i2c_reader.interrupt_event.wait(timeout=0.05):
            self.i2c_reader.interrupt_event.clear()
            time.sleep(0.01)

            switch, pot = self.i2c_reader.read_data()
            if switch is not None and pot is not None:
                # Dateiauswahl über Drehschalter
                if switch != self.last_switch_position:
                    self.last_switch_position = switch
                    if 0 <= switch < len(self.audiobook_files):
                        self.select_audiobook_by_index(switch)

                # Lautstärke über Potentiometer (0-1023 → 0-100)
                self.set_volume(int((pot / 1023) * 100))

    # ── Hauptschleife ────────────────────────────────────────────────

    def run(self):
        """Hauptschleife"""
        # Initiale I2C-Daten lesen
        if self.i2c_reader:
            try:
                switch, pot = self.i2c_reader.read_data()
                if switch is not None:
                    self.last_switch_position = switch
                    if 0 <= switch < len(self.audiobook_files):
                        self.select_audiobook_by_index(switch)
                if pot is not None:
                    self.set_volume(int((pot / 1023) * 100))
            except Exception as e:
                print(f"⚠️  Initiales I2C Lesen fehlgeschlagen: {e}")

        # Automatisch erstes Hörbuch starten falls noch nichts ausgewählt
        if self.current_index < 0:
            first_book = self._find_audiobook()
            if first_book:
                resume_pos = self.playback_positions.get(first_book, 0)
                self.play_audiobook(first_book, resume_position=resume_pos)

        print("\n⏹️  Strg+C zum Beenden\n")

        try:
            while self.running:
                self._check_buttons()
                self._check_i2c()
                self._save_position_throttled()
                time.sleep(0.01)  # 10ms Polling-Intervall
        except KeyboardInterrupt:
            print("\n\n⏹️  Beende...")
        finally:
            self._save_current_position()
            self.cleanup()

    # ── Kompatibilität & Aufräumen ───────────────────────────────────

    def get_current_station_name(self):
        """Gibt den Namen der aktuellen Datei zurück (für Kompatibilität)"""
        if self.current_file:
            return os.path.basename(self.current_file)
        return None

    def cleanup(self):
        """Aufräumen"""
        if self.player:
            self.player.stop()

        if self.i2c_reader:
            try:
                self.i2c_reader.cleanup()
            except Exception:
                pass

        if GPIO_AVAILABLE:
            try:
                GPIO.cleanup()
                print("✅ GPIO aufgeräumt")
            except Exception:
                pass

        print("✅ Hörbuch-Player beendet")


def main():
    """Entry-Point"""
    player = AudiobookPlayer()

    def signal_handler(sig, frame):
        print(f"\n📶 Signal {sig}")
        player.running = False

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    player.run()


if __name__ == "__main__":
    main()
