#!/usr/bin/env python3
"""
Media Center Core - Programmwahl und Hardware-Steuerung (Legacy/Monolithisch)

Dies ist der monolithische Media-Center-Kern, der alle Player in einem
einzigen Prozess verwaltet. Für den normalen Betrieb wird stattdessen
auswahl.py empfohlen, das die Player als separate Subprozesse startet.

Verantwortlich für:
  - GPIO-Interrupts (oder Polling-Fallback)
  - I2C-Kommunikation mit zwei Arduinos
  - Programmwahl über Arduino 2 (Adresse 0x09, GPIO 17)
  - Weiterleitung von Radio-Daten an den Radio-Player (Arduino 1: 0x08, GPIO 16)
  - Hörbuch-Taster (GPIO 22, 23, 24)

Hardware-Setup:
  Arduino 1 (0x08): Drehschalter (Station 0-10) + Poti (Lautstärke)
  Arduino 2 (0x09): Drehschalter (Programm 0-10) + Poti (Tonhöhe)
  GPIO 16: Interrupt von Arduino 1
  GPIO 17: Interrupt von Arduino 2
  GPIO 22/23/24: Hörbuch-Taster (Play/Pause, +30s, -30s)

Umbenannt von: media_center.py → core.py
"""

import sys
import time
import os
from threading import Thread, Event

import smbus
import RPi.GPIO as GPIO

from kopf_media_center.radio_player import IntegratedRadioPlayer
from kopf_media_center.audiobook_player import AudiobookPlayer

# =============================================================================
# Konfiguration
# =============================================================================
RADIO_ARDUINO_ADDRESS = 0x08
PROGRAM_ARDUINO_ADDRESS = 0x09
I2C_BUS = 1

# GPIO-Pins (BCM-Nummerierung)
RADIO_INTERRUPT_PIN = 16
PROGRAM_INTERRUPT_PIN = 17
BUTTON_PLAY_PAUSE = 22
BUTTON_FORWARD = 23
BUTTON_BACKWARD = 24


class MediaCenterFixed:
    """Media Center mit Programmwahl und Hardware-Steuerung"""
    
    def __init__(self):
        self.running = True
        self.current_program = -1  # -1 = noch nicht initialisiert
        self.current_volume = 50
        self.current_pitch = 50
        
        # Interrupt-Events
        self.program_interrupt_event = Event()
        self.radio_interrupt_event = Event()
        
        # Player-Module (werden bei Bedarf erstellt)
        self.radio_player = None
        self.audiobook_player = None
        
        # I2C Bus
        try:
            self.bus = smbus.SMBus(I2C_BUS)
            self.i2c_available = True
        except Exception as e:
            print(f"⚠️  I2C Fehler: {e}")
            self.i2c_available = False
        
        # GPIO Setup
        self.use_interrupts = False
        self._setup_gpio()
        
        # Letzte Zustände für Taster-Polling
        self.last_play_state = True
        self.last_forward_state = True
        self.last_backward_state = True
        
        # Threads
        self.event_thread = Thread(target=self._event_loop, daemon=True)
        self.i2c_thread = Thread(target=self._i2c_startup, daemon=True)
        
        print("="*60)
        print("🎵 MEDIA CENTER (Core/Legacy)")
        print("="*60)
        print(f"Arduino 1 (Radio):    0x{RADIO_ARDUINO_ADDRESS:02x}, GPIO {RADIO_INTERRUPT_PIN}")
        print(f"Arduino 2 (Programm): 0x{PROGRAM_ARDUINO_ADDRESS:02x}, GPIO {PROGRAM_INTERRUPT_PIN}")
        print(f"Interrupts: {'✅ aktiv' if self.use_interrupts else '❌ Polling'}")
        print(f"I2C: {'✅' if self.i2c_available else '❌'}")
        print("")
        print("Programme: 0=Aus, 1=Radio, 2=Hörbuch, 3-10=erweiterbar")
        print("Drücke Strg+C zum Beenden")
        print("="*60 + "\n")
    
    # =========================================================================
    # GPIO Setup
    # =========================================================================
    def _setup_gpio(self):
        """GPIO konfigurieren: Interrupts mit Polling-Fallback"""
        try:
            GPIO.setmode(GPIO.BCM)
            
            GPIO.setup(RADIO_INTERRUPT_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.setup(PROGRAM_INTERRUPT_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.setup(BUTTON_PLAY_PAUSE, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.setup(BUTTON_FORWARD, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.setup(BUTTON_BACKWARD, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            
            # Versuche Interrupts
            try:
                GPIO.add_event_detect(
                    PROGRAM_INTERRUPT_PIN, GPIO.FALLING,
                    callback=self._on_program_interrupt,
                    bouncetime=200
                )
                GPIO.add_event_detect(
                    RADIO_INTERRUPT_PIN, GPIO.FALLING,
                    callback=self._on_radio_interrupt,
                    bouncetime=200
                )
                self.use_interrupts = True
                print("✅ GPIO Interrupts aktiviert")
            except Exception as e:
                print(f"⚠️  Interrupts fehlgeschlagen: {e} - Polling-Fallback")
                self.use_interrupts = False
            
        except Exception as e:
            print(f"❌ GPIO Setup Fehler: {e}")
            raise
    
    def _on_program_interrupt(self, channel):
        """Interrupt-Callback: Arduino 2"""
        self.program_interrupt_event.set()
    
    def _on_radio_interrupt(self, channel):
        """Interrupt-Callback: Arduino 1"""
        self.radio_interrupt_event.set()
    
    # =========================================================================
    # I2C Lesen
    # =========================================================================
    def _read_arduino(self, address):
        """Liest 2 Bytes von einem Arduino: (switch, pot) oder (None, None)"""
        if not self.i2c_available:
            return None, None
        try:
            data = self.bus.read_i2c_block_data(address, 0, 2)
            switch = data[0]
            pot = data[1] * 4  # 8-bit → 10-bit
            if switch > 11:
                switch = 0
            if pot > 1023:
                pot = 1023
            return switch, pot
        except Exception:
            return None, None
    
    # =========================================================================
    # Event-Loop
    # =========================================================================
    def _event_loop(self):
        """Haupt-Event-Schleife: reagiert auf Interrupts oder pollt"""
        print("🔄 Event-Loop gestartet")
        
        last_program_pin = GPIO.input(PROGRAM_INTERRUPT_PIN)
        last_radio_pin = GPIO.input(RADIO_INTERRUPT_PIN)
        
        while self.running:
            try:
                if self.use_interrupts:
                    # === Interrupt-Modus ===
                    if self.program_interrupt_event.wait(timeout=0.05):
                        self.program_interrupt_event.clear()
                        time.sleep(0.01)
                        self._process_program_arduino()
                    
                    if self.radio_interrupt_event.wait(timeout=0.05):
                        self.radio_interrupt_event.clear()
                        time.sleep(0.01)
                        self._process_radio_arduino()
                else:
                    # === Polling-Fallback ===
                    program_pin = GPIO.input(PROGRAM_INTERRUPT_PIN)
                    if program_pin == False and last_program_pin == True:
                        time.sleep(0.01)
                        self._process_program_arduino()
                    last_program_pin = program_pin
                    
                    radio_pin = GPIO.input(RADIO_INTERRUPT_PIN)
                    if radio_pin == False and last_radio_pin == True:
                        time.sleep(0.01)
                        self._process_radio_arduino()
                    last_radio_pin = radio_pin
                
                # Taster-Polling
                self._poll_buttons()
                
                time.sleep(0.02)
                
            except Exception as e:
                print(f"[EVENT] Fehler: {e}")
                time.sleep(1)
    
    def _process_program_arduino(self):
        """Verarbeitet Daten vom Program-Arduino (0x09)"""
        switch, pot = self._read_arduino(PROGRAM_ARDUINO_ADDRESS)
        if switch is None:
            return
        
        # Programmwechsel
        if switch != self.current_program:
            self._switch_program(switch)
        
        # Tonhöhe
        pitch = int((pot / 1023) * 100)
        if abs(pitch - self.current_pitch) > 2:
            self.current_pitch = pitch
            print(f"[PROGRAMM] Tonhöhe: {pitch}%")
    
    def _process_radio_arduino(self):
        """Verarbeitet Daten vom Radio-Arduino (0x08)"""
        switch, pot = self._read_arduino(RADIO_ARDUINO_ADDRESS)
        if switch is None:
            return
        
        if self.current_program == 1 and self.radio_player:
            # === RADIO-MODUS ===
            # Stationswechsel
            station_key = str(switch)
            if station_key != self.radio_player.current_station and station_key in self.radio_player.stations:
                self.radio_player.change_station(station_key)
            
            # Lautstärke
            volume = int((pot / 1023) * 100)
            self.radio_player.set_volume(volume)
            
        elif self.current_program == 2 and self.audiobook_player:
            # === HÖRBUCH-MODUS ===
            # Hörbuch-Auswahl per Drehschalter (0-10)
            self.audiobook_player.select_audiobook_by_index(switch)
    
    def _poll_buttons(self):
        """Pollt Hörbuch-Taster"""
        play = GPIO.input(BUTTON_PLAY_PAUSE)
        if play == False and self.last_play_state == True:
            if self.current_program == 2 and self.audiobook_player:
                self.audiobook_player.toggle_pause()
            elif self.current_program == 2:
                print("[HÖRBUCH] Play/Pause (noch nicht bereit)")
        self.last_play_state = play
        
        fwd = GPIO.input(BUTTON_FORWARD)
        if fwd == False and self.last_forward_state == True:
            if self.current_program == 2 and self.audiobook_player:
                self.audiobook_player.skip_forward()
        self.last_forward_state = fwd
        
        bwd = GPIO.input(BUTTON_BACKWARD)
        if bwd == False and self.last_backward_state == True:
            if self.current_program == 2 and self.audiobook_player:
                self.audiobook_player.skip_backward()
        self.last_backward_state = bwd
    
    # =========================================================================
    # I2C Startup (Scan + initiale Position)
    # =========================================================================
    def _i2c_startup(self):
        """I2C-Geräte scannen und initiale Positionen lesen"""
        if not self.i2c_available:
            print("⚠️  I2C nicht verfügbar")
            return
        
        # I2C-Scan
        print("🔍 I2C Scan...")
        devices = []
        for addr in range(0x08, 0x78):
            try:
                self.bus.read_byte(addr)
                devices.append(f"0x{addr:02x}")
            except:
                pass
        
        if devices:
            print(f"✅ I2C Geräte: {', '.join(devices)}")
        else:
            print("⚠️  Keine I2C Geräte gefunden")
        
        # Initiale Position lesen
        time.sleep(0.5)
        print("📡 Lese initiale Positionen...")
        
        # Arduino 2: Programmwahl
        switch, pot = self._read_arduino(PROGRAM_ARDUINO_ADDRESS)
        if switch is not None:
            print(f"   Arduino 2 (Programm): Position={switch}, Poti={pot}")
            self._switch_program(switch)
        else:
            print("   ⚠️  Arduino 2 nicht erreichbar")
        
        # Arduino 1: Radio-Station oder Hörbuch-Auswahl
        switch, pot = self._read_arduino(RADIO_ARDUINO_ADDRESS)
        if switch is not None:
            print(f"   Arduino 1: Position={switch}, Poti={pot}")
            if self.current_program == 1 and self.radio_player:
                # Radio: Station wählen
                station_key = str(switch)
                if station_key in self.radio_player.stations:
                    self.radio_player.change_station(station_key)
                volume = int((pot / 1023) * 100)
                self.radio_player.set_volume(volume)
            elif self.current_program == 2 and self.audiobook_player:
                # Hörbuch: Datei wählen
                self.audiobook_player.select_audiobook_by_index(switch)
        else:
            print("   ⚠️  Arduino 1 nicht erreichbar")
    
    # =========================================================================
    # Programmwechsel
    # =========================================================================
    def _switch_program(self, program_position):
        """Wechselt zwischen Programmen"""
        if program_position == self.current_program:
            return
        
        print(f"\n{'='*50}")
        print(f"📻 PROGRAMM WECHSEL: {self.current_program} → {program_position}")
        print(f"{'='*50}")
        
        # Aktuelles Programm stoppen
        self._stop_current_program()
        
        self.current_program = program_position
        
        if program_position == 1:
            # === RADIO ===
            print("🎵 Starte Radio...")
            self.radio_player = IntegratedRadioPlayer()
            
            # Stationsliste anzeigen
            stations = self.radio_player.get_station_list()
            for key, station in sorted(stations.items(), key=lambda x: int(x[0])):
                print(f"   {key}: {station['name']} ({station.get('genre', '')})")
            
            # Aktuelle Position vom Radio-Arduino lesen
            switch, pot = self._read_arduino(RADIO_ARDUINO_ADDRESS)
            if switch is not None:
                station_key = str(switch)
                if station_key in stations:
                    self.radio_player.change_station(station_key)
                volume = int((pot / 1023) * 100)
                self.radio_player.set_volume(volume)
            
        elif program_position == 2:
            # === HÖRBUCH ===
            print("📚 Starte Hörbuch-Player...")
            self.audiobook_player = AudiobookPlayer()
            
            # Aktuelle Position vom Arduino 1 lesen und Hörbuch wählen
            switch, pot = self._read_arduino(RADIO_ARDUINO_ADDRESS)
            if switch is not None:
                print(f"   Drehschalter Position {switch} → Hörbuch-Auswahl")
                self.audiobook_player.select_audiobook_by_index(switch)
            else:
                # Fallback: erstes Hörbuch
                self.audiobook_player.play_audiobook()
            
        elif program_position >= 3:
            print(f"💿 Programm {program_position} noch nicht implementiert")
            
        else:
            print("📺 Kein Programm aktiv (Position 0)")
    
    def _stop_current_program(self):
        """Stoppt das aktuelle Programm"""
        if self.radio_player:
            self.radio_player.stop()
            self.radio_player = None
            print("   ⏹️  Radio beendet")
        
        if self.audiobook_player:
            self.audiobook_player.cleanup()
            self.audiobook_player = None
            print("   ⏹️  Hörbuch beendet")
    
    # =========================================================================
    # Hauptschleife und Cleanup
    # =========================================================================
    def run(self):
        """Startet das Media Center"""
        self.event_thread.start()
        self.i2c_thread.start()
        
        print("\n" + "="*50)
        print("🎵 MEDIA CENTER BEREIT")
        print("="*50)
        print("📻 Drehe Programmwähler (Arduino 2)")
        print("🎚️  Drehe Poti Arduino 1 für Lautstärke")
        print("⏹️  Strg+C zum Beenden")
        print("="*50 + "\n")
        
        try:
            while self.running:
                # Status alle 30s
                if int(time.time()) % 30 == 0:
                    self._print_status()
                time.sleep(1)
                
        except KeyboardInterrupt:
            print("\n\n⏹️  Beende durch Strg+C...")
        except Exception as e:
            print(f"\n⚠️  Fehler: {e}")
        finally:
            self.cleanup()
    
    def _print_status(self):
        """Zeigt den aktuellen Status an"""
        if self.current_program == 1 and self.radio_player:
            playing = "▶️" if self.radio_player.is_playing() else "⏸️"
            name = self.radio_player.get_current_station_name() or "?"
            print(f"[STATUS] {playing} Radio: {name}, 🔊 {self.radio_player.current_volume}%")
        elif self.current_program == 2 and self.audiobook_player:
            playing = "▶️"
            name = "Hörbuch"
            print(f"[STATUS] {playing} Hörbuch: {name}")
        elif self.current_program == 0:
            print("[STATUS] 📺 Kein Programm")
        else:
            print(f"[STATUS] Programm {self.current_program}")
    
    def cleanup(self):
        """Sauberes Beenden"""
        print("\n🧹 Räume auf...")
        self.running = False
        
        self._stop_current_program()
        time.sleep(0.5)
        
        try:
            GPIO.cleanup()
            print("✅ GPIO aufgeräumt")
        except:
            pass
        
        try:
            if hasattr(self, 'bus'):
                self.bus.close()
        except:
            pass
        
        print("✅ Media Center beendet")
