#!/usr/bin/env python3
"""
GPIO4 Selector - Umschalter zwischen media_center und kopf_media_center

GPIO 4 steuert den AMP2-Mute-Zustand:
  - GPIO 4 HIGH (AMP2 aktiv)    → media_center (HifiBerry AMP2, Soundkarte 3)
  - GPIO 4 LOW  (AMP2 gemutet)  → kopf_media_center (3.5mm Klinke, Soundkarte 2)

Beim Wechsel werden alle Prozesse der aktuellen Version sauber beendet
(SIGTERM → SIGKILL-Fallback) und die andere Version gestartet.

Hardware:
  GPIO 4 mit Pull-Up-Widerstand (intern).
  Schalter zwischen GPIO 4 und Masse (GND).

Starten:
  python3 gpio4_selector.py
"""

import os
import sys
import time
import signal
import subprocess
from pathlib import Path

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    print("⚠️  RPi.GPIO nicht verfügbar - Simulation ohne Hardware")
    GPIO_AVAILABLE = False

try:
    subprocess.run(['which', 'pico2wave'], check=True, capture_output=True)
    subprocess.run(['which', 'aplay'], check=True, capture_output=True)
    TTS_AVAILABLE = True
except (subprocess.CalledProcessError, FileNotFoundError):
    TTS_AVAILABLE = False

# ── Konfiguration ────────────────────────────────────────────────────

GPIO_PIN = 4

BASE_DIR = Path(__file__).parent

VERSIONS = {
    "high": {
        "name": "Lautsprecher",
        "package": "media_center",
    },
    "low": {
        "name": "Kopfhörer",
        "package": "kopf_media_center",
    },
}

STOP_TIMEOUT = 5
POLL_INTERVAL = 0.5
DEBOUNCE_SECONDS = 1.5


class GPIO4Selector:
    """Umschalter zwischen media_center und kopf_media_center via GPIO 4"""

    def __init__(self):
        self.running = True
        self.current_process = None
        self.current_version_key = None
        self.last_gpio_state = None
        self.debounce_time = 0

        self._setup_gpio()
        self._read_initial_state()

    # ── GPIO Setup ───────────────────────────────────────────────────

    def _setup_gpio(self):
        if not GPIO_AVAILABLE:
            print("⚠️  Kein GPIO - Simulation, GPIO 4 = HIGH (Lautsprecher)")
            self.last_gpio_state = True
            return

        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(GPIO_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            print(f"✅ GPIO {GPIO_PIN} konfiguriert (Pull-Up)")
        except Exception as e:
            print(f"❌ GPIO Setup Fehler: {e}")
            self.last_gpio_state = True

    def _read_gpio4(self):
        if not GPIO_AVAILABLE:
            return self.last_gpio_state
        return bool(GPIO.input(GPIO_PIN))

    def _read_initial_state(self):
        self.last_gpio_state = self._read_gpio4()
        state_str = "HIGH (Lautsprecher/AMP2)" if self.last_gpio_state else "LOW (Kopfhörer/3.5mm)"
        print(f"📍 GPIO {GPIO_PIN} Initialzustand: {state_str}")

    # ── TTS ──────────────────────────────────────────────────────────

    def _speak(self, text):
        if not TTS_AVAILABLE or not text:
            return
        try:
            temp_wav = "/tmp/tts_selector.wav"
            subprocess.run(
                ['pico2wave', '-l', 'de-DE', '-w', temp_wav, text],
                check=True, capture_output=True,
            )
            subprocess.run(['aplay', temp_wav], check=True, capture_output=True)
            if os.path.exists(temp_wav):
                os.remove(temp_wav)
        except Exception as e:
            print(f"⚠️  TTS-Fehler: {e}")

    # ── Prozessverwaltung ────────────────────────────────────────────

    def _stop_current(self):
        if self.current_process is None:
            return

        proc = self.current_process
        version_name = self._current_version_name()

        if proc.poll() is not None:
            print(f"⏹️  {version_name} war bereits beendet")
            self.current_process = None
            self.current_version_key = None
            return

        print(f"⏹️  Beende {version_name} (PID {proc.pid})...")

        proc.terminate()

        try:
            proc.wait(timeout=STOP_TIMEOUT)
            print(f"✅ {version_name} beendet (Hörbuch-Lesezeichen gesichert)")
        except subprocess.TimeoutExpired:
            print(f"⚠️  {version_name} reagiert nicht - erzwinge Beenden...")
            try:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
            print(f"🔴 {version_name} zwangsbeendet")

        self.current_process = None
        self.current_version_key = None

        time.sleep(1.0)

    def _start_version(self, version_key):
        version = VERSIONS[version_key]
        package = version["package"]
        name = version["name"]

        print(f"🚀 Starte {name} ({package})...")
        self._speak(name)

        try:
            self.current_process = subprocess.Popen(
                [sys.executable, '-m', package],
                cwd=str(BASE_DIR),
                start_new_session=True,
            )
            self.current_version_key = version_key
            print(f"✅ {name} gestartet (PID {self.current_process.pid})")
        except Exception as e:
            print(f"❌ Fehler beim Starten von {name}: {e}")
            self.current_process = None
            self.current_version_key = None

    def _current_version_name(self):
        if self.current_version_key:
            return VERSIONS[self.current_version_key]["name"]
        return "(keine)"

    # ── Versionswechsel ──────────────────────────────────────────────

    def _switch_to(self, version_key):
        if version_key == self.current_version_key:
            return

        new_name = VERSIONS[version_key]["name"]
        old_name = self._current_version_name()

        print(f"\n{'─' * 50}")
        print(f"🔀 Wechsel: {old_name} → {new_name}")
        print(f"{'─' * 50}")

        self._stop_current()
        self._start_version(version_key)

    # ── GPIO-Auswertung ──────────────────────────────────────────────

    def _gpio_state_to_version_key(self, gpio_high):
        return "high" if gpio_high else "low"

    # ── Hauptschleife ────────────────────────────────────────────────

    def run(self):
        version_key = self._gpio_state_to_version_key(self.last_gpio_state)
        self._start_version(version_key)

        print("\n⏹️  Strg+C zum Beenden\n")

        try:
            while self.running:
                gpio_high = self._read_gpio4()
                version_key = self._gpio_state_to_version_key(gpio_high)

                if gpio_high != self.last_gpio_state:
                    now = time.monotonic()
                    if now - self.debounce_time > DEBOUNCE_SECONDS:
                        print(f"📍 GPIO {GPIO_PIN}: {'HIGH' if gpio_high else 'LOW'}")
                        self.last_gpio_state = gpio_high
                        self.debounce_time = now
                        self._switch_to(version_key)
                    else:
                        pass
                else:
                    self.debounce_time = time.monotonic()

                if self.current_process and self.current_process.poll() is not None and self.current_version_key:
                    exit_code = self.current_process.returncode
                    print(f"⚠️  {self._current_version_name()} unerwartet beendet (Exit {exit_code})")
                    print(f"🔄 Starte {self._current_version_name()} neu...")
                    version_key_restart = self.current_version_key
                    self.current_process = None
                    self._start_version(version_key_restart)

                time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            print("\n\n⏹️  Beende GPIO4 Selector...")
        finally:
            self.cleanup()

    # ── Cleanup ──────────────────────────────────────────────────────

    def cleanup(self):
        print("🧹 Räume auf...")
        self._stop_current()

        if GPIO_AVAILABLE:
            try:
                GPIO.cleanup()
                print("✅ GPIO aufgeräumt")
            except Exception:
                pass

        print("✅ GPIO4 Selector beendet")


def main():
    selector = GPIO4Selector()

    def signal_handler(sig, frame):
        print(f"\n📶 Signal {sig}")
        selector.running = False

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    selector.run()


if __name__ == "__main__":
    main()
