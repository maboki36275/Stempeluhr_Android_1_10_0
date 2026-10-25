# -*- coding: utf-8 -*-
"""Nur für die Android-App: Auftragsbearbeitung am Tablet (seit App 1.9).

Bis 1.9.1 stand dieser Block am Ende der zeit.py. Seit 1.10.0 liegt er hier,
damit zeit.py und db.py wieder unverändert aus der Faktura übernommen
werden können (bei neuen Faktura-Versionen einfach beide ersetzen)."""

import datetime

from zeit import _sicher


# ---------------------------------------------------------------------------
# (1.9 / Faktura 10.3) Modul Auftragsverarbeitung – Buchung am Tablet
# ---------------------------------------------------------------------------
def av_sichtbar_fuer(db, ma_id):
    """Offene Aufträge, die dieser Mitarbeiter am Tablet sehen darf
    (zugeordnet über 'alle', Gruppe oder einzeln)."""
    def lesen():
        ma = db.one("SELECT id, gruppe1_id, gruppe2_id FROM mitarbeiter "
                    "WHERE id=%s", (ma_id,))
        if not ma:
            return []
        gruppen = [g for g in (ma["gruppe1_id"], ma["gruppe2_id"]) if g]
        treffer = []
        for a in db.query("SELECT * FROM av_auftrag WHERE status='offen' "
                          "ORDER BY nummer"):
            if a["zuordnung_art"] == "alle":
                treffer.append(a)
                continue
            zu = db.query("SELECT art, ref_id FROM av_zuordnung WHERE "
                          "auftrag_id=%s", (a["id"],))
            if any((r["art"] == "mitarbeiter" and r["ref_id"] == ma_id) or
                   (r["art"] == "gruppe" and r["ref_id"] in gruppen)
                   for r in zu):
                treffer.append(a)
        return treffer
    return _sicher(lesen, []) or []


def av_schritte(db, auftrag_id):
    return _sicher(lambda: db.query(
        "SELECT * FROM av_schritt WHERE auftrag_id=%s ORDER BY sortierung, "
        "id", (auftrag_id,)), []) or []


def av_material(db, auftrag_id):
    return _sicher(lambda: db.query(
        "SELECT * FROM av_material WHERE auftrag_id=%s ORDER BY sortierung, "
        "id", (auftrag_id,)), []) or []


def av_zeit_buchen(db, auftrag_id, ma_id, minuten, schritt_id=None,
                   quelle="tablet"):
    j = datetime.datetime.now().replace(microsecond=0)
    return db.execute(
        "INSERT INTO av_zeit (auftrag_id, schritt_id, mitarbeiter_id, datum, "
        "minuten, bemerkung, quelle, erstellt) VALUES "
        "(%s, %s, %s, %s, %s, %s, %s, %s)",
        (auftrag_id, schritt_id or None, ma_id, j.date(),
         int(round(minuten)), "", quelle[:20], j))


def av_verbrauch_buchen(db, auftrag_id, ma_id, menge, material_id=None,
                        quelle="tablet", lager_abbuchen=False):
    """Materialverbrauch am Tablet buchen. Bei aktivem Lager wird der
    Lagerbestand des Artikels zusätzlich verringert."""
    from db import to_decimal
    j = datetime.datetime.now().replace(microsecond=0)
    menge = to_decimal(menge)
    artikel_id = None
    bez = ""
    einheit = "Stk"
    if material_id:
        m = db.one("SELECT artikel_id, bezeichnung, einheit FROM av_material "
                   "WHERE id=%s", (material_id,))
        if m:
            artikel_id = m["artikel_id"]
            bez = m["bezeichnung"]
            einheit = m.get("einheit") or "Stk"
    lb_id = None
    if lager_abbuchen and artikel_id and menge > 0:
        try:
            db.execute("UPDATE artikel SET bestand=bestand-%s WHERE id=%s",
                       (menge, artikel_id))
            best = db.value("SELECT bestand FROM artikel WHERE id=%s",
                            (artikel_id,))
            lb_id = db.execute(
                "INSERT INTO lagerbewegungen (artikel_id, zeitpunkt, menge, "
                "bestand_nachher, art, bemerkung, benutzer) VALUES "
                "(%s, %s, %s, %s, %s, %s, %s)",
                (artikel_id, j, -menge, best or 0, "Auftrag",
                 f"Auftrag {auftrag_id}", "tablet"))
        except Exception:
            lb_id = None
    return db.execute(
        "INSERT INTO av_verbrauch (auftrag_id, material_id, artikel_id, "
        "mitarbeiter_id, datum, bezeichnung, einheit, menge, lagerbewegung, "
        "quelle, erstellt) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
        "%s)",
        (auftrag_id, material_id or None, artikel_id or None, ma_id, j.date(),
         bez[:200], einheit, menge, lb_id, quelle[:20], j))
