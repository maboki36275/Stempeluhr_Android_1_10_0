[app]
# Name und Kennung der App
title = Stempeluhr
package.name = stempeluhr
package.domain = de.faktura
version = 1.10.0

source.dir = .
source.include_exts = py,png
source.exclude_dirs = bin,.buildozer,__pycache__,.github

# pymysql ist reines Python; zeit.py und db.py kommen aus der Faktura
requirements = python3,kivy,pymysql,pyjnius

icon.filename = %(source.dir)s/icon.png
presplash.filename = %(source.dir)s/presplash.png
android.presplash_color = #1B1F24

# Tablet quer, Vollbild, Bildschirm bleibt an
orientation = landscape
fullscreen = 1
android.wakelock = True

android.permissions = INTERNET,ACCESS_NETWORK_STATE,WAKE_LOCK
android.api = 34
android.minapi = 24
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True
android.allow_backup = False

# Optional: Kiosk-Modus – die App kann als Startbildschirm festgelegt
# werden (startet dann auch nach einem Neustart des Tablets automatisch).
# Zeile aktivieren (# entfernen) und neu bauen, siehe ANLEITUNG.md.
#android.manifest.intent_filters = kiosk.xml

# bewährte Kombination: buildozer 1.5.0 + python-for-android 2024.01.21
p4a.branch = v2024.01.21

[buildozer]
log_level = 2
warn_on_root = 0
