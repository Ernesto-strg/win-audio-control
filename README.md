# audio-control

1. Verkable die rotary encoder an den Microcontroller.
2. Uploade die sketch_dec17b.ino datei aus dem ordner sketch_dec17b/ mit deinen Pin belegungen auf den microcontroller und passe je nachdem die anzahl der rotary encoder an.
3. Nutze die .exe oder audio-control.py und passe den com port in der im gleichen ordner liegenden config.json datei an, falls kein com port angegeben wird wird das erste gefundene gerät verwendet das ein com port nutzt.
4. Ändere die channels in der config.json, man hat 3 optionen:
   | Master | Verändert die Gesamt Lautstärke. |
   | foreground | Verändert die Lautstärke des im Vordergrund befindenden Prozesses. |
   | app | Verändert die Lautstärke einer selbst ausgewählten App. |
5. (Optional) Erstelle eine Verknüpfung der .exe im Windows Autostart Ordner.
