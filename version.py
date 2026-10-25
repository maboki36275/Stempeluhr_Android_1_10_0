# -*- coding: utf-8 -*-
"""(13.9.2) Zentrale Versions-/Revisionsnummer für alle Programmteile.

Faktura, Stempeluhr (Windows/Linux), Auftragsterminal und die Handy-App
(pwa, über stempel_api.py ausgeliefert) zeigen diese Nummer oben in der
Mitte an. Bei jeder neuen Version nur hier ändern."""

VERSION = "13.9.2"


def anzeige(programm=""):
    """Kurzer Text für die Kopfzeile, z. B. 'Rev. 13.9.2'."""
    return f"Rev. {VERSION}"
