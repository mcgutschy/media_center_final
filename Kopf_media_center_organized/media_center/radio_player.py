#!/usr/bin/env python3
"""
Radio-Player-Modul für das Media Center

Verantwortlich für:
  - Laden der Radio-Stationen aus config/radio_stations.json
  - Auflösen von Playlist-URLs (.m3u, .m3u8, .pls)
  - VLC-Wiedergabe mit dynamischer Lautstärke
  - Stationswechsel

Wird vom Media Center importiert und gesteuert.
Kann auch standalone genutzt werden (siehe main() unten).

Starten:
  cd media_center_organized
  python3 -m media_center.radio_player
"""

import json
import os
import re
import time
from urllib.request import urlopen, Request
from urllib.error import URLError

try:
    import vlc
    VLC_AVAILABLE = True
except ImportError:
    print("⚠️  python-vlc nicht installiert: sudo apt install python3-vlc vlc")
    VLC_AVAILABLE = False

# Pfad zur Stationsdatei (relativ zum Projekt-Root)
_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_MODULE_DIR)
DEFAULT_STATIONS_FILE = os.path.join(_PROJECT_DIR, "config", "radio_stations.json")


class IntegratedRadioPlayer:
    """Radio-Player mit VLC und dynamischer Lautstärke"""
    
    def __init__(self, stations_file=None):
        self.stations_file = stations_file or DEFAULT_STATIONS_FILE
        self.stations = self._load_stations()
        self.current_station = None
        self.current_volume = 50
        self.instance = None
        self.player = None
        
        if VLC_AVAILABLE:
            self._init_vlc()
        else:
            print("   ⚠️  VLC nicht verfügbar - Radio nur simuliert")
    
    def _load_stations(self):
        """Lädt Radio-Stationen aus JSON-Datei oder Fallback"""
        if os.path.exists(self.stations_file):
            try:
                with open(self.stations_file, 'r') as f:
                    stations = json.load(f)
                print(f"   📻 {len(stations)} Stationen aus {os.path.basename(self.stations_file)} geladen")
                return stations
            except json.JSONDecodeError as e:
                print(f"   ❌ JSON-Fehler in {self.stations_file}: {e}")
            except Exception as e:
                print(f"   ⚠️  Fehler beim Laden: {e}")
        else:
            print(f"   ⚠️  Datei nicht gefunden: {self.stations_file}")
        
        # Fallback: Getestete Stationen
        print("   📻 Verwende Fallback-Stationen")
        return {
            "0": {"name": "WDR 3", "url": "https://wdr-wdr3-live.icecastssl.wdr.de/wdr/wdr3/live/mp3/256/stream.mp3", "genre": "Kultur"},
            "1": {"name": "Deutschlandfunk", "url": "http://st01.dlf.de/dlf/01/128/mp3/stream.mp3", "genre": "Nachrichten"},
            "2": {"name": "Bayern 2", "url": "http://br-br2-nord.cast.addradio.de/br/br2/nord/mp3/128/stream.mp3", "genre": "Klassik"},
            "3": {"name": "SWR3", "url": "http://swr-swr3-live.cast.addradio.de/swr/swr3/live/mp3/128/stream.mp3", "genre": "Pop"},
            "4": {"name": "Radio Bob", "url": "http://streams.radiobob.de/bob-live/mp3-192/streams.radiobob.de/", "genre": "Rock"},
            "5": {"name": "1LIVE", "url": "http://wdr-1live-live.icecast.wdr.de/wdr/1live/live/mp3/128/stream.mp3", "genre": "Jugend"},
        }
    
    def _init_vlc(self):
        """VLC mit Audio-Fallback initialisieren"""
        # Versuche verschiedene Audio-Ausgabe-Optionen
        # Karte 2 = bcm2835 Headphones (3.5mm Klinke)
        audio_options = [
            ['--no-video', '--aout=alsa', '--alsa-audio-device=plughw:2,0'],
            ['--no-video', '--aout=alsa', '--alsa-audio-device=hw:2,0'],
            ['--no-video', '--aout=alsa'],
            ['--no-video'],
        ]
        
        for options in audio_options:
            try:
                self.instance = vlc.Instance(*options)
                self.player = self.instance.media_player_new()
                print(f"   ✅ VLC Audio: {' '.join(options)}")
                return
            except Exception:
                continue
        
        # Letzter Fallback
        self.instance = vlc.Instance('--no-video')
        self.player = self.instance.media_player_new()
        print("   ⚠️  VLC mit Standard-Audio gestartet")
    
    def resolve_playlist_url(self, url):
        """Löst .m3u/.m3u8/.pls Playlist-URLs zum direkten Stream auf"""
        lower_url = url.lower().rstrip('/')
        is_playlist = any(lower_url.endswith(ext) for ext in ('.m3u', '.m3u8', '.pls'))
        
        if not is_playlist:
            return url
        
        print(f"   📋 Playlist erkannt: {url}")
        try:
            req = Request(url, headers={'User-Agent': 'VLC/3.0'})
            with urlopen(req, timeout=10) as response:
                content = response.read().decode('utf-8', errors='ignore')
            
            # .pls Format
            if lower_url.endswith('.pls'):
                for line in content.splitlines():
                    match = re.match(r'File\d*\s*=\s*(https?://\S+)', line.strip(), re.IGNORECASE)
                    if match:
                        resolved = match.group(1)
                        print(f"   ✓ PLS aufgelöst: {resolved}")
                        return resolved
            
            # .m3u / .m3u8 Format
            for line in content.splitlines():
                line = line.strip()
                if line and not line.startswith('#') and (line.startswith('http://') or line.startswith('https://')):
                    print(f"   ✓ M3U aufgelöst: {line}")
                    return line
            
            print("   ⚠️  Keine URL in Playlist gefunden")
            return url
        except Exception as e:
            print(f"   ⚠️  Playlist-Auflösung fehlgeschlagen: {e}")
            return url
    
    def change_station(self, station_key):
        """Wechselt zur angegebenen Radio-Station"""
        if station_key not in self.stations:
            print(f"   ⚠️  Unbekannte Station: {station_key}")
            return
        
        station = self.stations[station_key]
        print(f"   🎵 Wechsle zu: {station['name']}")
        
        if not self.player:
            print("   ⚠️  VLC nicht verfügbar")
            return
        
        # Aktuelle Wiedergabe stoppen
        if self.player.is_playing():
            self.player.stop()
            time.sleep(0.1)
        
        # Playlist-URL auflösen
        stream_url = self.resolve_playlist_url(station['url'])
        
        # Neue Station laden und abspielen
        media = self.instance.media_new(stream_url)
        self.player.set_media(media)
        self.player.audio_set_volume(self.current_volume)
        self.player.play()
        
        self.current_station = station_key
        
        # Status prüfen
        wait_time = 2 if stream_url != station['url'] else 1
        time.sleep(wait_time)
        if self.player.is_playing():
            print(f"   ✅ {station['name']} spielt")
        else:
            print(f"   ⚠️  {station['name']} spielt nicht (URL: {stream_url})")
    
    def set_volume(self, volume):
        """Setzt Lautstärke dynamisch (0-100)"""
        volume = max(0, min(100, volume))
        if volume != self.current_volume:
            self.current_volume = volume
            if self.player:
                self.player.audio_set_volume(volume)
            print(f"   🔊 Lautstärke: {volume}%")
    
    def stop(self):
        """Stoppt die Radio-Wiedergabe"""
        if self.player and self.player.is_playing():
            self.player.stop()
            print("   ⏹️  Radio gestoppt")
        self.current_station = None
    
    def is_playing(self):
        """Prüft ob gerade abgespielt wird"""
        return self.player is not None and self.player.is_playing()
    
    def get_station_list(self):
        """Gibt die Stationsliste zurück"""
        return self.stations
    
    def get_current_station_name(self):
        """Gibt den Namen der aktuellen Station zurück"""
        if self.current_station and self.current_station in self.stations:
            return self.stations[self.current_station].get('name', '?')
        return None


# =============================================================================
# Standalone-Modus (ohne Media Center)
# =============================================================================
def main():
    """Standalone Radio Player mit I2C-Steuerung"""
    import signal
    import sys
    
    # Versuche I2C Reader zu importieren
    try:
        from media_center.i2c_reader_content import SimpleI2CReader
        i2c_available = True
    except ImportError:
        print("⚠️  i2c_reader_content.py nicht gefunden - Standalone ohne I2C")
        i2c_available = False
    
    player = IntegratedRadioPlayer()
    running = True
    
    def handle_signal(sig, frame):
        nonlocal running
        running = False
    
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    
    print("\n" + "="*50)
    print("🎧 RADIO PLAYER (STANDALONE)")
    print("="*50)
    for key, station in sorted(player.stations.items(), key=lambda x: int(x[0])):
        print(f"  {key}: {station['name']} ({station.get('genre', '')})")
    print("="*50 + "\n")
    
    if i2c_available:
        reader = SimpleI2CReader()
        
        # Initiale Position lesen
        switch, pot = reader.read_data()
        if switch is not None:
            station_key = str(switch)
            if station_key in player.stations:
                player.change_station(station_key)
            if pot is not None:
                player.set_volume(int((pot / 1023) * 100))
        
        # Hauptschleife mit I2C
        while running:
            if reader.interrupt_event.wait(timeout=1.0):
                reader.interrupt_event.clear()
                time.sleep(0.01)
                switch, pot = reader.read_data()
                if switch is not None:
                    station_key = str(switch)
                    if station_key != player.current_station and station_key in player.stations:
                        player.change_station(station_key)
                    if pot is not None:
                        player.set_volume(int((pot / 1023) * 100))
        
        reader.cleanup()
    else:
        # Ohne I2C: Erste Station abspielen
        if "1" in player.stations:
            player.change_station("1")
        
        while running:
            time.sleep(1)
    
    player.stop()
    print("\n👋 Radio Player beendet")


if __name__ == "__main__":
    main()
