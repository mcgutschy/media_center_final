#!/usr/bin/env python3
"""
I2C Reader für Arduino 2 (Programmwahl) - Interrupt-Modus

Liest Schalterposition (0-10) und Potentiometer (0-1023) vom Arduino 2
über I2C, wenn der Arduino einen Interrupt sendet (bei Änderungen).

Hardware:
  - Arduino 2 I2C Adresse: 0x09
  - Interrupt-Pin: GPIO 17
  - I2C: SDA (GPIO 2), SCL (GPIO 3)

Umbenannt von: i2c_reader_grün.py → i2c_reader_program.py

Installation:
  sudo apt install python3-smbus python3-gpiozero
  sudo raspi-config -> Interface Options -> I2C -> Enable
"""

import smbus
import time
from gpiozero import Button
from threading import Event

# Konfiguration
I2C_BUS = 1
ARDUINO_ADDR = 0x09
INTERRUPT_PIN = 17  # GPIO 17

class SimpleI2CReader:
    """Vereinfachter I2C Reader mit Interrupt-Unterstützung"""
    
    def __init__(self):
        self.bus = smbus.SMBus(I2C_BUS)
        self.interrupt_event = Event()
        self.running = True
        
        # GPIO-Interrupt einrichten
        self.button = Button(INTERRUPT_PIN, pull_up=False)
        self.button.when_pressed = self._interrupt_callback
        
        print(f"I2C Reader gestartet (Adresse 0x{ARDUINO_ADDR:02X})")
        print(f"Warte auf Interrupts von GPIO {INTERRUPT_PIN}...")
        print("Drücke Ctrl+C zum Beenden\n")
    
    def _interrupt_callback(self):
        """Wird aufgerufen, wenn Arduino Interrupt sendet"""
        self.interrupt_event.set()
    
    def read_data(self):
        """Liest 2 Bytes vom Arduino und dekodiert sie (2-Byte Format)"""
        try:
            # WICHTIG: Nur 2 Bytes lesen! Arduino sendet 2 Bytes.
            data = self.bus.read_i2c_block_data(ARDUINO_ADDR, 0, 2)
            switch = data[0]
            pot_8bit = data[1]
            pot = pot_8bit * 4  # 8-bit zurück auf 10-bit
            
            # Werte validieren
            if switch > 11:
                switch = 0
            if pot > 1023:
                pot = 1023
                
            return switch, pot
            
        except Exception as e:
            print(f"I2C Fehler: {e}")
            return None, None
    
    def format_output(self, switch, pot):
        """Formatiert die Ausgabe"""
        switch_text = f"Position {switch}"
        
        # Fortschrittsbalken für Potentiometer
        percent = int((pot / 1023) * 100)
        bar = "█" * (percent // 5) + "░" * (20 - (percent // 5))
        
        return f"{switch_text:15} | Pot: {pot:4} ({percent:3}%) [{bar}]"
    
    def run(self):
        """Hauptschleife - wartet auf Interrupts"""
        while self.running:
            try:
                # Warte auf Interrupt (max. 1 Sekunde)
                if self.interrupt_event.wait(timeout=1.0):
                    self.interrupt_event.clear()
                    
                    # Kurz warten, damit Arduino Daten bereit hat
                    time.sleep(0.01)
                    
                    # Daten lesen und anzeigen
                    switch, pot = self.read_data()
                    if switch is not None:
                        print(self.format_output(switch, pot))
                        
            except KeyboardInterrupt:
                print("\nBeendet durch Benutzer")
                self.running = False
            except Exception as e:
                print(f"Fehler: {e}")
    
    def cleanup(self):
        """Räumt Ressourcen auf"""
        self.running = False
        if hasattr(self, 'button'):
            self.button.close()
        if hasattr(self, 'bus'):
            self.bus.close()
        print("\nI2C Reader beendet")

def main():
    """Hauptfunktion"""
    reader = None
    try:
        reader = SimpleI2CReader()
        reader.run()
    except ImportError as e:
        print(f"Fehlende Abhängigkeit: {e}")
        print("Installiere: sudo apt install python3-smbus python3-gpiozero")
    except Exception as e:
        print(f"Startfehler: {e}")
    finally:
        if reader:
            reader.cleanup()

if __name__ == "__main__":
    main()
