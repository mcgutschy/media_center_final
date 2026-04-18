"""
Media Center Package

Modulare Struktur:
  - auswahl.py              : Programmauswahl (Entry-Point, Subprozess-Steuerung)
  - radio_player.py         : Radio-Modul (VLC, Stationen, Playlist-Auflösung)
  - youtube_player.py       : YouTube-Modul (yt-dlp, VLC, Kanalauswahl)
  - audiobook_player.py     : Hörbuch-Modul (VLC, Taster-Steuerung, Spielstand)
  - i2c_reader_program.py   : I2C Reader für Arduino 2 (Programmwahl, 0x09)
  - i2c_reader_content.py   : I2C Reader für Arduino 1 (Inhaltswahl, 0x08)
  - core.py                 : Monolithischer Media-Center-Kern (Legacy)

Konfiguration:
  - config/radio_stations.json
  - config/youtube_channels.json

Starten mit:
  cd media_center_organized
  python3 -m media_center
"""

from media_center.radio_player import IntegratedRadioPlayer
from media_center.audiobook_player import AudiobookPlayer
from media_center.core import MediaCenterFixed
