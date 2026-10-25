# -*- coding: utf-8 -*-
"""
Stempeluhr für Android-Tablets (Kivy) – gleiches Aussehen und gleiche
Funktionen wie das Terminal-Programm stempeluhr.py der Faktura.

- Taste "Kommt", "Geht", "Anfang Pause" oder "Ende Pause" antippen und
  dann die RFID-Karte an den Leser halten – oder zuerst die Karte, dann
  die Taste. Karte ohne Taste: Name, Status und Stundenstand.
- Nach dem Stempeln bzw. Karte vorhalten erscheinen einige Sekunden die
  Knöpfe "Monatsübersicht" (alle Stempelzeiten des Monats, Arbeitszeit,
  Pausen und Stundenkonto), "Urlaub beantragen" (Genehmigung im Büro;
  Auswahl nach Kalenderwochen, Urlaubssperren, "Urlaub stornieren")
  und "Auftrag" (Arbeitszeit auf einen offenen Auftrag buchen, nur wenn
  eingestempelt). Alle Fenster schließen mit "Schließen" oder
  automatisch.
- Nachrichten aus dem Büro erscheinen nach dem Stempeln, bis sie mit
  "Gelesen" bestätigt werden; danach offene Anfragen zum Einspringen
  (Ja/Nein). Knopf "Korrektur": fehlende/falsche Stempelung beantragen
  (ab Version 1.8 / Faktura 9.7).
- Knopf "Auftragsbearbeitung" (ab Version 1.9 / Faktura 10.3, nur wenn das
  Modul Auftragsverarbeitung aktiv ist und ein Auftrag für den Mitarbeiter
  vorliegt): Auftrag wählen, Arbeitszeit auf einen vordefinierten
  Arbeitsschritt buchen und verarbeitetes Material mit Menge melden.
- USB-RFID-Leser (per OTG-Adapter) arbeiten wie eine Tastatur. Die App
  nimmt die Kartennummer direkt entgegen, ohne Bildschirmtastatur.
  Tippen auf das Kartenfeld öffnet eine Eingabe von Hand.
- Zurück-Taste (bzw. Esc): Menü mit Beenden und Verbindung einrichten
  (PIN laut Firmenstamm, Register Zeiterfassung).
- Fällt die Verbindung zur Datenbank aus, werden Stempelungen auf dem
  Tablet gespeichert und automatisch nachgetragen.

Berechnungen (zeit.py) und Datenbankzugriff (db.py) sind dieselben
Dateien wie in der Faktura.
"""

import configparser
import datetime
import json
import os
import threading
import time

os.environ.setdefault("KIVY_NO_ARGS", "1")
os.environ.setdefault("KIVY_LOG_MODE", "PYTHON")

from kivy.config import Config  # noqa: E402

Config.set("kivy", "exit_on_escape", "0")
Config.set("input", "mouse", "mouse,disable_multitouch")

from kivy.app import App  # noqa: E402
from kivy.clock import Clock  # noqa: E402
from kivy.core.window import Window  # noqa: E402
from kivy.graphics import Color, Line, Rectangle  # noqa: E402
from kivy.properties import BooleanProperty, ListProperty  # noqa: E402
from kivy.uix.boxlayout import BoxLayout  # noqa: E402
from kivy.uix.button import Button  # noqa: E402
from kivy.uix.checkbox import CheckBox  # noqa: E402
from kivy.uix.gridlayout import GridLayout  # noqa: E402
from kivy.uix.label import Label  # noqa: E402
from kivy.uix.modalview import ModalView  # noqa: E402
from kivy.uix.popup import Popup  # noqa: E402
from kivy.uix.scrollview import ScrollView  # noqa: E402
from kivy.uix.textinput import TextInput  # noqa: E402
from kivy.uix.widget import Widget  # noqa: E402
from kivy.utils import get_color_from_hex, platform  # noqa: E402

try:
    import pymysql
except ImportError:          # pragma: no cover
    pymysql = None

import zeit  # noqa: E402
import av_tablet  # noqa: E402  (1.10.0) Auftragsbearbeitung am Tablet

try:
    from version import VERSION as FAKTURA_REVISION  # noqa: E402
except ImportError:
    FAKTURA_REVISION = "?"
APP_VERSION = "1.10.0"   # muss zu 'version' in buildozer.spec passen

TASTEN = [("kommt", "Kommt", "#1E8C3A", "#27B04A"),
          ("geht", "Geht", "#B3261E", "#D9362B"),
          ("pause_an", "Anfang Pause", "#C77700", "#E58A00"),
          ("pause_ende", "Ende Pause", "#1F5FA8", "#2A74CC")]
HINTERGRUND = "#1B1F24"
TEXT = "#FFFFFF"
GRAU = "#9AA4AF"
FELD = "#2B3138"
INAKTIV = "#3A4048"
KARTE_INFO = "#2B3A4F"
ROT = "#7A1F1A"
GELB = "#7A5A00"
WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag",
              "Samstag", "Sonntag"]
MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
          "August", "September", "Oktober", "November", "Dezember"]

# Farben der Monatsübersicht (wie stempeluhr.py der Faktura)
UE_KARTE = "#2B3138"
UE_ZEILE = ("#252A31", "#2B3138")    # abwechselnd
UE_WOCHENENDE = "#1F2328"
UE_HEUTE = "#24466E"
UE_FEHLER = "#5A2622"
UE_KOPF = "#3A4250"
UE_GRUEN = "#3CC35A"
UE_ROT = "#FF6B5E"
UE_GELB = "#F2B33D"
UE_LILA = "#C9B6FF"
UE_PAUSE = "#F5C77A"
UE_KNOPF = "#6A4FB3"
URLAUB_KNOPF = "#1E7B6E"
AUFTRAG_KNOPF = "#8A5A12"
AV_KNOPF = "#9A3F6E"            # (1.9 / Faktura 10.3) Auftragsbearbeitung
KORREKTUR_KNOPF = "#2F6690"     # (1.8 / Faktura 9.7)
AMPEL_FARBEN = {"gruen": "#1E5A33", "gelb": "#7A5A00", "rot": "#7A1F1A"}

# Dateien (werden in App.build() auf den App-Datenordner gesetzt)
INI = CACHE = OFFLINE = LOG = ""


def C(hexwert):
    return get_color_from_hex(hexwert)


def pfade_setzen(ordner):
    global INI, CACHE, OFFLINE, LOG
    os.makedirs(ordner, exist_ok=True)
    INI = os.path.join(ordner, "stempeluhr.ini")
    CACHE = os.path.join(ordner, "stempeluhr_cache.json")
    OFFLINE = os.path.join(ordner, "stempeluhr_offline.json")
    LOG = os.path.join(ordner, "stempeluhr.log")


def log(text):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{jetzt():%Y-%m-%d %H:%M:%S} {text}\n")
        # Protokoll klein halten
        if os.path.getsize(LOG) > 2_000_000:
            os.replace(LOG, LOG + ".alt")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Uhrzeit: Auf manchen Android-Geräten kennt Python die Zeitzone des Tablets
# nicht und liefert UTC. Die Ortszeit wird deshalb bei Bedarf über Java
# ermittelt (Zeitzone und Sommerzeit wie in den Android-Einstellungen).
# ---------------------------------------------------------------------------
_KORREKTUR = datetime.timedelta(0)


def zeit_abgleichen():
    global _KORREKTUR
    if platform != "android":
        return
    try:
        from jnius import autoclass
        TimeZone = autoclass("java.util.TimeZone")
        System = autoclass("java.lang.System")
        tz = TimeZone.getDefault()
        if os.environ.get("TZ") != tz.getID():
            os.environ["TZ"] = tz.getID()
            time.tzset()
        ms = System.currentTimeMillis()
        lokal = datetime.datetime(1970, 1, 1) + datetime.timedelta(
            milliseconds=ms + tz.getOffset(ms))
        diff = lokal - datetime.datetime.now()
        _KORREKTUR = diff if abs(diff.total_seconds()) > 30 \
            else datetime.timedelta(0)
    except Exception as exc:          # pragma: no cover
        _KORREKTUR = datetime.timedelta(0)
        log(f"Zeitzone nicht ermittelbar: {exc}")


def jetzt():
    return (datetime.datetime.now() + _KORREKTUR).replace(microsecond=0) \
        if _KORREKTUR else datetime.datetime.now()


# ---------------------------------------------------------------------------
# Einstellungen / Datenbank
# ---------------------------------------------------------------------------
def ini_lesen():
    cfg = configparser.ConfigParser()
    cfg.read(INI, encoding="utf-8")
    d = cfg["Datenbank"] if cfg.has_section("Datenbank") else {}
    t = cfg["Terminal"] if cfg.has_section("Terminal") else {}
    return {"host": d.get("host", ""), "port": d.get("port", "3306"),
            "benutzer": d.get("benutzer", "stempeluhr"),
            "passwort": d.get("passwort", ""),
            "datenbank": d.get("datenbank", "Firma"),
            "ersatz_host": d.get("ersatz_host", ""),
            "ersatz_port": d.get("ersatz_port", ""),
            "name": t.get("name", "Tablet"),
            "vollbild": t.get("vollbild", "1"),
            "vorhanden": cfg.has_section("Datenbank")}


def ini_schreiben(w):
    cfg = configparser.ConfigParser()
    cfg["Datenbank"] = {k: str(w.get(k, "")) for k in (
        "host", "port", "benutzer", "passwort", "datenbank")}
    if (w.get("ersatz_host") or "").strip():
        cfg["Datenbank"]["ersatz_host"] = w["ersatz_host"].strip()
        cfg["Datenbank"]["ersatz_port"] = str(w.get("ersatz_port") or
                                              w.get("port") or "3306")
    cfg["Terminal"] = {"name": w.get("name", ""),
                       "vollbild": w.get("vollbild", "1")}
    with open(INI, "w", encoding="utf-8") as f:
        cfg.write(f)


def verbinden(w):
    from db import Database
    # (1.3) optional Ersatzserver mit Live-Kopie (Faktura 8.7)
    return Database(w["host"], w["port"] or 3306, w["benutzer"],
                    w["passwort"], w["datenbank"],
                    ersatz_host=w.get("ersatz_host") or "",
                    ersatz_port=w.get("ersatz_port") or None
                    ).connect(create=False)


# ---------------------------------------------------------------------------
# Bausteine
# ---------------------------------------------------------------------------
class Flaeche(BoxLayout):
    """BoxLayout mit einfarbigem Hintergrund."""
    farbe = ListProperty(C(HINTERGRUND))

    def __init__(self, **kw):
        super().__init__(**kw)
        with self.canvas.before:
            self._c = Color(*self.farbe)
            self._r = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._neu, size=self._neu, farbe=self._farbe)

    def _neu(self, *a):
        self._r.pos, self._r.size = self.pos, self.size

    def _farbe(self, *a):
        self._c.rgba = self.farbe


class Text(Label):
    """Label mit Zeilenumbruch auf die eigene Breite."""

    def __init__(self, **kw):
        kw.setdefault("halign", "center")
        kw.setdefault("valign", "middle")
        super().__init__(**kw)
        self.bind(size=lambda *a: setattr(self, "text_size",
                                          (self.width, None)))


class Taste(Button):
    """Große farbige Taste; 'markiert' zeichnet einen weißen Rahmen
    (entspricht der hervorgehobenen Taste im Tk-Terminal)."""
    markiert = BooleanProperty(False)

    def __init__(self, **kw):
        super().__init__(background_normal="", background_down="",
                         bold=True, color=C(TEXT), **kw)
        with self.canvas.after:
            self._rc = Color(1, 1, 1, 0)
            self._rl = Line(rectangle=(0, 0, 0, 0), width=5)
        self.bind(pos=self._rahmen, size=self._rahmen,
                  markiert=self._rahmen)

    def _rahmen(self, *a):
        self._rc.a = 1 if self.markiert else 0
        self._rl.rectangle = (self.x + 3, self.y + 3, self.width - 6,
                              self.height - 6)


def knopf(text, befehl, farbe="#3A4048", hoehe=64, schrift=24):
    b = Button(text=text, size_hint_y=None, height=hoehe, font_size=schrift,
               background_normal="", background_color=C(farbe))
    b.bind(on_release=lambda *a: befehl())
    return b


# ---------------------------------------------------------------------------
# Stempel-Terminal
# ---------------------------------------------------------------------------
class Stempeluhr(Flaeche):
    def __init__(self, app, cfg, db, **kw):
        super().__init__(orientation="vertical", padding=(20, 12, 20, 10),
                         spacing=4, **kw)
        self.app = app
        self.cfg = cfg
        self.db = db
        self.online = db is not None
        self.settings = {}
        self.mitarbeiter = {}        # rfid -> dict
        self.aktion = None
        self.aktion_bis = None
        self.karte_ma = None
        self.karte_bis = None
        self.meldung_bis = None
        self.letzte = {}             # (ma_id, art) -> Zeitpunkt
        self.puffer = ""             # Eingabe des RFID-Lesers
        self._puffer_job = None
        self._verbinde = False
        self._geladen = None
        self.popup = None
        self._popup_seit = 0.0
        self._lang_ev = None         # langes Drücken auf die Kopfzeile
        self.uebersicht = None       # offene Monatsübersicht
        self._knopf_ma = None
        self._knopf_ende = 0
        self._knopf_ev = None
        # Knöpfe über der Uhr nach Karte/Stempeln
        self.angebot = Flaeche(size_hint=(None, None), spacing=14)
        self.angebot_rest = Label(text="", color=C(GRAU), size_hint=(None, 1),
                                  width=40)

        def angebot_knopf(text, farbe, befehl):
            b = UebersichtKnopf(text=text, bold=True, color=C(TEXT),
                                background_normal="", background_down="",
                                background_color=C(farbe))
            b.bind(on_release=lambda *a: befehl())
            b.basis_text = text
            return b
        self.knopf_uebersicht = angebot_knopf(
            "Monatsübersicht", UE_KNOPF, self._uebersicht_oeffnen)
        self.knopf_urlaub = angebot_knopf(
            "Urlaub beantragen", URLAUB_KNOPF, self._urlaub_oeffnen)
        self.knopf_auftrag = angebot_knopf(
            "Auftrag", AUFTRAG_KNOPF, self._auftrag_oeffnen)
        self.knopf_av = angebot_knopf(
            "Auftragsbearbeitung", AV_KNOPF, self._av_oeffnen)
        self.knopf_korrektur = angebot_knopf(
            "Korrektur", KORREKTUR_KNOPF, self._korrektur_oeffnen)

        kopf = BoxLayout(size_hint_y=None, height=40)
        self.kopf = kopf
        self.firma = Text(text="", color=C(GRAU), halign="left")
        self.verbindung = Text(text="", halign="right")
        # (1.10.0) Revisionsnummer klein oben in der Mitte (wie Faktura,
        # Stempeluhr und Auftragsterminal); Firma und Verbindung bekommen
        # je die Hälfte des Rests -> die Nummer steht genau mittig
        self.rev = Label(text=f"Rev. {FAKTURA_REVISION} · App {APP_VERSION}",
                         color=C(GRAU), size_hint_x=None, width=200)
        self.rev.bind(texture_size=lambda w, ts: setattr(w, "width",
                                                         ts[0] + 24))
        kopf.add_widget(self.firma)
        kopf.add_widget(self.rev)
        kopf.add_widget(self.verbindung)
        self.add_widget(kopf)

        self.uhr = Label(text="", color=C(TEXT), bold=True,
                         size_hint_y=None)
        self.datum = Label(text="", color=C(GRAU), size_hint_y=None)
        self.add_widget(self.uhr)
        self.add_widget(self.datum)

        # Meldungsfeld: Höhe richtet sich nach dem Text (wie im Tk-
        # Terminal), die Tasten bekommen den restlichen Platz
        self.meldung_rahmen = Flaeche(orientation="vertical",
                                      size_hint_y=None, padding=(10, 8),
                                      spacing=4)
        self.meldung = Text(text="", color=C(TEXT), bold=True,
                            size_hint_y=None)
        self.unterzeile = Text(text="", color=C(GRAU), size_hint_y=None)
        for lbl in (self.meldung, self.unterzeile):
            lbl.bind(texture_size=self._meldung_hoehe)
        self.meldung_rahmen.add_widget(self.meldung)
        self.meldung_rahmen.add_widget(self.unterzeile)
        self.add_widget(Widget(size_hint_y=None, height=6))
        self.add_widget(self.meldung_rahmen)

        self.tasten = GridLayout(cols=2, spacing=16, padding=(0, 10))
        self.knoepfe = {}
        for art, text, farbe, hell in TASTEN:
            b = Taste(text=text, background_color=C(farbe))
            b.bind(on_release=lambda w, a=art: self.taste(a))
            self.tasten.add_widget(b)
            self.knoepfe[art] = (b, farbe, hell)
        self.add_widget(self.tasten)

        fuss = BoxLayout(size_hint_y=None, height=40, spacing=8)
        self.karte_label = Label(text="Karte:", color=C(GRAU),
                                 size_hint_x=None, width=80, halign="left")
        self.kartenfeld = Button(text="", color=C(GRAU), size_hint_x=None,
                                 width=320, background_normal="",
                                 background_down="",
                                 background_color=C(FELD), halign="left")
        self.kartenfeld.bind(on_release=lambda *a: self.hand_eingabe())
        self.terminal_label = Text(text=cfg.get("name", ""), color=C(GRAU),
                                   halign="right")
        fuss.add_widget(self.karte_label)
        fuss.add_widget(self.kartenfeld)
        fuss.add_widget(self.terminal_label)
        self.add_widget(fuss)

        Window.bind(size=lambda *a: self.schriften())
        self.schriften()
        self._einstellungen_laden()
        self.ruhe()
        self._takt()
        self._ev_takt = Clock.schedule_interval(lambda dt: self._takt(),
                                                0.25)
        self._ev_hg = Clock.schedule_interval(lambda dt: self._hintergrund(),
                                              30)
        Clock.schedule_once(lambda dt: self._hintergrund(), 2)

    def _meldung_hoehe(self, *a):
        for lbl in (self.meldung, self.unterzeile):
            lbl.height = lbl.texture_size[1] if lbl.text else 0
        self.meldung_rahmen.height = self.meldung.height + \
            self.unterzeile.height + 20

    def beenden_timer(self):
        self._ev_takt.cancel()
        self._ev_hg.cancel()
        self._knopf_verbergen()
        self._uebersicht_schliessen(ruhe=False)

    # ------------------------------------------------------------------
    def schriften(self):
        """Schriftgrößen relativ zur Bildschirmhöhe (wie im Tk-Terminal)."""
        h = max(480, Window.height)
        pt = 1.33           # Tk-Punkt -> Pixel

        def f(faktor, minimum=10):
            return max(minimum, int(h * faktor * pt))
        self.firma.font_size = f(0.035)
        self.verbindung.font_size = f(0.03)
        self.uhr.font_size = f(0.14)
        self.uhr.height = f(0.14) * 1.08
        self.datum.font_size = f(0.04)
        self.datum.height = f(0.04) * 1.35
        self.meldung.font_size = f(0.055)
        for b in (self.knopf_uebersicht, self.knopf_urlaub,
                  self.knopf_auftrag):
            b.font_size = f(0.05)
        self.angebot_rest.font_size = f(0.035)
        self.unterzeile.font_size = f(0.04)
        self._meldung_hoehe()
        for b, _, _ in self.knoepfe.values():
            b.font_size = f(0.065)
        klein = f(0.025, 9)
        for w in (self.karte_label, self.kartenfeld, self.terminal_label,
                  self.rev):
            w.font_size = klein
        self.karte_label.width = klein * 4
        self.kartenfeld.width = klein * 14
        self.children[-1].height = f(0.035) * 1.6    # Kopfzeile
        self.children[0].height = klein * 2.2        # Fußzeile

    # ------------------------------------------------------------------
    # Datenbank / Offline
    # ------------------------------------------------------------------
    def _einstellungen_laden(self):
        if self.online:
            try:
                self.settings = self.db.settings(reload=True)
                rows = self.db.query("SELECT * FROM mitarbeiter WHERE "
                                     "aktiv=1 AND rfid IS NOT NULL")
                self.mitarbeiter = {r["rfid"]: r for r in rows}
                cache = {"settings": self.settings, "mitarbeiter": [
                    {k: (v.isoformat() if isinstance(
                        v, (datetime.date, datetime.datetime)) else
                        (str(v) if v is not None and not isinstance(
                            v, (int, str)) else v))
                     for k, v in r.items()} for r in rows]}
                with open(CACHE, "w", encoding="utf-8") as f:
                    json.dump(cache, f, ensure_ascii=False)
                self._geladen = jetzt()
            except Exception as exc:
                self._offline(exc)
        if not self.online and os.path.exists(CACHE):
            try:
                with open(CACHE, encoding="utf-8") as f:
                    cache = json.load(f)
                self.settings = cache.get("settings", {})
                self.mitarbeiter = {r["rfid"]: r for r in
                                    cache.get("mitarbeiter", [])}
            except (OSError, ValueError):
                pass
        self.firma.text = self.settings.get("firma_name", "")
        self._verbindung_anzeigen()

    def _offline(self, exc=None):
        if self.online:
            log(f"Verbindung verloren: {exc}")
        self.online = False
        self._verbindung_anzeigen()

    def _verbindung_anzeigen(self):
        offen = self._offline_liste()
        text = "• online" if self.online else "• OFFLINE"
        if offen:
            text += f"  ({len(offen)} Buchung(en) warten)"
        self.verbindung.text = text
        self.verbindung.color = C("#3CC35A" if self.online else "#FF6B5E")

    @staticmethod
    def _offline_liste():
        try:
            with open(OFFLINE, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return []

    @staticmethod
    def _offline_speichern(liste):
        tmp = OFFLINE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(liste, f, ensure_ascii=False, indent=1)
        os.replace(tmp, OFFLINE)

    def _hintergrund(self):
        """Alle 30 s: Verbindung prüfen/wiederherstellen (im Hintergrund,
        damit die Tasten bedienbar bleiben), Offline-Buchungen
        nachtragen, alle 5 min Mitarbeiter neu laden."""
        zeit_abgleichen()
        try:
            if not self.online:
                if not self._verbinde:
                    self._verbinde = True
                    threading.Thread(target=self._verbinden_thread,
                                     daemon=True).start()
                return
            try:
                self.db.conn.ping(reconnect=True)
            except Exception as exc:
                self._offline(exc)
                return
            self._nachtragen()
            self._warnungen_loggen()
            if not self._geladen or \
                    (jetzt() - self._geladen).total_seconds() > 300:
                self._einstellungen_laden()
        except Exception as exc:
            self._offline(exc)
        self._verbindung_anzeigen()

    def _warnungen_loggen(self):
        """Fehlende Tabellen/Rechte einmal ins Protokoll schreiben."""
        gemeldet = getattr(self, "_gemeldet", set())
        for w in zeit.WARNUNGEN:
            if w not in gemeldet:
                log(f"Hinweis Datenbank: {w} – bitte stempeluhr_einrichten"
                    f".sql der Faktura erneut ausführen.")
                gemeldet.add(w)
        self._gemeldet = gemeldet

    def _verbinden_thread(self):
        try:
            db = verbinden(self.cfg)
        except Exception:
            db = None
        Clock.schedule_once(lambda dt: self._verbunden(db))

    def _verbunden(self, db):
        self._verbinde = False
        if db is None:
            self._verbindung_anzeigen()
            return
        self.db = db
        self.online = True
        log("Verbindung wiederhergestellt")
        self._einstellungen_laden()
        try:
            self._nachtragen()
        except Exception as exc:
            self._offline(exc)
        self._verbindung_anzeigen()

    def _nachtragen(self):
        liste = self._offline_liste()
        if not liste:
            return
        rest = []
        for b in liste:
            try:
                zeit.stempeln(self.db, b["ma_id"], b["art"],
                              datetime.datetime.fromisoformat(b["zeitpunkt"]),
                              quelle="terminal-offline",
                              terminal=b.get("terminal", ""),
                              pruefung=False)
                log(f"nachgetragen: {b}")
            except Exception as exc:
                log(f"Nachtragen fehlgeschlagen ({exc}): {b}")
                rest.append(b)
                if pymysql and isinstance(exc,
                                          pymysql.err.OperationalError):
                    self._offline(exc)
                    rest += liste[liste.index(b) + 1:]
                    break
        self._offline_speichern(rest)

    # ------------------------------------------------------------------
    # Anzeige
    # ------------------------------------------------------------------
    def _takt(self):
        j = jetzt()
        self.uhr.text = j.strftime("%H:%M:%S")
        self.datum.text = f"{WOCHENTAGE[j.weekday()]}, {j:%d.%m.%Y}"
        if self.aktion and j >= self.aktion_bis:
            self.ruhe()
        elif self.aktion:
            rest = int((self.aktion_bis - j).total_seconds()) + 1
            self.unterzeile.text = f"noch {rest} Sekunden"
        if self.karte_ma and j >= self.karte_bis:
            self.ruhe()
        if self.meldung_bis and j >= self.meldung_bis:
            self.ruhe()

    def _tasten_farbe(self, aktiv=None):
        for art, (b, farbe, hell) in self.knoepfe.items():
            if aktiv is None:
                b.background_color = C(farbe)
                b.markiert = False
            elif art == aktiv:
                b.background_color = C(hell)
                b.markiert = True
            else:
                b.background_color = C(INAKTIV)
                b.markiert = False

    def _rahmen(self, farbe, text, unter, unter_farbe=TEXT):
        self.meldung_rahmen.farbe = C(farbe)
        self.meldung.text = text
        self.unterzeile.text = unter
        self.unterzeile.color = C(unter_farbe)

    def ruhe(self):
        self.aktion = self.karte_ma = None
        self.aktion_bis = self.karte_bis = self.meldung_bis = None
        self._tasten_farbe()
        self._rahmen(HINTERGRUND, "Bitte Taste wählen und Karte vorhalten",
                     "", GRAU)

    def anzeigen(self, text, unter="", farbe=HINTERGRUND, sek=None):
        sek = sek or int(self.settings.get("terminal_anzeige_sek") or 6)
        self._rahmen(farbe, text, unter)
        self.meldung_bis = jetzt() + datetime.timedelta(seconds=sek)

    # ------------------------------------------------------------------
    # Bedienung
    # ------------------------------------------------------------------
    def _wartezeit(self):
        return datetime.timedelta(seconds=int(
            self.settings.get("terminal_karte_sek") or 15))

    def taste(self, art):
        if self.popup:
            return
        self._uebersicht_schliessen(ruhe=False)
        if self.karte_ma:
            ma = self.karte_ma
            self.karte_ma = None
            self.buchen(ma, art)
            return
        self._knopf_verbergen()
        self.meldung_bis = None
        self.aktion = art
        self.aktion_bis = jetzt() + self._wartezeit()
        self._tasten_farbe(art)
        text = dict((a, t) for a, t, _, _ in TASTEN)[art]
        self._rahmen(HINTERGRUND, f"{text}: Bitte Karte an den Leser halten",
                     "")

    # --- Eingabe des RFID-Lesers (Tastatur-Emulation) --------------------
    def zeichen(self, z):
        self.puffer += z
        self.kartenfeld.text = "  " + self.puffer
        # Manche Leser senden kein Enter: Eingabe übernehmen, sobald sie
        # 0,5 s unverändert ist
        if self._puffer_job:
            self._puffer_job.cancel()
        self._puffer_job = Clock.schedule_once(
            lambda dt: self._puffer_pruefen(), 0.5)

    def zurueck(self):
        self.puffer = self.puffer[:-1]
        self.kartenfeld.text = "  " + self.puffer

    def _puffer_pruefen(self):
        self._puffer_job = None
        if len(self.puffer.strip()) >= 4:
            self.karte_eingabe()

    def karte_eingabe(self):
        if self._puffer_job:
            self._puffer_job.cancel()
            self._puffer_job = None
        roh = self.puffer
        self.puffer = ""
        self.kartenfeld.text = ""
        if roh.strip():
            self.karte(roh)

    def hand_eingabe(self):
        """Kartennummer von Hand eingeben (z.B. ohne Leser)."""
        feld = TextInput(multiline=False, font_size=32, size_hint_y=None,
                         height=64, input_filter=None)
        inhalt = BoxLayout(orientation="vertical", spacing=12, padding=12)
        inhalt.add_widget(Label(text="Kartennummer:", font_size=24))
        inhalt.add_widget(feld)
        zeile = BoxLayout(spacing=12, size_hint_y=None, height=64)
        inhalt.add_widget(zeile)

        def ok(*a):
            nr = feld.text
            self.popup_schliessen()
            if nr.strip():
                self.karte(nr)
        feld.bind(on_text_validate=ok)
        zeile.add_widget(knopf("Abbrechen", self.popup_schliessen))
        zeile.add_widget(knopf("OK", ok, "#1F5FA8"))
        self.popup_zeigen("Karte eingeben", inhalt, (560, 300))
        Clock.schedule_once(lambda dt: setattr(feld, "focus", True), 0.2)

    def _ma_suchen(self, rfid):
        norm = zeit.rfid_normalisieren(rfid)
        if self.online:
            try:
                ma = zeit.mitarbeiter_zu_rfid(self.db, rfid)
                if ma:
                    self.mitarbeiter[ma["rfid"]] = ma
                return ma
            except Exception as exc:
                self._offline(exc)
        return self.mitarbeiter.get(norm)

    def karte(self, rfid):
        self._uebersicht_schliessen(ruhe=False)
        self._knopf_verbergen()
        ma = self._ma_suchen(rfid)
        if not ma:
            log(f"unbekannte Karte {rfid.strip()}")
            self.aktion = None
            self._tasten_farbe()
            self.anzeigen("Karte unbekannt", f"Kartennummer: "
                          f"{zeit.rfid_normalisieren(rfid)}\nBitte im "
                          f"Mitarbeiterstamm hinterlegen.", ROT)
            return
        if self.aktion:
            art = self.aktion
            self.aktion = None
            self.buchen(ma, art)
            return
        # Karte zuerst: Info anzeigen und auf Taste warten
        self.karte_ma = ma
        self.karte_bis = jetzt() + self._wartezeit()
        self.meldung_bis = None
        self._tasten_farbe()
        unter = "Bitte jetzt die gewünschte Taste drücken."
        if self.online:
            try:
                st = zeit.stand(self.db, self.settings, ma, jetzt())
                status = {"anwesend": "anwesend", "pause": "in der Pause"}.get(
                    st["status"], "nicht eingestempelt")
                unter = self._stand_text(st) + f"\nStatus: {status}\n" + unter
            except Exception as exc:
                self._offline(exc)
        self._rahmen(KARTE_INFO, zeit.ma_name(ma), unter)
        self._nachrichten_oder_angebot(ma)

    @staticmethod
    def _stand_text(st):
        ampel = st.get("ampel")
        return (f"Heute {zeit.fmt_std(st['heute_ist'])} Std   |   Monat "
                f"{zeit.fmt_std(st['monat_ist'])} Std   |   Saldo "
                f"{zeit.fmt_std(st['gesamt_saldo'], True)} Std"
                + (f" (Ampel {zeit.AMPEL[ampel]})" if ampel in ("gelb", "rot")
                   else ""))

    def buchen(self, ma, art):
        self._tasten_farbe()
        j = jetzt().replace(microsecond=0)
        name = zeit.ma_name(ma)
        schluessel = (ma["id"], art)
        vorher = self.letzte.get(schluessel)
        if vorher and (j - vorher).total_seconds() < 60:
            self.anzeigen(name, f"{zeit.ARTEN[art]} wurde bereits um "
                          f"{vorher:%H:%M} gebucht.", GELB)
            self._uebersicht_anbieten(ma)
            return
        if self.online:
            try:
                zeit.stempeln(self.db, ma["id"], art, j,
                              terminal=self.cfg.get("name", ""))
            except ValueError as exc:
                self.anzeigen(name, str(exc), ROT)
                self._uebersicht_anbieten(ma)
                return
            except Exception as exc:
                self._offline(exc)
        if not self.online:
            liste = self._offline_liste()
            liste.append({"ma_id": ma["id"], "art": art,
                          "zeitpunkt": j.isoformat(),
                          "terminal": self.cfg.get("name", ""),
                          "rfid": ma.get("rfid")})
            self._offline_speichern(liste)
            log(f"offline gespeichert: {name} {art} {j}")
        self.letzte[schluessel] = j
        log(f"{name}: {art} {j:%H:%M:%S}")
        gruss = {"kommt": self._gruss(j), "geht": "Schönen Feierabend",
                 "pause_an": "Gute Pause", "pause_ende": "Willkommen zurück"}
        unter = f"{zeit.ARTEN[art]} um {j:%H:%M} Uhr gebucht"
        if self.online:
            try:
                st = zeit.stand(self.db, self.settings, ma, jetzt())
                unter += "\n" + self._stand_text(st)
            except Exception as exc:
                self._offline(exc)
        if not self.online:
            unter += "\n(offline gespeichert – Stundenstand später " \
                     "verfügbar)"
        farbe = dict((a, f) for a, _, f, _ in TASTEN)[art]
        self.anzeigen(f"{gruss[art]}, {name}", unter, farbe)
        self._verbindung_anzeigen()
        self._nachrichten_oder_angebot(ma, f"{zeit.ARTEN[art]} um "
                                           f"{j:%H:%M} Uhr gebucht")

    # ------------------------------------------------------------------
    # Monatsübersicht
    # ------------------------------------------------------------------
    def _sek(self, schluessel, standard):
        try:
            return max(1, int(self.settings.get(schluessel) or standard))
        except (TypeError, ValueError):
            return standard

    def _an(self, schluessel):
        return str(self.settings.get(schluessel, "1")) != "0"

    def _nachrichten_oder_angebot(self, ma, gebucht=""):
        """Offene Nachrichten aus dem Büro zeigen, danach die Knöpfe."""
        if self.online and self._an("terminal_nachrichten") and \
                self.popup is None:
            try:
                offen = zeit.nachrichten_offen(self.db, ma["id"], jetzt().date())
            except Exception as exc:
                log(f"Nachrichten nicht lesbar: {exc}")
                offen = []
            if offen:
                self._uebersicht_schliessen(ruhe=False)
                self.uebersicht = NachrichtenAnzeige(
                    self, ma, offen, gebucht,
                    self._sek("terminal_uebersicht_sek", 60))
                self.uebersicht.open()
                return
        self._einspringen_oder_angebot(ma)

    def _einspringen_oder_angebot(self, ma):
        """(Faktura 9.7) Offene Anfragen zum Einspringen zeigen, danach
        die Knöpfe."""
        if self.online and self._an("terminal_einspringen") and \
                self.popup is None:
            try:
                offen = zeit.einspring_offen(self.db, ma["id"],
                                             jetzt().date())
            except Exception as exc:
                log(f"Einspring-Anfragen nicht lesbar: {exc}")
                offen = []
            if offen:
                self._uebersicht_schliessen(ruhe=False)
                self.uebersicht = EinspringFrage(
                    self, ma, offen, self._sek("terminal_uebersicht_sek", 60))
                self.uebersicht.open()
                return
        self._uebersicht_anbieten(ma)

    def _angebote(self, ma):
        knoepfe = []
        if self._an("terminal_uebersicht"):
            knoepfe.append(self.knopf_uebersicht)
        if self._an("terminal_urlaubsantrag"):
            knoepfe.append(self.knopf_urlaub)
        if self._an("terminal_auftraege") and \
                str(self.settings.get("modul_verkauf", "1")) != "0":
            try:
                if zeit.aktueller_status(self.db, ma["id"], jetzt()) == \
                        "anwesend" and zeit.offene_auftraege(self.db):
                    knoepfe.append(self.knopf_auftrag)
            except Exception as exc:
                log(f"Aufträge nicht lesbar: {exc}")
        if self._an("terminal_auftragsverarbeitung") and \
                str(self.settings.get("modul_auftrag", "0")) != "0":
            try:
                if av_tablet.av_sichtbar_fuer(self.db, ma["id"]):
                    knoepfe.append(self.knopf_av)
            except Exception as exc:
                log(f"Auftragsverarbeitung nicht lesbar: {exc}")
        if self._an("terminal_korrektur"):
            knoepfe.append(self.knopf_korrektur)
        return knoepfe

    def _uebersicht_anbieten(self, ma):
        """Zeigt einige Sekunden die Knöpfe Monatsübersicht / Urlaub
        beantragen / Auftrag über der Uhr (nur online, weil die Daten aus
        der Datenbank kommen)."""
        self._knopf_verbergen()
        if not self.online:
            return
        knoepfe = self._angebote(ma)
        if not knoepfe:
            return
        for b in knoepfe:
            self.angebot.add_widget(b)
        self.angebot.add_widget(self.angebot_rest)
        self._knopf_ma = ma
        self._knopf_ende = time.monotonic() + self._sek(
            "terminal_uebersicht_knopf_sek", 5)
        if self.angebot.parent is None:
            Window.add_widget(self.angebot)
        self.uhr.bind(pos=self._knopf_lage, size=self._knopf_lage)
        self._knopf_lage()
        self._knopf_takt()
        self._knopf_ev = Clock.schedule_interval(
            lambda dt: self._knopf_takt(), 0.25)

    def _knopf_lage(self, *a):
        """Knöpfe in die Breite einpassen und über die Uhr legen."""
        knoepfe = [b for b in self.angebot.children
                   if isinstance(b, UebersichtKnopf)]
        if not knoepfe:
            return
        h = max(480, Window.height)
        platz = self.width - 30
        for faktor in (0.05, 0.045, 0.04, 0.035, 0.03, 0.025):
            groesse = max(10, int(h * faktor * 1.33))
            breiten = []
            for b in knoepfe:
                b.font_size = groesse
                b.texture_update()
                breiten.append(b.texture_size[0] + groesse * 1.6)
            gesamt = sum(breiten) + self.angebot.spacing * len(knoepfe) + \
                self.angebot_rest.width
            if gesamt <= platz:
                break
        hoehe = max(self.uhr.height * 0.92, groesse * 2.2)
        for b, w in zip(knoepfe, breiten):
            b.size_hint = (None, None)
            b.size = (w, hoehe)
        self.angebot.size = (gesamt, hoehe)
        self.angebot.center = self.uhr.center

    def _knopf_takt(self):
        if not self._knopf_ma:
            return
        rest = int(self._knopf_ende - time.monotonic() + 0.999)
        if rest <= 0:
            self._knopf_verbergen()
            return
        self.angebot_rest.text = str(rest)

    def _knopf_verbergen(self):
        if self._knopf_ev is not None:
            self._knopf_ev.cancel()
            self._knopf_ev = None
        self._knopf_ma = None
        self.uhr.unbind(pos=self._knopf_lage, size=self._knopf_lage)
        self.angebot.clear_widgets()
        if self.angebot.parent is not None:
            self.angebot.parent.remove_widget(self.angebot)

    def _db_fehler(self, ma, exc, was):
        log(f"{was} fehlgeschlagen: {exc}")
        if pymysql and isinstance(exc, pymysql.err.OperationalError):
            self._offline(exc)
        self.anzeigen(zeit.ma_name(ma), f"{was} ist gerade nicht "
                      f"verfügbar.", ROT)

    def _fenster_oeffnen(self, klasse, was):
        ma = self._knopf_ma
        self._knopf_verbergen()
        if not ma or self.popup is not None:
            return
        self.ruhe()
        try:
            self.uebersicht = klasse(self, ma,
                                     self._sek("terminal_uebersicht_sek", 60))
        except Exception as exc:
            self.uebersicht = None
            self._db_fehler(ma, exc, was)
            return
        self.uebersicht.open()

    def _urlaub_oeffnen(self):
        self._fenster_oeffnen(UrlaubsAntrag, "Der Urlaubsantrag")

    def _auftrag_oeffnen(self):
        self._fenster_oeffnen(AuftragWahl, "Die Auftragsauswahl")

    def _av_oeffnen(self):
        self._fenster_oeffnen(AuftragsVerarbeitung, "Die Auftragsbearbeitung")

    def _korrektur_oeffnen(self):
        self._fenster_oeffnen(KorrekturAntrag, "Der Korrekturantrag")

    def _uebersicht_oeffnen(self):
        ma = self._knopf_ma
        self._knopf_verbergen()
        if not ma or self.popup is not None:
            return
        self.ruhe()                 # Warten auf eine Taste abbrechen
        try:
            daten = zeit.monatsuebersicht(self.db, self.settings, ma, jetzt())
        except Exception as exc:
            log(f"Monatsübersicht fehlgeschlagen: {exc}")
            if pymysql and isinstance(exc, pymysql.err.OperationalError):
                self._offline(exc)
            self.anzeigen(zeit.ma_name(ma), "Die Monatsübersicht ist gerade "
                          "nicht verfügbar.", ROT)
            return
        self.uebersicht = MonatsUebersicht(
            self, ma, daten, self._sek("terminal_uebersicht_sek", 60))
        self.uebersicht.open()

    def _uebersicht_schliessen(self, ruhe=True):
        if self.uebersicht is not None:
            u, self.uebersicht = self.uebersicht, None
            u.beenden()
            if ruhe:
                self.ruhe()

    @staticmethod
    def _gruss(t):
        if t.hour < 11:
            return "Guten Morgen"
        if t.hour < 17:
            return "Guten Tag"
        return "Guten Abend"

    # ------------------------------------------------------------------
    # Menü (Zurück-Taste / Esc)
    # ------------------------------------------------------------------
    # (1.7) Menü auch ohne Zurück-Geste: Kopfzeile oder Uhr 2 Sekunden
    # gedrückt halten
    def _im_kopf(self, touch):
        return (self.kopf.collide_point(*touch.pos) or
                self.uhr.collide_point(*touch.pos))

    def on_touch_down(self, touch):
        if self.popup is None and self.uebersicht is None and \
                self._im_kopf(touch):
            self._lang_abbrechen()
            self._lang_ev = Clock.schedule_once(
                lambda dt: self._lang_gedrueckt(), 2.0)
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if self._lang_ev is not None and not self._im_kopf(touch):
            self._lang_abbrechen()
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        self._lang_abbrechen()
        return super().on_touch_up(touch)

    def _lang_abbrechen(self):
        if self._lang_ev is not None:
            self._lang_ev.cancel()
            self._lang_ev = None

    def _lang_gedrueckt(self):
        self._lang_ev = None
        log("Menü über langes Drücken geöffnet")
        if self.popup is None and self.uebersicht is None:
            self.menue_anfordern()

    def popup_zeigen(self, titel, inhalt, groesse=(600, 400)):
        self.popup_schliessen()
        self._popup_seit = time.monotonic()
        self.popup = Popup(title=titel, content=inhalt, size_hint=(None, None),
                           size=groesse, auto_dismiss=False, title_size=24,
                           separator_color=C("#1F5FA8"))
        self.popup.open()

    def popup_schliessen(self, *a):
        if self.popup:
            self.popup.dismiss()
            self.popup = None

    def menue_anfordern(self):
        if self.uebersicht is not None:
            self._uebersicht_schliessen()
            return
        if self.popup:
            # doppelt gemeldete Zurück-Geste darf das Menü nicht sofort
            # wieder schließen
            if time.monotonic() - self._popup_seit < 0.8:
                return
            self.popup_schliessen()
            return
        pin = self.settings.get("terminal_pin") or ""
        if pin:
            self._pin_abfrage(pin)
        else:
            self._menue()

    def _pin_abfrage(self, pin):
        feld = TextInput(multiline=False, password=True, font_size=36,
                         input_filter="int", size_hint_y=None, height=70)
        meldung = Label(text="PIN:", font_size=24)
        inhalt = BoxLayout(orientation="vertical", spacing=12, padding=12)
        inhalt.add_widget(meldung)
        inhalt.add_widget(feld)
        zeile = BoxLayout(spacing=12, size_hint_y=None, height=64)

        def ok(*a):
            if feld.text == pin:
                self._menue()
            else:
                log("falsche PIN am Terminal")
                self.popup_schliessen()
        feld.bind(on_text_validate=ok)
        zeile.add_widget(knopf("Abbrechen", self.popup_schliessen))
        zeile.add_widget(knopf("OK", ok, "#1F5FA8"))
        inhalt.add_widget(zeile)
        self.popup_zeigen("Stempeluhr – PIN", inhalt, (480, 320))
        Clock.schedule_once(lambda dt: setattr(feld, "focus", True), 0.2)

    def _menue(self):
        inhalt = BoxLayout(orientation="vertical", spacing=12, padding=12)
        inhalt.add_widget(knopf("Verbindung einrichten ...",
                                self._einrichten, "#1F5FA8"))
        inhalt.add_widget(knopf("Stempeluhr beenden", self.app.beenden,
                                "#B3261E"))
        inhalt.add_widget(knopf("Abbrechen", self.popup_schliessen))
        self.popup_zeigen("Stempeluhr", inhalt, (520, 330))

    def _einrichten(self):
        self.popup_schliessen()
        self.app.einrichtung_zeigen(self.cfg, "", zurueck=True)


# ---------------------------------------------------------------------------
# Monatsübersicht
# ---------------------------------------------------------------------------
class UebersichtKnopf(Button):
    """Knopf 'Monatsübersicht' mit weißem Rahmen, schwebt über der Uhr."""

    def __init__(self, **kw):
        super().__init__(size_hint=(None, None), **kw)
        with self.canvas.after:
            Color(1, 1, 1, 1)
            self._rl = Line(rectangle=(0, 0, 0, 0), width=2)
        self.bind(pos=self._rahmen, size=self._rahmen)

    def _rahmen(self, *a):
        self._rl.rectangle = (self.x + 1, self.y + 1, self.width - 2,
                              self.height - 2)


class MonatsUebersicht(ModalView):
    """Vollbild-Übersicht: Kennzahlen des Monats und alle Tage mit
    Stempelzeiten. Schließt mit 'Schließen', spätestens nach 'sekunden'."""

    SPALTEN = [("Tag", 0.13, "left"), ("Stempelzeiten", 0.37, "left"),
               ("Pause", 0.11, "right"), ("Arbeit", 0.13, "right"),
               ("Soll", 0.12, "right"), ("Saldo", 0.14, "right")]

    def __init__(self, uhr, ma, daten, sekunden=60):
        super().__init__(auto_dismiss=False, size_hint=(1, 1),
                         background="", background_color=C(HINTERGRUND),
                         overlay_color=(0, 0, 0, 0))
        self.uhr = uhr
        self.ende = time.monotonic() + sekunden
        skala = min(max(480, Window.height), Window.width * 0.52)

        def f(faktor, minimum=12):
            return max(minimum, int(skala * faktor * 1.33))
        self.f = f

        wurzel = Flaeche(orientation="vertical", padding=(16, 10, 16, 12),
                         spacing=6)

        # --- Kopf: Name, Monat, Schließen ---
        kopf = BoxLayout(size_hint_y=None, height=f(0.05) + f(0.03) + 16,
                         spacing=12)
        links = BoxLayout(orientation="vertical")
        links.add_widget(Text(text=zeit.ma_name(ma), bold=True,
                              font_size=f(0.05), color=C(TEXT),
                              halign="left"))
        m = daten["monat"]
        links.add_widget(Text(
            text=f"Monatsübersicht {MONATE[m.month - 1]} {m.year}  ·  "
                 f"Stand {jetzt():%d.%m.%Y %H:%M} Uhr",
            font_size=f(0.03), color=C(GRAU), halign="left"))
        kopf.add_widget(links)
        self.knopf = Button(text="Schließen", bold=True, font_size=f(0.045),
                            size_hint_x=None, width=f(0.045) * 8,
                            background_normal="", background_down="",
                            background_color=C("#B3261E"), color=C(TEXT))
        self.knopf.bind(on_release=lambda *a: uhr._uebersicht_schliessen())
        kopf.add_widget(self.knopf)
        wurzel.add_widget(kopf)

        # --- Kacheln ---
        def farbe_saldo(minuten):
            return UE_GRUEN if minuten > 0 else (UE_ROT if minuten < 0
                                                 else TEXT)
        kacheln = GridLayout(cols=5, spacing=10, size_hint_y=None,
                             height=f(0.05) + f(0.028) * 2.6 + 14)
        for titel, wert, fg, bg in [
                ("Gearbeitet (Std)", zeit.fmt_std(daten["ist"]), TEXT,
                 "#1E5A33"),
                ("Pausen (Std)", zeit.fmt_std(daten["pause"]), TEXT,
                 "#6B4A0E"),
                ("Soll bis gestern", zeit.fmt_std(daten["soll_bis_gestern"]),
                 TEXT, UE_KARTE),
                ("Monatssaldo bis gestern",
                 zeit.fmt_std(daten["saldo_bis_gestern"], True),
                 farbe_saldo(daten["saldo_bis_gestern"]), UE_KARTE),
                ("Stundenkonto (Std)" + (
                    f" – Ampel {zeit.AMPEL[daten['ampel']]}"
                    if daten.get("ampel") else ""),
                 zeit.fmt_std(daten["gesamt_saldo"], True),
                 TEXT if daten.get("ampel") else
                 farbe_saldo(daten["gesamt_saldo"]),
                 AMPEL_FARBEN.get(daten.get("ampel"), "#24466E"))]:
            k = Flaeche(orientation="vertical", padding=(6, 6), farbe=C(bg))
            k.add_widget(Text(text=wert, bold=True, font_size=f(0.05),
                              color=C(fg)))
            k.add_widget(Text(text=titel, font_size=f(0.028),
                              color=C("#D5DBE1")))
            kacheln.add_widget(k)
        wurzel.add_widget(kacheln)

        # --- Hinweise ---
        wurzel.add_widget(Text(
            text=f"Heute bisher {zeit.fmt_std(daten['heute_ist'])} Std "
                 f"gearbeitet (Soll {zeit.fmt_std(daten['heute_soll'])})"
                 f"   ·   Stundenkonto: Stand gestern, inkl. Übertrag",
            font_size=f(0.027), color=C(GRAU), halign="left",
            size_hint_y=None, height=f(0.027) * 1.5))
        if daten["fehler"]:
            wurzel.add_widget(Text(
                text=f"Achtung: {daten['fehler']} Tag(e) mit unvollständigen "
                     f"Stempelungen – bitte im Büro melden.", bold=True,
                font_size=f(0.03), color=C(UE_GELB), halign="left",
                size_hint_y=None, height=f(0.03) * 1.5))
        # (Faktura 9.7) nächste Dienste laut Dienstplan
        if daten.get("plan_vorschau"):
            wurzel.add_widget(Text(
                text="Ihr Dienstplan:  " + "  ·  ".join(
                    daten["plan_vorschau"]),
                font_size=f(0.027), color=C(UE_LILA), halign="left",
                size_hint_y=None, height=f(0.027) * 2.8))

        # --- Tabelle ---
        wurzel.add_widget(self._zeile([s for s, _, _ in self.SPALTEN],
                                      UE_KOPF, [TEXT] * 6, fett=True))
        self.scroll = ScrollView(bar_width=12, bar_color=C("#6A7585"),
                                 bar_inactive_color=C("#4C5566"),
                                 scroll_type=["bars", "content"],
                                 do_scroll_x=False)
        liste = GridLayout(cols=1, spacing=1, size_hint_y=None)
        liste.bind(minimum_height=liste.setter("height"))
        for i, t in enumerate(daten["tage"]):
            liste.add_widget(self._tageszeile(t, i))
        self.scroll.add_widget(liste)
        wurzel.add_widget(self.scroll)
        self.add_widget(wurzel)

        self._ev = Clock.schedule_interval(lambda dt: self._takt(), 0.5)
        self._takt()
        # heute (unten) sichtbar
        Clock.schedule_once(lambda dt: setattr(self.scroll, "scroll_y", 0),
                            0.1)

    # -- Bausteine -----------------------------------------------------------
    def _zeile(self, texte, bg, farben, fett=False):
        z = Flaeche(orientation="horizontal", size_hint_y=None,
                    padding=(8, 6, 22, 6), spacing=8, farbe=C(bg))
        labels = []
        for (_, anteil, ausrichtung), text, fg in zip(self.SPALTEN, texte,
                                                      farben):
            lbl = Text(text=text, color=C(fg), bold=fett, halign=ausrichtung,
                       font_size=self.f(0.03), size_hint_x=anteil,
                       size_hint_y=None)
            labels.append(lbl)
            z.add_widget(lbl)

        def hoehe(*a):
            h = max(l.texture_size[1] for l in labels)
            for l in labels:
                l.height = h
            z.height = h + 12
        for l in labels:
            l.bind(texture_size=hoehe)
        hoehe()
        return z

    def _tageszeile(self, t, nr):
        if t["fehler"]:
            bg = UE_FEHLER
        elif t["heute"]:
            bg = UE_HEUTE
        elif t["wochenende"] or t["feiertag"]:
            bg = UE_WOCHENENDE
        else:
            bg = UE_ZEILE[nr % 2]
        text = t["stempel_text"]
        zusatz = [h for h in (t["hinweis"] or "").split("; ")
                  if h and h != "Schicht über Mitternacht"]
        if t["mindestpause"] and t["ist"]:
            zusatz.append("inkl. Mindestpause")
        if zusatz:
            text = (text + "\n" if text else "") + " · ".join(zusatz)
        if not text:
            text = "–"
        saldo = t["saldo"]
        leer = not t["stempel"] and not t["soll"]
        werte = [f"{t['wochentag']} {t['datum']:%d.%m.}", text,
                 zeit.fmt_std(t["pause"]) if t["pause"] else "",
                 zeit.fmt_std(t["ist"]) if t["ist"] or t["stempel"] else "",
                 zeit.fmt_std(t["soll"]) if t["soll"] else "",
                 "" if leer else zeit.fmt_std(saldo, True)]
        farben = [TEXT if not (t["wochenende"] or t["feiertag"]) else GRAU,
                  UE_LILA if not t["stempel"] and zusatz else TEXT,
                  UE_PAUSE, TEXT, GRAU,
                  UE_GRUEN if saldo > 0 else (UE_ROT if saldo < 0 else GRAU)]
        if t["heute"] and t["laeuft"]:
            werte[5] = "läuft"
            farben[5] = GRAU
        return self._zeile(werte, bg, farben)

    def _takt(self):
        rest = int(self.ende - time.monotonic() + 0.999)
        if rest <= 0:
            self.uhr._uebersicht_schliessen()
            return
        self.knopf.text = f"Schließen  ({rest})"

    def beenden(self):
        self._ev.cancel()
        self.dismiss(animation=False)


# ---------------------------------------------------------------------------
# Weitere Vollbild-Fenster (ab 1.2): Urlaubsantrag, Auftrag, Nachrichten
# ---------------------------------------------------------------------------
class _Vollbild(ModalView):
    """Kopf mit Name, Titel und 'Schließen (n)'; schließt nach 'sekunden'
    ohne Berührung (jede Berührung verlängert)."""

    def __init__(self, uhr, ma, titel, sekunden=60, knopf_text="Schließen"):
        super().__init__(auto_dismiss=False, size_hint=(1, 1),
                         background="", background_color=C(HINTERGRUND),
                         overlay_color=(0, 0, 0, 0))
        self.uhr, self.ma, self.sekunden = uhr, ma, sekunden
        self.db, self.settings = uhr.db, uhr.settings
        self.knopf_text = knopf_text
        skala = min(max(480, Window.height), Window.width * 0.52)

        def f(faktor, minimum=12):
            return max(minimum, int(skala * faktor * 1.33))
        self.f = f
        self.wurzel = Flaeche(orientation="vertical",
                              padding=(16, 10, 16, 12), spacing=8)
        kopf = BoxLayout(size_hint_y=None, height=f(0.05) + f(0.035) + 16,
                         spacing=12)
        links = BoxLayout(orientation="vertical")
        links.add_widget(Text(text=zeit.ma_name(ma), bold=True,
                              font_size=f(0.05), color=C(TEXT),
                              halign="left"))
        links.add_widget(Text(text=titel, font_size=f(0.032), color=C(GRAU),
                              halign="left"))
        kopf.add_widget(links)
        self.knopf = self.gross(knopf_text, self.schliessen, "#B3261E",
                                0.045)
        self.knopf.size_hint_x = None
        self.knopf.width = f(0.045) * 8
        kopf.add_widget(self.knopf)
        self.wurzel.add_widget(kopf)
        self.inhalt = BoxLayout(orientation="vertical", spacing=8)
        self.wurzel.add_widget(self.inhalt)
        self.add_widget(self.wurzel)
        self.aktiv()
        self._ev = Clock.schedule_interval(lambda dt: self._takt(), 0.5)
        self._takt()

    def gross(self, text, befehl, farbe, faktor=0.04, **kw):
        b = Button(text=text, bold=True, font_size=self.f(faktor),
                   background_normal="", background_down="",
                   background_color=C(farbe), color=C(TEXT), **kw)

        def lauf(*a):
            try:
                befehl()
            except Exception as exc:      # z.B. Datenbank weg
                self.uhr._uebersicht_schliessen(ruhe=False)
                self.uhr._db_fehler(self.ma, exc, "Diese Funktion")
        b.bind(on_release=lauf)
        return b

    def on_touch_down(self, touch):
        self.aktiv()
        return super().on_touch_down(touch)

    def aktiv(self):
        self.ende = time.monotonic() + self.sekunden

    def _takt(self):
        rest = int(self.ende - time.monotonic() + 0.999)
        if rest <= 0:
            self.uhr._uebersicht_schliessen()
            return
        self.knopf.text = f"{self.knopf_text}  ({rest})"

    def schliessen(self):
        self.uhr._uebersicht_schliessen()

    def beenden(self):
        self._ev.cancel()
        self.dismiss(animation=False)


class UrlaubsAntrag(_Vollbild):
    """Urlaub am Tablet beantragen (Genehmigung im Büro)."""

    def __init__(self, uhr, ma, sekunden=60):
        super().__init__(uhr, ma, "Urlaub beantragen – die Genehmigung "
                         "erfolgt im Büro", sekunden)
        f = self.f
        heute = jetzt().date()
        self.von = self._naechster_arbeitstag(heute + datetime.timedelta(
            days=1))
        self.bis = self.von
        self.halb = False
        i = self.inhalt
        self.konto = Text(text="", bold=True, font_size=f(0.034),
                          color=C(UE_GELB), halign="left", size_hint_y=None,
                          height=f(0.034) * 1.6)
        i.add_widget(self.konto)
        boxen = GridLayout(cols=2, spacing=12, size_hint_y=None,
                           height=f(0.03) + f(0.055) + f(0.04) * 1.9 + 40)
        self.anzeige = {}
        self.box_titel = {}
        for key, text in (("von", "Erster Urlaubstag"),
                          ("bis", "Letzter Urlaubstag")):
            box = Flaeche(orientation="vertical", padding=(8, 6), spacing=4,
                          farbe=C(UE_KARTE))
            t = Text(text=text, font_size=f(0.03), color=C("#D5DBE1"),
                     size_hint_y=None, height=f(0.03) * 1.3)
            box.add_widget(t)
            self.box_titel[key] = (t, text)
            lbl = Text(text="", bold=True, font_size=f(0.055), color=C(TEXT),
                       size_hint_y=None, height=f(0.055) * 1.3)
            box.add_widget(lbl)
            self.anzeige[key] = lbl
            zeile = BoxLayout(spacing=8, size_hint_y=None,
                              height=f(0.04) * 1.9)
            for tage, beschr in ((-7, "-7"), (-1, "-1"), (1, "+1"),
                                 (7, "+7")):
                zeile.add_widget(self.gross(
                    beschr, lambda k=key, t=tage: self._schieben(k, t),
                    UE_KOPF, 0.04))
            box.add_widget(zeile)
            boxen.add_widget(box)
        i.add_widget(boxen)
        # (1.4) Auswahl nach Kalenderwochen, Urlaub stornieren
        woche = Flaeche(spacing=8, padding=(8, 4), size_hint_y=None,
                        height=f(0.036) * 2.1, farbe=C(UE_KARTE))
        woche.add_widget(Text(text="Woche:", font_size=f(0.03),
                              color=C("#D5DBE1"), size_hint_x=0.1))
        woche.add_widget(self.gross("« KW", lambda: self._woche(-1),
                                    UE_KOPF, 0.036, size_hint_x=0.12))
        self.kw_anzeige = Text(text="", bold=True, font_size=f(0.04),
                               color=C(TEXT), size_hint_x=0.16)
        woche.add_widget(self.kw_anzeige)
        woche.add_widget(self.gross("KW »", lambda: self._woche(1),
                                    UE_KOPF, 0.036, size_hint_x=0.12))
        woche.add_widget(self.gross("+1 Woche", self._woche_dazu, UE_KOPF,
                                    0.036, size_hint_x=0.16))
        woche.add_widget(Widget(size_hint_x=0.06))
        woche.add_widget(self.gross("Urlaub stornieren", self._storno_oeffnen,
                                    "#8E3B2F", 0.036, size_hint_x=0.28))
        i.add_widget(woche)
        zeile = BoxLayout(spacing=16, size_hint_y=None, height=f(0.05) * 1.8)
        self.halb_knopf = self.gross("", self._halb_umschalten, UE_KOPF, 0.04,
                                     size_hint_x=0.28)
        zeile.add_widget(self.halb_knopf)
        self.ergebnis = Text(text="", bold=True, font_size=f(0.042),
                             color=C(TEXT), halign="left", size_hint_x=0.4)
        zeile.add_widget(self.ergebnis)
        self.senden_knopf = self.gross("Antrag senden", self._senden,
                                       URLAUB_KNOPF, 0.05, size_hint_x=0.32)
        zeile.add_widget(self.senden_knopf)
        i.add_widget(zeile)
        self.meldung = Text(text="", bold=True, font_size=f(0.034),
                            color=C(UE_GRUEN), halign="left",
                            size_hint_y=None, height=f(0.034) * 2.6)
        i.add_widget(self.meldung)
        self.liste = Text(text="", font_size=f(0.03), color=C(GRAU),
                          halign="left", valign="top")
        if Window.height >= 560:
            # auf kleinen Bildschirmen fehlt der Platz; die Anträge stehen
            # dann unter "Urlaub stornieren"
            i.add_widget(self.liste)
        else:
            i.add_widget(Widget())
        self._konto_zeigen()
        self._aktualisieren()

    def _naechster_arbeitstag(self, d):
        for _ in range(21):
            if zeit.arbeitstage_liste(self.db, self.settings, self.ma, d, d):
                return d
            d += datetime.timedelta(days=1)
        return d

    def _konto_zeigen(self):
        jahr = self.von.year
        k = zeit.urlaub_konto(self.db, self.settings, self.ma, jahr,
                              jetzt().date())
        text = (f"Resturlaub {jahr}: {zeit.fmt_tage(k['rest'])} von "
                f"{zeit.fmt_tage(k['gesamt'])} Tagen")
        if k["geplant"]:
            text += f"  (davon {zeit.fmt_tage(k['geplant'])} schon geplant)"
        antraege = zeit.antraege_von(self.db, self.ma["id"], 20)
        offen = sum((a["tage"] for a in antraege if a["status"] == "offen"
                     and zeit.antrag_typ(a) != "storno"), 0)
        if offen:
            text += f"  ·  offene Anträge: {zeit.fmt_tage(offen)} Tage"
        self.konto.text = text
        zeilen = [("Storno " if zeit.antrag_typ(a) == "storno" else "") +
                  f"{a['von']:%d.%m.}–{a['bis']:%d.%m.%Y}   "
                  f"{zeit.kw_bereich_text(a['von'], a['bis'])}   "
                  f"{zeit.fmt_tage(a['tage'])} Tag(e)   "
                  f"{zeit.ANTRAG_STATUS.get(a['status'], a['status'])}" +
                  (f" – {a['antwort']}" if a.get("antwort") else "")
                  for a in antraege[:4]]
        self.liste.text = ("Meine letzten Anträge:\n   " +
                           "\n   ".join(zeilen)) if zeilen else ""

    def _schieben(self, key, tage):
        heute = jetzt().date()
        d = max(getattr(self, key) + datetime.timedelta(days=tage), heute)
        if key == "von":
            jahr_vorher = self.von.year
            dauer = self.bis - self.von
            self.von = d
            if self.bis < self.von or tage in (-7, 7):
                self.bis = self.von + (dauer if self.bis >= self.von else
                                       datetime.timedelta(0))
            if jahr_vorher != self.von.year:
                self._konto_zeigen()
        else:
            self.bis = max(d, self.von)
        if self.von != self.bis:
            self.halb = False
        self.meldung.text = ""
        self._aktualisieren()

    def _halb_umschalten(self):
        if self.von != self.bis:
            self.bis = self.von
        self.halb = not self.halb
        self.meldung.text = ""
        self._aktualisieren()

    def _aktualisieren(self):
        for key in ("von", "bis"):
            d = getattr(self, key)
            self.anzeige[key].text = \
                f"{zeit.WOCHENTAGE[d.weekday()]} {d:%d.%m.%Y}"
            t, text = self.box_titel[key]
            t.text = f"{text}  ·  {zeit.kw_text(d)}"
        self.kw_anzeige.text = zeit.kw_bereich_text(self.von, self.bis)
        self.halb_knopf.text = ("[X] " if self.halb else "[  ] ") + \
            "halber Tag"
        tage = zeit.arbeitstage_liste(self.db, self.settings, self.ma,
                                      self.von, self.bis)
        n = "0,5" if self.halb and tage else str(len(tage))
        sperren = zeit.sperren_im_zeitraum(self.db, self.ma["id"],
                                           self.von, self.bis)
        if sperren and tage:
            # (1.4) Urlaubssperre: kein Antrag möglich
            self.ergebnis.text = "Urlaubssperre!"
            self.ergebnis.color = C(UE_ROT)
            self.meldung.text = (zeit.sperre_text(sperren[0]) +
                                 " Bitte einen anderen Zeitraum wählen.")
            self.meldung.color = C(UE_ROT)
            self.senden_knopf.disabled = True
            return
        belegt = self.db.query(
            "SELECT datum FROM abwesenheiten WHERE mitarbeiter_id=%s AND "
            "datum BETWEEN %s AND %s ORDER BY datum LIMIT 1",
            (self.ma["id"], self.von, self.bis)) if tage else []
        if belegt:
            self.ergebnis.text = "schon eingetragen"
            self.ergebnis.color = C(UE_ROT)
            self.meldung.text = (f"Am {belegt[0]['datum']:%d.%m.%Y} ist "
                                 f"bereits eine Abwesenheit eingetragen.")
            self.meldung.color = C(UE_ROT)
            self.senden_knopf.disabled = True
            return
        if "Urlaubssperre" in self.meldung.text or \
                "Mindestbesetzung" in self.meldung.text or \
                "bereits eine Abwesenheit" in self.meldung.text:
            self.meldung.text = ""
        # (1.5) Mindestbesetzung der Arbeitsgruppe: nur Hinweis
        verl = zeit.mindest_verletzungen(self.db, self.settings, self.ma,
                                         self.von, self.bis,
                                         self.halb) if tage else []
        if verl:
            v = verl[0]
            self.meldung.text = (f"Hinweis: Am {v['datum']:%d.%m.} wäre die "
                                 f"Mindestbesetzung der Gruppe "
                                 f"{v['gruppe']['name']} unterschritten – der "
                                 f"Antrag wird voraussichtlich abgelehnt.")
            self.meldung.color = C(UE_GELB)
        self.ergebnis.text = f"= {n} Arbeitstag(e)" if tage else \
            "keine Arbeitstage"
        self.ergebnis.color = C(TEXT if tage else UE_ROT)
        self.senden_knopf.disabled = not tage

    def _storno_oeffnen(self):
        uhr, ma, sek = self.uhr, self.ma, self.sekunden
        self.beenden()
        try:
            uhr.uebersicht = UrlaubStorno(uhr, ma, sek)
        except Exception as exc:
            uhr.uebersicht = None
            uhr._db_fehler(ma, exc, "Die Urlaubsübersicht")
            return
        uhr.uebersicht.open()

    def _woche_tage(self, montag):
        heute = jetzt().date()
        tage = zeit.arbeitstage_liste(self.db, self.settings, self.ma,
                                      montag, montag +
                                      datetime.timedelta(days=6))
        return [d for d in tage if d >= heute]

    def _woche(self, delta):
        """Ganze Kalenderwoche wählen; der erste Druck wählt die Woche des
        ersten Urlaubstags, danach springen « / » eine KW weiter."""
        montag = zeit.kw_montag(self.von)
        akt = self._woche_tage(montag)
        if not akt or (self.von, self.bis) != (akt[0], akt[-1]):
            delta = 0
        heute_montag = zeit.kw_montag(jetzt().date())
        schritt = delta or 1
        montag += datetime.timedelta(days=7 * delta)
        for _ in range(10):
            if montag < heute_montag:
                montag, schritt = heute_montag, 1
            tage = self._woche_tage(montag)
            if tage:
                break
            montag += datetime.timedelta(days=7 * schritt)
        else:
            return
        jahr_vorher = self.von.year
        self.von, self.bis = tage[0], tage[-1]
        self.halb = False
        self.meldung.text = ""
        if jahr_vorher != self.von.year:
            self._konto_zeigen()
        self._aktualisieren()

    def _woche_dazu(self):
        montag = zeit.kw_montag(self.bis) + datetime.timedelta(days=7)
        for _ in range(6):
            tage = self._woche_tage(montag)
            if tage:
                self.bis = tage[-1]
                break
            montag += datetime.timedelta(days=7)
        self.halb = False
        self.meldung.text = ""
        self._aktualisieren()

    def _senden(self):
        try:
            _, tage = zeit.antrag_stellen(self.db, self.settings, self.ma,
                                          self.von, self.bis, self.halb,
                                          "urlaub", "", "tablet")
        except ValueError as exc:
            self.meldung.text = str(exc)
            self.meldung.color = C(UE_ROT)
            return
        except Exception as exc:
            log(f"Urlaubsantrag fehlgeschlagen: {exc}")
            self.meldung.text = ("Der Antrag konnte nicht gespeichert werden "
                                 "(Datenbank/Rechte). Bitte im Büro melden.")
            self.meldung.color = C(UE_ROT)
            return
        log(f"{zeit.ma_name(self.ma)}: Urlaubsantrag {self.von} – "
            f"{self.bis} ({tage} Tage)")
        self.meldung.text = (f"Antrag über {zeit.fmt_tage(tage)} Tag(e) "
                             f"gesendet. Sie erhalten die Antwort hier am "
                             f"Tablet.")
        self.meldung.color = C(UE_GRUEN)
        self._konto_zeigen()


class UrlaubStorno(_Vollbild):
    """(1.4) Eigenen Urlaub verwalten: offene Anträge zurückziehen,
    genehmigten (noch nicht begonnenen) Urlaub zur Stornierung beantragen
    – die Stornierung bestätigt das Büro."""

    def __init__(self, uhr, ma, sekunden=60):
        super().__init__(uhr, ma, "Meine Urlaube – zurückziehen oder "
                         "stornieren", sekunden)
        f = self.f
        self.seite = 0
        self.je_seite = 5 if Window.height >= 640 else 3
        self._bestaetigen = None
        i = self.inhalt
        self.kopfzeile = Text(text="", bold=True, font_size=f(0.034),
                              color=C(UE_GELB), halign="left",
                              size_hint_y=None, height=f(0.034) * 1.6)
        i.add_widget(self.kopfzeile)
        self.zeilen = BoxLayout(orientation="vertical", spacing=6)
        i.add_widget(self.zeilen)
        self.meldung = Text(text="", bold=True, font_size=f(0.032),
                            color=C(UE_GRUEN), halign="left",
                            size_hint_y=None, height=f(0.032) * 2.6)
        i.add_widget(self.meldung)
        unten = BoxLayout(spacing=8, size_hint_y=None, height=f(0.04) * 2)
        unten.add_widget(self.gross("«  Urlaub beantragen", self._zurueck,
                                    URLAUB_KNOPF, 0.04, size_hint_x=0.4))
        unten.add_widget(Widget(size_hint_x=0.2))
        self.zurueck_knopf = self.gross("«", lambda: self._blaettern(-1),
                                        UE_KOPF, 0.04, size_hint_x=0.12)
        self.seiten_text = Text(text="", font_size=f(0.03), color=C(GRAU),
                                size_hint_x=0.16)
        self.weiter_knopf = self.gross("»", lambda: self._blaettern(1),
                                       UE_KOPF, 0.04, size_hint_x=0.12)
        for w in (self.zurueck_knopf, self.seiten_text, self.weiter_knopf):
            unten.add_widget(w)
        i.add_widget(unten)
        self._laden()

    def _zurueck(self):
        uhr, ma, sek = self.uhr, self.ma, self.sekunden
        self.beenden()
        uhr.uebersicht = UrlaubsAntrag(uhr, ma, sek)
        uhr.uebersicht.open()

    def _laden(self):
        heute = jetzt().date()
        self.eintraege = zeit.geplanter_urlaub(self.db, self.settings,
                                               self.ma, heute)
        k = zeit.urlaub_konto(self.db, self.settings, self.ma, heute.year,
                              heute)
        self.kopfzeile.text = (f"Resturlaub {k['jahr']}: "
                               f"{zeit.fmt_tage(k['rest'])} Tage  ·  "
                               f"geplant: {zeit.fmt_tage(k['geplant'])} Tage")
        self._zeigen()

    def _blaettern(self, delta):
        self.seite += delta
        self._zeigen()

    def _zeigen(self):
        f = self.f
        self.zeilen.clear_widgets()
        n = len(self.eintraege)
        seiten = max(1, -(-n // self.je_seite))
        self.seite = max(0, min(self.seite, seiten - 1))
        self.seiten_text.text = (f"Seite {self.seite + 1}/{seiten}"
                                 if seiten > 1 else "")
        self.zurueck_knopf.disabled = self.seite <= 0
        self.weiter_knopf.disabled = self.seite >= seiten - 1
        self.zurueck_knopf.opacity = self.weiter_knopf.opacity = \
            1 if seiten > 1 else 0
        if not n:
            self.zeilen.add_widget(Text(
                text="Kein geplanter Urlaub und keine offenen Anträge.",
                bold=True, font_size=f(0.04), color=C(GRAU)))
            return
        hoehe = f(0.038) * 1.4 + f(0.03) * 1.4 + 16
        start = self.seite * self.je_seite
        for idx in range(start, min(n, start + self.je_seite)):
            e = self.eintraege[idx]
            von, bis = e["von"], e["bis"]
            zeitraum = (f"{zeit.WOCHENTAGE[von.weekday()]} {von:%d.%m.%Y}"
                        if von == bis else
                        f"{zeit.WOCHENTAGE[von.weekday()]} {von:%d.%m.}–"
                        f"{zeit.WOCHENTAGE[bis.weekday()]} {bis:%d.%m.%Y}")
            if e["art"] == "antrag":
                stand = ("Stornierung beantragt" if e["typ"] == "storno"
                         else "Antrag offen")
                farbe, knopf = UE_GELB, ("Zurückziehen", UE_KOPF)
            elif e.get("storno_offen"):
                stand, farbe, knopf = "genehmigt – Storno läuft", GRAU, None
            else:
                stand, farbe = "genehmigt", UE_GRUEN
                knopf = ("Stornieren", "#B3261E")
            karte = Flaeche(spacing=8, padding=(10, 6), size_hint_y=None,
                            height=hoehe, farbe=C(UE_KARTE))
            links = BoxLayout(orientation="vertical")
            links.add_widget(Text(text=zeitraum, bold=True,
                                  font_size=f(0.038), color=C(TEXT),
                                  halign="left"))
            links.add_widget(Text(
                text=f"{zeit.kw_bereich_text(von, bis)}  ·  "
                     f"{zeit.fmt_tage(e['tage'])} Tag(e)  ·  {stand}",
                font_size=f(0.03), color=C(farbe), halign="left"))
            karte.add_widget(links)
            if knopf:
                best = self._bestaetigen and self._bestaetigen[0] == idx
                b = self.gross("Wirklich?  Nochmal tippen" if best
                               else knopf[0], lambda i=idx: self._knopf(i),
                               "#B3261E" if best else knopf[1], 0.034,
                               size_hint_x=0.42 if best else 0.28)
                karte.add_widget(b)
            self.zeilen.add_widget(karte)
        self.zeilen.add_widget(Widget())

    def _knopf(self, idx):
        """Erster Tipp: Rückfrage, zweiter Tipp (innerhalb 5 s): ausführen."""
        if self._bestaetigen and self._bestaetigen[0] == idx:
            self._bestaetigen[1].cancel()
            self._bestaetigen = None
            self._ausfuehren(idx)
            return
        if self._bestaetigen:
            self._bestaetigen[1].cancel()
        ev = Clock.schedule_once(lambda dt: self._bestaetigen_aus(), 5)
        self._bestaetigen = (idx, ev)
        self.meldung.text = ""
        self._zeigen()

    def _bestaetigen_aus(self):
        self._bestaetigen = None
        self._zeigen()

    def _ausfuehren(self, idx):
        e = self.eintraege[idx]
        try:
            if e["art"] == "antrag":
                zeit.antrag_zurueckziehen(self.db, self.ma["id"],
                                          e["antrag"]["id"])
                text = ("Der Stornierungsantrag wurde zurückgezogen."
                        if e["typ"] == "storno" else
                        "Der Urlaubsantrag wurde zurückgezogen.")
                log(f"{zeit.ma_name(self.ma)}: Antrag {e['antrag']['id']} "
                    f"zurückgezogen")
            else:
                _, tage = zeit.storno_beantragen(self.db, self.settings,
                                                 self.ma, e["von"], e["bis"],
                                                 quelle="tablet")
                text = (f"Stornierung über {zeit.fmt_tage(tage)} Tag(e) "
                        f"beantragt. Das Büro bestätigt; die Antwort "
                        f"erscheint hier am Tablet.")
                log(f"{zeit.ma_name(self.ma)}: Stornierung {e['von']} – "
                    f"{e['bis']} beantragt")
        except ValueError as exc:
            self.meldung.text = str(exc)
            self.meldung.color = C(UE_ROT)
            self._laden()
            return
        except Exception as exc:
            log(f"Urlaub stornieren fehlgeschlagen: {exc}")
            self.meldung.text = ("Das hat nicht geklappt (Datenbank/Rechte). "
                                 "Bitte im Büro melden.")
            self.meldung.color = C(UE_ROT)
            return
        self.meldung.text = text
        self.meldung.color = C(UE_GRUEN)
        self._laden()

    def beenden(self):
        if self._bestaetigen:
            self._bestaetigen[1].cancel()
            self._bestaetigen = None
        super().beenden()


class AuftragWahl(_Vollbild):
    """Arbeitszeit auf einen offenen Auftrag buchen."""

    def __init__(self, uhr, ma, sekunden=60):
        super().__init__(uhr, ma, "Arbeitszeit auf Auftrag buchen",
                         sekunden)
        f = self.f
        akt = zeit.aktueller_auftrag(self.db, ma["id"])
        self.aktuell_id = akt["beleg_id"] if akt else None
        if akt:
            b = self.db.one("SELECT nummer, k_name FROM belege WHERE id=%s",
                            (akt["beleg_id"],)) or {}
            text = (f"Aktuell: {b.get('nummer', '?')} – "
                    f"{b.get('k_name', '')}  seit {akt['beginn']:%H:%M} Uhr")
        else:
            text = "Aktuell: kein Auftrag"
        oben = BoxLayout(spacing=12, size_hint_y=None, height=f(0.035) * 2)
        oben.add_widget(Text(text=text, bold=True, font_size=f(0.035),
                             color=C(UE_GELB), halign="left"))
        if akt:
            oben.add_widget(self.gross("Auftrag beenden",
                                       lambda: self._waehlen(None),
                                       "#5A2622", 0.035, size_hint_x=0.3))
        self.inhalt.add_widget(oben)
        self.scroll = ScrollView(bar_width=12, bar_color=C("#6A7585"),
                                 bar_inactive_color=C("#4C5566"),
                                 scroll_type=["bars", "content"],
                                 do_scroll_x=False)
        liste = GridLayout(cols=1, spacing=3, size_hint_y=None)
        liste.bind(minimum_height=liste.setter("height"))
        auftraege = zeit.offene_auftraege(self.db)
        for n, a in enumerate(auftraege):
            farbe = "#1E5A33" if a["id"] == self.aktuell_id else \
                UE_ZEILE[n % 2]
            text = f"{a['nummer']}   {a['k_name'] or ''}"
            if a.get("betreff"):
                text += f"\n{a['betreff']}"
            b = Button(text=text, bold=True, font_size=f(0.035),
                       halign="left", valign="middle", size_hint_y=None,
                       height=f(0.035) * (3.4 if a.get("betreff") else 2.2),
                       background_normal="", background_down="",
                       background_color=C(farbe), color=C(TEXT),
                       padding=(16, 8))
            b.bind(size=lambda w, *x: setattr(w, "text_size",
                                              (w.width - 32, None)))
            b.bind(on_release=lambda w, a=a: self._waehlen(a))
            liste.add_widget(b)
        if not auftraege:
            liste.add_widget(Text(text="Keine offenen Aufträge.",
                                  font_size=f(0.035), color=C(GRAU),
                                  size_hint_y=None, height=f(0.035) * 2))
        self.scroll.add_widget(liste)
        self.inhalt.add_widget(self.scroll)

    def _waehlen(self, auftrag):
        uhr = self.uhr
        j = jetzt().replace(microsecond=0)
        name = zeit.ma_name(self.ma)
        try:
            if zeit.aktueller_status(self.db, self.ma["id"], j) != "anwesend":
                uhr._uebersicht_schliessen()
                uhr.anzeigen(name, "Aufträge können nur gebucht werden, "
                             "wenn Sie eingestempelt sind.", GELB)
                return
            zeit.auftrag_starten(self.db, self.ma["id"],
                                 auftrag["id"] if auftrag else None, j,
                                 quelle="tablet")
        except Exception as exc:
            uhr._uebersicht_schliessen()
            uhr._db_fehler(self.ma, exc, "Das Buchen auf den Auftrag")
            return
        uhr._uebersicht_schliessen()
        if auftrag:
            log(f"{name}: Auftrag {auftrag['nummer']} ab {j:%H:%M}")
            uhr.anzeigen(name, f"Arbeitszeit ab {j:%H:%M} Uhr auf Auftrag "
                         f"{auftrag['nummer']} ({auftrag['k_name'] or ''})",
                         AUFTRAG_KNOPF)
        else:
            log(f"{name}: Auftrag beendet {j:%H:%M}")
            uhr.anzeigen(name, f"Auftrag um {j:%H:%M} Uhr beendet.",
                         AUFTRAG_KNOPF)


class AuftragsVerarbeitung(_Vollbild):
    """(1.9 / Faktura 10.3) Modul Auftragsverarbeitung: Auftrag wählen,
    Arbeitszeit auf einen Arbeitsschritt buchen und verarbeitetes Material
    melden."""

    def __init__(self, uhr, ma, sekunden=60):
        super().__init__(uhr, ma, "Auftragsbearbeitung", sekunden,
                         knopf_text="Fertig")
        self.lager = str(uhr.settings.get("modul_lager", "1")) != "0"
        self.auftraege = av_tablet.av_sichtbar_fuer(self.db, ma["id"])
        self.auftrag = None
        self.schritt_id = None
        self.schritt_knoepfe = {}
        self.mat_sel = None
        self.mat_knoepfe = {}
        self.minuten = 0
        self.menge = 0
        self._auswahl_ansicht()

    # -- Hilfen ---------------------------------------------------------
    def _titel(self, text, farbe=UE_GELB, faktor=0.038):
        self.inhalt.add_widget(Text(text=text, bold=True,
                                    font_size=self.f(faktor), color=C(farbe),
                                    halign="left", size_hint_y=None,
                                    height=self.f(faktor) * 1.9))

    def _liste(self):
        """Senkrecht scrollbare, einspaltige Liste in self.inhalt; liefert den
        inneren GridLayout (füllt den Platz über der festen unteren Leiste)."""
        scroll = ScrollView(bar_width=12, bar_color=C("#6A7585"),
                            bar_inactive_color=C("#4C5566"),
                            scroll_type=["bars", "content"], do_scroll_x=False)
        box = GridLayout(cols=1, spacing=4, size_hint_y=None, padding=(0, 2))
        box.bind(minimum_height=box.setter("height"))
        scroll.add_widget(box)
        self.inhalt.add_widget(scroll)
        return box

    def _zeilenknopf(self, box, text, befehl, farbe, speicher=None, key=None):
        f = self.f
        b = Button(text=text, bold=True, font_size=f(0.034), halign="left",
                   valign="middle", size_hint_y=None, height=f(0.034) * 2.6,
                   background_normal="", background_down="",
                   background_color=C(farbe), color=C(TEXT), padding=(16, 8))
        b.bind(size=lambda w, *x: setattr(w, "text_size", (w.width - 32,
                                                           None)))
        b.bind(on_release=lambda w: befehl())
        box.add_widget(b)
        if speicher is not None and key is not None:
            speicher[key] = b
        return b

    # -- Auftrag wählen -------------------------------------------------
    def _auswahl_ansicht(self):
        self.inhalt.clear_widgets()
        self._titel("Bitte einen Auftrag wählen:")
        box = self._liste()
        if not self.auftraege:
            box.add_widget(Text(text="Zurzeit liegt kein Auftrag für Sie "
                                "vor.", font_size=self.f(0.034), color=C(GRAU),
                                halign="left", size_hint_y=None,
                                height=self.f(0.034) * 2))
            return
        for n, a in enumerate(self.auftraege):
            self._zeilenknopf(box, f"{a['nummer']}   {a['name']}",
                              lambda a=a: self._order_menu(a),
                              UE_ZEILE[n % 2])

    # -- Nach Auftragswahl: Arbeitszeit oder Material? -----------------
    def _order_menu(self, a):
        self.auftrag = a
        f = self.f
        self.inhalt.clear_widgets()
        self._titel(f"Auftrag {a['nummer']} – {a['name']}")
        self.inhalt.add_widget(self.gross(
            "Arbeitszeit buchen", lambda: self._zeit_screen(a), "#1E8C3A",
            0.05, size_hint_y=None, height=f(0.05) * 2.6))
        if av_tablet.av_material(self.db, a["id"]):
            self.inhalt.add_widget(self.gross(
                "Material buchen", lambda: self._material_screen(a), AV_KNOPF,
                0.05, size_hint_y=None, height=f(0.05) * 2.6))
        self.inhalt.add_widget(self.gross(
            "‹ Zurück zur Auftragsliste", self._auswahl_ansicht, "#44525C",
            0.035, size_hint_y=None, height=f(0.035) * 2.4))
        self.inhalt.add_widget(Widget())      # Rest nach unten schieben

    def _leiste(self, bedien_bauen, buchen_text, buchen_cmd, zurueck):
        """Feste Leiste am unteren Rand: Bedienteil + Status + Zurück/Buchen."""
        f = self.f
        bar = BoxLayout(orientation="vertical", size_hint_y=None, spacing=4,
                        height=f(0.05) * 2 + f(0.03) * 1.8 + f(0.045) * 2.4)
        bedien = BoxLayout(spacing=6, size_hint_y=None, height=f(0.05) * 2)
        bedien_bauen(bedien)
        bar.add_widget(bedien)
        self.status = Text(text="", font_size=f(0.03), color=C("#9BE3B4"),
                           halign="left", size_hint_y=None,
                           height=f(0.03) * 1.8)
        bar.add_widget(self.status)
        zeile = BoxLayout(spacing=8, size_hint_y=None, height=f(0.045) * 2.4)
        zeile.add_widget(self.gross("‹ Zurück", zurueck, "#44525C", 0.035,
                                    size_hint_x=0.3))
        zeile.add_widget(self.gross(buchen_text, buchen_cmd, "#1E8C3A", 0.04))
        bar.add_widget(zeile)
        self.inhalt.add_widget(bar)

    # -- Arbeitszeit buchen --------------------------------------------
    def _zeit_screen(self, a):
        self.schritt_id = None
        self.schritt_knoepfe = {}
        self.minuten = 0
        f = self.f
        self.inhalt.clear_widgets()
        self._titel(f"Arbeitszeit – Auftrag {a['nummer']}")
        self.inhalt.add_widget(Text(text="Arbeitsschritt wählen:",
                                    font_size=f(0.032), color=C(TEXT),
                                    halign="left", size_hint_y=None,
                                    height=f(0.032) * 1.8))
        box = self._liste()
        schritte = av_tablet.av_schritte(self.db, a["id"])
        if schritte:
            for s in schritte:
                self._zeilenknopf(box, s["bezeichnung"],
                                  lambda s=s: self._schritt(s), "#3A4250",
                                  self.schritt_knoepfe, s["id"])
        else:
            box.add_widget(Text(text="(keine Arbeitsschritte – Zeit wird ohne "
                                "Schritt gebucht)", font_size=f(0.03),
                                color=C(GRAU), halign="left",
                                size_hint_y=None, height=f(0.03) * 2))

        def bedien(z):
            for text, m in (("-1 Std", -60), ("-15 Min", -15)):
                z.add_widget(self.gross(text, lambda m=m: self._std(m),
                                        "#3A4250", 0.03))
            self.std_label = Text(text="0:00", bold=True, font_size=f(0.055),
                                  color=C(TEXT))
            z.add_widget(self.std_label)
            for text, m in (("+15 Min", 15), ("+1 Std", 60)):
                z.add_widget(self.gross(text, lambda m=m: self._std(m),
                                        "#3A4250", 0.03))
        self._leiste(bedien, "Arbeitszeit buchen", self._zeit_buchen,
                     lambda: self._order_menu(a))

    # -- Material buchen -----------------------------------------------
    def _material_screen(self, a):
        self.mat_sel = None
        self.mat_knoepfe = {}
        self.menge = 0
        f = self.f
        self.inhalt.clear_widgets()
        self._titel(f"Material – Auftrag {a['nummer']}")
        self.inhalt.add_widget(Text(text="Material wählen:",
                                    font_size=f(0.032), color=C(TEXT),
                                    halign="left", size_hint_y=None,
                                    height=f(0.032) * 1.8))
        box = self._liste()
        for m in av_tablet.av_material(self.db, a["id"]):
            vg = ""
            if m.get("menge_geplant") is not None:
                vg = (f"  · Vorgabe "
                      f"{('%g' % float(m['menge_geplant'])).replace('.', ',')}"
                      f" {m['einheit']}")
            self._zeilenknopf(box, f"{m['bezeichnung']} ({m['einheit']}){vg}",
                              lambda m=m: self._mat(m), "#3A4250",
                              self.mat_knoepfe, m["id"])

        def bedien(z):
            for text, d in (("-10", -10), ("-1", -1)):
                z.add_widget(self.gross(text, lambda d=d: self._menge(d),
                                        "#3A4250", 0.03))
            self.menge_label = Text(text="0", bold=True, font_size=f(0.055),
                                    color=C(TEXT))
            z.add_widget(self.menge_label)
            for text, d in (("+1", 1), ("+10", 10)):
                z.add_widget(self.gross(text, lambda d=d: self._menge(d),
                                        "#3A4250", 0.03))
        self._leiste(bedien, "Material buchen", self._mat_buchen,
                     lambda: self._order_menu(a))

    def _schritt(self, s):
        self.schritt_id = s["id"]
        for sid, b in self.schritt_knoepfe.items():
            b.background_color = C("#1E7B4F" if sid == s["id"] else "#3A4250")
        self.aktiv()

    def _std(self, m):
        self.minuten = max(0, self.minuten + m)
        h, mm = divmod(self.minuten, 60)
        self.std_label.text = f"{h}:{mm:02d}"
        self.aktiv()

    def _mat(self, m):
        self.mat_sel = m
        for mid, b in self.mat_knoepfe.items():
            b.background_color = C("#1E7B4F" if mid == m["id"] else "#3A4250")
        self.aktiv()

    def _menge(self, d):
        self.menge = max(0, self.menge + d)
        self.menge_label.text = str(self.menge)
        self.aktiv()

    def _melden(self, text, farbe="#9BE3B4"):
        self.status.text = text
        self.status.color = C(farbe)
        self.aktiv()

    def _zeit_buchen(self):
        if self.minuten <= 0:
            self._melden("Bitte zuerst eine Stundenzahl einstellen.",
                         "#F2B33D")
            return
        if self.schritt_knoepfe and not self.schritt_id:
            self._melden("Bitte einen Arbeitsschritt auswählen.", "#F2B33D")
            return
        try:
            av_tablet.av_zeit_buchen(self.db, self.auftrag["id"], self.ma["id"],
                                self.minuten, schritt_id=self.schritt_id,
                                quelle="tablet")
        except Exception as exc:
            self.uhr._uebersicht_schliessen()
            self.uhr._db_fehler(self.ma, exc, "Das Buchen der Arbeitszeit")
            return
        h, mm = divmod(self.minuten, 60)
        log(f"{zeit.ma_name(self.ma)}: Auftrag {self.auftrag['nummer']} "
            f"{h}:{mm:02d} gebucht")
        self.minuten = 0
        self.std_label.text = "0:00"
        self._melden(f"{h}:{mm:02d} Std auf {self.auftrag['nummer']} "
                     f"gebucht.")

    def _mat_buchen(self):
        if not self.mat_sel:
            self._melden("Bitte ein Material auswählen.", "#F2B33D")
            return
        if self.menge <= 0:
            self._melden("Bitte eine Menge einstellen.", "#F2B33D")
            return
        try:
            av_tablet.av_verbrauch_buchen(self.db, self.auftrag["id"],
                                     self.ma["id"], self.menge,
                                     material_id=self.mat_sel["id"],
                                     quelle="tablet",
                                     lager_abbuchen=self.lager)
        except Exception as exc:
            self.uhr._uebersicht_schliessen()
            self.uhr._db_fehler(self.ma, exc, "Das Buchen des Materials")
            return
        text = (f"{self.menge} {self.mat_sel['einheit']} "
                f"{self.mat_sel['bezeichnung']} gebucht.")
        self.menge = 0
        self.menge_label.text = "0"
        self._melden(text)


class NachrichtenAnzeige(_Vollbild):
    """Nachrichten aus dem Büro; 'Gelesen' bestätigt sie."""

    def __init__(self, uhr, ma, nachrichten, gebucht="", sekunden=60):
        super().__init__(uhr, ma, (gebucht + "  ·  " if gebucht else "") +
                         f"{len(nachrichten)} Nachricht(en) aus dem Büro",
                         sekunden, knopf_text="Später")
        f = self.f
        self.nachrichten = nachrichten
        for n in nachrichten[:4]:
            k = Flaeche(orientation="vertical", padding=(14, 8), spacing=2,
                        farbe=C("#24466E"), size_hint_y=None)
            t = Text(text=n["text"], bold=True, font_size=f(0.045),
                     color=C(TEXT), halign="left", size_hint_y=None)
            u = Text(text=f"{n.get('von') or 'Büro'}, "
                          f"{n['erstellt']:%d.%m.%Y %H:%M}",
                     font_size=f(0.028), color=C("#B8C4D0"), halign="left",
                     size_hint_y=None, height=f(0.028) * 1.5)

            def hoehe(*a, t=t, u=u, k=k):
                t.height = t.texture_size[1]
                k.height = t.height + u.height + 20
            t.bind(texture_size=hoehe)
            k.add_widget(t)
            k.add_widget(u)
            self.inhalt.add_widget(k)
        if len(nachrichten) > 4:
            self.inhalt.add_widget(Text(
                text=f"... und {len(nachrichten) - 4} weitere",
                font_size=f(0.03), color=C(GRAU), halign="left",
                size_hint_y=None, height=f(0.03) * 1.5))
        self.inhalt.add_widget(Widget())
        zeile = BoxLayout(size_hint_y=None, height=f(0.06) * 1.9)
        zeile.add_widget(Widget())
        self.gelesen_knopf = self.gross("Gelesen", self._gelesen, "#1E8C3A",
                                        0.06, size_hint_x=None,
                                        width=f(0.06) * 7)
        zeile.add_widget(self.gelesen_knopf)
        zeile.add_widget(Widget())
        self.inhalt.add_widget(zeile)

    def _weiter(self):
        ma, uhr = self.ma, self.uhr
        uhr._uebersicht_schliessen(ruhe=False)
        if uhr.karte_ma:
            uhr.karte_bis = jetzt() + uhr._wartezeit()
        uhr._einspringen_oder_angebot(ma)

    def _gelesen(self):
        try:
            for n in self.nachrichten[:4]:
                zeit.nachricht_gelesen(self.db, n["id"], jetzt())
        except Exception as exc:
            log(f"Nachricht gelesen fehlgeschlagen: {exc}")
        self._weiter()

    def schliessen(self):
        self._weiter()


class EinspringFrage(_Vollbild):
    """(Faktura 9.7) Können Sie einspringen? Ja/Nein je Tag – das Büro
    sieht die Antwort sofort."""

    def __init__(self, uhr, ma, anfragen, sekunden=60):
        super().__init__(uhr, ma, "Mindestbesetzung unterschritten – "
                         "können Sie einspringen?", sekunden,
                         knopf_text="Später")
        f = self.f
        self.offen = 0
        self.inhalt.add_widget(Text(
            text="Bitte antworten Sie – das Büro sieht Ihre Antwort sofort.",
            font_size=f(0.032), color=C(GRAU), halign="left",
            size_hint_y=None, height=f(0.032) * 1.8))
        for a in anfragen[:4]:
            self.offen += 1
            d = a["datum"]
            fehlen = zeit.anzahl_text(a.get("fehlen") or 1)
            text = (f"{WOCHENTAGE[d.weekday()]}, {d:%d.%m.%Y}"
                    + (f" – {a['gruppe']}" if a.get("gruppe") else "")
                    + ("\nes fehlt 1 Person" if fehlen == "1" else
                       f"\nes fehlen {fehlen} Personen"))
            zeile = Flaeche(orientation="horizontal", padding=(14, 8),
                            spacing=12, farbe=C("#24466E"),
                            size_hint_y=None, height=f(0.04) * 3.4)
            zeile.add_widget(Text(text=text, bold=True, font_size=f(0.04),
                                  color=C(TEXT), halign="left"))
            knoepfe = BoxLayout(spacing=10, size_hint_x=0.45)
            knoepfe.add_widget(self.gross(
                "Ja, ich komme", lambda a=a, k=knoepfe: self._antwort(
                    a, "ja", k), "#1E8C3A", 0.04))
            knoepfe.add_widget(self.gross(
                "Nein", lambda a=a, k=knoepfe: self._antwort(a, "nein", k),
                "#5A6270", 0.04, size_hint_x=0.5))
            zeile.add_widget(knoepfe)
            self.inhalt.add_widget(zeile)
        self.inhalt.add_widget(Widget())

    def _antwort(self, anfrage, antwort, knoepfe):
        zeit.einspring_antworten(self.db, anfrage["id"], self.ma["id"],
                                 antwort, "tablet")
        log(f"{zeit.ma_name(self.ma)}: Einspringen "
            f"{anfrage['datum']:%d.%m.%Y} -> {antwort}")
        knoepfe.clear_widgets()
        knoepfe.add_widget(Text(
            text="Zugesagt – vielen Dank!" if antwort == "ja" else
            "Abgesagt", bold=True, font_size=self.f(0.04),
            color=C(UE_GRUEN if antwort == "ja" else GRAU)))
        self.offen -= 1
        if self.offen <= 0:
            Clock.schedule_once(lambda dt: self.schliessen(), 1.5)

    def schliessen(self):
        ma, uhr = self.ma, self.uhr
        if uhr.uebersicht is not self:
            return
        uhr._uebersicht_schliessen(ruhe=False)
        if uhr.karte_ma:
            uhr.karte_bis = jetzt() + uhr._wartezeit()
        uhr._uebersicht_anbieten(ma)


class KorrekturAntrag(_Vollbild):
    """(Faktura 9.7) Fehlende oder falsche Stempelung beantragen –
    das Büro genehmigt per Klick."""

    def __init__(self, uhr, ma, sekunden=60):
        super().__init__(uhr, ma, "Korrektur beantragen – die Genehmigung "
                         "erfolgt im Büro", sekunden)
        f = self.f
        self.heute = jetzt().date()
        try:
            n = max(1, int(self.settings.get("korrektur_tage") or 14))
        except (TypeError, ValueError):
            n = 14
        self.erster = self.heute - datetime.timedelta(days=n)
        self.datum, self.art = zeit.korrektur_vorschlag(
            self.db, self.settings, ma, self.heute)
        self.grund = zeit.KORREKTUR_GRUENDE[0]
        self.zp = None
        blau = "#3A4250"
        h = f(0.04) * 2.0

        def zeile_mit(titel):
            z = BoxLayout(spacing=6, size_hint_y=None, height=h)
            z.add_widget(Text(text=titel, font_size=f(0.035), color=C(GRAU),
                              halign="left", size_hint_x=0.13))
            self.inhalt.add_widget(z)
            return z
        z = zeile_mit("Tag:")
        z.add_widget(self.gross("<", lambda: self._tag(-1), blau, 0.04,
                                size_hint_x=0.08))
        self.tag_label = Text(text="", bold=True, font_size=f(0.042),
                              color=C(TEXT), size_hint_x=0.32)
        z.add_widget(self.tag_label)
        z.add_widget(self.gross(">", lambda: self._tag(1), blau, 0.04,
                                size_hint_x=0.08))
        z.add_widget(Widget(size_hint_x=0.39))
        self.stempel_label = Text(text="", font_size=f(0.03),
                                  color=C(UE_GELB), halign="left",
                                  size_hint_y=None, height=f(0.03) * 1.8)
        self.inhalt.add_widget(self.stempel_label)
        z = zeile_mit("Was:")
        self.art_knoepfe = {}
        for art, text in zeit.ARTEN.items():
            b = self.gross(text, lambda a=art: self._art(a), blau, 0.033)
            z.add_widget(b)
            self.art_knoepfe[art] = b
        z = zeile_mit("Uhrzeit:")
        for text, m in (("-1 Std", -60), ("-5 Min", -5)):
            z.add_widget(self.gross(text, lambda m=m: self._zeit(m), blau,
                                    0.032))
        self.zeit_label = Text(text="", bold=True, font_size=f(0.06),
                               color=C(TEXT))
        z.add_widget(self.zeit_label)
        for text, m in (("+5 Min", 5), ("+1 Std", 60)):
            z.add_widget(self.gross(text, lambda m=m: self._zeit(m), blau,
                                    0.032))
        gr = GridLayout(cols=3, spacing=6, size_hint_y=None,
                        height=f(0.028) * 2.4 * 2 + 6)
        self.grund_knoepfe = {}
        for g in zeit.KORREKTUR_GRUENDE:
            b = self.gross(g, lambda g=g: self._grund(g), blau, 0.028)
            gr.add_widget(b)
            self.grund_knoepfe[g] = b
        zg = BoxLayout(spacing=6, size_hint_y=None, height=gr.height)
        zg.add_widget(Text(text="Grund:", font_size=f(0.035), color=C(GRAU),
                           halign="left", valign="top", size_hint_x=0.13))
        zg.add_widget(gr)
        self.inhalt.add_widget(zg)
        unten = BoxLayout(spacing=12)
        self.info = Text(text="", font_size=f(0.027), color=C(GRAU),
                         halign="left", valign="top")
        unten.add_widget(self.info)
        knopf_box = BoxLayout(orientation="vertical", size_hint_x=0.35)
        knopf_box.add_widget(Widget())
        knopf_box.add_widget(self.gross("Antrag senden", self._senden,
                                        "#1E8C3A", 0.05, size_hint_y=None,
                                        height=f(0.05) * 2.2))
        unten.add_widget(knopf_box)
        self.inhalt.add_widget(unten)
        self._offene_zeigen()
        self._art(self.art)
        self._grund(self.grund)

    def _offene_zeigen(self):
        try:
            eigene = zeit.korrekturen(self.db, None, self.ma["id"], 4)
        except Exception:
            eigene = []
        self.info.color = C(GRAU)
        self.info.text = ("Ihre letzten Anträge:\n" + "\n".join(
            f"{zeit.korrektur_text(k)}: "
            f"{zeit.KORREKTUR_STATUS.get(k['status'], k['status'])}"
            for k in eigene)) if eigene else ""

    def _tag_anzeigen(self):
        d = self.datum
        self.tag_label.text = (f"{zeit.WOCHENTAGE[d.weekday()]} "
                               f"{d:%d.%m.%Y}"
                               + (" (heute)" if d == self.heute else ""))
        try:
            r = zeit.regeln(self.settings, self.ma)
            st, _ = zeit.arbeitstage_laden(self.db, self.ma["id"], d, d, r)
            text = zeit.stempel_text(st.get(d, []), d)
        except Exception as exc:
            log(f"Stempelungen nicht lesbar: {exc}")
            text = ""
        self.stempel_label.text = "Gestempelt: " + (text or "nichts")

    def _zeit_anzeigen(self):
        self.zeit_label.text = f"{self.zp:%H:%M}" + (
            " +1" if self.zp.date() > self.datum else "")

    def _markieren(self, knoepfe, aktiv):
        for k, b in knoepfe.items():
            b.background_color = C("#2F6690" if k == aktiv else "#3A4250")

    def _vorschlag(self):
        try:
            self.zp = zeit.korrektur_zeit_vorschlag(
                self.db, self.settings, self.ma, self.datum, self.art,
                jetzt())
        except Exception as exc:
            log(f"Zeitvorschlag fehlgeschlagen: {exc}")
            self.zp = datetime.datetime.combine(self.datum,
                                                datetime.time(8, 0))
        self._zeit_anzeigen()

    def _tag(self, delta):
        neu = self.datum + datetime.timedelta(days=delta)
        if self.erster <= neu <= self.heute:
            self.datum = neu
            self._tag_anzeigen()
            self._vorschlag()

    def _art(self, art):
        self.art = art
        self._markieren(self.art_knoepfe, art)
        self._tag_anzeigen()
        self._vorschlag()

    def _grund(self, grund):
        self.grund = grund
        self._markieren(self.grund_knoepfe, grund)

    def _zeit(self, minuten):
        neu = self.zp + datetime.timedelta(minutes=minuten)
        unten = datetime.datetime.combine(self.datum, datetime.time(0, 0))
        oben = min(jetzt(), unten + datetime.timedelta(days=1, hours=12))
        if unten <= neu <= oben:
            self.zp = neu
            self._zeit_anzeigen()

    def _senden(self):
        name = zeit.ma_name(self.ma)
        try:
            zeit.korrektur_beantragen(self.db, self.settings, self.ma,
                                      self.datum, self.art, self.zp,
                                      self.grund, "tablet", jetzt())
        except ValueError as exc:
            self.info.color = C(UE_ROT)
            self.info.text = str(exc)
            return
        d = self.datum
        text = (f"Korrekturantrag gesendet: {zeit.ARTEN[self.art]} "
                f"{self.zp:%H:%M} am {zeit.WOCHENTAGE[d.weekday()]} "
                f"{d:%d.%m.} – das Büro entscheidet.")
        log(f"{name}: {text}")
        self.uhr._uebersicht_schliessen()
        self.uhr.anzeigen(name, text, KORREKTUR_KNOPF)


# ---------------------------------------------------------------------------
# Einrichtung (Datenbankverbindung)
# ---------------------------------------------------------------------------
class Einrichtung(Flaeche):
    FELDER = [("host", "Datenbank-Server (IP-Adresse des Büro-PCs)"),
              ("port", "Port"), ("benutzer", "Benutzer"),
              ("passwort", "Passwort"), ("datenbank", "Datenbank"),
              ("ersatz_host", "Ersatzserver (optional, IP-Adresse)"),
              ("name", "Name des Terminals")]

    def __init__(self, app, werte, fehlertext="", zurueck=False, **kw):
        super().__init__(orientation="vertical", padding=24, spacing=10, **kw)
        self.app = app
        self.werte = werte
        self.add_widget(Label(text="Stempeluhr einrichten", font_size=34,
                              bold=True, size_hint_y=None, height=56,
                              color=C(TEXT)))
        scroll = ScrollView()
        raster = GridLayout(cols=2, spacing=(16, 10), size_hint_y=None,
                            padding=(0, 6))
        raster.bind(minimum_height=raster.setter("height"))
        self.felder = {}
        for key, text in self.FELDER:
            raster.add_widget(Text(text=text, color=C(GRAU), halign="right",
                                   font_size=22, size_hint_y=None,
                                   height=52))
            f = TextInput(text=str(werte.get(key, "")), multiline=False,
                          password=key == "passwort", font_size=24,
                          size_hint_y=None, height=52, write_tab=False,
                          input_filter="int" if key == "port" else None)
            raster.add_widget(f)
            self.felder[key] = f
        scroll.add_widget(raster)
        self.add_widget(scroll)
        self.meldung = Text(text=fehlertext, color=C("#FF6B5E"), font_size=20,
                            size_hint_y=None, height=60)
        self.add_widget(self.meldung)
        zeile = BoxLayout(spacing=16, size_hint_y=None, height=70)
        zeile.add_widget(knopf("Abbrechen", self._abbrechen, hoehe=70))
        self.ok = knopf("Verbinden", self._verbinden, "#1E8C3A", hoehe=70)
        zeile.add_widget(self.ok)
        self.add_widget(zeile)
        self.zurueck = zurueck
        felder = [self.felder[k] for k, _ in self.FELDER]
        for a, b in zip(felder, felder[1:]):
            a.bind(on_text_validate=lambda w, n=b: setattr(n, "focus", True))
        felder[-1].bind(on_text_validate=lambda w: self._verbinden())

    def _werte(self):
        w = {k: f.text.strip() for k, f in self.felder.items()}
        w["vollbild"] = self.werte.get("vollbild", "1")
        return w

    def _abbrechen(self):
        if self.zurueck or self.werte.get("vorhanden"):
            self.app.terminal_zeigen(self.werte, None)
        else:
            self.app.beenden()

    def _verbinden(self):
        w = self._werte()
        if not w["host"]:
            self.meldung.text = "Bitte den Datenbank-Server eintragen."
            return
        self.meldung.color = C(GRAU)
        self.meldung.text = "Verbinde ..."
        self.ok.disabled = True

        def lauf():
            try:
                db = verbinden(w)
                fehler = ""
            except Exception as exc:
                db, fehler = None, str(exc)
            Clock.schedule_once(lambda dt: self._ergebnis(w, db, fehler))
        threading.Thread(target=lauf, daemon=True).start()

    def _ergebnis(self, w, db, fehler):
        self.ok.disabled = False
        if db is None:
            self.meldung.color = C("#FF6B5E")
            self.meldung.text = f"Verbindung fehlgeschlagen: {fehler}"
            return
        ini_schreiben(w)
        self.app.terminal_zeigen(dict(w, vorhanden=True), db)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
KEY_ENTER = (13, 271)
KEY_ESC = 27
KEY_BACKSPACE = 8
KEY_F = {282: "kommt", 283: "geht", 284: "pause_an", 285: "pause_ende"}


class StempeluhrApp(App):
    title = "Stempeluhr"

    def build(self):
        pfade_setzen(self.user_data_dir)
        zeit_abgleichen()
        Window.clearcolor = C(HINTERGRUND)
        Window.softinput_mode = "below_target"
        Window.bind(on_key_down=self._taste_gedrueckt)
        self.terminal = None
        self.root_box = Flaeche()
        Clock.schedule_once(lambda dt: self._start(), 0.1)
        return self.root_box

    def _start(self):
        cfg = ini_lesen()
        if pymysql is None:
            self.einrichtung_zeigen(cfg, "Das Paket 'pymysql' fehlt.")
            return
        if not cfg["vorhanden"]:
            self.einrichtung_zeigen(cfg)
            return
        try:
            db = verbinden(cfg)
        except Exception as exc:
            log(f"Start ohne Datenbank: {exc}")
            if not os.path.exists(CACHE):
                self.einrichtung_zeigen(cfg, f"Verbindung fehlgeschlagen: "
                                             f"{exc}")
                return
            db = None
        self.terminal_zeigen(cfg, db)

    def _wechseln(self, widget):
        if self.terminal is not None and widget is not self.terminal:
            self.terminal.beenden_timer()
            self.terminal.popup_schliessen()
            self.terminal = None
        self.root_box.clear_widgets()
        self.root_box.add_widget(widget)

    def einrichtung_zeigen(self, cfg, fehlertext="", zurueck=False):
        self._wechseln(Einrichtung(self, cfg, fehlertext, zurueck))

    def terminal_zeigen(self, cfg, db):
        if db is None and self.terminal is not None:
            # Abbrechen in der Einrichtung: alte Verbindung weiter nutzen
            db = self.terminal.db
        t = Stempeluhr(self, cfg, db)
        self._wechseln(t)
        self.terminal = t
        self._tasten_binden()

    def _tasten_binden(self):
        """Zurück-Taste zuverlässig selbst bekommen: Reste der Bildschirm-
        tastatur (Eingabefelder der Einrichtung) freigeben und den eigenen
        Handler zuletzt binden – Kivy ruft ihn dann als ersten auf."""
        try:
            Window.release_all_keyboards()
        except Exception as exc:
            log(f"Tastatur freigeben: {exc}")
        Window.unbind(on_key_down=self._taste_gedrueckt)
        Window.bind(on_key_down=self._taste_gedrueckt)

    def beenden(self):
        log("Stempeluhr beendet")
        self.stop()

    def _taste_gedrueckt(self, window, key, scancode, codepoint, modifier):
        t = self.terminal
        if key == KEY_ESC:
            log("Zurück-Taste/Geste")
            if t is not None:
                t.menue_anfordern()
            return True          # Android: Zurück-Taste nicht beenden
        if t is None or t.popup is not None:
            return False         # Eingabefelder bedienen die Tastatur
        if key in KEY_F:
            t.taste(KEY_F[key])
            return True
        if key in KEY_ENTER:
            t.karte_eingabe()
            return True
        if key == KEY_BACKSPACE:
            t.zurueck()
            return True
        if 256 <= key <= 265:                 # Ziffernblock
            t.zeichen(str(key - 256))
            return True
        if 32 < key < 127:
            t.zeichen(chr(key))
            return True
        return False

    def on_pause(self):
        return True

    def on_resume(self):
        zeit_abgleichen()
        if self.terminal is not None:
            self._tasten_binden()


if __name__ == "__main__":
    StempeluhrApp().run()
