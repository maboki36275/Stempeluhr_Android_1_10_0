# -*- coding: utf-8 -*-
"""
Datenbankzugriff (MariaDB) für die Faktura.

- Verbindung per PyMySQL (reines Python, läuft unter Windows und Linux)
- legt die Datenbank "Firma" und alle Tabellen beim ersten Start selbst an
- Einstellungen / Firmenstamm werden als Schlüssel/Wert-Paare in der
  Tabelle "einstellungen" gespeichert (Standardwerte siehe DEFAULTS)
"""

import datetime
import threading
import time
from contextlib import contextmanager
from decimal import Decimal

import pymysql
import pymysql.cursors


# ---------------------------------------------------------------------------
# Standardwerte für Firmenstamm und Einstellungen
# ---------------------------------------------------------------------------
DEFAULTS = {
    # Firmenstamm
    "firma_name": "Meine Firma",
    "firma_zusatz": "",
    "firma_inhaber": "",
    "firma_strasse": "",
    "firma_plz": "",
    "firma_ort": "",
    "firma_land": "DE",
    "firma_telefon": "",
    "firma_email": "",
    "firma_web": "",
    "firma_ustid": "",
    "firma_steuernr": "",
    "firma_register": "",          # z.B. "Amtsgericht München HRB 12345"
    "firma_geschaeftsfuehrer": "",
    "bank_name": "",
    "bank_iban": "",
    "bank_bic": "",
    "bank_inhaber": "",
    "logo_pfad": "",

    # Mehrwertsteuer: drei Sätze (Schlüssel 1..3)
    # Kategorie nach EN 16931: S=Normal, Z=Nullsatz, E=steuerbefreit,
    # AE=Reverse Charge, K=innergem. Lieferung, G=Export, O=nicht steuerbar
    "mwst1_satz": "19.00", "mwst1_kat": "S", "mwst1_grund": "",
    "mwst1_name": "Regelsatz",
    "mwst2_satz": "7.00", "mwst2_kat": "S", "mwst2_grund": "",
    "mwst2_name": "ermäßigt",
    "mwst3_satz": "0.00", "mwst3_kat": "E",
    "mwst3_grund": "Steuerfrei gem. § 4 UStG",
    "mwst3_name": "steuerfrei",

    # Zahlungsbedingungen (global, pro Kunde überschreibbar)
    "zahlungsziel_tage": "14",
    "skonto_tage": "7",
    "skonto_prozent": "2.00",

    # Rabatt-Ermittlung: "max" = höherer von Kunden-/Artikelrabatt,
    # "kombiniert" = beide nacheinander (z.B. 10% und 5% -> 14,5%)
    "rabatt_modus": "max",

    # Nummernkreise ({jahr} und {nr} werden ersetzt)
    # A = Angebot, B = Auftragsbestätigung, L = Lieferschein,
    # R = Rechnung, G = Gutschrift/Rechnungskorrektur, M = Mahnung,
    # E = Bestellung (Einkauf)
    "nr_format_A": "AN{jahr}-{nr:04d}",
    "nr_format_B": "AB{jahr}-{nr:04d}",
    "nr_format_L": "LS{jahr}-{nr:04d}",
    "nr_format_R": "RE{jahr}-{nr:04d}",
    "nr_format_G": "GS{jahr}-{nr:04d}",
    "nr_format_M": "MA{jahr}-{nr:04d}",
    "nr_format_E": "BE{jahr}-{nr:04d}",
    "nr_start_A": "1",              # erste laufende Nummer in jedem Jahr
    "nr_start_B": "1",
    "nr_start_L": "1",
    "nr_start_R": "1",
    "nr_start_G": "1",
    "nr_start_M": "1",
    "nr_start_E": "1",
    "kundennr_start": "10001",
    "lieferantennr_start": "70001",

    # Texte
    "angebot_kopftext": "Sehr geehrte Damen und Herren,\n"
                        "vielen Dank für Ihre Anfrage. Gerne bieten wir "
                        "Ihnen an:",
    "angebot_fusstext": "Wir freuen uns auf Ihren Auftrag.\n"
                        "Mit freundlichen Grüßen",
    "angebot_gueltig_tage": "30",
    "rechnung_kopftext": "Sehr geehrte Damen und Herren,\n"
                         "für unsere Leistungen erlauben wir uns, Ihnen "
                         "Folgendes in Rechnung zu stellen:",
    "rechnung_fusstext": "Vielen Dank für Ihren Auftrag.\n"
                         "Mit freundlichen Grüßen",
    "auftrag_kopftext": "Sehr geehrte Damen und Herren,\n"
                        "vielen Dank für Ihren Auftrag, den wir hiermit wie "
                        "folgt bestätigen:",
    "auftrag_fusstext": "Wir danken für Ihr Vertrauen.\n"
                        "Mit freundlichen Grüßen",
    "lieferschein_kopftext": "Sehr geehrte Damen und Herren,\n"
                             "wir liefern Ihnen folgende Waren bzw. "
                             "Leistungen:",
    "lieferschein_fusstext": "Bitte prüfen Sie die Lieferung auf "
                             "Vollständigkeit.",
    "lieferschein_preise": "0",     # 1 = Preise auf dem Lieferschein
    "gutschrift_kopftext": "Sehr geehrte Damen und Herren,\n"
                           "hiermit schreiben wir Ihnen folgenden Betrag "
                           "gut:",
    "gutschrift_fusstext": "Mit freundlichen Grüßen",
    "abschlag_text": "{nr}. Abschlagsrechnung gemäß Auftrag {auftrag}",
    "bestellung_kopftext": "Sehr geehrte Damen und Herren,\n"
                           "hiermit bestellen wir zu den vereinbarten "
                           "Konditionen:",
    "bestellung_fusstext": "Bitte bestätigen Sie uns die Bestellung und den "
                           "Liefertermin.\nMit freundlichen Grüßen",

    # Lager
    "lager_rechnung_bucht": "1",    # Rechnung ohne Lieferschein bucht ab
    "lager_negativ_warnen": "1",

    # Wiederkehrende Rechnungen
    "abo_auto": "0",                # fällige Abo-Rechnungen automatisch
    "abo_uhrzeit": "07:00",

    # Ablage
    "pdf_verzeichnis": "",          # leer = Unterordner "Belege" im Programmverzeichnis

    # E-Mail (SMTP)
    "smtp_server": "",
    "smtp_port": "465",
    "smtp_verschluesselung": "SSL",  # SSL | STARTTLS | keine
    "smtp_benutzer": "",
    "smtp_passwort": "",
    "email_absender": "",
    "email_bcc": "",                 # Kopie an sich selbst (optional)
    "email_betreff_rechnung": "Rechnung {nummer}",
    "email_text_rechnung": "Sehr geehrte Damen und Herren,\n\n"
                           "anbei erhalten Sie unsere Rechnung {nummer} "
                           "vom {datum} über {brutto}.\n"
                           "Die Rechnung liegt im ZUGFeRD-Format vor "
                           "(PDF mit eingebetteten XML-Rechnungsdaten).\n\n"
                           "Mit freundlichen Grüßen\n{firma}",
    "email_betreff_angebot": "Angebot {nummer}",
    "email_text_angebot": "Sehr geehrte Damen und Herren,\n\n"
                          "anbei erhalten Sie unser Angebot {nummer} "
                          "vom {datum}.\n\nMit freundlichen Grüßen\n{firma}",
    "email_betreff_auftrag": "Auftragsbestätigung {nummer}",
    "email_text_auftrag": "Sehr geehrte Damen und Herren,\n\n"
                          "anbei erhalten Sie unsere Auftragsbestätigung "
                          "{nummer} vom {datum}.\n\nMit freundlichen Grüßen"
                          "\n{firma}",
    "email_betreff_lieferschein": "Lieferschein {nummer}",
    "email_text_lieferschein": "Sehr geehrte Damen und Herren,\n\n"
                               "anbei erhalten Sie unseren Lieferschein "
                               "{nummer} vom {datum}.\n\nMit freundlichen "
                               "Grüßen\n{firma}",
    "email_betreff_gutschrift": "Gutschrift {nummer}",
    "email_text_gutschrift": "Sehr geehrte Damen und Herren,\n\n"
                             "anbei erhalten Sie unsere Gutschrift "
                             "{nummer} vom {datum} über {brutto}.\n\n"
                             "Mit freundlichen Grüßen\n{firma}",
    "email_betreff_bestellung": "Bestellung {nummer}",
    "email_text_bestellung": "Sehr geehrte Damen und Herren,\n\n"
                             "anbei erhalten Sie unsere Bestellung {nummer} "
                             "vom {datum}.\n\nMit freundlichen Grüßen\n"
                             "{firma}",

    # Mahnwesen
    "mahn_auto": "0",               # 1 = Mahnlauf automatisch (Start + täglich)
    "mahn_auto_uhrzeit": "09:00",
    "mahn1_tage": "7",              # Tage nach Fälligkeit
    "mahn2_tage": "14",             # Tage nach vorheriger Mahnung
    "mahn3_tage": "14",
    "mahn1_gebuehr": "0.00",
    "mahn2_gebuehr": "5.00",
    "mahn3_gebuehr": "10.00",
    "mahn_frist_tage": "10",        # neue Zahlungsfrist in der Mahnung
    "mahn1_titel": "Zahlungserinnerung",
    "mahn2_titel": "1. Mahnung",
    "mahn3_titel": "2. Mahnung",
    "mahn1_text": "sicherlich haben Sie in der Hektik des Alltags "
                  "übersehen, die folgende Rechnung zu begleichen. Wir "
                  "bitten Sie, den offenen Betrag bis zum {frist} zu "
                  "überweisen. Sollten Sie die Zahlung bereits veranlasst "
                  "haben, betrachten Sie dieses Schreiben bitte als "
                  "gegenstandslos.",
    "mahn2_text": "leider konnten wir zu der folgenden Rechnung trotz "
                  "unserer Zahlungserinnerung noch keinen Zahlungseingang "
                  "feststellen. Bitte überweisen Sie den offenen Betrag "
                  "zuzüglich Mahngebühr bis zum {frist}.",
    "mahn3_text": "trotz wiederholter Aufforderung ist die folgende "
                  "Rechnung weiterhin offen. Wir fordern Sie letztmalig "
                  "auf, den Gesamtbetrag bis zum {frist} zu überweisen. "
                  "Nach Ablauf dieser Frist werden wir die Forderung ohne "
                  "weitere Ankündigung an ein Inkassobüro übergeben.",
    "mahn_email_betreff": "{titel} zu Rechnung {nummer}",
    "mahn_email_text": "Sehr geehrte Damen und Herren,\n\n"
                       "anbei erhalten Sie unsere {titel} zur Rechnung "
                       "{nummer} vom {datum}. Offener Betrag: {offen}.\n\n"
                       "Mit freundlichen Grüßen\n{firma}",

    # DATEV
    "datev_berater": "",
    "datev_mandant": "",
    "datev_wj_beginn": "0101",      # TTMM
    "datev_sachkontenlaenge": "4",
    "datev_skr": "03",
    "datev_bankkonto": "1200",      # SKR03 Bank (SKR04: 1800)
    "datev_erloes1": "8400",        # SKR03 Erlöse 19% (SKR04: 4400)
    "datev_erloes2": "8300",        # SKR03 Erlöse 7%  (SKR04: 4300)
    "datev_erloes3": "8100",        # SKR03 steuerfreie Umsätze (SKR04: 4100)
    "datev_skonto1": "8736",        # SKR03 gew. Skonti 19% (SKR04: 4736)
    "datev_skonto2": "8731",        # SKR03 gew. Skonti 7%  (SKR04: 4731)
    "datev_skonto3": "8705",        # SKR03 gew. Skonti steuerfrei (SKR04: 4705)
    # (9.6) Eingangsrechnungen: Aufwand (Automatikkonten mit Vorsteuer) und
    # erhaltene Skonti je MwSt-Schlüssel – mit dem Steuerberater abstimmen
    "datev_aufwand1": "3400",       # SKR03 Wareneingang 19 % VSt (SKR04 5400)
    "datev_aufwand2": "3300",       # SKR03 Wareneingang 7 % VSt (SKR04 5300)
    "datev_aufwand3": "3200",       # SKR03 Wareneingang (SKR04 5200)
    "datev_skonto_erh1": "3736",    # SKR03 erh. Skonti 19 % VSt (SKR04 5736)
    "datev_skonto_erh2": "3731",    # SKR03 erh. Skonti 7 % VSt (SKR04 5731)
    "datev_skonto_erh3": "3730",    # SKR03 erh. Skonti (SKR04 5730)
    "eingang_ordner": "",           # Ordner, aus dem eingelesen wird
    "datev_debitor_start": "10000", # Debitor = Start + Kundennummer-Offset
    "datev_kreditor_start": "70000",  # Kreditor = Lieferantennr. bzw. Offset
    "datev_diktat": "FA",
    "datev_verzeichnis": "",
    "datev_steuerberater": "",      # Name des Steuerberaters
    "datev_steuerberater_email": "",
    "datev_email_senden": "0",      # Export automatisch per E-Mail senden
    "datev_email_betreff": "DATEV-Daten {firma} {zeitraum}",
    "datev_email_text": "Sehr geehrte Damen und Herren,\n\n"
                        "anbei erhalten Sie unsere DATEV-Daten "
                        "({inhalt}) für den Zeitraum {zeitraum}.\n"
                        "Berater-Nr. {berater}, Mandanten-Nr. {mandant}.\n\n"
                        "Mit freundlichen Grüßen\n{firma}",

    # Bankabgleich
    "bank_auto_buchen": "1",        # eindeutige Treffer automatisch buchen
    "bank_ordner_aktiv": "0",       # Ordner automatisch überwachen
    "bank_ordner": "",
    "fints_blz": "",
    "fints_benutzer": "",
    "fints_url": "",
    "fints_iban": "",
    "fints_produkt_id": "",
    "fints_tage": "30",
    "fints_auto": "0",              # täglicher Onlineabruf
    "fints_uhrzeit": "08:00",
    "fints_pin": "",                # nur wenn der Benutzer das Speichern wählt
    "fints_zustand": "",            # gespeicherter FinTS-Dialogzustand

    # Datensicherung
    "sicherung_auto": "1",          # täglich beim Programmstart
    # (8.7) Ausfallsicherheit: Warn-E-Mail, wenn die Live-Kopie nicht läuft
    "ausfall_mail": "1",
    "ausfall_mail_an": "",
    "sicherung_beim_beenden": "1",
    "sicherung_ordner": "",         # leer = Ordner "Sicherungen" beim Programm
    "sicherung_anzahl": "30",       # so viele automatische Sicherungen behalten
    "sicherung_letzte": "",
    # (11.0) Warnung beim Start, wenn die letzte Sicherung zu alt ist
    "sicherung_warnung_tage": "3",  # 0 = keine Warnung
    # (11.0) Zustandsanzeige (Ampel) in der Fußzeile beim Start prüfen
    "health_check": "1",
    "health_platz_warnung_mb": "500",  # Warnung, wenn weniger frei
    # (12.0) Lizenz/Kopierschutz: Testphase -> Kulanz -> eingeschränkt
    "lizenz_testtage": "30",        # voller Umfang nach der Erstinstallation
    "lizenz_kulanztage": "14",      # danach Kulanz, erst dann eingeschränkt
    "lizenz_notfalltage": "7",      # einmaliger Notbetrieb auf Ersatz-Rechner
    "lizenz_mastertage": "28",      # Dauer einer Notaktivierung (Notfall-Schlüssel)
    # (13.6) Auftragsfotos: Ordner (leer = Unterordner „Auftragsfotos")
    "foto_ordner": "",
    # (13.6) Versandbenachrichtigung per E-Mail (Lieferschein)
    "versand_betreff": "Ihre Lieferung {nummer}",
    "versand_text": "Guten Tag,\n\nIhre Bestellung wurde versandt. "
    "Lieferschein-Nr.: {nummer}.\n\nMit freundlichen Grüßen\n{firma}",
    # (12.0) Formular/Layout: gemeinsames Layout (1) oder je Belegart (0)
    "form_gemeinsam": "1",

    # Zeiterfassung
    "zeit_bundesland": "",          # z.B. BY, NW ... (für Feiertage)
    "zeit_maria_himmelfahrt": "0",  # 15.08. Feiertag (Bayern, kath. Gemeinden)
    "zeit_wochenstunden": "40",
    "zeit_arbeitstage": "12345",    # 1=Mo ... 7=So
    "zeit_pause_minuten": "30",
    "zeit_pause_ab_stunden": "6",   # feste Pause erst ab dieser Anwesenheit
    "zeit_urlaub_tage": "30",       # Jahresurlaub (Arbeitstage), global
    # (11.0) Arbeitszeitgesetz-/Überstundenwarnungen (Zeitnachweis)
    "arbzg_warnungen": "1",         # ArbZG-Hinweise im Zeitnachweis anzeigen
    "arbzg_max_tag_stunden": "10",  # Höchstarbeitszeit/Tag (ArbZG §3)
    "arbzg_ruhe_stunden": "11",     # Mindestruhezeit zwischen zwei Tagen
    "ueberstunden_warnung_std": "",  # Saldo-Grenze (Std), leer = aus
    "zeit_max_schicht_stunden": "12",  # Schicht über Mitternacht: Höchstdauer
    # Programm-Module (Firmenstamm → Module), siehe module.py
    "modul_uebersicht": "1", "modul_verkauf": "1", "modul_zahlungen": "1",
    "modul_lager": "1", "modul_personal": "1",
    # (9.6) optionale Module: Waage aus, Eingangsrechnungen an
    "modul_waage": "0", "modul_eingang": "1",
    "terminal_anzeige_sek": "6",
    "terminal_karte_sek": "15",     # Wartezeit auf die Karte nach Tastendruck
    "terminal_pin": "",             # PIN zum Beenden des Terminals
    "terminal_uebersicht": "1",     # Knopf 'Monatsübersicht' anbieten
    "terminal_uebersicht_knopf_sek": "5",   # so lange ist der Knopf sichtbar
    "terminal_uebersicht_sek": "60",        # Übersicht schließt spätestens
    "terminal_urlaubsantrag": "1",  # Urlaub am Terminal beantragen
    # (8.9) Entscheidung über Urlaubs-/Stornoanträge zusätzlich per E-Mail
    # an den Mitarbeiter (wenn eine Adresse hinterlegt ist)
    "urlaub_mail": "1",
    # (9.2) Schichten / Arbeitsbeginn und -ende (optional)
    "zeit_schichten": "0",
    "zeit_schicht_standard": "",       # '' | tag | spaet | nacht | auto
    "zeit_tag_beginn": "", "zeit_tag_ende": "",
    "zeit_spaet_beginn": "", "zeit_spaet_ende": "",
    "zeit_nacht_beginn": "", "zeit_nacht_ende": "",
    "zeit_verspaetung_abzug": "0",     # Minuten
    "zeit_verspaetung_raster": "",     # '' | 15 | 30 | 60
    "zeit_nach_schichtende": "kappen",  # kappen | zaehlen
    # (9.4) Waage über Ethernet (siehe waage.py)
    "waage_aktiv": "0",
    "waage_name": "Waage 1",
    "waage_host": "", "waage_port": "",
    "waage_befehl": "",
    "waage_ende": "\\r\\n",
    "waage_timeout": "3",
    "waage_kodierung": "latin-1",
    "waage_muster": "",
    "waage_unruhig": "",
    "waage_fehler": "",
    "waage_einheit": "kg",          # wenn die Antwort keine Einheit enthält
    "waage_eichpflichtig": "1",
    # (9.0) Mindestbesetzung der Arbeitsgruppen
    "gruppe_mindest_ausnahme": "0",  # 1 = Büro darf nach Rückfrage trotzdem
                                     #     genehmigen, 0 = nie
    "gruppe_mail_betreff": "Können Sie einspringen? – {gruppe}",
    "gruppe_mail_text": "Hallo {vorname},\n\nin der Arbeitsgruppe "
                        "„{gruppe}“ ist wegen eines kurzfristigen Ausfalls "
                        "die Mindestbesetzung von {mindest} Personen "
                        "unterschritten:\n\n{tage}\n\nKönnten Sie "
                        "einspringen? Bitte antworten Sie beim nächsten "
                        "Stempeln am Terminal (Ja/Nein), geben Sie im Büro "
                        "Bescheid oder antworten Sie auf diese E-Mail.\n\n"
                        "Vielen Dank!\n{firma}",
    "terminal_auftragsverarbeitung": "1",   # (10.3) Auftragsbearbeitung am
    #                                 Terminal (nur mit Modul Auftragsverarbeitung)
    "terminal_auftraege": "1",      # Arbeitszeit am Terminal auf Aufträge
    "terminal_nachrichten": "1",    # Nachrichten beim Stempeln anzeigen
    # Zeitwirtschaft ab 8.6
    "zeit_nacht_von": "23:00",      # Nachtstunden (ArbZG: 23-6 Uhr)
    "zeit_nacht_bis": "06:00",
    "zeit_saldo_max_stunden": "",   # Kappung Stundenkonto beim Abschluss
    "zeit_stundensatz": "",         # Verkaufspreis je Stunde (Aufträge)
    "zeit_kostensatz": "",          # Kosten je Stunde (Nachkalkulation)
    "zeit_stunden_artikel": "",     # Artikelnummer für Arbeitsstunden
    "zeit_fehler_mail": "0",        # Stempelfehler täglich per E-Mail
    "zeit_fehler_mail_an": "",
    "zeit_fehler_mail_uhrzeit": "08:00",
    "zeit_fehler_mail_gesendet": "",
    "zeit_bericht_betreff": "Arbeitszeitnachweis {monat}",
    "zeit_bericht_text": "Hallo {vorname},\n\nanbei Ihr Arbeitszeitnachweis "
                         "für {monat}. Bitte prüfen Sie die Zeiten und melden "
                         "Sie Abweichungen im Büro.\n\nViele Grüße\n{firma}",
    # DATEV Lohn (LODAS-ASCII-Import)
    "lohn_la_stunden": "",          # Lohnart Arbeitsstunden
    "lohn_la_ueberstunden": "",     # Lohnart ausgezahlte Überstunden
    "lohn_la_nacht": "",
    "lohn_la_sonntag": "",
    "lohn_la_feiertag": "",
    "lohn_la_samstag": "",
    "lohn_la_urlaub": "",           # Urlaubstage
    "lohn_la_krank": "",            # Krankheitstage
    "lohn_bs_stunden": "1",         # Bearbeitungsschlüssel Stunden
    "lohn_bs_tage": "2",            # Bearbeitungsschlüssel Tage
    # (9.7) Einspringen
    "lohn_la_einspringen": "",      # Lohnart Stunden durch Einspringen
    "terminal_einspringen": "1",    # Einspring-Anfragen am Terminal
    "zeit_buero_email": "",         # Meldungen ans Büro (leer = Firmen-Mail)
    "einspringen_buero_mail": "1",  # Zusage/Absage per E-Mail ans Büro
    # (9.7) Korrekturanträge am Terminal
    "terminal_korrektur": "1",
    "korrektur_mail": "1",          # Entscheidung auch per E-Mail an den MA
    "korrektur_tage": "14",         # so viele Tage zurück beantragbar
    # (9.7) Erinnerung bei offenem Kommt
    "zeit_erinnerung": "1",
    "zeit_erinnerung_stunden": "10",
    "zeit_erinnerung_mail": "1",    # zusätzlich E-Mail an den Mitarbeiter
    "zeit_erinnerung_buero": "1",   # Liste ans Büro
    # (9.7) Tägliche Monats-Stundenaufstellung per E-Mail (Firmenstamm;
    # Gruppe und Mitarbeiter können abweichen: MA > Gruppe > Firma)
    "zeit_tagesmail": "0",
    "zeit_tagesmail_betreff": "Ihre Stunden {monat} (Stand {datum})",
    "zeit_tagesmail_text": "Hallo {vorname},\n\nanbei Ihre aktuelle "
                           "Stundenaufstellung für {monat} (Stand {datum}).\n"
                           "Stundenkonto: {saldo} Std.\n\nBitte melden Sie "
                           "Abweichungen im Büro.\n\nViele Grüße\n{firma}",
    "zeit_tagesmail_stand": "",     # zuletzt erledigter Arbeitstag
    # (9.7) Ampelkonto (Stunden; Plus- und Minusgrenzen)
    "zeit_ampel": "0",
    "zeit_ampel_plus_gelb": "20", "zeit_ampel_plus_rot": "40",
    "zeit_ampel_minus_gelb": "10", "zeit_ampel_minus_rot": "20",
    "zeit_ampel_mail": "1",         # bei Wechsel auf Rot Büro + MA melden
    # (9.7) Dienstplan
    "dienstplan_terminal": "1",     # eigener Plan in der Monatsübersicht
    # (13.9) Handy-Stempel-App über die Stempel-API (Variante B)
    "stempel_api_port": "8070",          # lokaler Port des API-Dienstes
    "stempel_api_bind": "127.0.0.1",     # nur lokal; HTTPS macht der Proxy
    "stempel_api_token_tage": "30",      # Gültigkeit eines App-Logins (Tage)
    "stempel_api_geofence": "1",         # GPS gegen Auftrags-Geofence prüfen
    "stempel_api_gps_pflicht": "0",      # Stempeln nur mit Standort erlauben
    "stempel_api_auftragswahl": "1",     # Baustelle/Auftrag in der App wählbar
    "stempel_api_geofence_toleranz": "50",  # zusätzl. Meter auf die GPS-Genauigkeit
}


SCHEMA = [
    """CREATE TABLE IF NOT EXISTS einstellungen (
        schluessel VARCHAR(64) NOT NULL PRIMARY KEY,
        wert TEXT
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",

    """CREATE TABLE IF NOT EXISTS nummernkreise (
        typ CHAR(1) NOT NULL,
        jahr INT NOT NULL,
        letzte INT NOT NULL DEFAULT 0,
        PRIMARY KEY (typ, jahr)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",

    """CREATE TABLE IF NOT EXISTS kunden (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        kundennr INT NOT NULL UNIQUE,
        firma VARCHAR(120) NOT NULL DEFAULT '',
        anrede VARCHAR(30) NOT NULL DEFAULT '',
        vorname VARCHAR(80) NOT NULL DEFAULT '',
        nachname VARCHAR(80) NOT NULL DEFAULT '',
        zusatz VARCHAR(120) NOT NULL DEFAULT '',
        strasse VARCHAR(120) NOT NULL DEFAULT '',
        plz VARCHAR(12) NOT NULL DEFAULT '',
        ort VARCHAR(80) NOT NULL DEFAULT '',
        land CHAR(2) NOT NULL DEFAULT 'DE',
        email VARCHAR(160) NOT NULL DEFAULT '',
        telefon VARCHAR(60) NOT NULL DEFAULT '',
        ustid VARCHAR(30) NOT NULL DEFAULT '',
        leitweg_id VARCHAR(60) NOT NULL DEFAULT '',
        rabatt DECIMAL(5,2) NOT NULL DEFAULT 0,
        zahlungsziel_tage INT NULL,
        skonto_tage INT NULL,
        skonto_prozent DECIMAL(5,2) NULL,
        debitor_konto INT NULL,
        mahnsperre TINYINT NOT NULL DEFAULT 0,
        notiz TEXT,
        aktiv TINYINT NOT NULL DEFAULT 1
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",

    """CREATE TABLE IF NOT EXISTS artikelgruppen (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        bezeichnung VARCHAR(80) NOT NULL UNIQUE,
        mwst_schluessel TINYINT NOT NULL DEFAULT 1
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",

    """CREATE TABLE IF NOT EXISTS artikel (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        artikelnr VARCHAR(40) NOT NULL UNIQUE,
        bezeichnung VARCHAR(200) NOT NULL,
        beschreibung TEXT,
        einheit VARCHAR(12) NOT NULL DEFAULT 'Stk',
        preis DECIMAL(12,4) NOT NULL DEFAULT 0,
        gruppe_id INT NULL,
        mwst_schluessel TINYINT NULL,
        rabatt DECIMAL(5,2) NOT NULL DEFAULT 0,
        aktiv TINYINT NOT NULL DEFAULT 1,
        CONSTRAINT fk_artikel_gruppe FOREIGN KEY (gruppe_id)
            REFERENCES artikelgruppen(id) ON DELETE SET NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",

    # (13.3) Filialen (einfach) – eigene Anschrift/Kontaktdaten je Filiale
    """CREATE TABLE IF NOT EXISTS filialen (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        filialnr VARCHAR(20) NOT NULL UNIQUE,
        name VARCHAR(120) NOT NULL DEFAULT '',
        strasse VARCHAR(120) NOT NULL DEFAULT '',
        plz VARCHAR(12) NOT NULL DEFAULT '',
        ort VARCHAR(80) NOT NULL DEFAULT '',
        land CHAR(2) NOT NULL DEFAULT 'DE',
        telefon VARCHAR(60) NOT NULL DEFAULT '',
        email VARCHAR(160) NOT NULL DEFAULT '',
        web VARCHAR(160) NOT NULL DEFAULT '',
        ansprechpartner VARCHAR(120) NOT NULL DEFAULT '',
        notiz TEXT,
        aktiv TINYINT NOT NULL DEFAULT 1
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",

    # (13.8) Reparaturaufträge / Werkstatt
    """CREATE TABLE IF NOT EXISTS reparatur (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        nummer VARCHAR(40) NOT NULL UNIQUE,
        kunde_id INT NULL,
        geraet VARCHAR(160) NOT NULL DEFAULT '',
        hersteller VARCHAR(120) NOT NULL DEFAULT '',
        modell VARCHAR(120) NOT NULL DEFAULT '',
        seriennr VARCHAR(120) NOT NULL DEFAULT '',
        zubehoer VARCHAR(400) NOT NULL DEFAULT '',
        fehler TEXT,
        diagnose TEXT,
        arbeiten TEXT,
        status VARCHAR(16) NOT NULL DEFAULT 'angenommen',
        angenommen_am DATE NULL,
        fertig_am DATE NULL,
        kv_betrag DECIMAL(12,2) NULL,
        bemerkung VARCHAR(400) NOT NULL DEFAULT '',
        erstellt_von VARCHAR(40) NOT NULL DEFAULT '',
        erstellt DATETIME NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",

    # (13.7) Seriennummern je Artikel (im Lager erfasst)
    """CREATE TABLE IF NOT EXISTS seriennummern (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        artikel_id INT NOT NULL,
        seriennr VARCHAR(80) NOT NULL,
        charge VARCHAR(60) NOT NULL DEFAULT '',
        status VARCHAR(12) NOT NULL DEFAULT 'lager',
        beleg_ein INT NULL,
        beleg_aus INT NULL,
        erfasst DATETIME NULL,
        KEY k_serie (seriennr),
        CONSTRAINT fk_serie_artikel FOREIGN KEY (artikel_id)
            REFERENCES artikel(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",

    # (13.7) Chargenbewegungen (Zugang/Abgang) für die Rückverfolgung
    """CREATE TABLE IF NOT EXISTS chargen (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        artikel_id INT NOT NULL,
        chargennr VARCHAR(60) NOT NULL,
        richtung VARCHAR(8) NOT NULL,
        menge DECIMAL(12,3) NOT NULL DEFAULT 0,
        mhd DATE NULL,
        beleg_id INT NULL,
        erfasst DATETIME NULL,
        KEY k_charge (chargennr),
        CONSTRAINT fk_charge_artikel FOREIGN KEY (artikel_id)
            REFERENCES artikel(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",

    # (13.7) Reservierungen (am Lager), z. B. für einen Auftrag/Kunden
    """CREATE TABLE IF NOT EXISTS reservierung (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        artikel_id INT NOT NULL,
        menge DECIMAL(12,3) NOT NULL DEFAULT 0,
        grund VARCHAR(160) NOT NULL DEFAULT '',
        auftrag_id INT NULL,
        kunde_id INT NULL,
        erfasst DATETIME NULL,
        erledigt TINYINT NOT NULL DEFAULT 0,
        CONSTRAINT fk_res_artikel FOREIGN KEY (artikel_id)
            REFERENCES artikel(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",

    # (13.5) Arbeitsschritte-Stammdaten (nach Aufgabengebieten)
    """CREATE TABLE IF NOT EXISTS arbeitsschritte (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        kuerzel VARCHAR(30) NOT NULL DEFAULT '',
        bezeichnung VARCHAR(160) NOT NULL,
        beschreibung TEXT,
        plan_minuten INT NULL,
        aktiv TINYINT NOT NULL DEFAULT 1
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",

    # (13.1) mengenabhängige Preisstaffel je Artikel
    """CREATE TABLE IF NOT EXISTS artikel_staffel (
        artikel_id INT NOT NULL,
        ab_menge DECIMAL(12,3) NOT NULL,
        preis DECIMAL(12,4) NOT NULL,
        PRIMARY KEY (artikel_id, ab_menge),
        CONSTRAINT fk_staffel_artikel FOREIGN KEY (artikel_id)
            REFERENCES artikel(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",

    """CREATE TABLE IF NOT EXISTS kunden_rabatte (
        kunde_id INT NOT NULL,
        artikel_id INT NOT NULL,
        rabatt DECIMAL(5,2) NOT NULL,
        PRIMARY KEY (kunde_id, artikel_id),
        CONSTRAINT fk_kr_kunde FOREIGN KEY (kunde_id)
            REFERENCES kunden(id) ON DELETE CASCADE,
        CONSTRAINT fk_kr_artikel FOREIGN KEY (artikel_id)
            REFERENCES artikel(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",

    # Belege: typ A = Angebot, R = Rechnung
    """CREATE TABLE IF NOT EXISTS belege (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        typ CHAR(1) NOT NULL,
        nummer VARCHAR(40) NOT NULL,
        kunde_id INT NOT NULL,
        datum DATE NOT NULL,
        leistungsdatum DATE NULL,
        gueltig_bis DATE NULL,
        betreff VARCHAR(200) NOT NULL DEFAULT '',
        kopftext TEXT,
        fusstext TEXT,
        status VARCHAR(20) NOT NULL DEFAULT 'entwurf',
        angebot_id INT NULL,
        storno_von_id INT NULL,
        zahlungsziel_tage INT NOT NULL DEFAULT 14,
        faellig_am DATE NULL,
        skonto_tage INT NOT NULL DEFAULT 0,
        skonto_prozent DECIMAL(5,2) NOT NULL DEFAULT 0,
        netto DECIMAL(12,2) NOT NULL DEFAULT 0,
        mwst DECIMAL(12,2) NOT NULL DEFAULT 0,
        brutto DECIMAL(12,2) NOT NULL DEFAULT 0,
        k_kundennr INT NULL,
        k_name VARCHAR(200) NOT NULL DEFAULT '',
        k_zusatz VARCHAR(200) NOT NULL DEFAULT '',
        k_strasse VARCHAR(120) NOT NULL DEFAULT '',
        k_plz VARCHAR(12) NOT NULL DEFAULT '',
        k_ort VARCHAR(80) NOT NULL DEFAULT '',
        k_land CHAR(2) NOT NULL DEFAULT 'DE',
        k_ustid VARCHAR(30) NOT NULL DEFAULT '',
        k_email VARCHAR(160) NOT NULL DEFAULT '',
        k_leitweg VARCHAR(60) NOT NULL DEFAULT '',
        pdf_datei VARCHAR(400) NOT NULL DEFAULT '',
        festgeschrieben_am DATETIME NULL,
        versendet_am DATETIME NULL,
        datev_exportiert DATETIME NULL,
        erstellt DATETIME NOT NULL,
        UNIQUE KEY uk_beleg_nummer (typ, nummer),
        KEY k_beleg_kunde (kunde_id),
        CONSTRAINT fk_beleg_kunde FOREIGN KEY (kunde_id)
            REFERENCES kunden(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",

    """CREATE TABLE IF NOT EXISTS positionen (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        beleg_id INT NOT NULL,
        pos INT NOT NULL,
        artikel_id INT NULL,
        artikelnr VARCHAR(40) NOT NULL DEFAULT '',
        bezeichnung VARCHAR(200) NOT NULL DEFAULT '',
        beschreibung TEXT,
        menge DECIMAL(12,3) NOT NULL DEFAULT 1,
        einheit VARCHAR(12) NOT NULL DEFAULT 'Stk',
        einzelpreis DECIMAL(12,4) NOT NULL DEFAULT 0,
        rabatt DECIMAL(5,2) NOT NULL DEFAULT 0,
        mwst_schluessel TINYINT NOT NULL DEFAULT 1,
        mwst_satz DECIMAL(5,2) NOT NULL DEFAULT 19,
        mwst_kat VARCHAR(2) NOT NULL DEFAULT 'S',
        mwst_grund VARCHAR(200) NOT NULL DEFAULT '',
        netto DECIMAL(12,2) NOT NULL DEFAULT 0,
        KEY k_pos_beleg (beleg_id),
        CONSTRAINT fk_pos_beleg FOREIGN KEY (beleg_id)
            REFERENCES belege(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",

    """CREATE TABLE IF NOT EXISTS zahlungen (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        rechnung_id INT NOT NULL,
        datum DATE NOT NULL,
        betrag DECIMAL(12,2) NOT NULL DEFAULT 0,
        skonto DECIMAL(12,2) NOT NULL DEFAULT 0,
        art VARCHAR(30) NOT NULL DEFAULT 'Überweisung',
        bemerkung VARCHAR(200) NOT NULL DEFAULT '',
        datev_exportiert DATETIME NULL,
        erstellt DATETIME NOT NULL,
        KEY k_zahl_rechnung (rechnung_id),
        CONSTRAINT fk_zahl_rechnung FOREIGN KEY (rechnung_id)
            REFERENCES belege(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",

    """CREATE TABLE IF NOT EXISTS mahnungen (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        rechnung_id INT NOT NULL,
        nummer VARCHAR(40) NOT NULL DEFAULT '',
        stufe TINYINT NOT NULL,
        datum DATE NOT NULL,
        frist DATE NULL,
        gebuehr DECIMAL(12,2) NOT NULL DEFAULT 0,
        offen DECIMAL(12,2) NOT NULL DEFAULT 0,
        pdf_datei VARCHAR(400) NOT NULL DEFAULT '',
        versendet_am DATETIME NULL,
        versandinfo VARCHAR(250) NOT NULL DEFAULT '',
        KEY k_mahn_rechnung (rechnung_id),
        CONSTRAINT fk_mahn_rechnung FOREIGN KEY (rechnung_id)
            REFERENCES belege(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
]


SCHEMA.append(
    """CREATE TABLE IF NOT EXISTS bankumsaetze (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        hash CHAR(40) NOT NULL UNIQUE,
        buchungsdatum DATE NOT NULL,
        valuta DATE NULL,
        betrag DECIMAL(12,2) NOT NULL,
        name VARCHAR(200) NOT NULL DEFAULT '',
        iban VARCHAR(40) NOT NULL DEFAULT '',
        verwendungszweck TEXT,
        referenz VARCHAR(100) NOT NULL DEFAULT '',
        quelle VARCHAR(20) NOT NULL DEFAULT '',
        status VARCHAR(20) NOT NULL DEFAULT 'offen',
        zahlung_ids VARCHAR(200) NOT NULL DEFAULT '',
        hinweis VARCHAR(250) NOT NULL DEFAULT '',
        importiert DATETIME NOT NULL,
        KEY k_bank_status (status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")


SCHEMA += [
    """CREATE TABLE IF NOT EXISTS mitarbeiter (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        personalnr INT NOT NULL UNIQUE,
        vorname VARCHAR(80) NOT NULL DEFAULT '',
        nachname VARCHAR(80) NOT NULL DEFAULT '',
        rfid VARCHAR(64) NULL UNIQUE,
        wochenstunden DECIMAL(5,2) NULL,
        arbeitstage VARCHAR(7) NULL,
        pause_minuten INT NULL,
        eintritt DATE NULL,
        austritt DATE NULL,
        uebertrag_minuten INT NOT NULL DEFAULT 0,
        email VARCHAR(160) NOT NULL DEFAULT '',
        telefon VARCHAR(60) NOT NULL DEFAULT '',
        notiz TEXT,
        aktiv TINYINT NOT NULL DEFAULT 1
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS stempelungen (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        mitarbeiter_id INT NOT NULL,
        zeitpunkt DATETIME NOT NULL,
        art VARCHAR(12) NOT NULL,
        quelle VARCHAR(20) NOT NULL DEFAULT 'terminal',
        terminal VARCHAR(60) NOT NULL DEFAULT '',
        bemerkung VARCHAR(200) NOT NULL DEFAULT '',
        erstellt DATETIME NOT NULL,
        KEY k_stempel_ma_zeit (mitarbeiter_id, zeitpunkt),
        CONSTRAINT fk_stempel_ma FOREIGN KEY (mitarbeiter_id)
            REFERENCES mitarbeiter(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS abwesenheiten (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        mitarbeiter_id INT NOT NULL,
        datum DATE NOT NULL,
        art VARCHAR(20) NOT NULL,
        bemerkung VARCHAR(200) NOT NULL DEFAULT '',
        UNIQUE KEY uk_abw (mitarbeiter_id, datum),
        CONSTRAINT fk_abw_ma FOREIGN KEY (mitarbeiter_id)
            REFERENCES mitarbeiter(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    # (13.9) Anmelde-Token der Handy-Stempel-App (nur Hash gespeichert)
    """CREATE TABLE IF NOT EXISTS stempel_token (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        mitarbeiter_id INT NOT NULL,
        token_hash CHAR(64) NOT NULL UNIQUE,
        geraet VARCHAR(80) NOT NULL DEFAULT '',
        erstellt DATETIME NOT NULL,
        gueltig_bis DATETIME NOT NULL,
        letzte_nutzung DATETIME NULL,
        letzte_ip VARCHAR(45) NOT NULL DEFAULT '',
        gesperrt TINYINT NOT NULL DEFAULT 0,
        KEY k_tok_ma (mitarbeiter_id),
        CONSTRAINT fk_tok_ma FOREIGN KEY (mitarbeiter_id)
            REFERENCES mitarbeiter(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
]


# Version 8: Lager & Einkauf, wiederkehrende Rechnungen, Urlaub, Benutzer
SCHEMA += [
    """CREATE TABLE IF NOT EXISTS lieferanten (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        lieferantennr INT NOT NULL UNIQUE,
        firma VARCHAR(120) NOT NULL DEFAULT '',
        ansprechpartner VARCHAR(120) NOT NULL DEFAULT '',
        strasse VARCHAR(120) NOT NULL DEFAULT '',
        plz VARCHAR(12) NOT NULL DEFAULT '',
        ort VARCHAR(80) NOT NULL DEFAULT '',
        land CHAR(2) NOT NULL DEFAULT 'DE',
        email VARCHAR(160) NOT NULL DEFAULT '',
        telefon VARCHAR(60) NOT NULL DEFAULT '',
        ustid VARCHAR(30) NOT NULL DEFAULT '',
        iban VARCHAR(40) NOT NULL DEFAULT '',
        unsere_kundennr VARCHAR(40) NOT NULL DEFAULT '',
        lieferzeit_tage INT NULL,
        kreditor_konto INT NULL,
        notiz TEXT,
        aktiv TINYINT NOT NULL DEFAULT 1
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS bestellungen (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        nummer VARCHAR(40) NOT NULL UNIQUE,
        lieferant_id INT NOT NULL,
        datum DATE NOT NULL,
        liefertermin DATE NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'entwurf',
        kopftext TEXT,
        fusstext TEXT,
        netto DECIMAL(12,2) NOT NULL DEFAULT 0,
        l_name VARCHAR(200) NOT NULL DEFAULT '',
        l_zusatz VARCHAR(200) NOT NULL DEFAULT '',
        l_strasse VARCHAR(120) NOT NULL DEFAULT '',
        l_plz VARCHAR(12) NOT NULL DEFAULT '',
        l_ort VARCHAR(80) NOT NULL DEFAULT '',
        l_land CHAR(2) NOT NULL DEFAULT 'DE',
        l_email VARCHAR(160) NOT NULL DEFAULT '',
        pdf_datei VARCHAR(400) NOT NULL DEFAULT '',
        versendet_am DATETIME NULL,
        erstellt DATETIME NOT NULL,
        KEY k_best_lief (lieferant_id),
        CONSTRAINT fk_best_lief FOREIGN KEY (lieferant_id)
            REFERENCES lieferanten(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS bestellpositionen (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        bestellung_id INT NOT NULL,
        pos INT NOT NULL,
        artikel_id INT NULL,
        artikelnr VARCHAR(40) NOT NULL DEFAULT '',
        lief_artikelnr VARCHAR(40) NOT NULL DEFAULT '',
        bezeichnung VARCHAR(200) NOT NULL DEFAULT '',
        menge DECIMAL(12,3) NOT NULL DEFAULT 1,
        geliefert DECIMAL(12,3) NOT NULL DEFAULT 0,
        einheit VARCHAR(12) NOT NULL DEFAULT 'Stk',
        einzelpreis DECIMAL(12,4) NOT NULL DEFAULT 0,
        netto DECIMAL(12,2) NOT NULL DEFAULT 0,
        KEY k_bpos_best (bestellung_id),
        CONSTRAINT fk_bpos_best FOREIGN KEY (bestellung_id)
            REFERENCES bestellungen(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS lagerbewegungen (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        artikel_id INT NOT NULL,
        zeitpunkt DATETIME NOT NULL,
        menge DECIMAL(12,3) NOT NULL,
        bestand_nachher DECIMAL(12,3) NOT NULL DEFAULT 0,
        art VARCHAR(20) NOT NULL,
        beleg_id INT NULL,
        bestellung_id INT NULL,
        belegnr VARCHAR(40) NOT NULL DEFAULT '',
        bemerkung VARCHAR(200) NOT NULL DEFAULT '',
        benutzer VARCHAR(40) NOT NULL DEFAULT '',
        KEY k_lb_artikel (artikel_id, zeitpunkt),
        CONSTRAINT fk_lb_artikel FOREIGN KEY (artikel_id)
            REFERENCES artikel(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS abo_vorlagen (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        bezeichnung VARCHAR(120) NOT NULL DEFAULT '',
        kunde_id INT NOT NULL,
        intervall_monate INT NOT NULL DEFAULT 1,
        naechstes_datum DATE NOT NULL,
        ende_datum DATE NULL,
        betreff VARCHAR(200) NOT NULL DEFAULT '',
        kopftext TEXT,
        fusstext TEXT,
        zahlungsziel_tage INT NULL,
        skonto_tage INT NULL,
        skonto_prozent DECIMAL(5,2) NULL,
        auto_festschreiben TINYINT NOT NULL DEFAULT 0,
        auto_mailen TINYINT NOT NULL DEFAULT 0,
        aktiv TINYINT NOT NULL DEFAULT 1,
        letzte_rechnung_id INT NULL,
        letzte_ausfuehrung DATE NULL,
        erstellt DATETIME NOT NULL,
        CONSTRAINT fk_abo_kunde FOREIGN KEY (kunde_id)
            REFERENCES kunden(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS abo_positionen (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        abo_id INT NOT NULL,
        pos INT NOT NULL,
        artikel_id INT NULL,
        artikelnr VARCHAR(40) NOT NULL DEFAULT '',
        bezeichnung VARCHAR(200) NOT NULL DEFAULT '',
        beschreibung TEXT,
        menge DECIMAL(12,3) NOT NULL DEFAULT 1,
        einheit VARCHAR(12) NOT NULL DEFAULT 'Stk',
        einzelpreis DECIMAL(12,4) NOT NULL DEFAULT 0,
        rabatt DECIMAL(5,2) NOT NULL DEFAULT 0,
        mwst_schluessel TINYINT NOT NULL DEFAULT 1,
        KEY k_apos_abo (abo_id),
        CONSTRAINT fk_apos_abo FOREIGN KEY (abo_id)
            REFERENCES abo_vorlagen(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS urlaub_jahr (
        mitarbeiter_id INT NOT NULL,
        jahr INT NOT NULL,
        anspruch DECIMAL(5,1) NULL,
        uebertrag DECIMAL(5,1) NOT NULL DEFAULT 0,
        bemerkung VARCHAR(200) NOT NULL DEFAULT '',
        PRIMARY KEY (mitarbeiter_id, jahr),
        CONSTRAINT fk_uj_ma FOREIGN KEY (mitarbeiter_id)
            REFERENCES mitarbeiter(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS benutzer (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(40) NOT NULL UNIQUE,
        anzeigename VARCHAR(80) NOT NULL DEFAULT '',
        passwort_hash VARCHAR(200) NOT NULL DEFAULT '',
        admin TINYINT NOT NULL DEFAULT 0,
        rechte VARCHAR(400) NOT NULL DEFAULT '',
        aktiv TINYINT NOT NULL DEFAULT 1,
        letzte_anmeldung DATETIME NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS protokoll (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        zeitpunkt DATETIME NOT NULL,
        benutzer VARCHAR(40) NOT NULL DEFAULT '',
        bereich VARCHAR(30) NOT NULL DEFAULT '',
        aktion VARCHAR(30) NOT NULL DEFAULT '',
        datensatz_id INT NULL,
        bezeichnung VARCHAR(200) NOT NULL DEFAULT '',
        text TEXT,
        alt TEXT,
        neu TEXT,
        KEY k_prot_zeit (zeitpunkt),
        KEY k_prot_bereich (bereich, datensatz_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    # --- Zeitwirtschaft ab Version 8.6 ---
    """CREATE TABLE IF NOT EXISTS arbeitszeitmodelle (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        mitarbeiter_id INT NOT NULL,
        gueltig_ab DATE NOT NULL,
        wochenstunden DECIMAL(5,2) NULL,
        arbeitstage VARCHAR(7) NULL,
        pause_minuten INT NULL,
        soll_tage VARCHAR(60) NOT NULL DEFAULT '',
        bemerkung VARCHAR(200) NOT NULL DEFAULT '',
        UNIQUE KEY uk_modell (mitarbeiter_id, gueltig_ab),
        CONSTRAINT fk_modell_ma FOREIGN KEY (mitarbeiter_id)
            REFERENCES mitarbeiter(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS monatsabschluesse (
        mitarbeiter_id INT NOT NULL,
        monat DATE NOT NULL,
        ist INT NOT NULL DEFAULT 0,
        soll INT NOT NULL DEFAULT 0,
        saldo INT NOT NULL DEFAULT 0,
        buchungen INT NOT NULL DEFAULT 0,
        saldo_vorher INT NOT NULL DEFAULT 0,
        saldo_ende INT NOT NULL DEFAULT 0,
        nacht INT NOT NULL DEFAULT 0,
        abgeschlossen DATETIME NOT NULL,
        benutzer VARCHAR(40) NOT NULL DEFAULT '',
        PRIMARY KEY (mitarbeiter_id, monat),
        CONSTRAINT fk_abschl_ma FOREIGN KEY (mitarbeiter_id)
            REFERENCES mitarbeiter(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS stundenbuchungen (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        mitarbeiter_id INT NOT NULL,
        datum DATE NOT NULL,
        minuten INT NOT NULL,
        art VARCHAR(20) NOT NULL,
        bemerkung VARCHAR(200) NOT NULL DEFAULT '',
        erstellt DATETIME NOT NULL,
        benutzer VARCHAR(40) NOT NULL DEFAULT '',
        KEY k_sb_ma (mitarbeiter_id, datum),
        CONSTRAINT fk_sb_ma FOREIGN KEY (mitarbeiter_id)
            REFERENCES mitarbeiter(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS urlaubsantraege (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        mitarbeiter_id INT NOT NULL,
        von DATE NOT NULL,
        bis DATE NOT NULL,
        halb TINYINT NOT NULL DEFAULT 0,
        art VARCHAR(20) NOT NULL DEFAULT 'urlaub',
        tage DECIMAL(5,1) NOT NULL DEFAULT 0,
        bemerkung VARCHAR(200) NOT NULL DEFAULT '',
        status VARCHAR(20) NOT NULL DEFAULT 'offen',
        erstellt DATETIME NOT NULL,
        quelle VARCHAR(20) NOT NULL DEFAULT '',
        bearbeitet DATETIME NULL,
        bearbeitet_von VARCHAR(40) NOT NULL DEFAULT '',
        antwort VARCHAR(200) NOT NULL DEFAULT '',
        KEY k_ua_ma (mitarbeiter_id, status),
        CONSTRAINT fk_ua_ma FOREIGN KEY (mitarbeiter_id)
            REFERENCES mitarbeiter(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS nachrichten (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        mitarbeiter_id INT NOT NULL,
        text VARCHAR(500) NOT NULL DEFAULT '',
        erstellt DATETIME NOT NULL,
        von VARCHAR(40) NOT NULL DEFAULT '',
        gueltig_bis DATE NULL,
        gelesen DATETIME NULL,
        KEY k_na_ma (mitarbeiter_id, gelesen),
        CONSTRAINT fk_na_ma FOREIGN KEY (mitarbeiter_id)
            REFERENCES mitarbeiter(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS auftragszeiten (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        mitarbeiter_id INT NOT NULL,
        beleg_id INT NULL,
        beginn DATETIME NOT NULL,
        ende DATETIME NULL,
        minuten INT NULL,
        ende_grund VARCHAR(20) NOT NULL DEFAULT '',
        taetigkeit VARCHAR(200) NOT NULL DEFAULT '',
        quelle VARCHAR(20) NOT NULL DEFAULT '',
        abgerechnet_in INT NULL,
        erstellt DATETIME NOT NULL,
        KEY k_az_ma (mitarbeiter_id, ende),
        KEY k_az_beleg (beleg_id),
        CONSTRAINT fk_az_ma FOREIGN KEY (mitarbeiter_id)
            REFERENCES mitarbeiter(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    # (8.7) Ausfallsicherheit mit Ersatzserver: welcher Server zuletzt
    # freigegeben wurde (Schutz, falls beide beschreibbar sind), Herzschlag
    # zur Überwachung der Live-Kopie, zuletzt gemeldete Warnung
    """CREATE TABLE IF NOT EXISTS ausfallsicherheit (
        id TINYINT NOT NULL PRIMARY KEY,
        aktiv_server VARCHAR(120) NOT NULL DEFAULT '',
        aktiv_seit DATETIME(6) NULL,
        herzschlag DATETIME(6) NULL,
        warnung_grund VARCHAR(60) NULL,
        warnung_am DATETIME NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    # (9.1) Bearbeitungssperren im Mehrplatzbetrieb (siehe bearbeitung.py)
    """CREATE TABLE IF NOT EXISTS bearbeitungen (
        objekt VARCHAR(30) NOT NULL,
        objekt_id VARCHAR(60) NOT NULL,
        sitzung VARCHAR(40) NOT NULL,
        benutzer VARCHAR(40) NOT NULL DEFAULT '',
        anzeigename VARCHAR(80) NOT NULL DEFAULT '',
        arbeitsplatz VARCHAR(60) NOT NULL DEFAULT '',
        text VARCHAR(120) NOT NULL DEFAULT '',
        seit DATETIME NOT NULL,
        herzschlag DATETIME NOT NULL,
        PRIMARY KEY (objekt, objekt_id),
        KEY k_bb_sitzung (sitzung)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    # (9.0) Arbeitsgruppen mit Mindestbesetzung (Mitarbeiter gehören zu
    # keiner, einer oder zwei Gruppen: mitarbeiter.gruppe1_id/gruppe2_id)
    """CREATE TABLE IF NOT EXISTS arbeitsgruppen (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(80) NOT NULL UNIQUE,
        mindest_anwesend INT NOT NULL DEFAULT 0,
        bemerkung VARCHAR(200) NOT NULL DEFAULT '',
        aktiv TINYINT NOT NULL DEFAULT 1
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    # (8.9) Urlaubssperren: mitarbeiter_id NULL = gilt für alle (global)
    """CREATE TABLE IF NOT EXISTS urlaubssperren (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        mitarbeiter_id INT NULL,
        von DATE NOT NULL,
        bis DATE NOT NULL,
        grund VARCHAR(200) NOT NULL DEFAULT '',
        erstellt DATETIME NOT NULL,
        erstellt_von VARCHAR(40) NOT NULL DEFAULT '',
        KEY k_us_zeit (von, bis),
        CONSTRAINT fk_us_ma FOREIGN KEY (mitarbeiter_id)
            REFERENCES mitarbeiter(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    # (9.6) Eingangsrechnungsbuch (Beträge bei Gutschriften negativ)
    """CREATE TABLE IF NOT EXISTS eingangsrechnungen (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        lieferant_id INT NULL,
        lf_name VARCHAR(200) NOT NULL DEFAULT '',
        lf_ustid VARCHAR(40) NOT NULL DEFAULT '',
        lf_steuernr VARCHAR(40) NOT NULL DEFAULT '',
        rechnungsnr VARCHAR(80) NOT NULL DEFAULT '',
        typcode VARCHAR(5) NOT NULL DEFAULT '',
        gutschrift TINYINT NOT NULL DEFAULT 0,
        datum DATE NOT NULL,
        leistungsdatum DATE NULL,
        faellig DATE NULL,
        skonto_prozent DECIMAL(5,2) NULL,
        skonto_bis DATE NULL,
        waehrung CHAR(3) NOT NULL DEFAULT 'EUR',
        netto DECIMAL(12,2) NOT NULL DEFAULT 0,
        steuer DECIMAL(12,2) NOT NULL DEFAULT 0,
        brutto DECIMAL(12,2) NOT NULL DEFAULT 0,
        zahlbetrag DECIMAL(12,2) NOT NULL DEFAULT 0,
        iban VARCHAR(40) NOT NULL DEFAULT '',
        bic VARCHAR(20) NOT NULL DEFAULT '',
        verwendungszweck VARCHAR(140) NOT NULL DEFAULT '',
        bestellnr VARCHAR(80) NOT NULL DEFAULT '',
        bestellung_id INT NULL,
        format VARCHAR(80) NOT NULL DEFAULT '',
        profil VARCHAR(80) NOT NULL DEFAULT '',
        pruefung VARCHAR(12) NOT NULL DEFAULT '',
        bericht MEDIUMTEXT,
        daten MEDIUMTEXT,
        datei VARCHAR(400) NOT NULL DEFAULT '',
        hash CHAR(64) NOT NULL DEFAULT '',
        status VARCHAR(12) NOT NULL DEFAULT 'offen',
        konto INT NULL,
        freigegeben_von VARCHAR(40) NOT NULL DEFAULT '',
        freigegeben_am DATETIME NULL,
        bezahlt_am DATE NULL,
        bezahlt_betrag DECIMAL(12,2) NULL,
        skonto_betrag DECIMAL(12,2) NULL,
        bemerkung TEXT,
        erfasst DATETIME NOT NULL,
        erfasst_von VARCHAR(40) NOT NULL DEFAULT '',
        datev_exportiert DATETIME NULL,
        zahlung_datev DATETIME NULL,
        KEY k_er_hash (hash),
        KEY k_er_nr (rechnungsnr),
        KEY k_er_status (status),
        KEY k_er_lf (lieferant_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS eingangsrechnung_steuer (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        er_id INT NOT NULL,
        kategorie VARCHAR(3) NOT NULL DEFAULT 'S',
        satz DECIMAL(5,2) NOT NULL DEFAULT 0,
        basis DECIMAL(12,2) NOT NULL DEFAULT 0,
        betrag DECIMAL(12,2) NOT NULL DEFAULT 0,
        KEY k_ers (er_id),
        CONSTRAINT fk_ers FOREIGN KEY (er_id)
            REFERENCES eingangsrechnungen(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
]


# (9.7) Einspringen, Korrekturanträge, Meldungen, Dienstplan
SCHEMA += [
    # Anfrage je Gruppe und Tag (Mindestbesetzung unterschritten)
    """CREATE TABLE IF NOT EXISTS einspring_anfragen (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        gruppe_id INT NULL,
        datum DATE NOT NULL,
        fehlen DECIMAL(4,1) NOT NULL DEFAULT 1,
        krank_ma_id INT NULL,
        status VARCHAR(10) NOT NULL DEFAULT 'offen',
        erstellt DATETIME NOT NULL,
        von VARCHAR(40) NOT NULL DEFAULT '',
        KEY k_ea_datum (datum, status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS einspring_antworten (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        anfrage_id INT NOT NULL,
        mitarbeiter_id INT NOT NULL,
        antwort VARCHAR(6) NOT NULL DEFAULT 'offen',
        zeitpunkt DATETIME NULL,
        quelle VARCHAR(20) NOT NULL DEFAULT '',
        UNIQUE KEY uk_eant (anfrage_id, mitarbeiter_id),
        KEY k_eant_ma (mitarbeiter_id, antwort),
        CONSTRAINT fk_eant_anfrage FOREIGN KEY (anfrage_id)
            REFERENCES einspring_anfragen(id) ON DELETE CASCADE,
        CONSTRAINT fk_eant_ma FOREIGN KEY (mitarbeiter_id)
            REFERENCES mitarbeiter(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    # Korrekturanträge vom Terminal (Geht vergessen, falsch gestempelt …)
    """CREATE TABLE IF NOT EXISTS korrekturantraege (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        mitarbeiter_id INT NOT NULL,
        datum DATE NOT NULL,
        art VARCHAR(12) NOT NULL,
        zeitpunkt DATETIME NOT NULL,
        grund VARCHAR(200) NOT NULL DEFAULT '',
        status VARCHAR(12) NOT NULL DEFAULT 'offen',
        erstellt DATETIME NOT NULL,
        quelle VARCHAR(20) NOT NULL DEFAULT '',
        bearbeitet DATETIME NULL,
        bearbeitet_von VARCHAR(40) NOT NULL DEFAULT '',
        antwort VARCHAR(200) NOT NULL DEFAULT '',
        stempel_id INT NULL,
        KEY k_ka_status (status, mitarbeiter_id),
        CONSTRAINT fk_ka_ma FOREIGN KEY (mitarbeiter_id)
            REFERENCES mitarbeiter(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    # einmalige Meldungen (Erinnerung, Tagesmail, Ampel) – verhindert
    # doppelten Versand auch bei mehreren Arbeitsplätzen
    """CREATE TABLE IF NOT EXISTS zeit_meldungen (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        art VARCHAR(20) NOT NULL,
        mitarbeiter_id INT NOT NULL,
        bezug VARCHAR(40) NOT NULL DEFAULT '',
        gesendet DATETIME NOT NULL,
        text VARCHAR(300) NOT NULL DEFAULT '',
        UNIQUE KEY uk_zm (art, mitarbeiter_id, bezug)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    # Dienstplan: je Mitarbeiter und Tag eine Schicht (tag/spaet/nacht),
    # 'frei' oder eigene Zeiten
    """CREATE TABLE IF NOT EXISTS dienstplan (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        mitarbeiter_id INT NOT NULL,
        datum DATE NOT NULL,
        schicht VARCHAR(8) NOT NULL DEFAULT '',
        beginn VARCHAR(5) NULL,
        ende VARCHAR(5) NULL,
        bemerkung VARCHAR(120) NOT NULL DEFAULT '',
        geaendert DATETIME NULL,
        geaendert_von VARCHAR(40) NOT NULL DEFAULT '',
        UNIQUE KEY uk_dp (mitarbeiter_id, datum),
        KEY k_dp_datum (datum),
        CONSTRAINT fk_dp_ma FOREIGN KEY (mitarbeiter_id)
            REFERENCES mitarbeiter(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
]


# (10.3) Modul „Auftragsverarbeitung“: Aufträge mit definierten
# Arbeitsschritten und Material; Mitarbeiter buchen an der Stempeluhr
# Arbeitszeit auf die Schritte und melden verarbeitetes Material.
SCHEMA += [
    """CREATE TABLE IF NOT EXISTS av_auftrag (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        nummer VARCHAR(40) NOT NULL UNIQUE,
        name VARCHAR(200) NOT NULL DEFAULT '',
        beschreibung TEXT,
        status VARCHAR(20) NOT NULL DEFAULT 'offen',
        zuordnung_art VARCHAR(10) NOT NULL DEFAULT 'alle',
        erstellt DATETIME NOT NULL,
        angelegt_von VARCHAR(40) NOT NULL DEFAULT ''
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS av_schritt (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        auftrag_id INT NOT NULL,
        bezeichnung VARCHAR(200) NOT NULL DEFAULT '',
        sortierung INT NOT NULL DEFAULT 0,
        KEY k_avs_auftrag (auftrag_id),
        CONSTRAINT fk_avs_auftrag FOREIGN KEY (auftrag_id)
            REFERENCES av_auftrag(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS av_material (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        auftrag_id INT NOT NULL,
        artikel_id INT NULL,
        bezeichnung VARCHAR(200) NOT NULL DEFAULT '',
        einheit VARCHAR(12) NOT NULL DEFAULT 'Stk',
        menge_geplant DECIMAL(12,3) NULL,
        sortierung INT NOT NULL DEFAULT 0,
        KEY k_avm_auftrag (auftrag_id),
        CONSTRAINT fk_avm_auftrag FOREIGN KEY (auftrag_id)
            REFERENCES av_auftrag(id) ON DELETE CASCADE,
        CONSTRAINT fk_avm_artikel FOREIGN KEY (artikel_id)
            REFERENCES artikel(id) ON DELETE SET NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS av_zuordnung (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        auftrag_id INT NOT NULL,
        art VARCHAR(12) NOT NULL,
        ref_id INT NOT NULL,
        UNIQUE KEY uk_avz (auftrag_id, art, ref_id),
        CONSTRAINT fk_avz_auftrag FOREIGN KEY (auftrag_id)
            REFERENCES av_auftrag(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS av_zeit (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        auftrag_id INT NOT NULL,
        schritt_id INT NULL,
        mitarbeiter_id INT NOT NULL,
        datum DATE NOT NULL,
        minuten INT NOT NULL DEFAULT 0,
        bemerkung VARCHAR(200) NOT NULL DEFAULT '',
        quelle VARCHAR(20) NOT NULL DEFAULT 'terminal',
        erstellt DATETIME NOT NULL,
        KEY k_avz_auftrag (auftrag_id),
        KEY k_avz_ma (mitarbeiter_id),
        CONSTRAINT fk_avzeit_auftrag FOREIGN KEY (auftrag_id)
            REFERENCES av_auftrag(id) ON DELETE CASCADE,
        CONSTRAINT fk_avzeit_schritt FOREIGN KEY (schritt_id)
            REFERENCES av_schritt(id) ON DELETE SET NULL,
        CONSTRAINT fk_avzeit_ma FOREIGN KEY (mitarbeiter_id)
            REFERENCES mitarbeiter(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS av_verbrauch (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        auftrag_id INT NOT NULL,
        material_id INT NULL,
        artikel_id INT NULL,
        mitarbeiter_id INT NOT NULL,
        datum DATE NOT NULL,
        bezeichnung VARCHAR(200) NOT NULL DEFAULT '',
        einheit VARCHAR(12) NOT NULL DEFAULT 'Stk',
        menge DECIMAL(12,3) NOT NULL DEFAULT 0,
        lagerbewegung INT NULL,
        quelle VARCHAR(20) NOT NULL DEFAULT 'terminal',
        erstellt DATETIME NOT NULL,
        KEY k_avv_auftrag (auftrag_id),
        KEY k_avv_ma (mitarbeiter_id),
        CONSTRAINT fk_avv_auftrag FOREIGN KEY (auftrag_id)
            REFERENCES av_auftrag(id) ON DELETE CASCADE,
        CONSTRAINT fk_avv_material FOREIGN KEY (material_id)
            REFERENCES av_material(id) ON DELETE SET NULL,
        CONSTRAINT fk_avv_ma FOREIGN KEY (mitarbeiter_id)
            REFERENCES mitarbeiter(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    # (10.3) Vorlagen für wiederkehrende Aufträge: speichern Arbeitsschritte
    # und Material und lassen sich in einen Auftrag umwandeln.
    """CREATE TABLE IF NOT EXISTS av_vorlage (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(200) NOT NULL DEFAULT '',
        beschreibung TEXT,
        erstellt DATETIME NOT NULL,
        angelegt_von VARCHAR(40) NOT NULL DEFAULT ''
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS av_vorlage_schritt (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        vorlage_id INT NOT NULL,
        bezeichnung VARCHAR(200) NOT NULL DEFAULT '',
        sortierung INT NOT NULL DEFAULT 0,
        KEY k_avvs_vorlage (vorlage_id),
        CONSTRAINT fk_avvs_vorlage FOREIGN KEY (vorlage_id)
            REFERENCES av_vorlage(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS av_vorlage_material (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        vorlage_id INT NOT NULL,
        artikel_id INT NULL,
        bezeichnung VARCHAR(200) NOT NULL DEFAULT '',
        einheit VARCHAR(12) NOT NULL DEFAULT 'Stk',
        menge_geplant DECIMAL(12,3) NULL,
        sortierung INT NOT NULL DEFAULT 0,
        KEY k_avvm_vorlage (vorlage_id),
        CONSTRAINT fk_avvm_vorlage FOREIGN KEY (vorlage_id)
            REFERENCES av_vorlage(id) ON DELETE CASCADE,
        CONSTRAINT fk_avvm_artikel FOREIGN KEY (artikel_id)
            REFERENCES artikel(id) ON DELETE SET NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",

    # (13.9.1) Diese beiden Tabellen stehen bewusst am Ende: ihre Fremdschluessel
    # verweisen auf mitarbeiter bzw. av_auftrag, die vorher angelegt sein muessen.
    # (13.4) Mitarbeiter in mehreren Filialen einsetzbar (n:m)
    """CREATE TABLE IF NOT EXISTS mitarbeiter_filialen (
        mitarbeiter_id INT NOT NULL,
        filiale_id INT NOT NULL,
        PRIMARY KEY (mitarbeiter_id, filiale_id),
        CONSTRAINT fk_mf_ma FOREIGN KEY (mitarbeiter_id)
            REFERENCES mitarbeiter(id) ON DELETE CASCADE,
        CONSTRAINT fk_mf_fil FOREIGN KEY (filiale_id)
            REFERENCES filialen(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",

    # (13.6) Baustellen-/Auftragsfotos: Datei im Ordner, Zuordnung in der DB
    """CREATE TABLE IF NOT EXISTS av_foto (
        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        auftrag_id INT NOT NULL,
        dateiname VARCHAR(260) NOT NULL,
        bemerkung VARCHAR(200) NOT NULL DEFAULT '',
        erfasst DATETIME NULL,
        CONSTRAINT fk_foto_auftrag FOREIGN KEY (auftrag_id)
            REFERENCES av_auftrag(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
]


# Spalten, die in späteren Versionen hinzugekommen sind (bestehende
# Datenbanken werden beim Start automatisch ergänzt)
MIGRATIONEN = [
    # (9.7) tägliche Monats-Stundenaufstellung: NULL = übergeordnet
    ("arbeitsgruppen", "tagesmail", "TINYINT NULL"),
    ("mitarbeiter", "tagesmail", "TINYINT NULL"),
    # (9.7) Ampelkonto: eigene Grenzen (Stunden), zuletzt gemeldeter Stand
    ("mitarbeiter", "ampel_plus_gelb", "DECIMAL(6,2) NULL"),
    ("mitarbeiter", "ampel_plus_rot", "DECIMAL(6,2) NULL"),
    ("mitarbeiter", "ampel_minus_gelb", "DECIMAL(6,2) NULL"),
    ("mitarbeiter", "ampel_minus_rot", "DECIMAL(6,2) NULL"),
    ("mitarbeiter", "ampel_stand", "VARCHAR(6) NOT NULL DEFAULT ''"),
    # (9.7) Soll und Arbeitsbeginn/-ende aus dem Dienstplan
    ("mitarbeiter", "nach_dienstplan", "TINYINT NOT NULL DEFAULT 0"),
    # (9.2) Schichten: Zuordnung und Arbeitsbeginn/-ende je Schicht
    # (leer = Vorgabe der Gruppe bzw. des Firmenstamms)
    ("arbeitsgruppen", "schicht", "VARCHAR(8) NOT NULL DEFAULT ''"),
    # (9.4) Wägung je Position (eichpflichtiger Verkauf nach Gewicht)
    ("positionen", "waage_netto", "DECIMAL(14,4) NULL"),
    ("positionen", "waage_tara", "DECIMAL(14,4) NULL"),
    ("positionen", "waage_brutto", "DECIMAL(14,4) NULL"),
    ("positionen", "waage_einheit", "VARCHAR(4) NULL"),
    ("positionen", "waage_stellen", "TINYINT NULL"),
    ("positionen", "waage_alibi", "VARCHAR(40) NULL"),
    ("positionen", "waage_zeit", "DATETIME NULL"),
    ("positionen", "waage_name", "VARCHAR(30) NULL"),
    # (9.2) Verspätungsregeln je Gruppe/Mitarbeiter (NULL = wie Gruppe bzw.
    # Firmenstamm); raster '0' = ausdrücklich nicht runden
    ("arbeitsgruppen", "verspaetung_abzug", "INT NULL"),
    ("arbeitsgruppen", "verspaetung_raster", "VARCHAR(4) NULL"),
    ("arbeitsgruppen", "nach_schichtende", "VARCHAR(8) NULL"),
    ("mitarbeiter", "verspaetung_abzug", "INT NULL"),
    ("mitarbeiter", "verspaetung_raster", "VARCHAR(4) NULL"),
    ("mitarbeiter", "nach_schichtende", "VARCHAR(8) NULL"),
    ("mitarbeiter", "schicht", "VARCHAR(8) NOT NULL DEFAULT ''"),
    ("arbeitsgruppen", "tag_beginn", "VARCHAR(5) NULL"),
    ("arbeitsgruppen", "tag_ende", "VARCHAR(5) NULL"),
    ("arbeitsgruppen", "spaet_beginn", "VARCHAR(5) NULL"),
    ("arbeitsgruppen", "spaet_ende", "VARCHAR(5) NULL"),
    ("arbeitsgruppen", "nacht_beginn", "VARCHAR(5) NULL"),
    ("arbeitsgruppen", "nacht_ende", "VARCHAR(5) NULL"),
    ("mitarbeiter", "tag_beginn", "VARCHAR(5) NULL"),
    ("mitarbeiter", "tag_ende", "VARCHAR(5) NULL"),
    ("mitarbeiter", "spaet_beginn", "VARCHAR(5) NULL"),
    ("mitarbeiter", "spaet_ende", "VARCHAR(5) NULL"),
    ("mitarbeiter", "nacht_beginn", "VARCHAR(5) NULL"),
    ("mitarbeiter", "nacht_ende", "VARCHAR(5) NULL"),
    # (9.1) Änderungszähler für Belege (Schutz vor Überschreiben)
    ("belege", "version", "INT NOT NULL DEFAULT 0"),
    ("belege", "geaendert_am", "DATETIME NULL"),
    ("belege", "geaendert_von", "VARCHAR(40) NOT NULL DEFAULT ''"),
    # (9.0) Arbeitsgruppen je Mitarbeiter (höchstens zwei)
    ("mitarbeiter", "gruppe1_id", "INT NULL"),
    ("mitarbeiter", "gruppe2_id", "INT NULL"),
    # (8.9) Urlaubsantrag oder Stornierungsantrag: 'antrag' | 'storno'
    ("urlaubsantraege", "typ", "VARCHAR(10) NOT NULL DEFAULT 'antrag'"),
    ("kunden", "einmalkunde", "TINYINT NOT NULL DEFAULT 0"),
    # (8.8) Rechnung sofort bezahlt: '' | 'Bar' | 'EC-/Kreditkarte'
    ("belege", "sofort_bezahlt", "VARCHAR(20) NOT NULL DEFAULT ''"),
    # Version 8
    ("kunden", "erechnung", "VARCHAR(12) NOT NULL DEFAULT 'zugferd'"),
    # Belegarten: rechnungsart '' = normal, gutschrift, abschlag, schluss
    ("belege", "rechnungsart", "VARCHAR(12) NOT NULL DEFAULT ''"),
    ("belege", "bezug_id", "INT NULL"),
    ("belege", "liefertermin", "DATE NULL"),
    ("belege", "bestellnr_kunde", "VARCHAR(60) NOT NULL DEFAULT ''"),
    ("belege", "abzug_netto", "DECIMAL(12,2) NOT NULL DEFAULT 0"),
    ("belege", "abzug_brutto", "DECIMAL(12,2) NOT NULL DEFAULT 0"),
    # Abschlag -> Schlussrechnung, Lieferschein/AB -> Rechnung
    ("belege", "abgerechnet_in", "INT NULL"),
    ("belege", "leistung_bis", "DATE NULL"),
    ("belege", "lager_gebucht", "DATETIME NULL"),
    ("belege", "abo_id", "INT NULL"),
    ("belege", "xml_datei", "VARCHAR(400) NOT NULL DEFAULT ''"),
    ("belege", "k_erechnung", "VARCHAR(12) NOT NULL DEFAULT ''"),
    ("belege", "erstellt_von", "VARCHAR(40) NOT NULL DEFAULT ''"),
    ("artikel", "lagerartikel", "TINYINT NOT NULL DEFAULT 0"),
    ("artikel", "bestand", "DECIMAL(12,3) NOT NULL DEFAULT 0"),
    ("artikel", "mindestbestand", "DECIMAL(12,3) NOT NULL DEFAULT 0"),
    ("artikel", "sollbestand", "DECIMAL(12,3) NOT NULL DEFAULT 0"),
    ("artikel", "lagerort", "VARCHAR(40) NOT NULL DEFAULT ''"),
    ("artikel", "einkaufspreis", "DECIMAL(12,4) NOT NULL DEFAULT 0"),
    ("artikel", "lieferant_id", "INT NULL"),
    ("artikel", "lief_artikelnr", "VARCHAR(40) NOT NULL DEFAULT ''"),
    ("artikel", "ean", "VARCHAR(20) NOT NULL DEFAULT ''"),
    ("mitarbeiter", "urlaub_tage", "DECIMAL(5,1) NULL"),
    ("mitarbeiter", "ueber_mitternacht", "TINYINT NOT NULL DEFAULT 0"),
    ("abwesenheiten", "anteil", "DECIMAL(3,2) NOT NULL DEFAULT 1.00"),
    # Version 8.6
    ("mitarbeiter", "soll_tage", "VARCHAR(60) NOT NULL DEFAULT ''"),
    ("mitarbeiter", "stundenkosten", "DECIMAL(8,2) NULL"),
    # (10.3) feste Pause je Arbeitsgruppe (NULL = keine Gruppenvorgabe)
    ("arbeitsgruppen", "pause_minuten", "INT NULL"),
    # (11.0) Soll/Ist je Auftrag: geplante Zeit je Arbeitsschritt (Minuten)
    ("av_schritt", "plan_minuten", "INT NULL"),
    ("av_vorlage_schritt", "plan_minuten", "INT NULL"),
    # (11.0) Auftrag -> Rechnung: in welchen Beleg übernommen
    ("av_auftrag", "abgerechnet_in", "INT NULL"),
    # (11.0) Mehrplatz-Schutz (optimistisches Sperren) für Aufträge
    ("av_auftrag", "version", "INT NOT NULL DEFAULT 0"),
    ("av_auftrag", "geaendert_am", "DATETIME NULL"),
    ("av_auftrag", "geaendert_von", "VARCHAR(40) NOT NULL DEFAULT ''"),
    # (13.0) Kunden-Zusatzfelder (keine Pflichtfelder)
    ("kunden", "firma2", "VARCHAR(120) NOT NULL DEFAULT ''"),
    ("kunden", "handy", "VARCHAR(60) NOT NULL DEFAULT ''"),
    ("kunden", "ansprechpartner", "VARCHAR(120) NOT NULL DEFAULT ''"),
    ("kunden", "webseite", "VARCHAR(160) NOT NULL DEFAULT ''"),
    ("kunden", "kennung", "VARCHAR(60) NOT NULL DEFAULT ''"),
    ("kunden", "wiedervorlage_am", "DATE NULL"),
    ("kunden", "wiedervorlage_text", "VARCHAR(200) NOT NULL DEFAULT ''"),
    ("kunden", "kreditlimit", "DECIMAL(12,2) NOT NULL DEFAULT 0"),
    # (13.1) Artikel-Zusatzfelder (keine Pflichtfelder)
    ("artikel", "sonderpreis", "DECIMAL(12,4) NULL"),
    ("artikel", "sonderpreis_von", "DATE NULL"),
    ("artikel", "sonderpreis_bis", "DATE NULL"),
    ("artikel", "rabattfaehig", "TINYINT NOT NULL DEFAULT 1"),
    ("artikel", "hersteller", "VARCHAR(120) NOT NULL DEFAULT ''"),
    ("artikel", "hersteller_nr", "VARCHAR(60) NOT NULL DEFAULT ''"),
    ("artikel", "versand_volumen", "DECIMAL(12,3) NULL"),
    ("artikel", "gewicht_brutto", "DECIMAL(12,3) NULL"),
    ("artikel", "gewicht_netto", "DECIMAL(12,3) NULL"),
    ("artikel", "abmessungen", "VARCHAR(60) NOT NULL DEFAULT ''"),
    ("artikel", "garantie_monate", "INT NULL"),
    ("artikel", "mhd_text1", "VARCHAR(120) NOT NULL DEFAULT ''"),
    ("artikel", "mhd_text2", "VARCHAR(120) NOT NULL DEFAULT ''"),
    ("artikel", "foto_pfad", "VARCHAR(400) NOT NULL DEFAULT ''"),
    # (13.2) Unter-Artikelgruppen + MwSt-Vererbung
    ("artikelgruppen", "parent_id", "INT NULL"),
    ("artikelgruppen", "mwst_erben", "TINYINT NOT NULL DEFAULT 0"),
    # (13.3) Mitarbeiter optional einer Filiale zuordnen (13.4: Mehrfach über
    # Tabelle mitarbeiter_filialen; Spalte bleibt für Altbestand/Kompat.)
    ("mitarbeiter", "filiale_id", "INT NULL"),
    # (13.4) Auftrag hat einen Kunden (Pflicht beim Anlegen)
    ("av_auftrag", "kunde_id", "INT NULL"),
    # (13.5) Verrechnungssatz (Abrechnung) global/Gruppe/Mitarbeiter
    ("arbeitsgruppen", "stundensatz", "DECIMAL(8,2) NULL"),
    ("mitarbeiter", "stundensatz", "DECIMAL(8,2) NULL"),
    # (13.5) Arbeitsschritt eines Auftrags kann aus den Stammdaten stammen
    ("av_schritt", "schritt_stamm_id", "INT NULL"),
    ("av_vorlage_schritt", "schritt_stamm_id", "INT NULL"),
    # (13.5) je Beleg überschreibbare Textfelder (Variablen Textfeld 1..5)
    ("belege", "text1", "VARCHAR(500) NOT NULL DEFAULT ''"),
    ("belege", "text2", "VARCHAR(500) NOT NULL DEFAULT ''"),
    ("belege", "text3", "VARCHAR(500) NOT NULL DEFAULT ''"),
    ("belege", "text4", "VARCHAR(500) NOT NULL DEFAULT ''"),
    ("belege", "text5", "VARCHAR(500) NOT NULL DEFAULT ''"),
    # (13.7) Serien-/Chargenpflicht je Artikel
    ("artikel", "serienpflicht", "TINYINT NOT NULL DEFAULT 0"),
    ("artikel", "chargenpflicht", "TINYINT NOT NULL DEFAULT 0"),
    # (13.9) Handy-Stempel-App (Variante B): GPS-Standort je Stempelung
    ("stempelungen", "lat", "DECIMAL(9,6) NULL"),
    ("stempelungen", "lon", "DECIMAL(9,6) NULL"),
    ("stempelungen", "genauigkeit_m", "DECIMAL(7,1) NULL"),
    ("stempelungen", "geo_auftrag_id", "INT NULL"),
    ("stempelungen", "geo_abstand_m", "DECIMAL(9,1) NULL"),
    # geo_status: '' = ohne GPS, 'innerhalb' / 'ausserhalb' des Geofence,
    # 'ohne_geofence' = Standort erfasst, Auftrag ohne Geofence
    ("stempelungen", "geo_status", "VARCHAR(14) NOT NULL DEFAULT ''"),
    # (13.9) Geofence je Auftrag (Baustelle): Mittelpunkt + Radius in Metern
    ("av_auftrag", "geo_lat", "DECIMAL(9,6) NULL"),
    ("av_auftrag", "geo_lon", "DECIMAL(9,6) NULL"),
    ("av_auftrag", "geo_radius_m", "INT NULL"),
    # (13.9) Mitarbeiter: Zugang zur Handy-Stempel-App (PIN nur als Hash)
    ("mitarbeiter", "stempel_pin", "VARCHAR(200) NOT NULL DEFAULT ''"),
    ("mitarbeiter", "stempel_aktiv", "TINYINT NOT NULL DEFAULT 0"),
]

# Belegarten (Spalte belege.typ) und ihre Bezeichnungen
BELEGARTEN = {"A": "Angebot", "B": "Auftragsbestätigung",
              "L": "Lieferschein", "R": "Rechnung"}
RECHNUNGSARTEN = {"": "Rechnung", "gutschrift": "Gutschrift",
                  "abschlag": "Abschlagsrechnung",
                  "schluss": "Schlussrechnung"}


class DBError(Exception):
    pass


class KeinAktiverServer(DBError):
    """Hauptserver/Ersatzserver: keiner der Server ist freigegeben
    (beschreibbar) oder keiner ist erreichbar. 'server' enthält die
    Prüfergebnisse je Server (siehe Database.server_pruefen)."""

    def __init__(self, text, server=None):
        super().__init__(text)
        self.server = server or []


UMGESCHALTET = ("Die Datenbank wurde inzwischen auf den anderen Server "
                "umgeschaltet. Der Vorgang wurde nicht gespeichert - bitte "
                "noch einmal ausführen.")

# Fehlercodes: 1290 = Server ist schreibgeschützt (read_only),
# 1142/1146 = Tabelle fehlt bzw. keine Rechte
_SCHREIBGESCHUETZT = 1290


def _fehlercode(exc):
    try:
        return int(exc.args[0])
    except (AttributeError, IndexError, TypeError, ValueError):
        return 0


def fehler_kurz(exc):
    """Verständlicher Text zu einem Verbindungsfehler."""
    code = _fehlercode(exc)
    text = str(exc)
    if code == 1045:
        return "Zugang verweigert (Benutzer oder Kennwort falsch)"
    if code in (2003, 2002) or "Errno 111" in text or "timed out" in text:
        return "nicht erreichbar (Server aus oder Netzwerk gestört)"
    if code == 2005:
        return "Rechnername unbekannt"
    if code == 1049:
        return "Datenbank fehlt"
    return text


def server_text(host, port):
    return f"{host}:{port}" if int(port or 3306) != 3306 else str(host)


class Database:
    """Verbindung zur MariaDB.

    Optional mit Ersatzserver (Live-Kopie per MariaDB-Replikation): Dann
    wird beim Verbinden der Server gewählt, der freigegeben (nicht
    read_only) ist. Geht die Verbindung verloren oder wird der Server
    gesperrt, verbindet sich das Programm selbständig mit dem anderen,
    sofern dieser freigegeben ist. Umgeschaltet (freigegeben) wird nie
    automatisch, sondern nur über 'Ersatzserver aktivieren' bzw.
    'Rollen tauschen' (ausfall.py)."""

    RO_PRUEFEN_SEK = 30     # so oft prüfen, ob der Server noch frei ist

    def __init__(self, host, port, user, password, database="Firma",
                 ersatz_host="", ersatz_port=None):
        self.server = [(str(host).strip(), int(port or 3306))]
        if ersatz_host and str(ersatz_host).strip():
            self.server.append((str(ersatz_host).strip(),
                                int(ersatz_port or port or 3306)))
        self.user = user
        self.password = password
        self.aktiv_index = 0
        self.params = dict(host=self.server[0][0], port=self.server[0][1],
                           user=user, password=password)
        self.database = database
        self.conn = None
        self._settings_cache = None
        self._in_tx = False
        self._ro_zeit = time.monotonic()
        # Hinweis, z.B. wenn beide Server beschreibbar sind
        self.warnung = ""
        # angemeldeter Benutzer (für Änderungsprotokoll und Rechte);
        # leer = keine Benutzerverwaltung eingerichtet
        self.benutzer = ""
        self.benutzer_info = None

    # ------------------------------------------------------------------
    @property
    def mit_ersatz(self):
        return len(self.server) > 1

    @property
    def aktiver_server(self):
        h, p = self.server[self.aktiv_index]
        return server_text(h, p)

    def _oeffnen(self, index, timeout=8):
        host, port = self.server[index]
        return pymysql.connect(host=host, port=port, user=self.user,
                               password=self.password, charset="utf8mb4",
                               autocommit=True,
                               cursorclass=pymysql.cursors.DictCursor,
                               connect_timeout=timeout)

    def _server_info(self, index, timeout):
        host, port = self.server[index]
        info = {"index": index, "host": host, "port": port,
                "name": server_text(host, port), "erreichbar": False,
                "read_only": None, "aktiv_server": "", "aktiv_seit": None,
                "herzschlag": None, "db_da": False, "fehler": ""}
        try:
            c = self._oeffnen(index, timeout)
        except Exception as exc:
            info["fehler"] = fehler_kurz(exc)
            return info
        try:
            with c.cursor() as cur:
                cur.execute("SELECT @@global.read_only AS ro")
                info["read_only"] = int(cur.fetchone()["ro"])
                info["erreichbar"] = True
                try:
                    name = self.database.replace("`", "")
                    cur.execute(f"SELECT aktiv_server, aktiv_seit, herzschlag "
                                f"FROM `{name}`.ausfallsicherheit WHERE id=1")
                    row = cur.fetchone()
                    info["db_da"] = True
                    if row:
                        info.update(row)
                except Exception:
                    pass            # Tabelle fehlt / keine Rechte
        except Exception as exc:
            info["fehler"] = str(exc)
        finally:
            try:
                c.close()
            except Exception:
                pass
        return info

    def server_pruefen(self, timeout=4):
        """Prüft alle eingetragenen Server gleichzeitig: erreichbar,
        read_only, zuletzt freigegeben (aktiv_seit), Herzschlag."""
        erg = [None] * len(self.server)

        def pruefen(i):
            erg[i] = self._server_info(i, timeout)
        threads = [threading.Thread(target=pruefen, args=(i,), daemon=True)
                   for i in range(len(self.server))]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout * 3 + 2)
        return [e or {"index": i, "host": self.server[i][0],
                      "port": self.server[i][1],
                      "name": server_text(*self.server[i]),
                      "erreichbar": False, "read_only": None,
                      "aktiv_server": "", "aktiv_seit": None,
                      "herzschlag": None, "db_da": False,
                      "fehler": "Zeitüberschreitung"}
                for i, e in enumerate(erg)]

    @staticmethod
    def aktiven_waehlen(infos):
        """Liefert (index, warnung) des freigegebenen Servers oder wirft
        KeinAktiverServer."""
        erreichbar = [i for i in infos if i["erreichbar"]]
        if not erreichbar:
            raise KeinAktiverServer(
                "Keiner der Datenbank-Server ist erreichbar:\n" + "\n".join(
                    f"  {i['name']}: {i['fehler']}" for i in infos), infos)
        frei = [i for i in erreichbar if i["read_only"] == 0]
        if not frei:
            raise KeinAktiverServer(
                "Kein Datenbank-Server ist freigegeben.\n\n" + "\n".join(
                    f"  {i['name']}: " + (
                        "erreichbar, gesperrt (Live-Kopie)" if i["erreichbar"]
                        else i["fehler"])
                    for i in infos), infos)
        if len(frei) > 1:
            # ein noch nicht eingerichteter Server (ohne Faktura-Datenbank)
            # zählt nicht als zweiter freigegebener Server
            mit_db = [i for i in frei if i.get("db_da")]
            if mit_db:
                frei = mit_db
        if len(frei) == 1:
            return frei[0]["index"], ""
        # Beide beschreibbar: der zuletzt freigegebene gewinnt
        frei.sort(key=lambda i: (i["aktiv_seit"] is not None,
                                 i["aktiv_seit"] or datetime.datetime.min,
                                 -i["index"]), reverse=True)
        gewaehlt = frei[0]
        return gewaehlt["index"], (
            f"Achtung: Beide Datenbank-Server sind beschreibbar. Verwendet "
            f"wird {gewaehlt['name']} (zuletzt freigegeben). Bitte den "
            f"anderen Server sperren (Datei → Ausfallsicherheit).")

    # ------------------------------------------------------------------
    def connect(self, create=True):
        """Verbindet sich mit dem Server, legt die Datenbank und die
        Tabellen bei Bedarf an."""
        if self.mit_ersatz:
            idx, self.warnung = self.aktiven_waehlen(self.server_pruefen())
        else:
            idx, self.warnung = 0, ""
        conn = self._oeffnen(idx)
        name = self.database.replace("`", "")
        if create:
            with conn.cursor() as cur:
                cur.execute(f"CREATE DATABASE IF NOT EXISTS `{name}` "
                            f"CHARACTER SET utf8mb4")
        conn.select_db(name)
        self._aktiv_setzen(idx, conn)
        if create:
            for stmt in SCHEMA:
                self.execute(stmt)
            for tabelle, spalte, definition in MIGRATIONEN:
                if not self.query(f"SHOW COLUMNS FROM `{tabelle}` LIKE %s",
                                  (spalte,)):
                    self.execute(f"ALTER TABLE `{tabelle}` ADD COLUMN "
                                 f"`{spalte}` {definition}")
        return self

    def _aktiv_setzen(self, idx, conn):
        self.aktiv_index = idx
        self.conn = conn
        self.params["host"], self.params["port"] = self.server[idx]
        self._ro_zeit = time.monotonic()

    def neu_verbinden(self):
        """Mit dem (jetzt) freigegebenen Server neu verbinden."""
        alt = self.conn
        self.conn = None
        if alt is not None:
            try:
                alt.close()
            except Exception:
                pass
        if self.mit_ersatz:
            idx, self.warnung = self.aktiven_waehlen(self.server_pruefen())
        else:
            idx = 0
        try:
            conn = self._oeffnen(idx)
            conn.select_db(self.database.replace("`", ""))
        except DBError:
            raise
        except Exception as exc:
            raise DBError(f"Datenbankverbindung verloren: {exc}")
        self._aktiv_setzen(idx, conn)

    def close(self):
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None

    def _cursor(self):
        if self.conn is None:
            if not self.mit_ersatz:
                raise DBError("Keine Datenbankverbindung.")
            self.neu_verbinden()
        if not self.mit_ersatz:
            try:
                self.conn.ping(reconnect=True)
            except Exception as exc:
                raise DBError(f"Datenbankverbindung verloren: {exc}")
            return self.conn.cursor()
        try:
            self.conn.ping(reconnect=False)
        except Exception as exc:
            if self._in_tx:
                raise DBError(f"Datenbankverbindung verloren: {exc}")
            self.neu_verbinden()
        if not self._in_tx and \
                time.monotonic() - self._ro_zeit > self.RO_PRUEFEN_SEK:
            # Wurde dieser Server inzwischen gesperrt (Rollentausch)?
            self._ro_zeit = time.monotonic()
            try:
                with self.conn.cursor() as cur:
                    cur.execute("SELECT @@global.read_only AS ro")
                    gesperrt = int(cur.fetchone()["ro"])
            except Exception:
                gesperrt = 0
            if gesperrt:
                self.neu_verbinden()
        return self.conn.cursor()

    def _ausfuehren(self, sql, args, holen):
        for versuch in (1, 2):
            try:
                with self._cursor() as cur:
                    cur.execute(sql, args)
                    return list(cur.fetchall()) if holen else cur.lastrowid
            except pymysql.err.MySQLError as exc:
                if not self.mit_ersatz or \
                        _fehlercode(exc) != _SCHREIBGESCHUETZT or versuch == 2:
                    raise
                # Server wurde gesperrt (umgeschaltet): neu verbinden;
                # einzelne Anweisungen werden wiederholt, Transaktionen
                # nicht (die bisherigen Schritte sind verworfen)
                if self._in_tx:
                    try:
                        self.neu_verbinden()
                    except Exception:
                        pass
                    raise DBError(UMGESCHALTET)
                self.neu_verbinden()

    def query(self, sql, args=None):
        return self._ausfuehren(sql, args, True)

    def one(self, sql, args=None):
        rows = self.query(sql, args)
        return rows[0] if rows else None

    def value(self, sql, args=None):
        row = self.one(sql, args)
        if not row:
            return None
        return list(row.values())[0]

    def execute(self, sql, args=None):
        return self._ausfuehren(sql, args, False)

    def aendern(self, sql, args=None):
        """(9.1) Wie execute, liefert aber die Anzahl geänderter Zeilen
        (für bedingte Änderungen: UPDATE … WHERE status='offen')."""
        for versuch in (1, 2):
            try:
                with self._cursor() as cur:
                    return cur.execute(sql, args)
            except pymysql.err.MySQLError as exc:
                if not self.mit_ersatz or \
                        _fehlercode(exc) != _SCHREIBGESCHUETZT or versuch == 2:
                    raise
                if self._in_tx:
                    try:
                        self.neu_verbinden()
                    except Exception:
                        pass
                    raise DBError(UMGESCHALTET)
                self.neu_verbinden()

    @contextmanager
    def transaction(self):
        """Mehrere Anweisungen atomar ausführen."""
        self._cursor().close()
        self.conn.begin()
        self._in_tx = True
        try:
            yield self
            self.conn.commit()
        except Exception:
            try:
                self.conn.rollback()
            except Exception:
                pass
            raise
        finally:
            self._in_tx = False

    # ------------------------------------------------------------------
    # Einstellungen / Firmenstamm
    # ------------------------------------------------------------------
    def settings(self, reload=False):
        if self._settings_cache is None or reload:
            values = dict(DEFAULTS)
            for row in self.query("SELECT schluessel, wert FROM einstellungen"):
                values[row["schluessel"]] = row["wert"] if row["wert"] \
                    is not None else ""
            self._settings_cache = values
        return dict(self._settings_cache)

    def save_settings(self, values: dict):
        with self.transaction():
            for key, val in values.items():
                self.execute(
                    "REPLACE INTO einstellungen (schluessel, wert) "
                    "VALUES (%s, %s)", (key, "" if val is None else str(val)))
        self._settings_cache = None

    # ------------------------------------------------------------------
    # Nummernkreise
    # ------------------------------------------------------------------
    def next_number(self, typ, datum=None):
        """Vergibt die nächste fortlaufende Nummer je Nummernkreis
        (A, B, L, R, G, M, E – lückenlos, jährlich neu beginnend)."""
        datum = datum or datetime.date.today()
        jahr = datum.year
        fmt = self.settings().get(f"nr_format_{typ}") or \
            DEFAULTS.get(f"nr_format_{typ}", typ + "{jahr}-{nr:04d}")
        try:
            start = max(1, int(self.settings().get(f"nr_start_{typ}") or 1))
        except ValueError:
            start = 1
        with self.transaction():
            row = self.one("SELECT letzte FROM nummernkreise WHERE typ=%s "
                           "AND jahr=%s FOR UPDATE", (typ, jahr))
            if row is None:
                nr = start
                self.execute("INSERT INTO nummernkreise (typ, jahr, letzte) "
                             "VALUES (%s, %s, %s)", (typ, jahr, nr))
            else:
                # nie rückwärts: bereits vergebene Nummern bleiben eindeutig
                nr = max(row["letzte"] + 1, start)
                self.execute("UPDATE nummernkreise SET letzte=%s WHERE "
                             "typ=%s AND jahr=%s", (nr, typ, jahr))
        try:
            return fmt.format(jahr=jahr, nr=nr)
        except (KeyError, ValueError, IndexError):
            return f"{typ}{jahr}-{nr:04d}"

    def next_kundennr(self):
        start = int(self.settings().get("kundennr_start") or 10001)
        cur = self.value("SELECT MAX(kundennr) FROM kunden")
        return max(start, (cur or 0) + 1)

    def next_lieferantennr(self):
        start = int(self.settings().get("lieferantennr_start") or 70001)
        cur = self.value("SELECT MAX(lieferantennr) FROM lieferanten")
        return max(start, (cur or 0) + 1)


def to_decimal(value, default="0"):
    if value is None or value == "":
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value).strip().replace(".", "").replace(",", ".")
                   if isinstance(value, str) and "," in value
                   else str(value).strip())
