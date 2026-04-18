#!/usr/bin/env python3
"""
YouTube-Player - Spielt die neuesten Videos von YouTube-Kanälen als Audio

Bedienung:
  - GPIO 22 (Pin 15): Play/Pause
  - GPIO 23 (Pin 16): Nächstes Video (kurz) / +2 Minuten vorspulen (lang)
  - GPIO 24 (Pin 18): Vorheriges Video (kurz) / -2 Minuten zurückspulen (lang)
  - Arduino Nano I2C: Drehschalter für Kanalauswahl (0-10), Poti für Lautstärke

Features:
  - 11 YouTube-Kanäle konfigurierbar (config/youtube_channels.json)
  - Spielt automatisch das neueste Video eines Kanals
  - Automatisches Weiterschalten zum nächsten Video
  - Kanal-Ansage per TTS beim Umschalten
  - Lautstärke über Potentiometer

Installation:
  sudo apt install libttspico-utils alsa-utils python3-vlc vlc
  pip3 install yt-dlp

Starten:
  cd media_center_organized
  python3 -m media_center.youtube_player
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


def _check_ytdlp_available():
    """Prüft ob yt-dlp verfügbar ist"""
    try:
        subprocess.run(['yt-dlp', '--version'], check=True, capture_output=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


TTS_AVAILABLE = _check_tts_available()
if not TTS_AVAILABLE:
    print("⚠️  pico2wave oder aplay nicht gefunden - keine TTS-Ansage")
    print("    Installieren mit: sudo apt install libttspico-utils alsa-utils")

YTDLP_AVAILABLE = _check_ytdlp_available()
if not YTDLP_AVAILABLE:
    print("❌ yt-dlp nicht gefunden! Installieren mit: pip3 install yt-dlp")

# ── Konfiguration ────────────────────────────────────────────────────

BUTTON_PLAY_PAUSE = 22   # GPIO 22, Pin 15
BUTTON_FORWARD = 23      # GPIO 23, Pin 16
BUTTON_BACKWARD = 24     # GPIO 24, Pin 18

LONG_PRESS_THRESHOLD = 1.0   # Sekunden bis langes Spulen
LONG_SKIP_MINUTES = 2
LONG_SKIP_MS = LONG_SKIP_MINUTES * 60 * 1000

BEEP_FREQUENCY = 800
BEEP_DURATION = 0.012

MAX_VIDEOS_PER_CHANNEL = 20   # Wie viele neueste Videos pro Kanal laden
CACHE_LIFETIME = 600           # Sekunden bevor Video-Liste neu geladen wird (10 min)

# Richtungs-Konstanten
FORWARD = 1
BACKWARD = -1

# Verzeichnisse
MODULE_DIR = Path(__file__).parent
PROJECT_DIR = MODULE_DIR.parent
CHANNELS_FILE = PROJECT_DIR / "config" / "youtube_channels.json"


class YouTubePlayer:
    """YouTube-Player mit Kanalauswahl, TTS-Ansage und I2C-Steuerung"""

    def __init__(self):
        self.running = True
        self.player = None
        self.instance = None
        self.is_paused = False
        self.current_volume = 50

        # Kanal-Verwaltung
        self.channels = []
        self.current_channel_index = -1
        self.last_switch_position = -1

        # Video-Verwaltung pro Kanal
        # {channel_url: {"videos": [...], "fetched_at": timestamp}}
        self._video_cache = {}
        self.current_videos = []       # Video-Liste des aktuellen Kanals
        self.current_video_index = -1  # Aktuelles Video im Kanal
        self.current_video_title = ""

        # I2C Reader
        self.i2c_reader = None

        # Button-Zustand: Play/Pause Flanken-Erkennung
        self._play_btn_was_pressed = False

        # Button-Zustand: Forward/Backward (langes Spulen)
        self._btn_state = {
            FORWARD:  {'press_start': None, 'long_active': False, 'last_skip': 0},
            BACKWARD: {'press_start': None, 'long_active': False, 'last_skip': 0},
        }
        self._was_playing_before_skip = False

        # Fetch-Thread-Lock
        self._fetch_lock = threading.Lock()
        self._is_fetching = False

        # Hardware-Initialisierung
        if GPIO_AVAILABLE:
            self._setup_gpio()
        if VLC_AVAILABLE:
            self._init_vlc()

        # Kanäle laden
        self._load_channels()

        # I2C Setup
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
            '--alsa-audio-device=plughw:3,0',
            '--network-caching=5000',
            '--file-caching=2000',
            '--clock-jitter=0',
            '--clock-synchro=0',
        ]
        try:
            self.instance = vlc.Instance(*options)
        except Exception as e:
            print(f"⚠️  VLC ALSA-Optionen fehlgeschlagen: {e}")
            self.instance = vlc.Instance('--no-video')
        self.player = self.instance.media_player_new()
        subprocess.run(['amixer', '-c', '3', '-q', 'set', 'Digital', '100%'],
                        capture_output=True, timeout=2)
        print("✅ VLC initialisiert")

    def _print_startup_info(self):
        """Zeigt Startinformationen an"""
        tts_status = "✅ TTS-Ansage aktiviert" if TTS_AVAILABLE else "⚠️  TTS nicht verfügbar"
        ytdlp_status = "✅ yt-dlp verfügbar" if YTDLP_AVAILABLE else "❌ yt-dlp FEHLT"
        sep = "=" * 50
        print(f"\n{sep}")
        print("📺 YOUTUBE-PLAYER (Audio-only)")
        print(sep)
        print(f"Kanäle-Datei: {CHANNELS_FILE}")
        configured = sum(1 for c in self.channels if c.get('url'))
        print(f"{configured} von {len(self.channels)} Kanälen konfiguriert")
        print("Taster:")
        print(f"  GPIO {BUTTON_PLAY_PAUSE} (Pin 15): Play/Pause")
        print(f"  GPIO {BUTTON_FORWARD} (Pin 16): Nächstes Video / +{LONG_SKIP_MINUTES}min (lang)")
        print(f"  GPIO {BUTTON_BACKWARD} (Pin 18): Vorheriges Video / -{LONG_SKIP_MINUTES}min (lang)")
        print("Nano 1 I2C: Drehschalter (Kanal 0-10), Poti (Lautstärke)")
        print(ytdlp_status)
        print(tts_status)
        print(f"{sep}\n")
        self._list_channels()

    # ── Kanal-Verwaltung ─────────────────────────────────────────────

    def _load_channels(self):
        """Lädt Kanal-Konfiguration aus JSON-Datei"""
        if not CHANNELS_FILE.exists():
            print(f"⚠️  Kanäle-Datei nicht gefunden: {CHANNELS_FILE}")
            self._create_default_channels()
            return

        try:
            with open(CHANNELS_FILE, 'r') as f:
                data = json.load(f)
            self.channels = data.get('channels', [])
            # Auf 11 Einträge erweitern falls nötig
            while len(self.channels) < 11:
                self.channels.append({
                    'position': len(self.channels),
                    'name': '',
                    'url': '',
                })
            print(f"📺 {len(self.channels)} Kanal-Slots geladen")
        except Exception as e:
            print(f"⚠️  Fehler beim Laden der Kanäle: {e}")
            self._create_default_channels()

    def _create_default_channels(self):
        """Erstellt eine Standard-Kanäle-Datei"""
        self.channels = [
            {'position': i, 'name': '', 'url': ''}
            for i in range(11)
        ]
        self._save_channels()
        print(f"📝 Standard-Kanäle-Datei erstellt: {CHANNELS_FILE}")

    def _save_channels(self):
        """Speichert Kanäle in JSON-Datei"""
        try:
            CHANNELS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(CHANNELS_FILE, 'w') as f:
                json.dump({'channels': self.channels}, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️  Fehler beim Speichern der Kanäle: {e}")

    def _list_channels(self):
        """Zeigt konfigurierte Kanäle an"""
        print("📺 Konfigurierte Kanäle:")
        print("   (Drehschalter-Position → Kanal)")
        for i, ch in enumerate(self.channels[:11]):
            name = ch.get('name', '')
            url = ch.get('url', '')
            if name and url:
                marker = " ← aktuell" if i == self.current_channel_index else ""
                print(f"   Pos {i:2d}: {name}{marker}")
            else:
                print(f"   Pos {i:2d}: (nicht konfiguriert)")
        print()

    # ── YouTube / yt-dlp ─────────────────────────────────────────────

    def _fetch_channel_videos(self, channel_url):
        """Holt die neuesten Videos eines Kanals per yt-dlp

        Returns:
            Liste von dicts: [{"id": "...", "title": "..."}, ...]
        """
        if not YTDLP_AVAILABLE:
            print("❌ yt-dlp nicht verfügbar")
            return []

        # Cache prüfen
        cached = self._video_cache.get(channel_url)
        if cached and (time.time() - cached['fetched_at']) < CACHE_LIFETIME:
            print(f"📋 Video-Liste aus Cache ({len(cached['videos'])} Videos)")
            return cached['videos']

        print(f"🔍 Lade Videos von: {channel_url} ...")
        try:
            result = subprocess.run(
                [
                    'yt-dlp',
                    '--flat-playlist',
                    '--print', '%(id)s|||%(title)s',
                    '--playlist-items', f'1:{MAX_VIDEOS_PER_CHANNEL}',
                    '--no-warnings',
                    '--quiet',
                    channel_url,
                ],
                capture_output=True, text=True, timeout=30,
            )

            if result.returncode != 0:
                stderr = result.stderr.strip()
                print(f"⚠️  yt-dlp Fehler: {stderr[:200]}")
                return []

            videos = []
            for line in result.stdout.strip().split('\n'):
                if '|||' in line:
                    vid_id, title = line.split('|||', 1)
                    videos.append({'id': vid_id.strip(), 'title': title.strip()})

            # Cache aktualisieren
            self._video_cache[channel_url] = {
                'videos': videos,
                'fetched_at': time.time(),
            }

            print(f"✅ {len(videos)} Videos geladen")
            return videos

        except subprocess.TimeoutExpired:
            print("⚠️  yt-dlp Timeout (>30s)")
            return []
        except Exception as e:
            print(f"⚠️  Fehler beim Laden der Videos: {e}")
            return []

    def _get_audio_url(self, video_id):
        """Holt die direkte Audio-Stream-URL per yt-dlp

        Returns:
            Audio-URL als String oder None
        """
        if not YTDLP_AVAILABLE:
            return None

        video_url = f"https://www.youtube.com/watch?v={video_id}"
        print(f"🔗 Lade Audio-URL für: {video_id} ...")

        try:
            result = subprocess.run(
                [
                    'yt-dlp',
                    '-g',                    # URL ausgeben
                    '-f', 'bestaudio',       # Beste Audio-Qualität
                    '--no-warnings',
                    '--quiet',
                    video_url,
                ],
                capture_output=True, text=True, timeout=20,
            )

            if result.returncode != 0:
                # Fallback: jedes Audio-Format
                result = subprocess.run(
                    [
                        'yt-dlp',
                        '-g',
                        '-f', 'bestaudio/best',
                        '--no-warnings',
                        '--quiet',
                        video_url,
                    ],
                    capture_output=True, text=True, timeout=20,
                )

            url = result.stdout.strip()
            if url and url.startswith('http'):
                print("✅ Audio-URL erhalten")
                return url
            else:
                print(f"⚠️  Keine gültige URL erhalten")
                return None

        except subprocess.TimeoutExpired:
            print("⚠️  yt-dlp Timeout beim URL-Abruf")
            return None
        except Exception as e:
            print(f"⚠️  Fehler beim Audio-URL-Abruf: {e}")
            return None

    # ── VLC-Hilfsmethoden ────────────────────────────────────────────

    def _is_vlc_ended(self):
        """Prüft ob VLC im Ended- oder Stopped-Zustand ist"""
        if not self.player:
            return False
        return self.player.get_state() in (vlc.State.Ended, vlc.State.Stopped)

    def _wait_for_vlc_ready(self, max_wait=5.0):
        """Wartet bis VLC bereit ist (für Streams längeres Timeout)"""
        waited = 0.0
        while not self.player.is_playing() and waited < max_wait:
            time.sleep(0.1)
            waited += 0.1
        time.sleep(0.5)  # Extra-Warten für Stream-Buffering

    # ── Audio-Feedback ───────────────────────────────────────────────

    def _play_beep(self, frequency=BEEP_FREQUENCY, duration=BEEP_DURATION):
        """Spielt einen kurzen Piepton über den Lautsprecher (USB-Soundkarte 2)"""
        try:
            subprocess.run(
                ['amixer', '-c', '3', '-q', 'set', 'Digital', '15%'],
                capture_output=True, timeout=2,
            )
            time.sleep(0.02)

            proc = subprocess.Popen(
                ['speaker-test', '-D', 'plughw:3,0', '-t', 'sine',
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
                ['amixer', '-c', '3', '-q', 'set', 'Digital', '100%'],
                capture_output=True, timeout=2,
            )
        except Exception:
            pass

    def _play_skip_beep(self):
        """Kurzer asynchroner Piepton"""
        threading.Thread(target=self._play_beep, daemon=True).start()

    # ── TTS ──────────────────────────────────────────────────────────

    def _run_tts(self, text, volume=None):
        """Text mit pico2wave vorlesen"""
        if not TTS_AVAILABLE or not text or not text.strip():
            return
        volume = min((volume if volume is not None else self.current_volume) + 40, 100)
        try:
            print(f"🔊 Sage: '{text}' (Lautstärke: {volume}%)")
            temp_wav = "/tmp/tts_announcement.wav"
            subprocess.run(
                ['pico2wave', '-l', 'de-DE', '-w', temp_wav, text],
                check=True, capture_output=True,
            )
            subprocess.run(
                ['amixer', '-c', '3', '-q', 'set', 'Digital', f'{volume}%'],
                capture_output=True, timeout=2,
            )
            subprocess.run(['aplay', '-D', 'plughw:3,0', temp_wav], check=True, capture_output=True)
            subprocess.run(
                ['amixer', '-c', '3', '-q', 'set', 'Digital', '100%'],
                capture_output=True, timeout=2,
            )
            if os.path.exists(temp_wav):
                os.remove(temp_wav)
        except Exception as e:
            print(f"⚠️  TTS-Fehler: {e}")

    def speak_channel_name(self, name):
        """Liest den Kanalnamen per TTS vor"""
        if name:
            self._run_tts(name)

    def speak_text(self, text):
        """Liest einen beliebigen Text per TTS vor"""
        self._run_tts(text)

    # ── Formatierung ─────────────────────────────────────────────────

    @staticmethod
    def _format_time(ms):
        """Formatiert Millisekunden als mm:ss"""
        if ms <= 0:
            return "00:00"
        seconds = ms // 1000
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    def _print_status(self):
        """Zeigt aktuelle Wiedergabe-Position"""
        if not self.player:
            return
        time.sleep(0.2)
        current = self.player.get_time()
        duration = self.player.get_length()
        video_info = f"[{self.current_video_index + 1}/{len(self.current_videos)}]" \
            if self.current_videos else ""
        if duration > 0:
            print(f"   ⏱️  {self._format_time(current)} / {self._format_time(duration)} {video_info}")
        elif current > 0:
            print(f"   ⏱️  {self._format_time(current)} (Live/Unbekannte Dauer) {video_info}")

    # ── Wiedergabe-Steuerung ─────────────────────────────────────────

    def select_channel(self, index):
        """Wählt einen Kanal per Index (0-10 vom Drehschalter)"""
        if not self.channels:
            print("⚠️  Keine Kanäle konfiguriert")
            return False

        index = max(0, min(index, len(self.channels) - 1))
        if index == self.current_channel_index:
            return True

        channel = self.channels[index]
        name = channel.get('name', '')
        url = channel.get('url', '')

        if not url:
            print(f"📺 Pos {index}: Kein Kanal konfiguriert")
            self.speak_text("Kein Kanal konfiguriert")
            return False

        # Aktuelles Playback stoppen
        if self.player and self.player.is_playing():
            self.player.stop()
            self.is_paused = False

        self.current_channel_index = index
        print(f"📺 Drehschalter Pos {index} → {name}")

        # Kanalname ansagen
        self.speak_channel_name(name)

        # Videos laden und abspielen (im Hintergrund)
        self._start_channel_playback(url)
        return True

    def _start_channel_playback(self, channel_url):
        """Startet die Wiedergabe eines Kanals (lädt Videos und spielt erstes)"""
        if self._is_fetching:
            print("⏳ Bereits beim Laden...")
            return

        def fetch_and_play():
            self._is_fetching = True
            try:
                videos = self._fetch_channel_videos(channel_url)
                if not videos:
                    print("⚠️  Keine Videos gefunden")
                    self.speak_text("Keine Videos gefunden")
                    return

                self.current_videos = videos
                self.current_video_index = 0

                # Zeige erste 5 Videos an
                print(f"📋 Neueste Videos:")
                for i, v in enumerate(videos[:5]):
                    marker = " ◀" if i == 0 else ""
                    print(f"   {i + 1}. {v['title'][:60]}{marker}")
                if len(videos) > 5:
                    print(f"   ... und {len(videos) - 5} weitere")

                # Erstes Video abspielen
                self._play_video_by_index(0)

            finally:
                self._is_fetching = False

        thread = threading.Thread(target=fetch_and_play, daemon=True)
        thread.start()

    def _play_video_by_index(self, index):
        """Spielt ein bestimmtes Video des aktuellen Kanals"""
        if not self.current_videos:
            print("⚠️  Keine Videos vorhanden")
            return

        index = max(0, min(index, len(self.current_videos) - 1))
        video = self.current_videos[index]
        self.current_video_index = index
        self.current_video_title = video['title']

        print(f"🎵 Video {index + 1}/{len(self.current_videos)}: {video['title'][:70]}")

        # Audio-URL abrufen
        audio_url = self._get_audio_url(video['id'])
        if not audio_url:
            print(f"⚠️  Audio-URL nicht verfügbar für: {video['title'][:50]}")
            # Nächstes Video versuchen
            if index + 1 < len(self.current_videos):
                print("⏭️  Versuche nächstes Video...")
                self._play_video_by_index(index + 1)
            return

        # Mit VLC abspielen
        if not self.player:
            print("❌ VLC nicht verfügbar")
            return

        media = self.instance.media_new(audio_url)
        self.player.set_media(media)
        self.player.audio_set_volume(self.current_volume)
        self.player.play()
        self._wait_for_vlc_ready()

        self.is_paused = False

        if self.player.is_playing():
            print(f"▶️  Spiele: {video['title'][:60]}")
            self._print_status()
        else:
            print(f"⚠️  Konnte nicht abspielen: {video['title'][:50]}")

    def next_video(self):
        """Spielt das nächste Video im Kanal"""
        if not self.current_videos:
            print("⚠️  Keine Videos geladen")
            return

        if self.current_video_index + 1 >= len(self.current_videos):
            print("⏹️  Letztes Video im Kanal erreicht")
            self.speak_text("Letztes Video")
            return

        new_index = self.current_video_index + 1
        print(f"⏭️  Nächstes Video ({new_index + 1}/{len(self.current_videos)})")
        self._play_skip_beep()
        self._play_video_by_index(new_index)

    def prev_video(self):
        """Spielt das vorherige Video im Kanal"""
        if not self.current_videos:
            print("⚠️  Keine Videos geladen")
            return

        if self.current_video_index <= 0:
            # Am Anfang: aktuelles Video neu starten
            print("⏮️  Erstes Video - starte von vorne")
            if self.player:
                self.player.set_time(0)
            return

        new_index = self.current_video_index - 1
        print(f"⏮️  Vorheriges Video ({new_index + 1}/{len(self.current_videos)})")
        self._play_skip_beep()
        self._play_video_by_index(new_index)

    def toggle_pause(self):
        """Play/Pause umschalten"""
        if not self.player:
            print("⚠️  Kein Video geladen")
            return

        # Wenn Video zu Ende → nächstes Video
        if self._is_vlc_ended():
            print("🔄 Video zu Ende - spiele nächstes...")
            self.next_video()
            return

        self.player.pause()
        self.is_paused = not self.is_paused
        if self.is_paused:
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

    # ── Spulen (langes Drücken) ──────────────────────────────────────

    def _perform_long_skip(self, direction):
        """Langes Spulen: ±LONG_SKIP_MINUTES Minuten innerhalb des Videos"""
        if not self.player:
            return

        icon = "⏩" if direction == FORWARD else "⏪"
        label = f"{'+' if direction == FORWARD else '-'}{LONG_SKIP_MINUTES} Minuten"

        current = self.player.get_time()
        if current < 0:
            current = 0
        new_pos = current + (direction * LONG_SKIP_MS)
        duration = self.player.get_length()

        if direction == FORWARD:
            if duration > 0 and new_pos >= duration - 3000:
                # Ende erreicht → nächstes Video
                print(f"{icon} Video-Ende erreicht")
                self.next_video()
                return
        else:
            new_pos = max(0, new_pos)

        self.player.set_time(int(new_pos))
        print(f"{icon} {label} (Position: {self._format_time(new_pos)})")
        self._play_skip_beep()

    # ── Button-Handling ──────────────────────────────────────────────

    def _handle_skip_button(self, direction, is_pressed, current_time):
        """Verarbeitet einen Spul-Button (Forward oder Backward)

        Kurzer Druck: Nächstes/Vorheriges Video
        Langer Druck: ±2 Minuten innerhalb des Videos
        """
        state = self._btn_state[direction]
        dir_name = "Vorwärts" if direction == FORWARD else "Rückwärts"

        if is_pressed:
            if state['press_start'] is None:
                state['press_start'] = current_time
                state['long_active'] = False
                state['last_skip'] = 0
                self._was_playing_before_skip = (
                    self.player is not None and self.player.is_playing()
                )

            press_duration = current_time - state['press_start']

            if not state['long_active'] and press_duration >= LONG_PRESS_THRESHOLD:
                state['long_active'] = True
                icon = "⏩" if direction == FORWARD else "⏪"
                print(f"{icon} Langes Spulen aktiviert ({LONG_SKIP_MINUTES} Minuten)")
                self._perform_long_skip(direction)
                state['last_skip'] = current_time

            elif state['long_active']:
                if current_time - state['last_skip'] >= LONG_PRESS_THRESHOLD:
                    self._perform_long_skip(direction)
                    state['last_skip'] = current_time

        elif state['press_start'] is not None:
            if not state['long_active']:
                # Kurzer Druck → nächstes/vorheriges Video
                if direction == FORWARD:
                    self.next_video()
                else:
                    self.prev_video()
            else:
                # Langes Spulen beendet
                print(f"▶️  {dir_name} beendet")
                if self.player and self._was_playing_before_skip:
                    if not self.player.is_playing() and not self._is_vlc_ended():
                        self.player.play()
                        self.is_paused = False

            state['press_start'] = None
            state['long_active'] = False
            state['last_skip'] = 0

    def _check_buttons(self):
        """Prüft alle Taster-Zustände (Polling)"""
        if not GPIO_AVAILABLE:
            return

        # Play/Pause
        play_pressed = not GPIO.input(BUTTON_PLAY_PAUSE)
        if play_pressed and not self._play_btn_was_pressed:
            self.toggle_pause()
            time.sleep(0.3)
        self._play_btn_was_pressed = play_pressed

        # Forward & Backward
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
                if switch != self.last_switch_position:
                    self.last_switch_position = switch
                    if 0 <= switch < len(self.channels):
                        self.select_channel(switch)

                self.set_volume(int((pot / 1023) * 100))

    # ── Auto-Advance ─────────────────────────────────────────────────

    def _check_auto_advance(self):
        """Prüft ob das aktuelle Video zu Ende ist und spielt automatisch das nächste"""
        if not self.player or self.is_paused or self._is_fetching:
            return
        if self._is_vlc_ended() and self.current_videos:
            print("🔄 Video zu Ende - automatisches Weiterschalten...")
            self.next_video()

    # ── Hauptschleife ────────────────────────────────────────────────

    def run(self):
        """Hauptschleife"""
        # Initiale I2C-Daten lesen
        if self.i2c_reader:
            try:
                switch, pot = self.i2c_reader.read_data()
                if switch is not None:
                    self.last_switch_position = switch
                    if 0 <= switch < len(self.channels):
                        self.select_channel(switch)
                if pot is not None:
                    self.set_volume(int((pot / 1023) * 100))
            except Exception as e:
                print(f"⚠️  Initiales I2C Lesen fehlgeschlagen: {e}")

        print("\n⏹️  Strg+C zum Beenden\n")

        # Auto-Advance Timer (alle 2 Sekunden prüfen)
        last_advance_check = 0.0

        try:
            while self.running:
                self._check_buttons()
                self._check_i2c()

                # Auto-Advance prüfen (alle 2 Sekunden)
                now = time.time()
                if now - last_advance_check >= 2.0:
                    last_advance_check = now
                    self._check_auto_advance()

                time.sleep(0.01)  # 10ms Polling-Intervall
        except KeyboardInterrupt:
            print("\n\n⏹️  Beende...")
        finally:
            self.cleanup()

    # ── Kompatibilität & Aufräumen ───────────────────────────────────

    def get_current_station_name(self):
        """Gibt den Namen des aktuellen Kanals zurück (für Kompatibilität)"""
        if 0 <= self.current_channel_index < len(self.channels):
            return self.channels[self.current_channel_index].get('name', '')
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

        print("✅ YouTube-Player beendet")


def main():
    """Entry-Point"""
    player = YouTubePlayer()

    def signal_handler(sig, frame):
        print(f"\n📶 Signal {sig}")
        player.running = False

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    player.run()


if __name__ == "__main__":
    main()
