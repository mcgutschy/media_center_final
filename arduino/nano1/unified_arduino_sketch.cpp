/*
 * Arduino Nano 1 (ROT) - Lautstärke und Unterprogramm Auswahl
 * 
 * Hardware:
 *   - 11-Position Drehschalter an Pins 2-12
 *   - Potentiometer an A0 (für Lautstärke)
 *   - Interrupt-Pin: Pin 15 (A1) -> Raspberry Pi GPIO 16
 *   - LED an Pin 13 (ROT)
 *   - I2C-Adresse: 0x08
 * 
 * Funktion:
 *   - Liest Schalterposition (1-11 = Radio-Stationen/Unterprogramme)
 *   - Liest Potentiometer für Lautstärkeregelung
 *   - Sendet Interrupt an Raspberry Pi bei Änderungen
 *   - Raspberry Pi fragt Daten per I2C nach Interrupt ab
 * 
 * Datenformat: 2 Bytes
 *   Byte 0: Schalterposition (1-11, 0 = keine)
 *   Byte 1: Potentiometer-Wert >> 2 (10-bit auf 8-bit reduziert)
 */

#include <Arduino.h>
#include <Wire.h>

// KONFIGURATION FÜR NANO 1 (ROT)
#define I2C_SLAVE_ADDRESS 0x08    // I2C-Adresse für Radio-Arduino
#define INTERRUPT_PIN 15           // A1 -> Raspberry Pi GPIO 16
#define POTENTIOMETER_PIN A0       // Lautstärke-Potentiometer
#define LED_PIN 13                 // ROTE LED

// Schalter-Pins (11 Positionen)
const int switchPins[] = {2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12};
const int NUM_SWITCHES = 11;

// Globale Variablen
int currentSwitchValue = 0;      // Aktuelle Schalterposition (1-11)
int lastSwitchValue = 0;         // Letzte Position für Änderungserkennung
int potentiometerValue = 0;      // Aktueller Potentiometer-Wert (0-1023)
unsigned long lastInterruptTime = 0;
const unsigned long DEBOUNCE_DELAY = 50;  // Entprellzeit in ms

// Funktionsprototypen
int readSwitchValue();
void sendInterrupt();
void requestEvent();

void setup() {
  // Serial für Debugging
  Serial.begin(9600);
  Serial.println("=== Arduino Nano 1 (ROT) ===");
  Serial.println("Funktion: Lautstärke und Unterprogramm Auswahl");
  Serial.print("I2C-Adresse: 0x");
  Serial.println(I2C_SLAVE_ADDRESS, HEX);
  Serial.println("Interrupt-Pin: 15 (A1) -> GPIO 16");
  
  // ROTE LED
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);
  
  // Schalter-Pins als INPUT_PULLUP konfigurieren
  for (int i = 0; i < NUM_SWITCHES; i++) {
    pinMode(switchPins[i], INPUT_PULLUP);
  }
  
  // Interrupt-Pin als OUTPUT (sendet Interrupts an Raspberry Pi)
  pinMode(INTERRUPT_PIN, OUTPUT);
  digitalWrite(INTERRUPT_PIN, HIGH);  // Pull-up (aktiv LOW)
  
  // I2C als Slave initialisieren
  Wire.begin(I2C_SLAVE_ADDRESS);
  Wire.onRequest(requestEvent);  // Callback für I2C-Leseanfragen
  
  Serial.println("✅ Slave bereit");
  Serial.println("📻 Warte auf Schalter-Änderungen...");
  Serial.println("🎚️  Drehe Potentiometer für Lautstärke");
}

void loop() {
  // Schalter lesen
  int switchValue = readSwitchValue();
  
  // Potentiometer lesen (Lautstärke)
  int potValue = analogRead(POTENTIOMETER_PIN);
  
  // Prüfe auf Änderungen
  if (switchValue != lastSwitchValue) {
    currentSwitchValue = switchValue;
    lastSwitchValue = switchValue;
    
    // Interrupt an Raspberry Pi senden
    sendInterrupt();
    
    // ROTE LED: an bei Position 1-5, aus bei 6-11
    if (switchValue >= 1 && switchValue <= 5) {
      digitalWrite(LED_PIN, HIGH);
    } else {
      digitalWrite(LED_PIN, LOW);
    }
    
    // Debug-Ausgabe
    Serial.print("📻 Neue Radio-Position: ");
    Serial.println(switchValue);
  }
  
  // Potentiometer-Änderung (alle 100ms prüfen)
  static unsigned long lastPotCheck = 0;
  if (millis() - lastPotCheck > 100) {
    lastPotCheck = millis();
    
    // Signifikante Änderung? (mehr als 10 Einheiten)
    if (abs(potValue - potentiometerValue) > 10) {
      potentiometerValue = potValue;
      sendInterrupt();  // Auch Lautstärkeänderung melden
      
      // Debug-Ausgabe
      Serial.print("🎚️  Lautstärke-Potentiometer: ");
      Serial.println(potentiometerValue);
    }
  }
  
  // Kurze Pause
  delay(30);
}

int readSwitchValue() {
  // Scanne alle Schalter-Pins
  for (int i = 0; i < NUM_SWITCHES; i++) {
    if (digitalRead(switchPins[i]) == LOW) {
      return i + 1;  // Position 1-11
    }
  }
  return 0;  // Kein Schalter gedrückt
}

void sendInterrupt() {
  // Entprellung
  unsigned long currentTime = millis();
  if (currentTime - lastInterruptTime < DEBOUNCE_DELAY) {
    return;
  }
  lastInterruptTime = currentTime;
  
  // Interrupt an Raspberry Pi senden (aktiv LOW)
  digitalWrite(INTERRUPT_PIN, LOW);
  delayMicroseconds(100);  // Kurzer Impuls
  digitalWrite(INTERRUPT_PIN, HIGH);
  
  Serial.println("📡 Interrupt an Raspberry Pi gesendet");
}

// I2C Callback: Sendet Daten an Raspberry Pi
// WICHTIG: Sendet 2 Bytes im 8-bit Format
void requestEvent() {
  // Sende 2 Bytes: Schalterposition + Potentiometer (8-bit)
  byte data[2];
  data[0] = currentSwitchValue;  // Schalterposition (1-11)
  data[1] = potentiometerValue >> 2;  // 10-bit auf 8-bit reduzieren
  
  Wire.write(data, 2);
  
  // Debug-Ausgabe
  Serial.print("🔗 I2C gesendet: Position=");
  Serial.print(currentSwitchValue);
  Serial.print(", Lautstärke=");
  Serial.println(potentiometerValue);
}
