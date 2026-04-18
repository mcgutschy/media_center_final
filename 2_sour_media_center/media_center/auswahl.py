#!/usr/bin/env python3
"""
Programmauswahl - Startet Player als eigenständige Subprozesse

Liest Arduino 2 (I2C 0x09, Interrupt GPIO 17) über i2c_reader_program.py.
Der Drehschalter wählt das Programm, das Poti steuert die Tonhöhe.

Drehschalter-Belegung:
  Pos 0: Radio-Player       (radio_player.py)
  Pos 1: YouTube-Player     (youtube_player.py)
  Pos 2: Hörbuch-Player     (audiobook_player.py)
  Pos 3-10: (noch nicht belegt)

Prinzip:
  Jeder Player läuft als eigener Subprozess (python3 -m ...).
  Beim Wechsel wird der laufende Prozess per SIGTERM sauber beendet
  und der neue gestartet. So gibt es keine Konflikte mit GPIO, VLC
  oder I2C zwischen den Playern.

Starten:
  cd media_center_organized
  python3 -m media_center            (via __main__.py)
  python3 -m media_center.auswahl   (direkt)
"""

import os
import sys
import time
import signal
import subprocess
from pathlib import Path

try:
    import smbus
    SMBUS_AVAILABLE = True
except ImportError:
    SMBUS_AVAILABLE = False

# ── I2C Reader importieren ───────────────────────────────────────────

try:
    from media_center.i2c_reader_program import SimpleI2CReader
    I2C_AVAILABLE = True
except Exception as e:
    print(f"❌ i2c_reader_program.py konnte nicht geladen werden: {e}")
    I2C_AVAILABLE = False

# Prüfe ob pico2wave für TTS verfügbar ist
try:
    subprocess.run(['which', 'pico2wave'], check=True, capture_output=True)
    subprocess.run(['which', 'aplay'], check=True, capture_output=True)
    TTS_AVAILABLE = True
except (subprocess.CalledProcessError, FileNotFoundError):
    TTS_AVAILABLE = False
    print("⚠️  TTS nicht verfügbar (pico2wave/aplay fehlt)")

# ── Konfiguration ────────────────────────────────────────────────────

# Arbeitsverzeichnis für Subprozesse (Projekt-Root = media_center_organized/)
MODULE_DIR = Path(__file__).parent
PROJECT_DIR = MODULE_DIR.parent

# Programm-Zuordnung: Drehschalter-Position → (Name, Modul-Pfad)
PROGRAMS = {
    0: ("Radio",    "media_center.radio_player"),
    1: ("YouTube",  "media_center.youtube_player"),
    2: ("Hörbuch",  "media_center.audiobook_player"),
    # Positionen 3-10 können später ergänzt werden:
    # 3: ("Podcast", "media_center.podcast_player"),
}

# Timeout beim Beenden eines Subprozesses (Sekunden)
STOP_TIMEOUT = 5


class ProgramSelector:
    """Startet und wechselt zwischen Player-Programmen als Subprozesse"""

    def __init__(self):
        self.running = True
        self.current_position = -1
        self.current_process = None
        self.current_program_name = ""
        self.i2c_reader = None
        self.current_volume = 50
        self._volume_bus = None

        if I2C_AVAILABLE:
            try:
                self.i2c_reader = SimpleI2CReader()
                print("✅ I2C Reader (Arduino 2, 0x09) initialisiert")
            except Exception as e:
                print(f"❌ I2C Fehler: {e}")

        if SMBUS_AVAILABLE:
            try:
                self._volume_bus = smbus.SMBus(1)
                print("✅ Volume-Bus (Arduino 1, 0x08) bereit")
            except Exception as e:
                print(f"⚠️  Volume-Bus nicht verfügbar: {e}")

        self._print_startup_info()

    def _print_startup_info(self):
        """Zeigt Startinformationen an"""
        sep = "=" * 50
        print(f"\n{sep}")
        print("🎛️  PROGRAMMAUSWAHL")
        print(sep)
        print("Drehschalter-Belegung:")
        for pos in range(11):
            if pos in PROGRAMS:
                name, module = PROGRAMS[pos]
                marker = " ← aktuell" if pos == self.current_position else ""
                print(f"  Pos {pos:2d}: {name} ({module}){marker}")
            else:
                print(f"  Pos {pos:2d}: (nicht belegt)")
        print(f"\nArbeitsverzeichnis: {PROJECT_DIR}")
        print(f"{sep}\n")

    # ── TTS ──────────────────────────────────────────────────────────

    def _read_volume_pot(self):
        """Liest Poti-Wert von Arduino 1 (0x08) für TTS-Lautstärke"""
        if not self._volume_bus:
            return self.current_volume
        try:
            data = self._volume_bus.read_i2c_block_data(0x08, 0, 2)
            pot = data[1] * 4
            if pot > 1023:
                pot = 1023
            return int((pot / 1023) * 100)
        except Exception:
            return self.current_volume

    def _speak(self, text):
        """Text per TTS vorlesen (Lautstärke vom Poti Arduino 1)"""
        if not TTS_AVAILABLE or not text:
            return
        try:
            volume = min(self._read_volume_pot() + 31, 100)
            self.current_volume = volume
            temp_wav = "/tmp/tts_auswahl.wav"
            subprocess.run(
                ['pico2wave', '-l', 'de-DE', '-w', temp_wav, text],
                check=True, capture_output=True,
            )
            subprocess.run(
                ['amixer', '-c', '3', '-q', 'set', 'Digital', f'{volume}%'],
                capture_output=True, timeout=2,
            )
            subprocess.run(['aplay', '-D', 'plughw:3,0', temp_wav], check=True, capture_output=True)
            if os.path.exists(temp_wav):
                os.remove(temp_wav)
        except Exception as e:
            print(f"⚠️  TTS-Fehler: {e}")

    # ── Subprozess-Verwaltung ────────────────────────────────────────

    def _stop_current(self):
        """Beendet den aktuell laufenden Subprozess sauber"""
        if self.current_process is None:
            return

        proc = self.current_process
        name = self.current_program_name

        if proc.poll() is not None:
            # Prozess ist bereits beendet
            print(f"⏹️  {name} war bereits beendet")
            self.current_process = None
            return

        print(f"⏹️  Beende {name} (PID {proc.pid})...")

        # Erst SIGTERM (sauberes Beenden)
        proc.terminate()
        try:
            proc.wait(timeout=STOP_TIMEOUT)
            print(f"✅ {name} beendet")
        except subprocess.TimeoutExpired:
            # Notfall: SIGKILL
            print(f"⚠️  {name} reagiert nicht - erzwinge Beenden...")
            proc.kill()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
            print(f"🔴 {name} zwangsbeendet")

        self.current_process = None

    def _start_program(self, position):
        """Startet das Programm für die gegebene Drehschalter-Position"""
        if position not in PROGRAMS:
            print(f"⚠️  Position {position}: Kein Programm zugeordnet")
            self._speak(f"Position {position} nicht belegt")
            return

        name, module = PROGRAMS[position]

        # Aktuelles Programm beenden
        self._stop_current()

        # Kurze Pause damit Ressourcen (GPIO, VLC, I2C) freigegeben werden
        time.sleep(0.5)

        print(f"🚀 Starte {name} ({module})...")
        self._speak(name)

        try:
            # Subprozess starten: python3 -m media_center.xxx
            # Arbeitsverzeichnis = Projekt-Root, damit Package-Imports funktionieren
            self.current_process = subprocess.Popen(
                [sys.executable, '-m', module],
                cwd=str(PROJECT_DIR),
                # stdout/stderr durchreichen (sichtbar im Terminal)
            )
            self.current_program_name = name
            self.current_position = position
            print(f"✅ {name} gestartet (PID {self.current_process.pid})")

        except Exception as e:
            print(f"❌ Fehler beim Starten von {name}: {e}")
            self.current_process = None

    # ── Programmwechsel ──────────────────────────────────────────────

    def switch_to(self, position):
        """Wechselt zum Programm an der gegebenen Position"""
        if position == self.current_position:
            return  # Bereits aktiv

        if position not in PROGRAMS:
            # Nicht belegte Position → nur Info, kein Wechsel
            if self.current_position >= 0:
                print(f"ℹ️  Position {position} nicht belegt - {self.current_program_name} läuft weiter")
            return

        print(f"\n{'─' * 40}")
        print(f"🎛️  Drehschalter: Pos {self.current_position} → Pos {position}")
        print(f"{'─' * 40}")

        self._start_program(position)

    # ── Hauptschleife ────────────────────────────────────────────────

    def run(self):
        """Hauptschleife - liest I2C und wechselt Programme"""
        if not self.i2c_reader:
            print("❌ Kein I2C Reader - kann nicht starten")
            print("   Prüfe: i2c_reader_program.py vorhanden? I2C aktiviert?")
            return

        # Initiale Position lesen und erstes Programm starten
        try:
            switch, pot = self.i2c_reader.read_data()
            if switch is not None:
                print(f"📍 Initiale Drehschalter-Position: {switch}")
                self.switch_to(switch)
        except Exception as e:
            print(f"⚠️  Initiales Lesen fehlgeschlagen: {e}")
            # Fallback: Position 0 (Radio)
            self.switch_to(0)

        print("\n⏹️  Strg+C zum Beenden\n")

        try:
            while self.running:
                # Auf Interrupt vom Arduino warten
                if self.i2c_reader.interrupt_event.wait(timeout=1.0):
                    self.i2c_reader.interrupt_event.clear()
                    time.sleep(0.01)  # Kurz warten für Daten

                    switch, pot = self.i2c_reader.read_data()
                    if switch is not None:
                        self.switch_to(switch)

                # Prüfen ob Subprozess unerwartet beendet wurde
                if self.current_process and self.current_process.poll() is not None:
                    exit_code = self.current_process.returncode
                    print(f"⚠️  {self.current_program_name} unerwartet beendet (Exit {exit_code})")
                    print(f"🔄 Starte {self.current_program_name} neu...")
                    self.current_process = None
                    self._start_program(self.current_position)

        except KeyboardInterrupt:
            print("\n\n⏹️  Beende Programmauswahl...")
        finally:
            self.cleanup()

    def cleanup(self):
        """Aufräumen: Subprozess und I2C beenden"""
        self._stop_current()

        if self.i2c_reader:
            try:
                self.i2c_reader.cleanup()
            except Exception:
                pass

        if self._volume_bus:
            try:
                self._volume_bus.close()
            except Exception:
                pass

        print("✅ Programmauswahl beendet")


def main():
    """Entry-Point"""
    selector = ProgramSelector()

    def signal_handler(sig, frame):
        print(f"\n📶 Signal {sig}")
        selector.running = False

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    selector.run()


if __name__ == "__main__":
    main()
