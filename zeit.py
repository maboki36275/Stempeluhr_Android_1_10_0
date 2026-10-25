# -*- coding: utf-8 -*-
"""
Zeitwirtschaft: Feiertage, Tages- und Monatsauswertung, Stempel-Logik.

Wird vom Hauptprogramm (faktura.py) und vom Stempel-Terminal
(stempeluhr.py) gemeinsam benutzt – braucht nur pymysql (über db.py).

Regeln:
- Normalerweise endet die Arbeit am selben Tag. Mitarbeiter mit dem Haken
  'Arbeitet über 24 Uhr' dürfen über Mitternacht eingestempelt sein
  (auch eine Pause über Mitternacht ist möglich). Die Schicht gehört dann
  zum Tag ihres 'Kommt' (Soll, Ist, Pause); Stunden an Samstagen,
  Sonntagen und Feiertagen werden nach Kalendertag aufgeteilt. Liegen
  zwischen dem 'Kommt' des Vortags und dem 'Geht' mehr als
  'zeit_max_schicht_stunden' (Standard 12), gilt das als Stempelfehler
  (Geht bzw. Kommt vergessen).
- Tagessoll = Wochenstunden / Anzahl Arbeitstage; an Feiertagen, Tagen
  mit Urlaub/Krankheit/Abwesenheit und außerhalb des Beschäftigungs-
  zeitraums ist das Soll 0.
- Pause: gestempelte Pausen zählen nie als Arbeitszeit. Die feste Pause
  (Mitarbeiter, sonst global) wird als Mindestpause abgezogen, wenn die
  Anwesenheit länger als 'zeit_pause_ab_stunden' ist. Feste Pause 0 =
  kein automatischer Abzug.
"""

import datetime
from decimal import Decimal

ARTEN = {"kommt": "Kommt", "geht": "Geht", "pause_an": "Anfang Pause",
         "pause_ende": "Ende Pause"}
ABWESENHEITEN = {"urlaub": "Urlaub", "krank": "Krank",
                 "sonder": "Sonderurlaub", "frei": "Freizeitausgleich",
                 "schule": "Berufsschule / Fortbildung"}
WOCHENTAGE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def verrechnungssatz(db, settings, mitarbeiter_id):
    """(13.5) Abrechnungs-Stundensatz (Verrechnungssatz): Mitarbeiter vor
    Arbeitsgruppe vor globalem Satz (Firmenstamm → Zeiterfassung)."""
    def d(v):
        try:
            return Decimal(str(v).replace(",", ".")) \
                if v not in (None, "") else None
        except Exception:
            return None
    if mitarbeiter_id:
        ma = db.one("SELECT stundensatz, gruppe1_id, gruppe2_id FROM "
                    "mitarbeiter WHERE id=%s", (mitarbeiter_id,))
        if ma:
            s = d(ma.get("stundensatz"))
            if s is not None:
                return s
            for gid in (ma.get("gruppe1_id"), ma.get("gruppe2_id")):
                if gid:
                    gs = d(db.value("SELECT stundensatz FROM arbeitsgruppen "
                                    "WHERE id=%s", (gid,)))
                    if gs is not None:
                        return gs
    return d(settings.get("zeit_stundensatz")) or Decimal("0")

BUNDESLAENDER = {
    "BW": "Baden-Württemberg", "BY": "Bayern", "BE": "Berlin",
    "BB": "Brandenburg", "HB": "Bremen", "HH": "Hamburg", "HE": "Hessen",
    "MV": "Mecklenburg-Vorpommern", "NI": "Niedersachsen",
    "NW": "Nordrhein-Westfalen", "RP": "Rheinland-Pfalz", "SL": "Saarland",
    "SN": "Sachsen", "ST": "Sachsen-Anhalt", "SH": "Schleswig-Holstein",
    "TH": "Thüringen",
}

ARBEITSTAGE_OPTIONEN = [("12345", "Mo–Fr (5 Tage)"),
                        ("123456", "Mo–Sa (6 Tage)"),
                        ("1234", "Mo–Do (4 Tage)"),
                        ("1234567", "Mo–So (7 Tage)")]


# ---------------------------------------------------------------------------
# (11.0) Zeitumstellung (Sommer-/Winterzeit)
# ---------------------------------------------------------------------------
def _letzter_sonntag(jahr, monat):
    d = datetime.date(jahr, monat, 31)
    while d.month != monat:
        d -= datetime.timedelta(days=1)
    while d.weekday() != 6:
        d -= datetime.timedelta(days=1)
    return d


def zeitumstellung_hinweis(datum):
    """Liefert einen Hinweistext, wenn an diesem Tag in Mitteleuropa die Uhr
    umgestellt wird (Sommerzeit beginnt Ende März, endet Ende Oktober), sonst
    ''. An diesen Tagen stimmen aus Stempelzeiten berechnete Dauern über die
    Umstellung hinweg nicht automatisch – bitte prüfen."""
    if not datum:
        return ""
    if datum == _letzter_sonntag(datum.year, 3):
        return ("Heute beginnt die Sommerzeit (Uhr 2:00 → 3:00 vorgestellt). "
                "Eine Nachtschicht über die Umstellung ist 1 Stunde kürzer "
                "als die reine Stempeldifferenz – bitte prüfen.")
    if datum == _letzter_sonntag(datum.year, 10):
        return ("Heute endet die Sommerzeit (Uhr 3:00 → 2:00 zurückgestellt). "
                "Eine Nachtschicht über die Umstellung ist 1 Stunde länger "
                "als die reine Stempeldifferenz – bitte prüfen.")
    return ""


# ---------------------------------------------------------------------------
# Feiertage
# ---------------------------------------------------------------------------
def ostersonntag(jahr):
    """Gaußsche Osterformel (gregorianisch, Algorithmus nach Meeus)."""
    a = jahr % 19
    b, c = divmod(jahr, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    monat, tag = divmod(h + l_ - 7 * m + 114, 31)
    return datetime.date(jahr, monat, tag + 1)


def feiertage(jahr, land="", maria_himmelfahrt_by=False):
    """Gesetzliche Feiertage {datum: name} für ein Bundesland
    (landesweit geltende; Feiertage einzelner Gemeinden nur optional)."""
    D = datetime.date
    ostern = ostersonntag(jahr)
    t = datetime.timedelta
    f = {
        D(jahr, 1, 1): "Neujahr",
        ostern - t(days=2): "Karfreitag",
        ostern + t(days=1): "Ostermontag",
        D(jahr, 5, 1): "Tag der Arbeit",
        ostern + t(days=39): "Christi Himmelfahrt",
        ostern + t(days=50): "Pfingstmontag",
        D(jahr, 10, 3): "Tag der Deutschen Einheit",
        D(jahr, 12, 25): "1. Weihnachtstag",
        D(jahr, 12, 26): "2. Weihnachtstag",
    }
    land = (land or "").upper()
    if land in ("BW", "BY", "ST"):
        f[D(jahr, 1, 6)] = "Heilige Drei Könige"
    if (land == "BE" and jahr >= 2019) or (land == "MV" and jahr >= 2023):
        f[D(jahr, 3, 8)] = "Internationaler Frauentag"
    if land == "BB":
        f[ostern] = "Ostersonntag"
        f[ostern + t(days=49)] = "Pfingstsonntag"
    if land in ("BW", "BY", "HE", "NW", "RP", "SL"):
        f[ostern + t(days=60)] = "Fronleichnam"
    if land == "SL" or (land == "BY" and maria_himmelfahrt_by):
        f[D(jahr, 8, 15)] = "Mariä Himmelfahrt"
    if land == "TH" and jahr >= 2019:
        f[D(jahr, 9, 20)] = "Weltkindertag"
    if land in ("BB", "MV", "SN", "ST", "TH") or \
            (land in ("HB", "HH", "NI", "SH") and jahr >= 2018):
        f[D(jahr, 10, 31)] = "Reformationstag"
    if jahr == 2017:
        f[D(jahr, 10, 31)] = "Reformationstag"
    if land in ("BW", "BY", "NW", "RP", "SL"):
        f[D(jahr, 11, 1)] = "Allerheiligen"
    if land == "SN":
        # Mittwoch vor dem 23. November
        d = D(jahr, 11, 22)
        while d.weekday() != 2:
            d -= t(days=1)
        f[d] = "Buß- und Bettag"
    return f


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------
def rfid_normalisieren(text):
    """Kartennummer vereinheitlichen (Leerzeichen, Groß/Klein, führende
    Nullen), damit verschiedene Leser-Einstellungen passen."""
    t = "".join((text or "").split()).upper()
    t = t.lstrip("0")
    return t or ("0" if text and text.strip() else "")


def fmt_std(minuten, vorzeichen=False):
    """Minuten -> 'h:mm' (z.B. 8:30, -1:15)."""
    if minuten is None:
        return ""
    minuten = int(round(minuten))
    v = "-" if minuten < 0 else ("+" if vorzeichen and minuten > 0 else "")
    h, m = divmod(abs(minuten), 60)
    return f"{v}{h}:{m:02d}"


def fmt_tage(v):
    """Tage mit Komma, z.B. 2 / 2,5 / 1,33."""
    v = Decimal(str(v or 0))
    if v == v.to_integral():
        return str(int(v))
    t = f"{v:.2f}".rstrip("0").rstrip(".")
    return t.replace(".", ",")


def fmt_dezimal(minuten):
    return f"{minuten / 60:.2f}".replace(".", ",")


def pause_aus_gruppen(gruppen, ma):
    """(10.3) Feste Pause (Minuten) aus den Arbeitsgruppen eines
    Mitarbeiters. 'gruppen' ist ein dict {id: gruppen_row}. Ist der
    Mitarbeiter in zwei Gruppen mit Pausenvorgabe, gilt die längere Pause;
    None, wenn keine Gruppe eine Pause vorgibt."""
    if not ma:
        return None
    werte = []
    for gid in (ma.get("gruppe1_id"), ma.get("gruppe2_id")):
        g = gruppen.get(gid) if gid else None
        if g and g.get("pause_minuten") not in (None, ""):
            werte.append(int(g["pause_minuten"]))
    return max(werte) if werte else None


def regeln(settings, ma, datum=None, modelle=None, gruppen_pause=None):
    """Wochenstunden, Arbeitstage, Pause (und Soll je Wochentag) für einen
    Mitarbeiter: Wert des Arbeitszeitmodells, das am 'datum' gilt, sonst
    Mitarbeiterwert, sonst Arbeitsgruppe (gruppen_pause), sonst global aus
    dem Firmenstamm."""
    if modelle and datum is not None:
        m = modell_am(modelle, datum)
        if m is not None:
            ma = dict(ma or {}, **{k: m.get(k) for k in MODELL_FELDER})

    def wert(feld, key, default):
        v = ma.get(feld) if ma else None
        if v is None or v == "":
            v = settings.get(key)
        return default if v in (None, "") else v
    woche = Decimal(str(wert("wochenstunden", "zeit_wochenstunden", "40"))
                    .replace(",", "."))
    tage = str(wert("arbeitstage", "zeit_arbeitstage", "12345"))
    tage_set = {int(c) - 1 for c in tage if c.isdigit() and "1" <= c <= "7"}
    if not tage_set:
        tage_set = {0, 1, 2, 3, 4}
    # Pause: Modell/Mitarbeiter -> Arbeitsgruppe -> Firmenstamm
    pm = ma.get("pause_minuten") if ma else None
    if pm in (None, "") and gruppen_pause is not None:
        pm = gruppen_pause
    if pm in (None, ""):
        pm = settings.get("zeit_pause_minuten")
    pause = int(pm) if str(pm).strip() not in ("", "None") else 30
    soll_je_tag = soll_tage_lesen(ma.get("soll_tage") if ma else None)
    if soll_je_tag:
        tage_set = {i for i, v in enumerate(soll_je_tag) if v > 0} or tage_set
        woche = Decimal(sum(soll_je_tag)) / 60
    ab = Decimal(str(settings.get("zeit_pause_ab_stunden") or "6")
                 .replace(",", "."))
    try:
        max_h = Decimal(str(settings.get("zeit_max_schicht_stunden") or "12")
                        .replace(",", "."))
    except Exception:
        max_h = Decimal(12)
    return {"wochen_min": int(woche * 60), "tage": tage_set,
            "tages_soll": int(round(woche * 60 / len(tage_set))),
            "soll_je_tag": soll_je_tag,
            "pause_min": pause, "pause_ab_min": int(ab * 60),
            "ueber_mitternacht": bool(int(ma.get("ueber_mitternacht") or 0))
            if ma else False,
            "max_schicht_min": int(max_h * 60)}


# ---------------------------------------------------------------------------
# Tagesauswertung
# ---------------------------------------------------------------------------
def tag_auswerten(stempel, jetzt=None):
    """stempel: Liste (zeitpunkt, art), beliebig sortiert, alle vom selben
    Arbeitstag (bei Schichten über Mitternacht auch Zeitpunkte des
    Folgetags). jetzt: bei laufender Anwesenheit die aktuelle Zeit (offene
    Anwesenheit zählt bis jetzt). Liefert dict mit anwesend, pause
    (Minuten), kommt, geht, status (abwesend/anwesend/pause), seit (Beginn
    der laufenden Anwesenheit), je_datum (gearbeitete Minuten je
    Kalendertag) und fehler (Liste)."""
    stempel = sorted(stempel, key=lambda s: s[0])
    anwesend = 0
    pause = 0
    fehler = []
    status = "abwesend"
    seit = None           # Beginn der laufenden Anwesenheit
    pause_seit = None
    abschnitt = None      # Beginn des laufenden Arbeitsabschnitts
    je_datum = {}
    segmente = []         # Arbeitsabschnitte (von, bis)
    pausen = []           # Pausenabschnitte (von, bis)
    einsaetze = []        # (9.7) Kommt..Geht-Blöcke (von, bis)
    luecken = []          # (9.7) Unterbrechungen Geht..Kommt in Minuten
    erster = letzter = None
    for zp, art in stempel:
        if art == "kommt":
            if status != "abwesend":
                fehler.append(f"{zp:%H:%M} Kommt ohne vorheriges Geht")
                continue
            if letzter is not None and zp > letzter:
                luecken.append(_minuten(letzter, zp))
            status, seit, abschnitt = "anwesend", zp, zp
            erster = erster or zp
        elif art == "geht":
            if status == "abwesend":
                fehler.append(f"{zp:%H:%M} Geht ohne Kommt")
                continue
            if status == "pause":
                pause += _minuten(pause_seit, zp)
                pausen.append((pause_seit, zp))
            else:
                _verteilen(je_datum, abschnitt, zp)
                segmente.append((abschnitt, zp))
            anwesend += _minuten(seit, zp)
            einsaetze.append((seit, zp))
            status, seit, pause_seit, abschnitt = "abwesend", None, None, None
            letzter = zp
        elif art == "pause_an":
            if status != "anwesend":
                fehler.append(f"{zp:%H:%M} Pause ohne Anwesenheit")
                continue
            _verteilen(je_datum, abschnitt, zp)
            segmente.append((abschnitt, zp))
            status, pause_seit = "pause", zp
        elif art == "pause_ende":
            if status != "pause":
                fehler.append(f"{zp:%H:%M} Pausenende ohne Pausenanfang")
                continue
            pause += _minuten(pause_seit, zp)
            pausen.append((pause_seit, zp))
            status, pause_seit, abschnitt = "anwesend", None, zp
    offen = status != "abwesend"
    laufend_seit = seit
    if offen:
        if jetzt is not None:
            ende = jetzt
            if status == "pause":
                pause += _minuten(pause_seit, ende)
                pausen.append((pause_seit, ende))
            else:
                _verteilen(je_datum, abschnitt, ende)
                segmente.append((abschnitt, ende))
            anwesend += _minuten(seit, ende)
            einsaetze.append((seit, ende))
        else:
            fehler.append("Geht fehlt")
            if seit is not None:
                einsaetze.append((seit, None))
    return {"anwesend": anwesend, "pause": pause, "kommt": erster,
            "geht": letzter, "status": status, "offen": offen,
            "seit": laufend_seit, "je_datum": je_datum, "fehler": fehler,
            "segmente": [x for x in segmente if x[0] and x[1] > x[0]],
            "pausen": [x for x in pausen if x[0] and x[1] > x[0]],
            "einsaetze": einsaetze, "luecken": luecken}


def _verteilen(je_datum, von, bis):
    """Minuten von..bis auf die Kalendertage verteilen."""
    if von is None or bis is None or bis <= von:
        return
    t = von
    while t < bis:
        mitternacht = datetime.datetime.combine(
            t.date() + datetime.timedelta(days=1), datetime.time())
        ende = min(bis, mitternacht)
        je_datum[t.date()] = je_datum.get(t.date(), 0) + _minuten(t, ende)
        t = ende


def schichten_zuordnen(stempel, r):
    """Ordnet Stempelungen ihrem Arbeitstag zu.
    stempel: Liste (zeitpunkt, art). Ohne 'über Mitternacht' ist der
    Arbeitstag das Kalenderdatum. Mit: Stempelungen nach Mitternacht, die
    eine am Vortag begonnene Schicht fortsetzen (Geht, Pause), gehören
    zum Tag des 'Kommt' – sofern die Schicht nicht länger als die
    Höchstdauer ist. Liefert ({arbeitstag: [(zp, art)]},
    {arbeitstag: [Hinweise zu Fehlern]})."""
    tage, zusatz = {}, {}
    stempel = sorted(stempel, key=lambda s: s[0])
    if not r.get("ueber_mitternacht"):
        for zp, art in stempel:
            tage.setdefault(zp.date(), []).append((zp, art))
        return tage, zusatz
    grenze = datetime.timedelta(minutes=r["max_schicht_min"])
    status, start = "abwesend", None
    for zp, art in stempel:
        tag = zp.date()
        if status != "abwesend" and start is not None and \
                start.date() < tag:
            if art != "kommt" and zp - start <= grenze:
                tag = start.date()          # Schicht vom Vortag geht weiter
            else:
                if art != "kommt":
                    zusatz.setdefault(tag, []).append(
                        f"{zp:%H:%M} {ARTEN.get(art, art)}: letztes Kommt "
                        f"({start:%d.%m. %H:%M}) liegt mehr als "
                        f"{r['max_schicht_min'] // 60} Std. zurück – Geht "
                        f"bzw. Kommt vergessen?")
                status, start = "abwesend", None   # Vortag: 'Geht fehlt'
        tage.setdefault(tag, []).append((zp, art))
        if art == "kommt" and status == "abwesend":
            status, start = "anwesend", zp
        elif art == "geht" and status != "abwesend":
            status, start = "abwesend", None
        elif art == "pause_an" and status == "anwesend":
            status = "pause"
        elif art == "pause_ende" and status == "pause":
            status = "anwesend"
    return tage, zusatz


def laeuft_noch(t, r, jetzt, datum):
    """Ist die offene Anwesenheit des Arbeitstags 'datum' noch gültig
    (heute, oder bei 'über Mitternacht' eine Schicht vom Vortag innerhalb
    der Höchstdauer)?"""
    if jetzt is None or not t["offen"]:
        return False
    if datum == jetzt.date():
        return True
    return bool(r.get("ueber_mitternacht") and t.get("seit") and
                datum == jetzt.date() - datetime.timedelta(days=1) and
                datetime.timedelta(0) <= jetzt - t["seit"] <=
                datetime.timedelta(minutes=r["max_schicht_min"]))


def _minuten(von, bis):
    if von is None or bis is None or bis < von:
        return 0
    return int((bis - von).total_seconds() // 60)


RUHEPAUSE_MIN = 15      # § 4 ArbZG: Pausen zählen ab 15 Minuten


def netto(tag, r):
    """(Arbeitszeit netto, abgezogene Pause) in Minuten.
    (9.7) Unterbrechungen zwischen Geht und nächstem Kommt (mindestens
    15 Minuten) werden auf die feste Mindestpause angerechnet – wer
    vormittags und nachmittags je 4 Stunden arbeitet, hat seine Pause
    dazwischen gehabt."""
    gestempelt = tag["pause"]
    brutto = tag["anwesend"]
    abzug = gestempelt
    if r["pause_min"] > 0 and brutto > r["pause_ab_min"]:
        luecken = sum(x for x in tag.get("luecken", [])
                      if x >= RUHEPAUSE_MIN)
        fehlt = max(0, r["pause_min"] - gestempelt - luecken)
        abzug = gestempelt + fehlt
    return max(0, brutto - abzug), abzug


# ---------------------------------------------------------------------------
# Datenbank
# ---------------------------------------------------------------------------
def stempel_laden(db, ma_id, von, bis):
    """{datum: [(zeitpunkt, art)]} für von..bis (inklusive)."""
    rows = db.query(
        "SELECT zeitpunkt, art FROM stempelungen WHERE mitarbeiter_id=%s "
        "AND zeitpunkt >= %s AND zeitpunkt < %s ORDER BY zeitpunkt, id",
        (ma_id, datetime.datetime.combine(von, datetime.time()),
         datetime.datetime.combine(bis + datetime.timedelta(days=1),
                                   datetime.time())))
    tage = {}
    for r in rows:
        tage.setdefault(r["zeitpunkt"].date(), []).append(
            (r["zeitpunkt"], r["art"]))
    return tage


def stempel_roh(db, ma_id, von, bis):
    """[(zeitpunkt, art)] von 0:00 am Tag 'von' bis 24:00 am Tag 'bis'."""
    return [(r["zeitpunkt"], r["art"]) for r in db.query(
        "SELECT zeitpunkt, art FROM stempelungen WHERE mitarbeiter_id=%s "
        "AND zeitpunkt >= %s AND zeitpunkt < %s ORDER BY zeitpunkt, id",
        (ma_id, datetime.datetime.combine(von, datetime.time()),
         datetime.datetime.combine(bis + datetime.timedelta(days=1),
                                   datetime.time())))]


def arbeitstage_laden(db, ma_id, von, bis, r):
    """Stempelungen je Arbeitstag für von..bis (Schichten über
    Mitternacht berücksichtigt). Liefert (tage, zusatz_hinweise)."""
    if not r.get("ueber_mitternacht"):
        return stempel_laden(db, ma_id, von, bis), {}
    eins = datetime.timedelta(days=1)
    tage, zusatz = schichten_zuordnen(
        stempel_roh(db, ma_id, von - eins, bis + eins), r)
    return ({d: v for d, v in tage.items() if von <= d <= bis},
            {d: v for d, v in zusatz.items() if von <= d <= bis})


def abwesenheiten_laden(db, ma_id, von, bis, mit_anteil=False):
    """{datum: art} bzw. mit_anteil=True {datum: (art, anteil)} – anteil
    0,5 = halber Tag."""
    rows = db.query(
        "SELECT datum, art, anteil FROM abwesenheiten WHERE "
        "mitarbeiter_id=%s AND datum BETWEEN %s AND %s", (ma_id, von, bis))
    if mit_anteil:
        return {r["datum"]: (r["art"], Decimal(str(r["anteil"])))
                for r in rows}
    return {r["datum"]: r["art"] for r in rows}


def zeitraum_auswerten(db, settings, ma, von, bis, jetzt=None):
    """Tagesliste und Summen für einen Zeitraum. Soll und Pause richten
    sich nach dem Arbeitszeitmodell, das am jeweiligen Tag gilt."""
    r = regeln(settings, ma)
    modelle = modelle_laden(db, ma["id"])
    jetzt = jetzt or datetime.datetime.now()
    heute = jetzt.date()
    stempel, zusatz = arbeitstage_laden(db, ma["id"], von, bis, r)
    abw_roh = abwesenheiten_laden(db, ma["id"], von, bis, mit_anteil=True)
    abw = {d: a for d, (a, _) in abw_roh.items()}
    anteil = {d: t for d, (_, t) in abw_roh.items()}
    buchungen = {}
    for b in stundenbuchungen_laden(db, ma["id"], von, bis):
        buchungen.setdefault(b["datum"], []).append(b)
    ft = {}
    for j in range(von.year, bis.year + 2):
        ft.update(feiertage(j, settings.get("zeit_bundesland"),
                            settings.get("zeit_maria_himmelfahrt") == "1"))
    eintritt, austritt = ma.get("eintritt"), ma.get("austritt")
    # (9.2) Schichten: Arbeitsbeginn/-ende
    gruppen = {g["id"]: g for g in arbeitsgruppen(db, False)}
    gp = pause_aus_gruppen(gruppen, ma)      # (10.3) feste Pause der Gruppe
    vorgaben = schicht_vorgaben(settings, ma, gruppen) \
        if schichten_aktiv(settings) else None
    # (9.7) Dienstplan und Einspringen
    plan = {d: e for (_m, d), e in dienstplan_laden(db, [ma["id"]], von,
                                                     bis).items()}
    nach_plan = bool(int(ma.get("nach_dienstplan") or 0))
    plan_basis = None
    if nach_plan and schichten_aktiv(settings) and plan:
        s2 = dict(settings, zeit_schicht_standard=settings.get(
            "zeit_schicht_standard") or "auto")
        plan_basis = schicht_vorgaben(s2, dict(ma, schicht=ma.get(
            "schicht") or "auto"), gruppen)
    eingesprungen = eingesprungen_tage(db, ma["id"], von, bis)
    tage = []
    s = {"ist": 0, "soll": 0, "pause": 0, "samstag": 0, "sonntag": 0,
         "feiertag": 0, "nacht": 0, "fehler": 0, "abw": {}, "buchungen": 0,
         "auszahlung": 0, "verspaetungen": 0, "verspaetung_min": 0,
         "rahmen_abzug": 0, "einspringen": 0, "einspring_tage": 0,
         "plan_fehlt": 0, "plan_zusaetzlich": 0}
    d = von
    while d <= bis:
        wt = d.weekday()
        rd = regeln(settings, ma, d, modelle, gruppen_pause=gp)
        st = stempel.get(d, [])
        t = tag_auswerten(st)
        laeuft = laeuft_noch(t, r, jetzt, d)
        if laeuft:
            t = tag_auswerten(st, jetzt)
        beschaeftigt = (not eintritt or d >= eintritt) and \
            (not austritt or d <= austritt)
        soll = soll_fuer(rd, wt) if (beschaeftigt and d not in ft) else 0
        hinweise = []
        pe = plan.get(d)
        vorg_d = vorgaben
        plan_zeiten = dienst_zeiten(pe, settings, ma, gruppen) if pe \
            else (None, None)
        if nach_plan and pe and beschaeftigt and d not in ft:
            # Soll und Arbeitsbeginn/-ende laut Dienstplan
            soll = dienst_minuten(*plan_zeiten, rd) \
                if pe["schicht"] != "frei" else 0
            if plan_zeiten[0] and schichten_aktiv(settings):
                vorg_d = _plan_vorgaben(plan_basis or vorgaben,
                                        *plan_zeiten)
        if vorg_d and soll > 0 and t["kommt"]:
            t = schichtrahmen(t, vorg_d, settings, d)
            if t.get("schicht_text"):
                hinweise.append(t["schicht_text"])
            if t.get("verspaetung"):
                s["verspaetungen"] += 1
                s["verspaetung_min"] += t["verspaetung"]
            s["rahmen_abzug"] += t.get("rahmen_abzug", 0)
        ist, abzug = netto(t, rd)
        if d in ft:
            hinweise.append(ft[d])
        if d in abw:
            # halber Tag: Soll halbiert, sonst Soll 0
            soll = int(round(soll * (1 - float(anteil[d]))))
            text = ABWESENHEITEN.get(abw[d], abw[d])
            if anteil[d] < 1:
                text += " (½ Tag)"
            hinweise.append(text)
            s["abw"][abw[d]] = s["abw"].get(abw[d], 0) + anteil[d]
        folgetag = bool(t["geht"] and t["geht"].date() > d) or bool(
            laeuft and d < heute)
        if folgetag and not t["fehler"]:
            hinweise.append("Schicht über Mitternacht")
        # (9.7) mehrere Einsätze am Tag (z. B. Einspringen)
        ein = [e for e in t.get("einsaetze") or [] if e[0]]
        if len(ein) > 1:
            hinweise.append(f"{len(ein)} Einsätze: " + ", ".join(
                f"{a_:%H:%M}–{e_:%H:%M}" if e_ else f"{a_:%H:%M}–…"
                for a_, e_ in ein))
        # (9.7) Plan/Ist
        if pe:
            if pe["schicht"] == "frei":
                if t["kommt"]:
                    hinweise.append("laut Dienstplan frei – zusätzlich "
                                    "gekommen")
                    s["plan_zusaetzlich"] += 1
            elif not t["kommt"] and d < heute and d not in abw and \
                    beschaeftigt and d not in ft:
                hinweise.append(f"laut Dienstplan "
                                f"{dienst_text(pe, plan_zeiten)} – nicht "
                                f"erschienen")
                s["plan_fehlt"] += 1
        einspr = ist if (d in eingesprungen and ist > 0) else 0
        if d in eingesprungen:
            hinweise.append("Eingesprungen")
            if einspr:
                s["einspringen"] += einspr
                s["einspring_tage"] += 1
        hinweise += t["fehler"] + zusatz.get(d, [])
        buchung = 0
        for b in buchungen.get(d, []):
            buchung += int(b["minuten"])
            if b["art"] == "auszahlung":
                s["auszahlung"] += -int(b["minuten"])
            hinweise.append(f"Stundenkonto {fmt_std(b['minuten'], True)} "
                            f"({BUCHUNGSARTEN.get(b['art'], b['art'])}"
                            + (f": {b['bemerkung']}" if b["bemerkung"]
                               else "") + ")")
        fehlerhaft = bool(t["fehler"] or zusatz.get(d))
        if fehlerhaft:
            s["fehler"] += 1
        nacht = min(ist, nacht_minuten(t["segmente"], settings))
        tag = {"datum": d, "wochentag": WOCHENTAGE[wt], "kommt": t["kommt"],
               "geht": t["geht"], "pause": abzug, "ist": ist, "soll": soll,
               "saldo": ist - soll, "feiertag": ft.get(d),
               "abwesenheit": abw.get(d), "hinweis": "; ".join(hinweise),
               "fehler": fehlerhaft, "status": t["status"],
               "laeuft": laeuft, "folgetag": folgetag,
               "zukunft": d > heute, "nacht": nacht, "buchung": buchung,
               "segmente": t["segmente"], "pausen": t["pausen"],
               "pause_gestempelt": t["pause"],
               "schicht": t.get("schicht"),
               "verspaetung": t.get("verspaetung", 0),
               "rahmen_abzug": t.get("rahmen_abzug", 0),
               "plan": pe, "plan_text": dienst_text(pe, plan_zeiten),
               "einspringen": einspr}
        tage.append(tag)
        s["ist"] += ist
        s["soll"] += soll
        s["pause"] += abzug
        s["nacht"] += nacht
        s["buchungen"] += buchung
        # Samstag/Sonntag/Feiertag nach Kalendertag (Schichten über
        # Mitternacht anteilig)
        roh = sum(t["je_datum"].values())
        for dd, minuten in (t["je_datum"].items() if roh else
                            [(d, 1)]):
            teil = ist * minuten / (roh or 1)
            if dd in ft:
                s["feiertag"] += teil
            elif dd.weekday() == 5:
                s["samstag"] += teil
            elif dd.weekday() == 6:
                s["sonntag"] += teil
        d += datetime.timedelta(days=1)
    for k in ("samstag", "sonntag", "feiertag"):
        s[k] = int(round(s[k]))
    s["saldo"] = s["ist"] - s["soll"]
    s["ueberstunden"] = max(0, s["saldo"])
    return tage, s


def monat_grenzen(jahr, monat):
    von = datetime.date(jahr, monat, 1)
    naechster = datetime.date(jahr + monat // 12, monat % 12 + 1, 1)
    return von, naechster - datetime.timedelta(days=1)


def saldo_bis(db, settings, ma, bis):
    """Stundenkonto bis einschließlich 'bis': Stand des letzten
    Monatsabschlusses (sonst Übertrag ab Eintritt bzw. erster Stempelung)
    plus Saldo und Stundenkonto-Buchungen der Tage danach."""
    abschl = letzter_abschluss(db, ma["id"], bis)
    if abschl:
        start = monat_grenzen(abschl["monat"].year,
                              abschl["monat"].month)[1] + \
            datetime.timedelta(days=1)
        basis = int(abschl["saldo_ende"])
    else:
        start = ma.get("eintritt")
        erste = db.value("SELECT MIN(zeitpunkt) FROM stempelungen WHERE "
                         "mitarbeiter_id=%s", (ma["id"],))
        if erste and (not start or erste.date() < start):
            start = erste.date()
        erste_b = _sicher(lambda: db.value(
            "SELECT MIN(datum) FROM stundenbuchungen WHERE mitarbeiter_id=%s",
            (ma["id"],)))
        if erste_b and (not start or erste_b < start):
            start = erste_b
        basis = int(ma.get("uebertrag_minuten") or 0)
    if not start or start > bis:
        return basis
    _, s = zeitraum_auswerten(db, settings, ma, start, bis)
    return basis + s["saldo"] + s["buchungen"]


def stand(db, settings, ma, jetzt=None):
    """Kennzahlen für die Anzeige am Terminal: heute, Monat bis heute,
    Saldo bis gestern."""
    jetzt = jetzt or datetime.datetime.now()
    heute = jetzt.date()
    von, _ = monat_grenzen(heute.year, heute.month)
    tage, s = zeitraum_auswerten(db, settings, ma, von, heute, jetzt)
    gestern = heute - datetime.timedelta(days=1)
    heute_tag = tage[-1]
    monat_bis_gestern = s["saldo"] - heute_tag["saldo"]
    heute_ist = heute_tag["ist"]
    info = status_info(db, ma, jetzt, settings)
    if regeln(settings, ma)["ueber_mitternacht"]:
        # Schicht vom Vortag, die heute endet oder noch läuft, gehört für
        # die Anzeige 'heute' dazu
        v, _ = zeitraum_auswerten(db, settings, ma, gestern, gestern, jetzt)
        if v and v[0]["folgetag"]:
            heute_ist += v[0]["ist"]
    gesamt = saldo_bis(db, settings, ma, gestern)
    return {"monat_ist": s["ist"], "heute_ist": heute_ist,
            "monat_saldo": monat_bis_gestern,
            "gesamt_saldo": gesamt, "ampel": ampel(settings, ma, gesamt),
            "status": info["status"]}


def stempel_text(stempel, arbeitstag, offen=False):
    """Stempelungen eines Arbeitstags als lesbarer Text, z.B.
    'Kommt 07:58 · Pause 12:00–12:30 · Geht 16:45'. Zeitpunkte am
    Folgetag (Schicht über Mitternacht) bekommen '(+1)'."""
    def uhr(zp):
        t = f"{zp:%H:%M}"
        if zp.date() > arbeitstag:
            t += " (+1)"
        return t
    teile = []
    pause_an = None
    for zp, art in sorted(stempel, key=lambda s: s[0]):
        if art == "pause_an":
            pause_an = zp
        elif art == "pause_ende":
            if pause_an is not None:
                teile.append(f"Pause {uhr(pause_an)}–{uhr(zp)}")
            else:
                teile.append(f"Ende Pause {uhr(zp)}")
            pause_an = None
        else:
            if pause_an is not None:     # Pause ohne Ende (z.B. Geht)
                teile.append(f"Pause ab {uhr(pause_an)}")
                pause_an = None
            teile.append(f"{ARTEN.get(art, art)} {uhr(zp)}")
    if pause_an is not None:
        teile.append(f"Pause seit {uhr(pause_an)}" if offen
                     else f"Pause ab {uhr(pause_an)}")
    if offen and pause_an is None:
        teile.append("(läuft)")
    return " · ".join(teile)


def monatsuebersicht(db, settings, ma, jetzt=None):
    """Monatsübersicht für das Terminal: alle Tage vom Monatsersten bis
    heute mit allen Stempelzeiten, Arbeitszeit (netto), Pause, Soll und
    Saldo sowie die Monatssummen und das Stundenkonto.

    Liefert dict: tage (Liste), ist, pause, soll, saldo (Monat bis heute),
    soll_bis_gestern, saldo_bis_gestern (ohne den laufenden Tag),
    heute_ist, heute_soll, gesamt_saldo (Stundenkonto inkl. Übertrag bis
    gestern), gesamt_inkl_heute, fehler (Tage mit Stempelfehlern),
    monat (date des Monatsersten)."""
    jetzt = jetzt or datetime.datetime.now()
    heute = jetzt.date()
    von, _ = monat_grenzen(heute.year, heute.month)
    r = regeln(settings, ma)
    tage, s = zeitraum_auswerten(db, settings, ma, von, heute, jetzt)
    stempel, _ = arbeitstage_laden(db, ma["id"], von, heute, r)
    liste = []
    for t in tage:
        d = t["datum"]
        st = [x for x in stempel.get(d, []) if x[0] <= jetzt]
        roh = tag_auswerten(st, jetzt if t["laeuft"] else None)
        liste.append(dict(
            t, stempel=st,
            stempel_text=stempel_text(st, d, t["laeuft"]),
            pause_gestempelt=roh["pause"],
            mindestpause=t["pause"] > roh["pause"],
            wochenende=d.weekday() >= 5, heute=d == heute))
    heute_tag = liste[-1] if liste else None
    gestern = heute - datetime.timedelta(days=1)
    gesamt = saldo_bis(db, settings, ma, gestern)
    h_soll = heute_tag["soll"] if heute_tag else 0
    h_saldo = heute_tag["saldo"] if heute_tag else 0
    return {"monat": von, "tage": liste, "ist": s["ist"],
            "pause": s["pause"], "soll": s["soll"], "saldo": s["saldo"],
            # der laufende Tag ist noch nicht abgeschlossen
            "soll_bis_gestern": s["soll"] - h_soll,
            "saldo_bis_gestern": s["saldo"] - h_saldo,
            "fehler": s["fehler"], "buchungen": s["buchungen"],
            "nacht": s["nacht"],
            "heute_ist": heute_tag["ist"] if heute_tag else 0,
            "heute_soll": heute_tag["soll"] if heute_tag else 0,
            "gesamt_saldo": gesamt,
            "ampel": ampel(settings, ma, gesamt),
            "einspringen": s.get("einspringen", 0),
            "plan_vorschau": plan_vorschau(db, settings, ma, heute)
            if str(settings.get("dienstplan_terminal", "1")) != "0" else [],
            "gesamt_inkl_heute": gesamt + (heute_tag["saldo"]
                                           if heute_tag else 0)}


def status_info(db, ma, jetzt=None, settings=None):
    """Aktueller Stand eines Mitarbeiters (ma = dict oder ID): status,
    t (Tagesauswertung der laufenden bzw. heutigen Schicht), stempel,
    ueberlang (offene Schicht vom Vortag älter als die Höchstdauer)."""
    jetzt = jetzt or datetime.datetime.now()
    heute = jetzt.date()
    if not isinstance(ma, dict):
        ma = db.one("SELECT * FROM mitarbeiter WHERE id=%s", (ma,)) or \
            {"id": ma}
    if settings is None:
        settings = db.settings() if hasattr(db, "settings") else {}
    r = regeln(settings, ma)
    gestern = heute - datetime.timedelta(days=1)
    ueberlang = False
    if r["ueber_mitternacht"]:
        roh = [s for s in stempel_roh(db, ma["id"], gestern, heute)
               if s[0] <= jetzt]
        tage, _ = schichten_zuordnen(roh, r)
        st_v = tage.get(gestern, [])
        tv = tag_auswerten(st_v)
        if laeuft_noch(tv, r, jetzt, gestern):
            t = tag_auswerten(st_v, jetzt)
            return {"status": t["status"], "t": t, "stempel": st_v,
                    "ueberlang": False, "vortag": True}
        ueberlang = tv["offen"] and bool(tv["seit"])
        st = tage.get(heute, [])
    else:
        st = stempel_laden(db, ma["id"], heute, heute).get(heute, [])
    t = tag_auswerten(st, jetzt)
    return {"status": t["status"], "t": t, "stempel": st,
            "ueberlang": ueberlang and t["status"] == "abwesend" and
            not st, "vortag": False, "seit_vortag": tv["seit"]
            if r["ueber_mitternacht"] else None,
            "max_std": r["max_schicht_min"] // 60}


def aktueller_status(db, ma_id, jetzt=None):
    return status_info(db, ma_id, jetzt)["status"]


STATUS_TEXT = {"anwesend": "Anwesend", "pause": "Pause",
               "abwesend": "Nicht anwesend"}


def anwesenheit_alle(db, settings, jetzt=None):
    """Aktueller Status aller aktiven Mitarbeiter für die Anwesenheits-
    übersicht. Liefert eine Liste von dicts (sortiert: Anwesend, Pause,
    Nicht anwesend; jeweils nach Name) mit status, seit (Zeitpunkt des
    letzten Statuswechsels), dauer (Minuten seitdem), kommt, arbeitszeit
    (netto heute, Minuten) und hinweis."""
    jetzt = jetzt or datetime.datetime.now()
    heute = jetzt.date()
    mitarbeiter = db.query("SELECT * FROM mitarbeiter WHERE aktiv=1 "
                           "ORDER BY nachname, vorname")
    stempel = {}
    for r in db.query(
            "SELECT mitarbeiter_id, zeitpunkt, art FROM stempelungen WHERE "
            "zeitpunkt >= %s AND zeitpunkt < %s ORDER BY zeitpunkt, id",
            (datetime.datetime.combine(heute, datetime.time()),
             datetime.datetime.combine(heute + datetime.timedelta(days=1),
                                       datetime.time()))):
        stempel.setdefault(r["mitarbeiter_id"], []).append(
            (r["zeitpunkt"], r["art"]))
    abw = {r["mitarbeiter_id"]: r["art"] for r in db.query(
        "SELECT mitarbeiter_id, art FROM abwesenheiten WHERE datum=%s",
        (heute,))}
    feiertag = feiertage(heute.year, settings.get("zeit_bundesland"),
                         settings.get("zeit_maria_himmelfahrt") == "1"
                         ).get(heute)
    erg = []
    gruppen = {g["id"]: g for g in arbeitsgruppen(db, False)} \
        if schichten_aktiv(settings) else {}
    for ma in mitarbeiter:
        r = regeln(settings, ma, heute, modelle_laden(db, ma["id"]))
        vortag = False
        if r["ueber_mitternacht"]:
            info = status_info(db, ma, jetzt, settings)
            st, t, vortag = info["stempel"], info["t"], info["vortag"]
        else:
            st = stempel.get(ma["id"], [])
            t = tag_auswerten(st, jetzt)
        vg = schicht_vorgaben(settings, ma, gruppen) if gruppen is not None \
            else None
        tw = schichtrahmen(t, vg, settings, (t["kommt"] or jetzt).date()) \
            if vg and t["kommt"] else t
        ist, _ = netto(tw, r)
        # Zeitpunkt des letzten gültigen Statuswechsels
        seit = None
        for zp, art in reversed(st):
            if (t["status"] == "anwesend" and art in ("kommt", "pause_ende")) \
                    or (t["status"] == "pause" and art == "pause_an") \
                    or (t["status"] == "abwesend" and art == "geht"):
                seit = zp
                break
        hinweis = []
        if t["status"] == "abwesend":
            if ma["id"] in abw:
                hinweis.append(ABWESENHEITEN.get(abw[ma["id"]],
                                                 abw[ma["id"]]))
            elif feiertag:
                hinweis.append(feiertag)
            elif seit:
                hinweis.append(f"gegangen um {seit:%H:%M}")
            elif heute.weekday() not in r["tage"]:
                hinweis.append("kein Arbeitstag")
            else:
                hinweis.append("heute noch nicht gestempelt")
        elif vortag:
            hinweis.append(f"Schicht seit gestern {t['seit']:%H:%M}"
                           if t.get("seit") else "Schicht seit gestern")
        elif ma["id"] in abw:
            hinweis.append(f"eingetragen: "
                           f"{ABWESENHEITEN.get(abw[ma['id']], abw[ma['id']])}")
        if tw.get("verspaetung"):
            hinweis.append(f"{tw['verspaetung']} Min. zu spät")
        hinweis += t["fehler"]
        erg.append({
            "id": ma["id"], "personalnr": ma["personalnr"],
            "name": f"{ma['nachname']}, {ma['vorname']}",
            "status": t["status"], "seit": seit,
            "dauer": _minuten(seit, jetzt) if seit else None,
            "kommt": t["kommt"], "arbeitszeit": ist if st else 0,
            "abwesenheit": abw.get(ma["id"]), "hinweis": "; ".join(hinweis),
            "fehler": bool(t["fehler"])})
    rang = {"anwesend": 0, "pause": 1, "abwesend": 2}
    erg.sort(key=lambda z: (rang[z["status"]], z["name"].lower()))
    return erg


def pruefen(status, art):
    """Prüft, ob die Stempelung zum aktuellen Status passt. Liefert
    Fehlermeldung oder None."""
    if art == "kommt" and status != "abwesend":
        return "Sie sind bereits eingestempelt."
    if art == "geht" and status == "abwesend":
        return "Sie sind nicht eingestempelt."
    if art == "pause_an":
        if status == "abwesend":
            return "Sie sind nicht eingestempelt."
        if status == "pause":
            return "Sie sind bereits in der Pause."
    if art == "pause_ende" and status != "pause":
        return "Sie sind nicht in der Pause."
    return None


def stempeln(db, ma_id, art, zeitpunkt=None, quelle="terminal", terminal="",
             bemerkung="", pruefung=True):
    """Speichert eine Stempelung. Bei 'geht' während der Pause wird die
    Pause automatisch beendet."""
    zeitpunkt = (zeitpunkt or datetime.datetime.now()).replace(microsecond=0)
    if art not in ARTEN:
        raise ValueError("Unbekannte Stempelart.")
    if pruefung:
        info = status_info(db, ma_id, zeitpunkt)
        status = info["status"]
        meldung = pruefen(status, art)
        if meldung and art in ("geht", "pause_an", "pause_ende") and \
                info.get("ueberlang") and info.get("seit_vortag"):
            seit = info["seit_vortag"].strftime("%d.%m. %H:%M")
            meldung = (f"Ihr letztes Kommt ({seit}) liegt mehr als "
                       f"{info['max_std']} Stunden zurück. Bitte im Büro "
                       f"melden.")
        if meldung:
            raise ValueError(meldung)
        if art == "geht" and status == "pause":
            _einfuegen(db, ma_id, "pause_ende", zeitpunkt, quelle, terminal,
                       "automatisch bei Geht")
    neu = _einfuegen(db, ma_id, art, zeitpunkt, quelle, terminal, bemerkung)
    try:
        # Auftragszeit mitführen (fehlende Tabelle/Rechte stören nicht)
        _sicher(lambda: _auftrag_beim_stempeln(db, ma_id, art, zeitpunkt))
    except Exception:
        pass
    return neu


def _einfuegen(db, ma_id, art, zeitpunkt, quelle, terminal, bemerkung):
    return db.execute(
        "INSERT INTO stempelungen (mitarbeiter_id, zeitpunkt, art, quelle, "
        "terminal, bemerkung, erstellt) VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (ma_id, zeitpunkt, art, quelle, terminal[:60], bemerkung[:200],
         datetime.datetime.now()))


def mitarbeiter_zu_rfid(db, rfid):
    norm = rfid_normalisieren(rfid)
    if not norm:
        return None
    return db.one("SELECT * FROM mitarbeiter WHERE rfid=%s AND aktiv=1",
                  (norm,))


def ma_name(ma):
    return f"{ma.get('vorname', '')} {ma.get('nachname', '')}".strip()


# ===========================================================================
# Ab Version 8.6
# ===========================================================================
MODELL_FELDER = ("wochenstunden", "arbeitstage", "pause_minuten",
                 "soll_tage")
BUCHUNGSARTEN = {"auszahlung": "Auszahlung", "korrektur": "Korrektur",
                 "kappung": "Kappung", "abbau": "Freizeitausgleich"}
ANTRAG_STATUS = {"offen": "offen", "genehmigt": "genehmigt",
                 "abgelehnt": "abgelehnt", "zurueckgezogen": "zurückgezogen",
                 "storniert": "storniert"}
ANTRAG_TYP = {"antrag": "Urlaub", "storno": "Stornierung"}
# Fehler, die nur heißen "Tabelle fehlt" bzw. "keine Rechte" (z.B. alte
# Datenbank oder Terminal-Benutzer ohne neue Rechte) -> leise übergehen
_TOLERIERT = (1142, 1143, 1146)
WARNUNGEN = []


def _sicher(funktion, ersatz=None):
    """Führt eine Abfrage auf neue Tabellen aus; fehlt die Tabelle oder das
    Recht, wird 'ersatz' geliefert und eine Warnung gemerkt."""
    try:
        return funktion()
    except Exception as exc:
        code = exc.args[0] if getattr(exc, "args", None) else None
        if code in _TOLERIERT:
            text = str(exc)
            if text not in WARNUNGEN:
                WARNUNGEN.append(text)
            return ersatz
        raise


def minuten_text(minuten):
    return fmt_std(minuten)


# ---------------------------------------------------------------------------
# Arbeitszeitmodelle (gültig ab) und Soll je Wochentag
# ---------------------------------------------------------------------------
def soll_tage_lesen(text):
    """'480,480,480,480,360,0,0' (Minuten Mo..So) -> Liste oder None."""
    if not text:
        return None
    try:
        werte = [int(v) for v in str(text).split(",")]
    except ValueError:
        return None
    return werte if len(werte) == 7 and any(werte) else None


def soll_tage_eingabe(text):
    """Eingabe 'Mo..So' in Stunden ('8,5 8,5 8,5 8,5 6 0 0' oder mit ';'
    getrennt, auch h:mm) -> '510,510,510,510,360,0,0' bzw. '' (leer)."""
    t = (text or "").strip()
    if not t:
        return ""
    teile = [x for x in t.replace(";", " ").replace("|", " ").split() if x]
    if len(teile) != 7:
        raise ValueError("Soll je Wochentag: bitte genau 7 Werte für "
                         "Mo bis So eingeben, z.B. 8,5 8,5 8,5 8,5 6 0 0")
    erg = []
    for x in teile:
        try:
            if ":" in x:
                h, m = x.split(":")
                erg.append(int(h or 0) * 60 + int(m or 0))
            else:
                erg.append(int(round(float(x.replace(",", ".")) * 60)))
        except ValueError:
            raise ValueError(f"Soll je Wochentag: '{x}' ist keine Zahl.")
    if any(v < 0 or v > 24 * 60 for v in erg):
        raise ValueError("Soll je Wochentag: Werte zwischen 0 und 24 "
                         "Stunden.")
    if not any(erg):
        return ""
    return ",".join(str(v) for v in erg)


def soll_tage_anzeige(text):
    werte = soll_tage_lesen(text)
    if not werte:
        return ""
    return " ".join(fmt_dezimal(v).replace(",00", "").rstrip("0")
                    .rstrip(",") if v else "0" for v in werte)


def soll_fuer(r, wochentag):
    """Tagessoll (Minuten) laut Regel r für einen Wochentag 0..6."""
    if r.get("soll_je_tag"):
        return r["soll_je_tag"][wochentag]
    return r["tages_soll"] if wochentag in r["tage"] else 0


def modelle_laden(db, ma_id):
    """Arbeitszeitmodelle eines Mitarbeiters, aufsteigend nach gültig ab."""
    return _sicher(lambda: db.query(
        "SELECT * FROM arbeitszeitmodelle WHERE mitarbeiter_id=%s ORDER BY "
        "gueltig_ab", (ma_id,)), []) or []


def modell_am(modelle, datum):
    """Das am 'datum' gültige Modell (vor dem ersten Modell: das erste)."""
    if not modelle:
        return None
    gueltig = modelle[0]
    for m in modelle:
        if m["gueltig_ab"] <= datum:
            gueltig = m
    return gueltig


def modell_speichern(db, ma, werte, ab, erster_tag=None):
    """Neues Arbeitszeitmodell ab 'ab'. Gibt es noch keins, wird vorher der
    bisherige Stand des Mitarbeiters als erstes Modell (ab Eintritt bzw.
    erster Stempelung) gesichert, damit die Vergangenheit unverändert
    bleibt. werte: dict mit MODELL_FELDER."""
    pruefe_offen(db, ma["id"], ab, "Arbeitszeitmodelle")
    if not modelle_laden(db, ma["id"]):
        start = erster_tag or ma.get("eintritt") or datetime.date(2000, 1, 1)
        erste = db.value("SELECT MIN(zeitpunkt) FROM stempelungen WHERE "
                         "mitarbeiter_id=%s", (ma["id"],))
        if erste and erste.date() < start:
            start = erste.date()
        if start < ab:
            db.execute(
                "INSERT INTO arbeitszeitmodelle (mitarbeiter_id, gueltig_ab, "
                "wochenstunden, arbeitstage, pause_minuten, soll_tage, "
                "bemerkung) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (ma["id"], start, ma.get("wochenstunden"),
                 ma.get("arbeitstage"), ma.get("pause_minuten"),
                 ma.get("soll_tage") or "", "bisheriger Stand"))
    db.execute(
        "REPLACE INTO arbeitszeitmodelle (mitarbeiter_id, gueltig_ab, "
        "wochenstunden, arbeitstage, pause_minuten, soll_tage, bemerkung) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (ma["id"], ab, werte.get("wochenstunden"), werte.get("arbeitstage"),
         werte.get("pause_minuten"), werte.get("soll_tage") or "",
         (werte.get("bemerkung") or "")[:200]))


def modell_loeschen(db, modell_id):
    m = db.one("SELECT * FROM arbeitszeitmodelle WHERE id=%s", (modell_id,))
    if not m:
        return None
    pruefe_offen(db, m["mitarbeiter_id"], m["gueltig_ab"],
                 "Arbeitszeitmodelle")
    db.execute("DELETE FROM arbeitszeitmodelle WHERE id=%s", (modell_id,))
    return m


def modell_text(m, settings=None):
    settings = settings or {}
    teile = []
    if soll_tage_lesen(m.get("soll_tage")):
        teile.append("Soll Mo–So: " + soll_tage_anzeige(m["soll_tage"]))
    else:
        w = m.get("wochenstunden")
        teile.append(f"{fmt_dezimal(float(w) * 60) if w is not None else '(global)'}"
                     f" Std/Woche")
        tage = m.get("arbeitstage")
        teile.append(", ".join(WOCHENTAGE[int(c) - 1] for c in tage
                               if c.isdigit()) if tage else "Tage global")
    p = m.get("pause_minuten")
    teile.append("Pause global" if p is None else
                 ("keine Pause" if p == 0 else f"Pause {p} Min."))
    return " · ".join(teile)


# ---------------------------------------------------------------------------
# Stundenkonto-Buchungen (Auszahlung, Korrektur, Kappung)
# ---------------------------------------------------------------------------
def stundenbuchungen_laden(db, ma_id, von, bis):
    return _sicher(lambda: db.query(
        "SELECT * FROM stundenbuchungen WHERE mitarbeiter_id=%s AND datum "
        "BETWEEN %s AND %s ORDER BY datum, id", (ma_id, von, bis)), []) or []


def stundenbuchung(db, ma_id, datum, minuten, art, bemerkung="",
                   benutzer="", pruefen=True):
    """Bucht Minuten auf das Stundenkonto (negativ = Abzug)."""
    if art not in BUCHUNGSARTEN:
        raise ValueError("Unbekannte Buchungsart.")
    if not minuten:
        raise ValueError("Bitte eine Stundenzahl ungleich 0 eingeben.")
    if pruefen:
        pruefe_offen(db, ma_id, datum, "Stundenkonto-Buchungen")
    return db.execute(
        "INSERT INTO stundenbuchungen (mitarbeiter_id, datum, minuten, art, "
        "bemerkung, erstellt, benutzer) VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (ma_id, datum, int(minuten), art, (bemerkung or "")[:200],
         datetime.datetime.now(), (benutzer or "")[:40]))


def stundenbuchung_loeschen(db, buchung_id):
    b = db.one("SELECT * FROM stundenbuchungen WHERE id=%s", (buchung_id,))
    if b:
        pruefe_offen(db, b["mitarbeiter_id"], b["datum"],
                     "Stundenkonto-Buchungen")
        db.execute("DELETE FROM stundenbuchungen WHERE id=%s", (buchung_id,))
    return b


# ---------------------------------------------------------------------------
# Monatsabschluss
# ---------------------------------------------------------------------------
def letzter_abschluss(db, ma_id, bis=None):
    """Letzter Monatsabschluss, dessen Monat vor oder bis 'bis' endet."""
    sql = "SELECT * FROM monatsabschluesse WHERE mitarbeiter_id=%s"
    args = [ma_id]
    if bis is not None:
        # Monat muss vollständig <= bis sein
        sql += " AND LAST_DAY(monat) <= %s"
        args.append(bis)
    return _sicher(lambda: db.one(sql + " ORDER BY monat DESC LIMIT 1",
                                  args))


def abgeschlossen_bis(db, ma_id):
    """Letzter Tag des zuletzt abgeschlossenen Monats oder None."""
    a = letzter_abschluss(db, ma_id)
    if not a:
        return None
    return monat_grenzen(a["monat"].year, a["monat"].month)[1]


def monat_gesperrt(db, ma_id, datum):
    ende = abgeschlossen_bis(db, ma_id)
    return bool(ende and datum <= ende)


def pruefe_offen(db, ma_id, datum, was="Änderungen"):
    """Wirft ValueError, wenn 'datum' in einem abgeschlossenen Monat liegt."""
    ende = abgeschlossen_bis(db, ma_id)
    if ende and datum <= ende:
        raise ValueError(
            f"Der Monat {datum:%m/%Y} ist abgeschlossen (bis "
            f"{ende:%d.%m.%Y}). {was} sind dort nicht mehr möglich.\n\n"
            f"Falls nötig: Zeiterfassung → Monatsabschluss → Abschluss "
            f"aufheben.")


def monat_abschluss_vorschau(db, settings, ma, jahr, monat):
    """Berechnet die Werte für den Abschluss eines Monats (ohne zu
    speichern). Liefert dict oder wirft ValueError."""
    von, bis = monat_grenzen(jahr, monat)
    if bis >= datetime.date.today():
        raise ValueError("Nur vergangene Monate können abgeschlossen werden.")
    letzter = letzter_abschluss(db, ma["id"])
    if letzter and letzter["monat"] >= von:
        raise ValueError(f"{ma_name(ma)}: {letzter['monat']:%m/%Y} ist "
                         f"bereits abgeschlossen.")
    vorher = saldo_bis(db, settings, ma, von - datetime.timedelta(days=1))
    tage, s = zeitraum_auswerten(db, settings, ma, von, bis)
    ende_roh = vorher + s["saldo"] + s["buchungen"]
    kappung = 0
    try:
        grenze = float(str(settings.get("zeit_saldo_max_stunden") or "")
                       .replace(",", ".") or 0)
    except ValueError:
        grenze = 0
    if grenze > 0 and ende_roh > grenze * 60:
        kappung = int(round(grenze * 60)) - ende_roh
    return {"ma": ma, "monat": von, "vorher": vorher, "ist": s["ist"],
            "soll": s["soll"], "saldo": s["saldo"],
            "buchungen": s["buchungen"], "kappung": kappung,
            "saldo_ende": ende_roh + kappung, "nacht": s["nacht"],
            "fehler": s["fehler"]}


def monat_abschliessen(db, settings, ma, jahr, monat, benutzer=""):
    """Schließt einen Monat für einen Mitarbeiter ab (inkl. Kappung)."""
    v = monat_abschluss_vorschau(db, settings, ma, jahr, monat)
    bis = monat_grenzen(jahr, monat)[1]
    if v["kappung"]:
        stundenbuchung(db, ma["id"], bis, v["kappung"], "kappung",
                       "Kappung auf Höchststand Stundenkonto", benutzer,
                       pruefen=False)
    db.execute(
        "REPLACE INTO monatsabschluesse (mitarbeiter_id, monat, ist, soll, "
        "saldo, buchungen, saldo_vorher, saldo_ende, nacht, abgeschlossen, "
        "benutzer) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (ma["id"], v["monat"], v["ist"], v["soll"], v["saldo"],
         v["buchungen"] + v["kappung"], v["vorher"], v["saldo_ende"],
         v["nacht"], datetime.datetime.now(), (benutzer or "")[:40]))
    return v


def monat_abschluss_aufheben(db, ma_id, jahr, monat):
    """Hebt den (letzten) Abschluss eines Monats auf; eine automatische
    Kappung dieses Monats wird wieder gelöscht."""
    von, bis = monat_grenzen(jahr, monat)
    letzter = letzter_abschluss(db, ma_id)
    if not letzter or letzter["monat"] != von:
        raise ValueError("Es kann nur der zuletzt abgeschlossene Monat "
                         "wieder geöffnet werden.")
    db.execute("DELETE FROM monatsabschluesse WHERE mitarbeiter_id=%s AND "
               "monat=%s", (ma_id, von))
    db.execute("DELETE FROM stundenbuchungen WHERE mitarbeiter_id=%s AND "
               "art='kappung' AND datum BETWEEN %s AND %s", (ma_id, von, bis))


# ---------------------------------------------------------------------------
# Nachtstunden
# ---------------------------------------------------------------------------
def _uhrzeit(text, standard):
    try:
        return datetime.datetime.strptime((text or standard).strip(),
                                          "%H:%M").time()
    except ValueError:
        return datetime.datetime.strptime(standard, "%H:%M").time()


def nacht_minuten(segmente, settings):
    """Minuten der Arbeitsabschnitte, die in der Nachtzeit liegen
    (Standard 23:00–06:00, Firmenstamm → Zeiterfassung)."""
    von = _uhrzeit(settings.get("zeit_nacht_von"), "23:00")
    bis = _uhrzeit(settings.get("zeit_nacht_bis"), "06:00")
    if von == bis:
        return 0
    summe = 0
    for a, b in segmente:
        d = a.date() - datetime.timedelta(days=1)
        while d <= b.date():
            n_von = datetime.datetime.combine(d, von)
            n_bis = datetime.datetime.combine(
                d + datetime.timedelta(days=1) if bis <= von else d, bis)
            anfang, ende = max(a, n_von), min(b, n_bis)
            if ende > anfang:
                summe += _minuten(anfang, ende)
            d += datetime.timedelta(days=1)
    return summe


# ---------------------------------------------------------------------------
# Arbeitszeitgesetz
# ---------------------------------------------------------------------------
def arbzg_pruefen(db, settings, von, bis, mitarbeiter=None, pausen=True):
    """Prüft die Stempelzeiten gegen das Arbeitszeitgesetz. Liefert Liste
    von dicts (ma, datum, stufe 'Verstoß'/'Hinweis', text)."""
    if mitarbeiter is None:
        mitarbeiter = db.query("SELECT * FROM mitarbeiter WHERE aktiv=1 OR "
                               "austritt >= %s ORDER BY nachname, vorname",
                               (von,))
    erg = []
    # (11.0) Grenzwerte konfigurierbar (Firmenstamm → Zeiterfassung)
    try:
        max_tag = int(float(settings.get("arbzg_max_tag_stunden") or 10) * 60)
    except (TypeError, ValueError):
        max_tag = 600
    try:
        ruhe_min = int(float(settings.get("arbzg_ruhe_stunden") or 11) * 60)
    except (TypeError, ValueError):
        ruhe_min = 660
    # für Ruhezeit und Woche einen Tag bzw. eine Woche davor mitnehmen
    start = von - datetime.timedelta(days=von.weekday())
    for ma in mitarbeiter:
        tage, _ = zeitraum_auswerten(db, settings, ma, start - datetime.
                                     timedelta(days=1), bis)
        name = ma_name(ma)

        def melden(d, stufe, text):
            if von <= d <= bis:
                erg.append({"ma": ma, "name": name, "datum": d,
                            "stufe": stufe, "text": text})
        vorher_ende = None
        woche = {}
        for t in tage:
            d = t["datum"]
            seg = t["segmente"]
            hw = zeitumstellung_hinweis(d)
            if hw and seg:
                melden(d, "Hinweis", hw)
            if seg and not t["laeuft"]:
                if t["ist"] > max_tag:
                    melden(d, "Verstoß", f"Arbeitszeit {fmt_std(t['ist'])} "
                           f"Std – höchstens {fmt_std(max_tag)} Std. am Tag "
                           f"erlaubt (§ 3)")
                if pausen:
                    brutto = sum(_minuten(a, b) for a, b in seg)
                    noetig = 45 if brutto > 540 else (30 if brutto > 360
                                                      else 0)
                    echt = sum(_minuten(a, b) for a, b in t["pausen"]
                               if _minuten(a, b) >= 15)
                    if noetig and echt < noetig:
                        melden(d, "Verstoß", f"Pause {fmt_std(echt)} "
                               f"gestempelt, {noetig} Min. vorgeschrieben bei "
                               f"{fmt_std(brutto)} Std Arbeit (§ 4)")
                    laengster = max(_minuten(a, b) for a, b in seg)
                    if laengster > 360:
                        melden(d, "Verstoß", f"{fmt_std(laengster)} Std am "
                               f"Stück ohne Pause – höchstens 6 Std. (§ 4)")
                anfang = seg[0][0]
                if vorher_ende and anfang > vorher_ende:
                    ruhe = _minuten(vorher_ende, anfang)
                    if ruhe < ruhe_min:
                        melden(d, "Verstoß", f"Ruhezeit nur {fmt_std(ruhe)} "
                               f"Std seit {vorher_ende:%d.%m. %H:%M} – "
                               f"mindestens {fmt_std(ruhe_min)} Std. (§ 5)")
                vorher_ende = seg[-1][1]
                if d.weekday() == 6 or t["feiertag"]:
                    melden(d, "Hinweis", "Arbeit an einem " + (
                        "Feiertag" if t["feiertag"] else "Sonntag") +
                        " (§ 9 – nur mit Ausnahme nach § 10 erlaubt)")
            kw = d.isocalendar()[:2]
            woche.setdefault(kw, [0, d])
            woche[kw][0] += t["ist"]
            woche[kw][1] = d
        for (jahr, kw), (summe, letzter) in sorted(woche.items()):
            if summe > 60 * 60:
                melden(letzter, "Verstoß", f"KW {kw}: {fmt_std(summe)} Std "
                       f"in der Woche – höchstens 60 Std. (§ 3)")
            elif summe > 48 * 60:
                melden(letzter, "Hinweis", f"KW {kw}: {fmt_std(summe)} Std "
                       f"in der Woche – im Durchschnitt höchstens 48 Std. "
                       f"(Ausgleich innerhalb von 6 Monaten nötig)")
    erg.sort(key=lambda z: (z["datum"], z["name"]))
    return erg


def stempelfehler_alle(db, settings, von, bis):
    """Alle Tage mit unvollständigen Stempelungen aller aktiven
    Mitarbeiter. Liefert Liste (ma, name, datum, hinweis)."""
    erg = []
    for ma in db.query("SELECT * FROM mitarbeiter WHERE aktiv=1 ORDER BY "
                       "nachname, vorname"):
        tage, _ = zeitraum_auswerten(db, settings, ma, von, bis)
        for t in tage:
            if t["fehler"]:
                erg.append({"ma": ma, "name": ma_name(ma), "datum": t["datum"],
                            "hinweis": t["hinweis"]})
    erg.sort(key=lambda z: (z["datum"], z["name"]))
    return erg


# ---------------------------------------------------------------------------
# Urlaubskonto (für Büro und Terminal)
# ---------------------------------------------------------------------------
def _volle_monate(von, bis):
    n = 0
    for m in range(1, 13):
        anfang = datetime.date(von.year, m, 1)
        ende = datetime.date(von.year + m // 12, m % 12 + 1, 1) - \
            datetime.timedelta(days=1)
        if von <= anfang and ende <= bis:
            n += 1
    return n


def _dec(v, standard="0"):
    if v is None or v == "":
        return Decimal(standard)
    return Decimal(str(v).replace(",", "."))


def urlaub_anspruch_standard(settings, ma, jahr):
    basis = ma.get("urlaub_tage")
    if basis is None or basis == "":
        basis = settings.get("zeit_urlaub_tage") or "30"
    basis = _dec(basis)
    eintritt, austritt = ma.get("eintritt"), ma.get("austritt")
    anfang = datetime.date(jahr, 1, 1)
    ende = datetime.date(jahr, 12, 31)
    if eintritt and eintritt > ende or austritt and austritt < anfang:
        return Decimal(0)
    von = max(anfang, eintritt) if eintritt else anfang
    bis = min(ende, austritt) if austritt else ende
    if von == anfang and bis == ende:
        return basis
    wert = basis * _volle_monate(von, bis) / Decimal(12)
    if wert - int(wert) >= Decimal("0.5"):
        return Decimal(int(wert) + 1)
    return wert.quantize(Decimal("0.01"))


def urlaub_konto(db, settings, ma, jahr, heute=None):
    """Urlaubskonto eines Mitarbeiters für ein Jahr."""
    heute = heute or datetime.date.today()
    uj = _sicher(lambda: db.one("SELECT * FROM urlaub_jahr WHERE "
                                "mitarbeiter_id=%s AND jahr=%s",
                                (ma["id"], jahr)))
    std = urlaub_anspruch_standard(settings, ma, jahr)
    anspruch = _dec(uj["anspruch"]) if uj and uj["anspruch"] is not None \
        else std
    uebertrag = _dec(uj["uebertrag"]) if uj else Decimal(0)
    rows = db.query("SELECT datum, anteil FROM abwesenheiten WHERE "
                    "mitarbeiter_id=%s AND art='urlaub' AND datum BETWEEN "
                    "%s AND %s", (ma["id"], datetime.date(jahr, 1, 1),
                                  datetime.date(jahr, 12, 31)))
    genommen = sum((_dec(r["anteil"]) for r in rows if r["datum"] <= heute),
                   Decimal(0))
    geplant = sum((_dec(r["anteil"]) for r in rows if r["datum"] > heute),
                  Decimal(0))
    return {"jahr": jahr, "anspruch": anspruch, "anspruch_standard": std,
            "anspruch_manuell": bool(uj and uj["anspruch"] is not None),
            "uebertrag": uebertrag, "genommen": genommen, "geplant": geplant,
            "gesamt": anspruch + uebertrag,
            "rest": anspruch + uebertrag - genommen - geplant,
            "bemerkung": uj["bemerkung"] if uj else ""}


def arbeitstage_liste(db, settings, ma, von, bis):
    """Arbeitstage (Soll > 0, kein Feiertag) zwischen von und bis laut dem
    jeweils gültigen Arbeitszeitmodell."""
    modelle = modelle_laden(db, ma["id"])
    ft = {}
    for j in range(von.year, bis.year + 1):
        ft.update(feiertage(j, settings.get("zeit_bundesland"),
                            settings.get("zeit_maria_himmelfahrt") == "1"))
    # (9.7) nach Dienstplan: der Plan entscheidet (frei / eingeteilt)
    plan = {}
    if int(ma.get("nach_dienstplan") or 0):
        plan = {d: e for (_m, d), e in dienstplan_laden(
            db, [ma["id"]], von, bis).items()}
    erg = []
    d = von
    while d <= bis:
        r = regeln(settings, ma, d, modelle)
        if d in plan:
            if plan[d]["schicht"] != "frei" and d not in ft:
                erg.append(d)
        elif soll_fuer(r, d.weekday()) > 0 and d not in ft:
            erg.append(d)
        d += datetime.timedelta(days=1)
    return erg


# ---------------------------------------------------------------------------
# Urlaubsanträge (Terminal / App)
# ---------------------------------------------------------------------------
def antrag_stellen(db, settings, ma, von, bis, halb=False, art="urlaub",
                   bemerkung="", quelle="terminal"):
    """Stellt einen Urlaubsantrag. Liefert (id, tage) oder wirft
    ValueError."""
    heute = datetime.date.today()
    if bis < von:
        raise ValueError("Das Ende liegt vor dem Beginn.")
    if von < heute:
        raise ValueError("Urlaub kann nur für heute oder später beantragt "
                         "werden.")
    if halb and von != bis:
        raise ValueError("Ein halber Tag geht nur für ein einzelnes Datum.")
    tage = arbeitstage_liste(db, settings, ma, von, bis)
    if not tage:
        raise ValueError("Im gewählten Zeitraum gibt es keine Arbeitstage.")
    if art == "urlaub":
        sp = sperren_im_zeitraum(db, ma["id"], von, bis)
        if sp:
            raise ValueError(sperre_text(sp[0]))
    belegt = db.query("SELECT datum FROM abwesenheiten WHERE mitarbeiter_id="
                      "%s AND datum BETWEEN %s AND %s", (ma["id"], von, bis))
    if belegt:
        raise ValueError(f"Am {belegt[0]['datum']:%d.%m.%Y} ist bereits eine "
                         f"Abwesenheit eingetragen.")
    offen = db.one("SELECT von, bis FROM urlaubsantraege WHERE "
                   "mitarbeiter_id=%s AND status='offen' AND von <= %s AND "
                   "bis >= %s", (ma["id"], bis, von))
    if offen:
        raise ValueError(f"Für {offen['von']:%d.%m.}–{offen['bis']:%d.%m.%Y}"
                         f" gibt es schon einen offenen Antrag.")
    anzahl = Decimal("0.5") if halb else Decimal(len(tage))
    aid = db.execute(
        "INSERT INTO urlaubsantraege (mitarbeiter_id, von, bis, halb, art, "
        "tage, bemerkung, status, erstellt, quelle) VALUES "
        "(%s,%s,%s,%s,%s,%s,%s,'offen',%s,%s)",
        (ma["id"], von, bis, int(bool(halb)), art, anzahl,
         (bemerkung or "")[:200], datetime.datetime.now(), quelle[:20]))
    return aid, anzahl


def antraege_von(db, ma_id, anzahl=5):
    return _sicher(lambda: db.query(
        "SELECT * FROM urlaubsantraege WHERE mitarbeiter_id=%s ORDER BY "
        "erstellt DESC LIMIT %s", (ma_id, int(anzahl))), []) or []


def antrag_typ(a):
    """'antrag' oder 'storno' (alte Datenbanken ohne Spalte: 'antrag')."""
    return (a.get("typ") or "antrag") if a else "antrag"


# ---------------------------------------------------------------------------
# (8.9) Kalenderwochen
# ---------------------------------------------------------------------------
def kw(datum):
    """ISO-Kalenderwoche als Zahl."""
    return datum.isocalendar()[1]


def kw_text(datum):
    return f"KW {kw(datum):02d}"


def kw_montag(datum):
    return datum - datetime.timedelta(days=datum.weekday())


def kw_bereich_text(von, bis):
    a, b = von.isocalendar()[:2], bis.isocalendar()[:2]
    if a == b:
        return f"KW {a[1]:02d}"
    return f"KW {a[1]:02d}–{b[1]:02d}"


# ---------------------------------------------------------------------------
# (8.9) Urlaubssperren – global (mitarbeiter_id NULL) oder je Mitarbeiter
# ---------------------------------------------------------------------------
def sperren_im_zeitraum(db, ma_id, von, bis):
    """Sperren, die den Zeitraum berühren und für den Mitarbeiter gelten
    (ma_id None: alle Sperren)."""
    if ma_id is None:
        sql, p = ("SELECT * FROM urlaubssperren WHERE von <= %s AND "
                  "bis >= %s ORDER BY von, id", (bis, von))
    else:
        sql, p = ("SELECT * FROM urlaubssperren WHERE von <= %s AND "
                  "bis >= %s AND (mitarbeiter_id IS NULL OR "
                  "mitarbeiter_id=%s) ORDER BY von, id", (bis, von, ma_id))
    return _sicher(lambda: db.query(sql, p), []) or []


def sperre_text(sp, kurz=False):
    wer = "für alle" if sp.get("mitarbeiter_id") is None else "für Sie"
    zeitraum = (f"{sp['von']:%d.%m.%Y}" if sp["von"] == sp["bis"] else
                f"{sp['von']:%d.%m.}–{sp['bis']:%d.%m.%Y}")
    grund = f" ({sp['grund']})" if sp.get("grund") else ""
    if kurz:
        return f"Urlaubssperre {zeitraum}{grund}"
    return f"Urlaubssperre {wer} {zeitraum}{grund}."


def sperren_alle(db, ab=None):
    sql = ("SELECT s.*, m.vorname, m.nachname FROM urlaubssperren s LEFT "
           "JOIN mitarbeiter m ON m.id=s.mitarbeiter_id")
    p = ()
    if ab:
        sql += " WHERE s.bis >= %s"
        p = (ab,)
    return _sicher(lambda: db.query(sql + " ORDER BY s.von, s.id", p),
                   []) or []


def sperre_speichern(db, werte, sperre_id=None, benutzer=""):
    von, bis = werte["von"], werte["bis"]
    if bis < von:
        raise ValueError("Das Ende liegt vor dem Beginn.")
    ma_id = werte.get("mitarbeiter_id") or None
    grund = (werte.get("grund") or "")[:200]
    if sperre_id:
        db.execute("UPDATE urlaubssperren SET mitarbeiter_id=%s, von=%s, "
                   "bis=%s, grund=%s WHERE id=%s",
                   (ma_id, von, bis, grund, sperre_id))
        return sperre_id
    return db.execute(
        "INSERT INTO urlaubssperren (mitarbeiter_id, von, bis, grund, "
        "erstellt, erstellt_von) VALUES (%s,%s,%s,%s,%s,%s)",
        (ma_id, von, bis, grund, datetime.datetime.now(),
         (benutzer or "")[:40]))


def sperre_loeschen(db, sperre_id):
    db.execute("DELETE FROM urlaubssperren WHERE id=%s", (sperre_id,))


# ---------------------------------------------------------------------------
# (8.9) Urlaub zurückziehen / stornieren (Terminal)
# ---------------------------------------------------------------------------
def _bloecke(tage, arbeitstage):
    """Fasst Abwesenheitstage zu Blöcken zusammen; Tage gelten als
    zusammenhängend, wenn dazwischen kein Arbeitstag liegt (nur
    Wochenende/Feiertage)."""
    bloecke = []
    for r in tage:
        d, anteil = r["datum"], _dec(r["anteil"])
        if bloecke and not any(bloecke[-1]["bis"] < a < d
                               for a in arbeitstage):
            b = bloecke[-1]
            b["bis"] = d
            b["tage"] += anteil
            b["tage_liste"].append(d)
        else:
            bloecke.append({"von": d, "bis": d, "tage": anteil,
                            "tage_liste": [d]})
    return bloecke


def geplanter_urlaub(db, settings, ma, heute=None):
    """Für das Terminal: offene Anträge (zurückziehbar) und genehmigter,
    noch nicht begonnener Urlaub ab heute (stornierbar), in Blöcken.
    Liefert eine Liste von Einträgen mit 'art' = 'antrag' | 'urlaub'."""
    heute = heute or datetime.date.today()
    ma_id = ma["id"]
    erg = []
    for a in _sicher(lambda: db.query(
            "SELECT * FROM urlaubsantraege WHERE mitarbeiter_id=%s AND "
            "status='offen' ORDER BY von", (ma_id,)), []) or []:
        erg.append({"art": "antrag", "von": a["von"], "bis": a["bis"],
                    "tage": _dec(a["tage"]), "antrag": a,
                    "typ": antrag_typ(a)})
    rows = db.query("SELECT datum, anteil FROM abwesenheiten WHERE "
                    "mitarbeiter_id=%s AND art='urlaub' AND datum >= %s "
                    "ORDER BY datum", (ma_id, heute))
    offen_storno = [e for e in erg if e["typ"] == "storno"]
    at = arbeitstage_liste(db, settings, ma, rows[0]["datum"],
                           rows[-1]["datum"]) if rows else []
    for b in _bloecke(rows, set(at)):
        b["art"] = "urlaub"
        b["storno_offen"] = any(e["von"] <= b["bis"] and e["bis"] >= b["von"]
                                for e in offen_storno)
        if any(e["von"] <= b["von"] and e["bis"] >= b["bis"]
               for e in offen_storno):
            continue        # ganz in einer offenen Stornierung -> nur diese
        erg.append(b)
    erg.sort(key=lambda e: (e["von"], e["art"]))
    return erg


def antrag_zurueckziehen(db, ma_id, antrag_id):
    """Offenen Antrag (Urlaub oder Stornierung) selbst zurückziehen."""
    a = db.one("SELECT status FROM urlaubsantraege WHERE id=%s AND "
               "mitarbeiter_id=%s", (antrag_id, ma_id))
    if not a or a["status"] != "offen":
        raise ValueError("Der Antrag ist nicht mehr offen.")
    db.execute("UPDATE urlaubsantraege SET status='zurueckgezogen', "
               "bearbeitet=%s, bearbeitet_von='Mitarbeiter' WHERE id=%s AND "
               "status='offen'", (datetime.datetime.now(), antrag_id))


def storno_beantragen(db, settings, ma, von, bis, bemerkung="",
                      quelle="terminal"):
    """Stornierung von genehmigtem Urlaub beantragen (Büro entscheidet).
    Liefert (id, tage)."""
    heute = datetime.date.today()
    if bis < von:
        raise ValueError("Das Ende liegt vor dem Beginn.")
    if von < heute:
        raise ValueError("Bereits begonnener oder vergangener Urlaub kann "
                         "nur im Büro geändert werden.")
    rows = db.query("SELECT datum, anteil FROM abwesenheiten WHERE "
                    "mitarbeiter_id=%s AND art='urlaub' AND datum BETWEEN "
                    "%s AND %s", (ma["id"], von, bis))
    if not rows:
        raise ValueError("In diesem Zeitraum ist kein Urlaub eingetragen.")
    offen = _sicher(lambda: db.one(
        "SELECT id FROM urlaubsantraege WHERE mitarbeiter_id=%s AND "
        "status='offen' AND typ='storno' AND von <= %s AND bis >= %s",
        (ma["id"], bis, von)))
    if offen:
        raise ValueError("Für diesen Urlaub ist die Stornierung schon "
                         "beantragt.")
    tage = sum((_dec(r["anteil"]) for r in rows), Decimal(0))
    halb = len(rows) == 1 and tage < 1
    aid = db.execute(
        "INSERT INTO urlaubsantraege (mitarbeiter_id, von, bis, halb, art, "
        "tage, bemerkung, status, erstellt, quelle, typ) VALUES "
        "(%s,%s,%s,%s,'urlaub',%s,%s,'offen',%s,%s,'storno')",
        (ma["id"], von, bis, int(halb), tage, (bemerkung or "")[:200],
         datetime.datetime.now(), quelle[:20]))
    return aid, tage


# ---------------------------------------------------------------------------
# Nachrichten an Mitarbeiter (erscheinen am Terminal)
# ---------------------------------------------------------------------------
def nachrichten_offen(db, ma_id, heute=None):
    heute = heute or datetime.date.today()
    return _sicher(lambda: db.query(
        "SELECT * FROM nachrichten WHERE mitarbeiter_id=%s AND gelesen IS "
        "NULL AND (gueltig_bis IS NULL OR gueltig_bis >= %s) ORDER BY "
        "erstellt, id", (ma_id, heute)), []) or []


def nachricht_gelesen(db, nachricht_id, zeitpunkt=None):
    db.execute("UPDATE nachrichten SET gelesen=%s WHERE id=%s",
               (zeitpunkt or datetime.datetime.now(), nachricht_id))


def nachricht_senden(db, ma_ids, text, gueltig_bis=None, von=""):
    jetzt = datetime.datetime.now()
    for mid in ma_ids:
        db.execute("INSERT INTO nachrichten (mitarbeiter_id, text, erstellt, "
                   "von, gueltig_bis) VALUES (%s,%s,%s,%s,%s)",
                   (mid, text[:500], jetzt, (von or "")[:40], gueltig_bis))
    return len(ma_ids)


# ---------------------------------------------------------------------------
# Auftragszeiten (Arbeitszeit auf Aufträge buchen)
# ---------------------------------------------------------------------------
def offene_auftraege(db):
    """Offene/gelieferte Auftragsbestätigungen für die Auswahl."""
    return _sicher(lambda: db.query(
        "SELECT id, nummer, k_name, betreff, datum FROM belege WHERE "
        "typ='B' AND status IN ('offen', 'geliefert') ORDER BY datum DESC, "
        "id DESC"), []) or []


def aktueller_auftrag(db, ma_id):
    return _sicher(lambda: db.one(
        "SELECT * FROM auftragszeiten WHERE mitarbeiter_id=%s AND ende IS "
        "NULL ORDER BY beginn DESC LIMIT 1", (ma_id,)))


def _auftrag_schliessen(db, ma_id, zeitpunkt, grund=""):
    offen = db.query("SELECT id, beginn, beleg_id FROM auftragszeiten WHERE "
                     "mitarbeiter_id=%s AND ende IS NULL", (ma_id,))
    for o in offen:
        ende = max(zeitpunkt, o["beginn"])
        db.execute("UPDATE auftragszeiten SET ende=%s, minuten=%s, "
                   "ende_grund=%s WHERE id=%s",
                   (ende, _minuten(o["beginn"], ende), grund[:20], o["id"]))
    return offen


def auftrag_starten(db, ma_id, beleg_id, zeitpunkt=None, taetigkeit="",
                    quelle="terminal"):
    """Beendet den laufenden Auftrag des Mitarbeiters und startet (bei
    beleg_id) einen neuen."""
    zeitpunkt = (zeitpunkt or datetime.datetime.now()).replace(microsecond=0)
    _auftrag_schliessen(db, ma_id, zeitpunkt, "wechsel")
    if beleg_id:
        return db.execute(
            "INSERT INTO auftragszeiten (mitarbeiter_id, beleg_id, beginn, "
            "taetigkeit, quelle, erstellt) VALUES (%s,%s,%s,%s,%s,%s)",
            (ma_id, beleg_id, zeitpunkt, (taetigkeit or "")[:200],
             quelle[:20], datetime.datetime.now()))
    return None


def _auftrag_beim_stempeln(db, ma_id, art, zeitpunkt):
    """Hält die Auftragszeit synchron zu Geht/Pause: Geht und Pause
    beenden den laufenden Auftrag, Ende Pause setzt ihn fort."""
    if art in ("geht", "pause_an"):
        _auftrag_schliessen(db, ma_id, zeitpunkt,
                            "geht" if art == "geht" else "pause")
    elif art == "pause_ende":
        letzte = db.one("SELECT * FROM auftragszeiten WHERE mitarbeiter_id="
                        "%s AND ende IS NOT NULL ORDER BY ende DESC LIMIT 1",
                        (ma_id,))
        if letzte and letzte["ende_grund"] == "pause" and \
                letzte["ende"].date() == zeitpunkt.date() and \
                not aktueller_auftrag(db, ma_id):
            db.execute(
                "INSERT INTO auftragszeiten (mitarbeiter_id, beleg_id, "
                "beginn, taetigkeit, quelle, erstellt) VALUES "
                "(%s,%s,%s,%s,%s,%s)",
                (ma_id, letzte["beleg_id"], zeitpunkt, letzte["taetigkeit"],
                 letzte["quelle"], datetime.datetime.now()))


# ---------------------------------------------------------------------------
# (9.0) Arbeitsgruppen und Mindestbesetzung
# ---------------------------------------------------------------------------
def arbeitsgruppen(db, nur_aktive=True):
    sql = "SELECT * FROM arbeitsgruppen"
    if nur_aktive:
        sql += " WHERE aktiv=1"
    return _sicher(lambda: db.query(sql + " ORDER BY name"), []) or []


def gruppen_ids(ma):
    """Gruppen-IDs eines Mitarbeiters (0, 1 oder 2)."""
    erg = []
    for f in ("gruppe1_id", "gruppe2_id"):
        g = (ma or {}).get(f)
        if g and g not in erg:
            erg.append(g)
    return erg


def gruppen_von(db, ma, nur_aktive=True):
    ids = gruppen_ids(ma)
    if not ids:
        return []
    return [g for g in arbeitsgruppen(db, nur_aktive) if g["id"] in ids]


def gruppen_text(db, ma, gruppen=None):
    namen = {g["id"]: g["name"] for g in (gruppen if gruppen is not None
                                          else arbeitsgruppen(db, False))}
    return ", ".join(namen[i] for i in gruppen_ids(ma) if i in namen)


def gruppe_mitglieder(db, gruppe_id, von=None, bis=None):
    """Mitglieder einer Gruppe; mit von/bis nur die, die im Zeitraum
    beschäftigt sind (Eintritt/Austritt), sonst nur aktive."""
    sql = ("SELECT * FROM mitarbeiter WHERE (gruppe1_id=%s OR "
           "gruppe2_id=%s)")
    p = [gruppe_id, gruppe_id]
    if von and bis:
        sql += (" AND (eintritt IS NULL OR eintritt <= %s) AND "
                "(austritt IS NULL OR austritt >= %s) AND (aktiv=1 OR "
                "austritt IS NOT NULL)")
        p += [bis, von]
    else:
        sql += " AND aktiv=1"
    return _sicher(lambda: db.query(sql + " ORDER BY nachname, vorname",
                                    p), []) or []


def besetzung(db, settings, gruppe, von, bis):
    """Besetzung einer Gruppe je Tag von..bis. Gezählt werden die
    Mitglieder, für die der Tag laut Arbeitszeitmodell ein Arbeitstag ist;
    Abwesenheiten jeder Art (Urlaub, krank, …) werden abgezogen, halbe
    Tage zur Hälfte. Tage, an denen niemand aus der Gruppe arbeitet,
    fehlen. Liefert Liste von dicts: datum, soll (Anzahl), verfuegbar,
    mindest, unter (bool), abwesend [(ma, art, anteil)], da [ma]."""
    mitglieder = gruppe_mitglieder(db, gruppe["id"], von, bis)
    if not mitglieder:
        return []
    ids = [m["id"] for m in mitglieder]
    platz = ",".join(["%s"] * len(ids))
    abw = {}
    for r in db.query(f"SELECT mitarbeiter_id, datum, art, anteil FROM "
                      f"abwesenheiten WHERE mitarbeiter_id IN ({platz}) AND "
                      f"datum BETWEEN %s AND %s", ids + [von, bis]):
        abw[(r["mitarbeiter_id"], r["datum"])] = r
    tage = {}
    for m in mitglieder:
        for d in arbeitstage_liste(db, settings, m, von, bis):
            if (m["eintritt"] and d < m["eintritt"]) or \
                    (m["austritt"] and d > m["austritt"]):
                continue
            tage.setdefault(d, []).append(m)
    mindest = int(gruppe.get("mindest_anwesend") or 0)
    # (9.7) Zusagen zum Einspringen zählen mit
    zusagen = _eingesprungen_gruppe(db, gruppe["id"], von, bis)
    nach_id = {m["id"]: m for m in mitglieder}
    for d, ids in zusagen.items():
        tage.setdefault(d, [])
    erg = []
    for d in sorted(tage):
        verf = Decimal(0)
        abwesend, da, eingesprungen = [], [], []
        for m in tage[d]:
            a = abw.get((m["id"], d))
            anteil = _dec(a["anteil"]) if a else Decimal(0)
            verf += Decimal(1) - anteil
            if a:
                abwesend.append((m, a["art"], anteil))
            if anteil < 1:
                da.append(m)
        geplant = {m["id"] for m in tage[d]}
        for mid in sorted(zusagen.get(d, ())):
            if mid in geplant:
                continue
            m = nach_id.get(mid) or db.one(
                "SELECT * FROM mitarbeiter WHERE id=%s", (mid,))
            if m:
                verf += 1
                da.append(m)
                eingesprungen.append(m)
        if not tage[d] and not eingesprungen:
            continue
        erg.append({"datum": d, "soll": len(tage[d]), "verfuegbar": verf,
                    "mindest": mindest, "unter": mindest > 0 and
                    verf < mindest, "abwesend": abwesend, "da": da,
                    "eingesprungen": eingesprungen})
    return erg


def mindest_verletzungen(db, settings, ma, von, bis, halb=False):
    """Würde eine zusätzliche Abwesenheit des Mitarbeiters von..bis die
    Mindestbesetzung einer seiner Gruppen unterschreiten? Kranke und
    Urlauber sind schon abgezogen. Liefert Liste von dicts: gruppe,
    datum, verfuegbar (danach), mindest."""
    erg = []
    for g in gruppen_von(db, ma):
        mindest = int(g.get("mindest_anwesend") or 0)
        if mindest <= 0:
            continue
        for t in besetzung(db, settings, g, von, bis):
            if not any(m["id"] == ma["id"] for m in t["da"]):
                continue            # an dem Tag ohnehin nicht da
            eigen = Decimal(1)
            for m, art, anteil in t["abwesend"]:
                if m["id"] == ma["id"]:
                    eigen = Decimal(1) - anteil
            weg = min(eigen, Decimal("0.5")) if halb else eigen
            nachher = t["verfuegbar"] - weg
            if nachher < mindest:
                erg.append({"gruppe": g, "datum": t["datum"],
                            "verfuegbar": nachher, "mindest": mindest})
    erg.sort(key=lambda v: (v["datum"], v["gruppe"]["name"]))
    return erg


def unterbesetzung(db, settings, ma, von, bis, ab=None):
    """Tage (ab 'ab', Standard heute), an denen eine Gruppe des
    Mitarbeiters ihre Mindestbesetzung jetzt unterschreitet.
    Liefert {gruppe_id: (gruppe, [tag, …])}."""
    ab = ab or datetime.date.today()
    von = max(von, ab)
    erg = {}
    if bis < von:
        return erg
    for g in gruppen_von(db, ma):
        if int(g.get("mindest_anwesend") or 0) <= 0:
            continue
        tage = [t for t in besetzung(db, settings, g, von, bis) if t["unter"]]
        if tage:
            erg[g["id"]] = (g, tage)
    return erg


def anzahl_text(v):
    """0,5-genaue Personenzahl als Text."""
    v = _dec(v)
    return str(int(v)) if v == int(v) else f"{v:.1f}".replace(".", ",")


def mindest_text(verletzungen, max_zeilen=6):
    zeilen = []
    for v in verletzungen[:max_zeilen]:
        d = v["datum"]
        zeilen.append(f"{WOCHENTAGE[d.weekday()]} {d:%d.%m.%Y} – "
                      f"{v['gruppe']['name']}: nur {anzahl_text(v['verfuegbar'])}"
                      f" statt mindestens {v['mindest']}")
    if len(verletzungen) > max_zeilen:
        zeilen.append(f"… und {len(verletzungen) - max_zeilen} weitere Tag(e)")
    return "\n".join(zeilen)


# ---------------------------------------------------------------------------
# (9.2) Schichten: Arbeitsbeginn/-ende, Verspätung
# ---------------------------------------------------------------------------
SCHICHTEN = {"tag": "Tagschicht", "spaet": "Spätschicht",
             "nacht": "Nachtschicht"}
SCHICHT_ZUORDNUNG = {"": "(keine Vorgabe)", "tag": "Tagschicht",
                     "spaet": "Spätschicht", "nacht": "Nachtschicht",
                     "auto": "automatisch nach Kommt-Zeit"}
RASTER = {"": "nicht runden", "15": "Viertelstunde", "30": "halbe Stunde",
          "60": "Stunde"}
SCHICHT_FELDER = [f"{s}_{x}" for s in SCHICHTEN for x in ("beginn", "ende")]
# (9.2) Verspätungsregeln: auch je Gruppe und Mitarbeiter
REGEL_FELDER = ["verspaetung_abzug", "verspaetung_raster", "nach_schichtende"]
NACH_ENDE = {"kappen": "nicht zählen (bis Arbeitsende)",
             "zaehlen": "weiter zählen (Überstunden)"}


def uhr_lesen(text):
    """'7:30' / '07:30' -> datetime.time, leer/ungültig -> None."""
    t = (text or "").strip().replace(".", ":")
    if not t:
        return None
    try:
        h, m = t.split(":") if ":" in t else (t, "0")
        h, m = int(h), int(m)
        if 0 <= h <= 23 and 0 <= m <= 59:
            return datetime.time(h, m)
    except ValueError:
        pass
    return None


def uhr_pruefen(text, name):
    """Für Eingabeformulare: leer oder HH:MM, sonst ValueError."""
    if (text or "").strip() and uhr_lesen(text) is None:
        raise ValueError(f"{name}: Uhrzeit bitte als HH:MM eingeben "
                         f"(oder leer lassen).")
    t = uhr_lesen(text)
    return f"{t:%H:%M}" if t else ""


def schichten_aktiv(settings):
    return settings.get("zeit_schichten") == "1"


def _gruppen_des_ma(ma, gruppen):
    return [gruppen[g] for g in gruppen_ids(ma) if g in (gruppen or {})]


def schicht_vorgaben(settings, ma, gruppen=None):
    """Wirksame Schicht-Vorgaben eines Mitarbeiters (oder None, wenn das
    Schichtmodell aus ist bzw. keine Schicht gilt):
    {"zuordnung": tag|spaet|nacht|auto, "zeiten": {schicht: (beginn,
    ende)}, "quelle": {schicht: "Mitarbeiter"|"Gruppe …"|"Firmenstamm"}}.
    Reihenfolge: Mitarbeiter, dann seine Gruppe(n), dann Firmenstamm.
    gruppen: {id: gruppe} (z. B. aus arbeitsgruppen())."""
    if not schichten_aktiv(settings) or not ma:
        return None
    grp = _gruppen_des_ma(ma, gruppen)
    zuordnung = (ma.get("schicht") or "").strip()
    for g in grp:
        if not zuordnung:
            zuordnung = (g.get("schicht") or "").strip()
    if not zuordnung:
        zuordnung = (settings.get("zeit_schicht_standard") or "").strip()
    if zuordnung not in ("tag", "spaet", "nacht", "auto"):
        return None
    zeiten, quelle = {}, {}
    for s in SCHICHTEN:
        werte = {}
        for x in ("beginn", "ende"):
            f = f"{s}_{x}"
            v, q = uhr_lesen(ma.get(f)), "Mitarbeiter"
            if v is None:
                for g in grp:
                    v = uhr_lesen(g.get(f))
                    if v is not None:
                        q = f"Gruppe {g['name']}"
                        break
            if v is None:
                v, q = uhr_lesen(settings.get(f"zeit_{f}")), "Firmenstamm"
            werte[x] = v
            if v is not None:
                quelle[f] = q
        if werte["beginn"] or werte["ende"]:
            zeiten[s] = (werte["beginn"], werte["ende"])
    if not zeiten:
        return None
    # Verspätungsregeln: Mitarbeiter, dann Gruppe(n), dann Firmenstamm
    regeln_ = {}
    for f in REGEL_FELDER:
        v, q = ma.get(f), "Mitarbeiter"
        if v is None or v == "":
            v = None
            for g in grp:
                if g.get(f) is not None and g.get(f) != "":
                    v, q = g.get(f), f"Gruppe {g['name']}"
                    break
        if v is None:
            v, q = settings.get(f"zeit_{f}"), "Firmenstamm"
        regeln_[f] = v
        quelle[f] = q
    try:
        abzug = max(0, int(regeln_["verspaetung_abzug"] or 0))
    except (TypeError, ValueError):
        abzug = 0
    try:
        raster = int(regeln_["verspaetung_raster"] or 0)
    except (TypeError, ValueError):
        raster = 0
    nach = regeln_["nach_schichtende"] or "kappen"
    return {"zuordnung": zuordnung, "zeiten": zeiten, "quelle": quelle,
            "abzug": abzug, "raster": raster if raster in (15, 30, 60) else 0,
            "nach_ende": "zaehlen" if nach == "zaehlen" else "kappen"}


def schicht_kreuzt_mitternacht(vorgaben):
    """Kann eine der möglichen Schichten über Mitternacht gehen?"""
    if not vorgaben:
        return False
    namen = list(vorgaben["zeiten"]) if vorgaben["zuordnung"] == "auto" \
        else [vorgaben["zuordnung"]]
    for s in namen:
        b, e = vorgaben["zeiten"].get(s, (None, None))
        if b and e and e <= b:
            return True
    return False


def _schicht_waehlen(vorgaben, kommt):
    """Schicht des Tages: feste Zuordnung oder (automatisch) die Schicht,
    deren Beginn der ersten Kommt-Zeit am nächsten liegt."""
    z = vorgaben["zuordnung"]
    if z != "auto":
        return z if z in vorgaben["zeiten"] else None
    best, abstand = None, None
    k = kommt.hour * 60 + kommt.minute
    for s, (b, _e) in vorgaben["zeiten"].items():
        if not b:
            continue
        d = abs(k - (b.hour * 60 + b.minute))
        d = min(d, 1440 - d)
        if abstand is None or d < abstand:
            best, abstand = s, d
    return best


def _aufrunden(zp, raster):
    if not raster:
        return zp
    zp = zp.replace(second=0, microsecond=0)
    m = zp.hour * 60 + zp.minute
    rest = m % raster
    if not rest:
        return zp
    return zp + datetime.timedelta(minutes=raster - rest)


def schichtrahmen(t, vorgaben, settings, datum):
    """Wendet Arbeitsbeginn/-ende auf eine Tagesauswertung an:
    - Zeit vor Arbeitsbeginn zählt nicht.
    - Verspätung: Beginn wird auf das Raster (Viertel-/halbe/ganze Stunde)
      aufgerundet, zusätzlich 'Abzug bei Verspätung' Minuten.
    - Zeit nach Arbeitsende zählt je nach Einstellung nicht ('kappen').
    Liefert die geänderte Auswertung (Kopie) mit 'schicht', 'schicht_text',
    'verspaetung' (Minuten) und 'rahmen_abzug' (Minuten)."""
    kommt = t.get("kommt")
    if not vorgaben or not kommt:
        return t
    s = _schicht_waehlen(vorgaben, kommt)
    if not s:
        return t
    b, e = vorgaben["zeiten"].get(s, (None, None))
    beginn = datetime.datetime.combine(datum, b) if b else None
    ende = None
    if e:
        ende = datetime.datetime.combine(datum, e)
        if beginn and ende <= beginn:
            ende += datetime.timedelta(days=1)     # Nachtschicht
    if ende and kommt >= ende:
        return dict(t, schicht=s, schicht_text=f"{SCHICHTEN.get(s, 'Dienstplan')}: Kommt "
                    f"nach Schichtende – nicht angewendet")
    # Regeln aus schicht_vorgaben (Mitarbeiter > Gruppe > Firmenstamm)
    raster = vorgaben.get("raster", 0)
    strafe = vorgaben.get("abzug", 0)
    kappen = vorgaben.get("nach_ende", "kappen") == "kappen"
    k0 = kommt.replace(second=0, microsecond=0)
    verspaetung = 0
    start = None
    if beginn:
        if k0 > beginn:
            verspaetung = _minuten(beginn, k0)
            start = _aufrunden(kommt, raster)
        else:
            start = beginn
    stop = ende if (ende and kappen) else None
    # (9.7) Arbeitsbeginn/-ende gelten nur für den ersten Einsatz des
    # Tages; jeder weitere Einsatz (neues Kommt nach einem Geht, z. B.
    # Einspringen) zählt voll.
    einsaetze = t.get("einsaetze") or []
    erst_ende = einsaetze[0][1] if einsaetze else None

    def im_ersten(von):
        return erst_ende is None or von < erst_ende
    neu, entfernt = [], 0
    for von, bis in t["segmente"]:
        if not im_ersten(von):
            neu.append((von, bis))
            continue
        v = max(von, start) if start else von
        b2 = min(bis, stop) if stop else bis
        entfernt += _minuten(von, bis) - (_minuten(v, b2) if b2 > v else 0)
        if b2 > v:
            neu.append((v, b2))
    vor = nach = 0
    if start:
        vor = sum(_minuten(von, min(bis, start)) for von, bis in t["segmente"]
                  if von < start and im_ersten(von))
    if stop:
        nach = sum(_minuten(max(von, stop), bis) for von, bis in t["segmente"]
                   if bis > stop and im_ersten(von))
    abzug_strafe = strafe if verspaetung else 0
    je = {}
    for von, bis in neu:
        _verteilen(je, von, bis)
    if abzug_strafe and je:
        erster = min(je)
        je[erster] = max(0, je[erster] - abzug_strafe)
    anwesend = max(0, t["anwesend"] - entfernt - abzug_strafe)
    zeitraum = (f"{b:%H:%M}" if b else "…") + "–" + (f"{e:%H:%M}" if e
                                                       else "…")
    teile = []
    if verspaetung:
        teil = f"{verspaetung} Min. zu spät"
        if start and start > k0:
            teil += f", gewertet ab {start:%H:%M}"
        if abzug_strafe:
            teil += f", Abzug {abzug_strafe} Min."
        teile.append(teil)
    elif vor:
        teile.append(f"vor Schichtbeginn {vor} Min. nicht gezählt")
    if nach:
        teile.append(f"nach Schichtende {nach} Min. nicht gezählt")
    # Hinweis nur, wenn sich etwas auswirkt
    text = f"{SCHICHTEN.get(s, 'Dienstplan')} {zeitraum}: " + \
        "; ".join(teile) if teile else ""
    return dict(t, anwesend=anwesend, segmente=neu, je_datum=je, schicht=s,
                schicht_text=text, verspaetung=verspaetung,
                rahmen_abzug=entfernt + abzug_strafe,
                gewertet_ab=start if (start and start > kommt) else None)


def ueber_mitternacht_setzen(db, settings=None):
    """Mitarbeiter, deren Schicht über Mitternacht gehen kann (Nacht-
    schicht), bekommen 'arbeitet über 24 Uhr', damit Kommt und Geht zum
    selben Arbeitstag gehören. Liefert die Anzahl geänderter."""
    settings = settings or db.settings()
    if not schichten_aktiv(settings):
        return 0
    gruppen = {g["id"]: g for g in arbeitsgruppen(db, False)}
    n = 0
    for ma in db.query("SELECT * FROM mitarbeiter WHERE aktiv=1 AND "
                       "ueber_mitternacht=0"):
        if schicht_kreuzt_mitternacht(schicht_vorgaben(settings, ma,
                                                       gruppen)):
            db.execute("UPDATE mitarbeiter SET ueber_mitternacht=1 WHERE "
                       "id=%s", (ma["id"],))
            n += 1
    return n


# ===========================================================================
# (9.7) Einspringen, Korrekturanträge, Dienstplan, Ampelkonto, Meldungen
# ===========================================================================
def _jetzt():
    return datetime.datetime.now().replace(microsecond=0)


# ---------------------------------------------------------------------------
# Einmalige Meldungen (Erinnerung, Tagesmail, Ampel …)
# ---------------------------------------------------------------------------
def meldung_beanspruchen(db, art, ma_id, bezug, text=""):
    """True nur beim ersten Aufruf für (art, Mitarbeiter, bezug) – auch
    wenn mehrere Arbeitsplätze gleichzeitig prüfen."""
    n = db.aendern(
        "INSERT IGNORE INTO zeit_meldungen (art, mitarbeiter_id, bezug, "
        "gesendet, text) VALUES (%s,%s,%s,%s,%s)",
        (art[:20], ma_id, str(bezug)[:40], _jetzt(), (text or "")[:300]))
    return bool(n)


def meldung_freigeben(db, art, ma_id, bezug):
    """Anspruch zurücknehmen (z. B. wenn der E-Mail-Versand scheiterte)."""
    db.execute("DELETE FROM zeit_meldungen WHERE art=%s AND mitarbeiter_id=%s"
               " AND bezug=%s", (art, ma_id, str(bezug)[:40]))


def buero_email(settings):
    return (settings.get("zeit_buero_email") or settings.get(
        "zeit_fehler_mail_an") or settings.get("firma_email") or "").strip()


# ---------------------------------------------------------------------------
# Einspringen: Anfrage je Gruppe und Tag, Antwort je Mitarbeiter
# ---------------------------------------------------------------------------
EINSPRING_STATUS = {"offen": "offen", "besetzt": "besetzt",
                    "erledigt": "erledigt"}
EINSPRING_ANTWORT = {"offen": "keine Antwort", "ja": "Zusage",
                     "nein": "Absage"}


def einspring_anfragen_anlegen(db, empfaenger, krank_ma_id=None, von="",
                               mit_antworten=True):
    """empfaenger: Liste (ma, gruppe, tage) wie im Einspringen-Dialog
    (tage = Ergebnis von besetzung() mit 'unter'). Legt je Gruppe und Tag
    eine Anfrage an (bzw. nutzt eine offene) und für jeden Empfänger eine
    offene Antwort für die Tage, an denen er nicht selbst ganztägig
    abwesend ist. Liefert die Anzahl der Anfragen."""
    jetzt = _jetzt()
    anfragen = {}
    for m, g, tage in empfaenger:
        abw = {}
        if tage:
            abw = abwesenheiten_laden(db, m["id"], tage[0]["datum"],
                                      tage[-1]["datum"], mit_anteil=True)
        for t in tage:
            d = t["datum"]
            key = (g["id"], d)
            if key not in anfragen:
                fehlen = max(Decimal("0.5"), _dec(t.get("mindest") or
                                                  g.get("mindest_anwesend")
                                                  or 0) -
                             _dec(t.get("verfuegbar") or 0))
                alt = db.one("SELECT id FROM einspring_anfragen WHERE "
                             "gruppe_id=%s AND datum=%s AND status='offen'",
                             (g["id"], d))
                if alt:
                    aid = alt["id"]
                    db.execute("UPDATE einspring_anfragen SET fehlen=%s "
                               "WHERE id=%s", (fehlen, aid))
                else:
                    aid = db.execute(
                        "INSERT INTO einspring_anfragen (gruppe_id, datum, "
                        "fehlen, krank_ma_id, status, erstellt, von) VALUES "
                        "(%s,%s,%s,%s,'offen',%s,%s)",
                        (g["id"], d, fehlen, krank_ma_id, jetzt,
                         (von or "")[:40]))
                anfragen[key] = aid
            a = abw.get(d)
            if not mit_antworten or (a and a[1] >= 1):
                continue
            db.execute("INSERT IGNORE INTO einspring_antworten (anfrage_id, "
                       "mitarbeiter_id, antwort) VALUES (%s,%s,'offen')",
                       (anfragen[key], m["id"]))
    return len(anfragen)


def einspring_offen(db, ma_id, heute=None):
    """Offene Anfragen an einen Mitarbeiter (für das Terminal)."""
    heute = heute or datetime.date.today()
    return _sicher(lambda: db.query(
        "SELECT w.id AS antwort_id, a.id, a.datum, a.fehlen, a.gruppe_id, "
        "g.name AS gruppe FROM einspring_antworten w JOIN einspring_anfragen "
        "a ON a.id=w.anfrage_id LEFT JOIN arbeitsgruppen g ON "
        "g.id=a.gruppe_id WHERE w.mitarbeiter_id=%s AND w.antwort='offen' "
        "AND a.status='offen' AND a.datum >= %s ORDER BY a.datum, g.name",
        (ma_id, heute)), []) or []


def einspring_antworten(db, anfrage_id, ma_id, antwort, quelle="terminal"):
    """Zusage ('ja') oder Absage ('nein') speichern. Bei genügend
    Zusagen wird die Anfrage 'besetzt'. Liefert dict mit anfrage, gruppe,
    zusagen (Anzahl) und besetzt (bool)."""
    if antwort not in ("ja", "nein", "offen"):
        raise ValueError("Antwort ja/nein erwartet.")
    a = db.one("SELECT a.*, g.name AS gruppe FROM einspring_anfragen a "
               "LEFT JOIN arbeitsgruppen g ON g.id=a.gruppe_id WHERE a.id=%s",
               (anfrage_id,))
    if not a:
        raise ValueError("Die Anfrage gibt es nicht mehr.")
    db.execute("INSERT INTO einspring_antworten (anfrage_id, mitarbeiter_id, "
               "antwort, zeitpunkt, quelle) VALUES (%s,%s,%s,%s,%s) ON "
               "DUPLICATE KEY UPDATE antwort=VALUES(antwort), "
               "zeitpunkt=VALUES(zeitpunkt), quelle=VALUES(quelle)",
               (anfrage_id, ma_id, antwort,
                _jetzt() if antwort != "offen" else None, quelle[:20]))
    zusagen = int(db.value("SELECT COUNT(*) FROM einspring_antworten WHERE "
                           "anfrage_id=%s AND antwort='ja'", (anfrage_id,))
                  or 0)
    besetzt = zusagen >= _dec(a["fehlen"])
    if a["status"] in ("offen", "besetzt"):
        neu = "besetzt" if besetzt else "offen"
        if neu != a["status"]:
            db.execute("UPDATE einspring_anfragen SET status=%s WHERE id=%s",
                       (neu, anfrage_id))
    return {"anfrage": a, "gruppe": a.get("gruppe") or "", "zusagen":
            zusagen, "besetzt": besetzt}


def einspring_status(db, anfrage_id, status):
    db.execute("UPDATE einspring_anfragen SET status=%s WHERE id=%s",
               (status, anfrage_id))


def einspring_liste(db, ab=None, alle=False):
    """Anfragen ab 'ab' mit ihren Antworten (für das Büro)."""
    ab = ab or (datetime.date.today() - datetime.timedelta(days=7))
    sql = ("SELECT a.*, g.name AS gruppe, g.mindest_anwesend FROM "
           "einspring_anfragen a LEFT JOIN arbeitsgruppen g ON "
           "g.id=a.gruppe_id WHERE a.datum >= %s")
    if not alle:
        sql += " AND a.status<>'erledigt'"
    rows = _sicher(lambda: db.query(sql + " ORDER BY a.datum, g.name",
                                    (ab,)), []) or []
    for a in rows:
        a["antworten"] = db.query(
            "SELECT w.*, m.vorname, m.nachname, m.email FROM "
            "einspring_antworten w JOIN mitarbeiter m ON m.id=w.mitarbeiter_id"
            " WHERE w.anfrage_id=%s ORDER BY FIELD(w.antwort,'ja','offen',"
            "'nein'), m.nachname", (a["id"],))
    return rows


def eingesprungen_tage(db, ma_id, von, bis):
    """Tage, für die der Mitarbeiter das Einspringen zugesagt hat."""
    return {r["datum"] for r in (_sicher(lambda: db.query(
        "SELECT DISTINCT a.datum FROM einspring_antworten w JOIN "
        "einspring_anfragen a ON a.id=w.anfrage_id WHERE w.mitarbeiter_id=%s "
        "AND w.antwort='ja' AND a.datum BETWEEN %s AND %s",
        (ma_id, von, bis)), []) or [])}


def _eingesprungen_gruppe(db, gruppe_id, von, bis):
    """{datum: {ma_id, …}} Zusagen für eine Gruppe."""
    erg = {}
    for r in (_sicher(lambda: db.query(
            "SELECT a.datum, w.mitarbeiter_id FROM einspring_antworten w "
            "JOIN einspring_anfragen a ON a.id=w.anfrage_id WHERE "
            "a.gruppe_id=%s AND w.antwort='ja' AND a.datum BETWEEN %s AND %s",
            (gruppe_id, von, bis)), []) or []):
        erg.setdefault(r["datum"], set()).add(r["mitarbeiter_id"])
    return erg


def einspring_text(a):
    d = a["datum"]
    return (f"{WOCHENTAGE[d.weekday()]} {d:%d.%m.%Y}"
            + (f" – {a['gruppe']}" if a.get("gruppe") else ""))


# ---------------------------------------------------------------------------
# Korrekturanträge (Terminal → Büro)
# ---------------------------------------------------------------------------
KORREKTUR_GRUENDE = ["Stempeln vergessen", "Falsch gestempelt",
                     "Karte vergessen", "Dienstgang / Außentermin",
                     "Terminal gestört"]
KORREKTUR_STATUS = {"offen": "offen", "genehmigt": "genehmigt",
                    "abgelehnt": "abgelehnt", "zurueck": "zurückgezogen"}


def korrektur_beantragen(db, settings, ma, datum, art, zeitpunkt, grund="",
                         quelle="terminal", jetzt=None):
    """Antrag auf eine fehlende/falsche Stempelung. Liefert die ID."""
    if art not in ARTEN:
        raise ValueError("Unbekannte Stempelart.")
    zeitpunkt = zeitpunkt.replace(second=0, microsecond=0)
    jetzt = (jetzt or _jetzt()).replace(microsecond=0)
    if zeitpunkt > jetzt + datetime.timedelta(minutes=5):
        raise ValueError("Der Zeitpunkt liegt in der Zukunft.")
    try:
        tage = max(1, int(settings.get("korrektur_tage") or 14))
    except (TypeError, ValueError):
        tage = 14
    if datum < jetzt.date() - datetime.timedelta(days=tage):
        raise ValueError(f"Korrekturen sind nur für die letzten {tage} Tage "
                         f"möglich. Bitte im Büro melden.")
    if not (datum <= zeitpunkt.date() <= datum + datetime.timedelta(days=1)):
        raise ValueError("Der Zeitpunkt passt nicht zum Tag.")
    if monat_gesperrt(db, ma["id"], datum):
        raise ValueError("Der Monat ist bereits abgeschlossen. Bitte im "
                         "Büro melden.")
    if db.value("SELECT id FROM korrekturantraege WHERE mitarbeiter_id=%s AND "
                "art=%s AND zeitpunkt=%s AND status='offen'",
                (ma["id"], art, zeitpunkt)):
        raise ValueError("Diesen Antrag haben Sie bereits gestellt.")
    if db.value("SELECT id FROM stempelungen WHERE mitarbeiter_id=%s AND "
                "art=%s AND zeitpunkt=%s", (ma["id"], art, zeitpunkt)):
        raise ValueError("Diese Stempelung gibt es bereits.")
    return db.execute(
        "INSERT INTO korrekturantraege (mitarbeiter_id, datum, art, "
        "zeitpunkt, grund, status, erstellt, quelle) VALUES "
        "(%s,%s,%s,%s,%s,'offen',%s,%s)",
        (ma["id"], datum, art, zeitpunkt, (grund or "")[:200], jetzt,
         quelle[:20]))


def korrekturen(db, status="offen", ma_id=None, anzahl=None):
    sql = ("SELECT k.*, m.vorname, m.nachname, m.personalnr, m.email FROM "
           "korrekturantraege k JOIN mitarbeiter m ON m.id=k.mitarbeiter_id "
           "WHERE 1=1")
    p = []
    if status:
        sql += " AND k.status=%s"
        p.append(status)
    if ma_id:
        sql += " AND k.mitarbeiter_id=%s"
        p.append(ma_id)
    sql += " ORDER BY k.status='offen' DESC, k.datum DESC, k.zeitpunkt"
    if anzahl:
        sql += f" LIMIT {int(anzahl)}"
    return _sicher(lambda: db.query(sql, p), []) or []


def korrektur_text(k, mit_name=False):
    zp = k["zeitpunkt"]
    t = (f"{WOCHENTAGE[k['datum'].weekday()]} {k['datum']:%d.%m.}: "
         f"{ARTEN.get(k['art'], k['art'])} {zp:%H:%M}"
         + (" (+1)" if zp.date() > k["datum"] else ""))
    if mit_name:
        t = f"{ma_name(k)} – {t}"
    return t


def korrektur_genehmigen(db, antrag_id, benutzer="", antwort=""):
    """Fügt die beantragte Stempelung ein. Liefert (antrag, stempel_id)."""
    k = db.one("SELECT * FROM korrekturantraege WHERE id=%s", (antrag_id,))
    if not k:
        raise ValueError("Den Antrag gibt es nicht mehr.")
    if k["status"] != "offen":
        raise ValueError("Der Antrag ist nicht mehr offen.")
    pruefe_offen(db, k["mitarbeiter_id"], k["datum"], "Korrekturen")
    sid = None
    if not db.value("SELECT id FROM stempelungen WHERE mitarbeiter_id=%s AND "
                    "art=%s AND zeitpunkt=%s",
                    (k["mitarbeiter_id"], k["art"], k["zeitpunkt"])):
        sid = _einfuegen(db, k["mitarbeiter_id"], k["art"], k["zeitpunkt"],
                         "korrektur", "", ("Korrekturantrag: " +
                                           (k["grund"] or ""))[:200])
    db.execute("UPDATE korrekturantraege SET status='genehmigt', "
               "bearbeitet=%s, bearbeitet_von=%s, antwort=%s, stempel_id=%s "
               "WHERE id=%s", (_jetzt(), (benutzer or "")[:40],
                               (antwort or "")[:200], sid, antrag_id))
    return k, sid


def korrektur_ablehnen(db, antrag_id, benutzer="", antwort=""):
    k = db.one("SELECT * FROM korrekturantraege WHERE id=%s", (antrag_id,))
    if not k or k["status"] != "offen":
        raise ValueError("Der Antrag ist nicht mehr offen.")
    db.execute("UPDATE korrekturantraege SET status='abgelehnt', "
               "bearbeitet=%s, bearbeitet_von=%s, antwort=%s WHERE id=%s",
               (_jetzt(), (benutzer or "")[:40], (antwort or "")[:200],
                antrag_id))
    return k


def korrektur_zurueckziehen(db, ma_id, antrag_id):
    n = db.aendern("UPDATE korrekturantraege SET status='zurueck', "
                   "bearbeitet=%s WHERE id=%s AND mitarbeiter_id=%s AND "
                   "status='offen'", (_jetzt(), antrag_id, ma_id))
    if not n:
        raise ValueError("Der Antrag ist nicht mehr offen.")


def korrektur_vorschlag(db, settings, ma, heute=None):
    """Vorschlag für den Antrag am Terminal: der jüngste Tag der letzten
    Tage mit fehlendem Geht (dann 'geht') bzw. heute/'kommt'.
    Liefert (datum, art)."""
    heute = heute or datetime.date.today()
    try:
        tage_n = max(1, int(settings.get("korrektur_tage") or 14))
    except (TypeError, ValueError):
        tage_n = 14
    von = heute - datetime.timedelta(days=min(tage_n, 14))
    r = regeln(settings, ma)
    stempel, _ = arbeitstage_laden(db, ma["id"], von, heute, r)
    jetzt = datetime.datetime.now()
    for d in sorted(stempel, reverse=True):
        t = tag_auswerten(stempel[d])
        if d == heute and t["offen"]:
            continue                  # läuft noch
        if t["offen"] and not laeuft_noch(t, r, jetzt, d):
            return d, ("pause_ende" if t["status"] == "pause" else "geht")
        if any("Kommt" in f and "ohne vorheriges Geht" in f
               for f in t["fehler"]):
            return d, "geht"
        if any("Geht ohne Kommt" in f for f in t["fehler"]):
            return d, "kommt"
    return heute, ("kommt" if not stempel.get(heute) else "geht")


# ---------------------------------------------------------------------------
# Erinnerung bei offenem Kommt
# ---------------------------------------------------------------------------
def offen_eingestempelt(db, settings, jetzt=None):
    """Mitarbeiter, deren letzte Stempelung (Kommt/Pause) länger als
    'zeit_erinnerung_stunden' zurückliegt. Liefert Liste von dicts ma,
    seit (letztes Kommt), stempel_id, stunden."""
    jetzt = jetzt or datetime.datetime.now()
    try:
        grenze = float(str(settings.get("zeit_erinnerung_stunden") or "10")
                       .replace(",", "."))
    except ValueError:
        grenze = 10.0
    ab = jetzt - datetime.timedelta(days=3)
    erg = []
    for ma in db.query("SELECT * FROM mitarbeiter WHERE aktiv=1"):
        letzte = db.one("SELECT id, zeitpunkt, art FROM stempelungen WHERE "
                        "mitarbeiter_id=%s AND zeitpunkt >= %s AND "
                        "zeitpunkt <= %s ORDER BY zeitpunkt DESC, id DESC "
                        "LIMIT 1", (ma["id"], ab, jetzt))
        if not letzte or letzte["art"] == "geht":
            continue
        kommt = db.one("SELECT id, zeitpunkt FROM stempelungen WHERE "
                       "mitarbeiter_id=%s AND art='kommt' AND zeitpunkt <= %s "
                       "AND zeitpunkt >= %s ORDER BY zeitpunkt DESC LIMIT 1",
                       (ma["id"], letzte["zeitpunkt"], ab))
        if not kommt:
            continue
        stunden = (jetzt - kommt["zeitpunkt"]).total_seconds() / 3600
        if stunden >= grenze:
            erg.append({"ma": ma, "seit": kommt["zeitpunkt"],
                        "stempel_id": kommt["id"], "stunden": stunden,
                        "pause": letzte["art"] == "pause_an"})
    return erg


# ---------------------------------------------------------------------------
# Tägliche Monats-Stundenaufstellung: MA > Gruppe > Firmenstamm
# ---------------------------------------------------------------------------
TAGESMAIL_WAHL = {None: "", 1: "ja", 0: "nein"}


def tagesmail_aktiv(settings, ma, gruppen=None):
    """Bekommt der Mitarbeiter die tägliche Aufstellung? Liefert
    (bool, quelle). gruppen: {id: gruppe}."""
    v = ma.get("tagesmail")
    if v is not None and v != "":
        return bool(int(v)), "Mitarbeiter"
    for g in _gruppen_des_ma(ma, gruppen or {}):
        if g.get("tagesmail") is not None and g.get("tagesmail") != "":
            return bool(int(g["tagesmail"])), f"Gruppe {g['name']}"
    return settings.get("zeit_tagesmail") == "1", "Firmenstamm"


def gearbeitet_am(db, ma_ids, tage):
    """{ma_id} der Mitarbeiter mit einem Kommt an einem der Tage."""
    if not ma_ids or not tage:
        return set()
    platz = ",".join(["%s"] * len(ma_ids))
    von = datetime.datetime.combine(min(tage), datetime.time())
    bis = datetime.datetime.combine(max(tage) + datetime.timedelta(days=1),
                                    datetime.time())
    tage = set(tage)
    erg = set()
    for r in db.query(f"SELECT mitarbeiter_id, zeitpunkt FROM stempelungen "
                      f"WHERE art='kommt' AND mitarbeiter_id IN ({platz}) "
                      f"AND zeitpunkt >= %s AND zeitpunkt < %s",
                      list(ma_ids) + [von, bis]):
        if r["zeitpunkt"].date() in tage:
            erg.add(r["mitarbeiter_id"])
    return erg


# ---------------------------------------------------------------------------
# Ampelkonto
# ---------------------------------------------------------------------------
AMPEL = {"gruen": "grün", "gelb": "gelb", "rot": "rot"}
AMPEL_FELDER = ("ampel_plus_gelb", "ampel_plus_rot", "ampel_minus_gelb",
                "ampel_minus_rot")


def ampel_aktiv(settings):
    return settings.get("zeit_ampel") == "1"


def ampel_grenzen(settings, ma=None):
    """Grenzen in Minuten: {feld: minuten} (Mitarbeiter, sonst global)."""
    erg = {}
    for f in AMPEL_FELDER:
        v = (ma or {}).get(f)
        if v is None or v == "":
            v = settings.get(f"zeit_{f}")
        try:
            erg[f] = int(round(float(str(v).replace(",", ".")) * 60)) \
                if v not in (None, "") else None
        except ValueError:
            erg[f] = None
    return erg


def ampel(settings, ma, saldo_min):
    """'gruen' | 'gelb' | 'rot' (oder None, wenn das Ampelkonto aus ist)."""
    if not ampel_aktiv(settings) or saldo_min is None:
        return None
    g = ampel_grenzen(settings, ma)
    if saldo_min >= 0:
        rot, gelb = g["ampel_plus_rot"], g["ampel_plus_gelb"]
        wert = saldo_min
    else:
        rot, gelb = g["ampel_minus_rot"], g["ampel_minus_gelb"]
        wert = -saldo_min
    if rot is not None and wert >= rot:
        return "rot"
    if gelb is not None and wert >= gelb:
        return "gelb"
    return "gruen"


def ampel_text(settings, ma=None):
    g = ampel_grenzen(settings, ma)

    def h(v):
        return "–" if v is None else fmt_std(v)
    return (f"Plus: gelb ab {h(g['ampel_plus_gelb'])}, rot ab "
            f"{h(g['ampel_plus_rot'])} Std · Minus: gelb ab "
            f"{h(g['ampel_minus_gelb'])}, rot ab {h(g['ampel_minus_rot'])} "
            f"Std")


# ---------------------------------------------------------------------------
# Dienstplan
# ---------------------------------------------------------------------------
DIENST = {"tag": "Tagschicht", "spaet": "Spätschicht", "nacht": "Nachtschicht",
          "eigen": "eigene Zeit", "frei": "frei"}
DIENST_KURZ = {"tag": "Tag", "spaet": "Spät", "nacht": "Nacht",
               "eigen": "", "frei": "frei"}


def dienstplan_laden(db, ma_ids, von, bis):
    """{(ma_id, datum): eintrag}."""
    if not ma_ids:
        return {}
    platz = ",".join(["%s"] * len(ma_ids))
    rows = _sicher(lambda: db.query(
        f"SELECT * FROM dienstplan WHERE mitarbeiter_id IN ({platz}) AND "
        f"datum BETWEEN %s AND %s", list(ma_ids) + [von, bis]), []) or []
    return {(r["mitarbeiter_id"], r["datum"]): r for r in rows}


def dienstplan_setzen(db, ma_id, datum, schicht, beginn=None, ende=None,
                      bemerkung="", benutzer=""):
    """Eintrag setzen; schicht '' löscht ihn."""
    if not schicht:
        db.execute("DELETE FROM dienstplan WHERE mitarbeiter_id=%s AND "
                   "datum=%s", (ma_id, datum))
        return
    if schicht not in DIENST:
        raise ValueError("Unbekannte Schicht.")
    if schicht == "eigen":
        beginn = uhr_pruefen(beginn, "Beginn")
        ende = uhr_pruefen(ende, "Ende")
        if not beginn or not ende:
            raise ValueError("Für eigene Zeiten bitte Beginn und Ende "
                             "eintragen.")
    else:
        beginn = ende = None
    db.execute("INSERT INTO dienstplan (mitarbeiter_id, datum, schicht, "
               "beginn, ende, bemerkung, geaendert, geaendert_von) VALUES "
               "(%s,%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE "
               "schicht=VALUES(schicht), beginn=VALUES(beginn), "
               "ende=VALUES(ende), bemerkung=VALUES(bemerkung), "
               "geaendert=VALUES(geaendert), "
               "geaendert_von=VALUES(geaendert_von)",
               (ma_id, datum, schicht, beginn, ende, (bemerkung or "")[:120],
                _jetzt(), (benutzer or "")[:40]))


def dienstplan_kopieren(db, ma_ids, quelle_montag, ziel_montag, benutzer="",
                        ueberschreiben=False):
    """Woche kopieren. Liefert die Anzahl kopierter Einträge."""
    alt = dienstplan_laden(db, ma_ids, quelle_montag,
                           quelle_montag + datetime.timedelta(days=6))
    ziel = dienstplan_laden(db, ma_ids, ziel_montag,
                            ziel_montag + datetime.timedelta(days=6))
    n = 0
    for (mid, d), e in alt.items():
        nd = ziel_montag + (d - quelle_montag)
        if (mid, nd) in ziel and not ueberschreiben:
            continue
        dienstplan_setzen(db, mid, nd, e["schicht"], e.get("beginn"),
                          e.get("ende"), e.get("bemerkung") or "", benutzer)
        n += 1
    return n


def _schichtzeiten_immer(settings, ma, gruppen):
    """Schichtzeiten (Mitarbeiter > Gruppe > Firmenstamm), auch wenn
    'Schichten verwenden' aus ist (für den Dienstplan)."""
    s2 = dict(settings, zeit_schichten="1",
              zeit_schicht_standard=settings.get("zeit_schicht_standard")
              or "auto")
    v = schicht_vorgaben(s2, dict(ma, schicht=ma.get("schicht") or "auto"),
                         gruppen)
    return v


def dienst_zeiten(eintrag, settings, ma, gruppen=None):
    """(beginn, ende) als datetime.time eines Plan-Eintrags oder
    (None, None) bei 'frei' bzw. fehlenden Schichtzeiten."""
    if not eintrag or eintrag["schicht"] == "frei":
        return None, None
    if eintrag["schicht"] == "eigen":
        return uhr_lesen(eintrag.get("beginn")), uhr_lesen(eintrag.get("ende"))
    v = _schichtzeiten_immer(settings, ma, gruppen)
    if not v:
        return None, None
    return v["zeiten"].get(eintrag["schicht"], (None, None))


def dienst_minuten(beginn, ende, r=None):
    """Geplante Arbeitszeit in Minuten (Pause laut Regel abgezogen)."""
    if not beginn or not ende:
        return 0
    b = beginn.hour * 60 + beginn.minute
    e = ende.hour * 60 + ende.minute
    if e <= b:
        e += 1440
    m = e - b
    if r and r.get("pause_min") and m > r.get("pause_ab_min", 0):
        m -= r["pause_min"]
    return max(0, m)


def dienst_text(eintrag, zeiten=None, kurz=False):
    if not eintrag:
        return ""
    s = eintrag["schicht"]
    if s == "frei":
        return "frei"
    b, e = zeiten or (uhr_lesen(eintrag.get("beginn")),
                      uhr_lesen(eintrag.get("ende")))
    zeit_t = f"{b:%H:%M}–{e:%H:%M}" if b and e else ""
    if kurz:
        return (DIENST_KURZ.get(s, "") + " " + zeit_t).strip()
    name = DIENST.get(s, s) if s != "eigen" else "Dienst"
    return (name + " " + zeit_t).strip()


def _plan_vorgaben(basis, beginn, ende):
    v = dict(basis or {"abzug": 0, "raster": 0, "nach_ende": "kappen",
                       "quelle": {}})
    v["zuordnung"] = "plan"
    v["zeiten"] = {"plan": (beginn, ende)}
    return v


def korrektur_zeit_vorschlag(db, settings, ma, datum, art, jetzt=None):
    """Vorschlag für die Uhrzeit eines Korrekturantrags (5-Minuten-Raster,
    nicht in der Zukunft)."""
    jetzt = (jetzt or datetime.datetime.now()).replace(second=0,
                                                       microsecond=0)
    r = regeln(settings, ma, datum, modelle_laden(db, ma["id"]))
    stempel, _ = arbeitstage_laden(db, ma["id"], datum, datum, regeln(
        settings, ma))
    st = sorted(stempel.get(datum, []))
    soll = soll_fuer(r, datum.weekday()) or r["tages_soll"]
    dauer = datetime.timedelta(minutes=soll + (r["pause_min"] if soll >
                                                r["pause_ab_min"] else 0))
    kommt = [zp for zp, a in st if a == "kommt"]
    geht = [zp for zp, a in st if a == "geht"]
    pause_an = [zp for zp, a in st if a == "pause_an"]
    if art == "geht" and kommt:
        zp = kommt[-1] + dauer
    elif art == "kommt" and geht:
        zp = geht[0] - dauer
    elif art == "pause_ende" and pause_an:
        zp = pause_an[-1] + datetime.timedelta(minutes=r["pause_min"] or 30)
    elif art == "pause_an":
        zp = datetime.datetime.combine(datum, datetime.time(12, 0))
    else:
        zp = datetime.datetime.combine(datum, datetime.time(7, 0)
                                       if art == "kommt" else
                                       datetime.time(16, 0))
    if zp.date() < datum:
        zp = datetime.datetime.combine(datum, datetime.time(0, 0))
    if zp.date() > datum + datetime.timedelta(days=1):
        zp = datetime.datetime.combine(datum, datetime.time(23, 55))
    zp = zp.replace(minute=zp.minute - zp.minute % 5, second=0,
                    microsecond=0)
    if zp > jetzt:
        zp = jetzt.replace(minute=jetzt.minute - jetzt.minute % 5)
    return zp


def plan_vorschau(db, settings, ma, ab=None, tage=7):
    """Die nächsten Dienste laut Dienstplan als Textliste."""
    ab = ab or datetime.date.today()
    bis = ab + datetime.timedelta(days=tage - 1)
    plan = dienstplan_laden(db, [ma["id"]], ab, bis)
    if not plan:
        return []
    gruppen = {g["id"]: g for g in arbeitsgruppen(db, False)}
    erg = []
    d = ab
    while d <= bis:
        e = plan.get((ma["id"], d))
        if e:
            erg.append(f"{WOCHENTAGE[d.weekday()]} {d:%d.%m.} "
                       f"{dienst_text(e, dienst_zeiten(e, settings, ma, gruppen), kurz=True)}")
        d += datetime.timedelta(days=1)
    return erg


def dienstplan_woche(db, settings, mitarbeiter, montag, jetzt=None):
    """Daten für die Wochenansicht des Dienstplans. Liefert (zeilen,
    feiertage). zeilen: [{ma, zellen: [{datum, plan, zeiten, text, abw,
    abw_anteil, ist, status ('da'|'fehlt'|'zusaetzlich'|''), feiertag,
    minuten}], summe (geplante Minuten)}]."""
    jetzt = jetzt or datetime.datetime.now()
    heute = jetzt.date()
    tage = [montag + datetime.timedelta(days=i) for i in range(7)]
    sonntag = tage[-1]
    ids = [m["id"] for m in mitarbeiter]
    plan = dienstplan_laden(db, ids, montag, sonntag)
    gruppen = {g["id"]: g for g in arbeitsgruppen(db, False)}
    ft = {}
    for j in {montag.year, sonntag.year}:
        ft.update(feiertage(j, settings.get("zeit_bundesland"),
                            settings.get("zeit_maria_himmelfahrt") == "1"))
    abw = {}
    if ids:
        platz = ",".join(["%s"] * len(ids))
        for r in db.query(f"SELECT mitarbeiter_id, datum, art, anteil FROM "
                          f"abwesenheiten WHERE mitarbeiter_id IN ({platz}) "
                          f"AND datum BETWEEN %s AND %s",
                          ids + [montag, sonntag]):
            abw[(r["mitarbeiter_id"], r["datum"])] = (r["art"],
                                                      _dec(r["anteil"]))
    zeilen = []
    for ma in mitarbeiter:
        ist = {}
        if montag <= heute:
            t_liste, _ = zeitraum_auswerten(db, settings, ma, montag,
                                            min(sonntag, heute), jetzt)
            ist = {t["datum"]: t for t in t_liste}
        r = regeln(settings, ma)
        zellen, summe = [], 0
        for d in tage:
            e = plan.get((ma["id"], d))
            z = dienst_zeiten(e, settings, ma, gruppen) if e else (None, None)
            minuten = dienst_minuten(*z, r) if e and e["schicht"] != "frei" \
                else 0
            summe += minuten
            a = abw.get((ma["id"], d))
            t = ist.get(d)
            status = ""
            if t:
                if t["kommt"] and t["fehler"] and not t["laeuft"]:
                    status = "fehler"
                elif t["kommt"]:
                    status = "zusaetzlich" if e and e["schicht"] == "frei" \
                        else "da"
                elif e and e["schicht"] != "frei" and d < heute and not a \
                        and d not in ft:
                    status = "fehlt"
            zellen.append({"datum": d, "plan": e, "zeiten": z,
                           "text": dienst_text(e, z, kurz=True),
                           "abw": a[0] if a else None,
                           "abw_anteil": a[1] if a else 0,
                           "ist": t["ist"] if t else 0, "status": status,
                           "feiertag": ft.get(d), "minuten": minuten})
        zeilen.append({"ma": ma, "zellen": zellen, "summe": summe})
    return zeilen, ft


def dienstplan_besetzung(zeilen):
    """Je Wochentag (0..6) die Anzahl eingeteilter Mitarbeiter (nicht
    frei, nicht ganztägig abwesend; halbe Abwesenheit zählt halb)."""
    erg = [Decimal(0)] * 7
    for z in zeilen:
        for i, c in enumerate(z["zellen"]):
            if c["plan"] and c["plan"]["schicht"] != "frei":
                erg[i] += Decimal(1) - _dec(c["abw_anteil"] or 0)
    return erg
