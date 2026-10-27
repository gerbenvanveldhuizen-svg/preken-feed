"""
Maakt een podcastfeed (feed.xml) met preken van kerkwebsites.
Draait dagelijks via GitHub Actions; de feed verwijst naar de mp3's
op de kerkwebsites zelf. Abonneer je in Player FM op de feed-URL.
"""
import argparse
import datetime
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("Installeer eerst de benodigde onderdelen met:")
    print("    pip install requests beautifulsoup4")
    sys.exit(1)



HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) preken-archief"}

MAANDEN = {
    "januari": 1, "februari": 2, "maart": 3, "april": 4, "mei": 5, "juni": 6,
    "juli": 7, "augustus": 8, "september": 9, "oktober": 10, "november": 11, "december": 12,
}
DATUM_RE = re.compile(r"(\d{1,2})\s+(" + "|".join(MAANDEN) + r")\s+(\d{4})", re.I)
AUDIO_ATTR_RE = re.compile(r"\.(mp3|m4a|ogg|wav)(\?|#|$)", re.I)
AUDIO_URL_RE = re.compile(r"""(?:https?:)?//[^\s"'<>\\]+?\.(?:mp3|m4a|ogg|wav)(?:\?[^\s"'<>\\]*)?""", re.I)


# ---------------------------------------------------------------- hulpjes

def haal_pagina(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text


def schoon(tekst, max_len=110):
    tekst = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", tekst)
    tekst = re.sub(r"\s+", " ", tekst).strip(" .-")
    if len(tekst) > max_len:
        tekst = tekst[:max_len].rsplit(" ", 1)[0]
    return tekst.strip(" .-")


def nl_datum(tekst):
    m = DATUM_RE.search(tekst or "")
    if not m:
        return None
    try:
        return datetime.date(int(m.group(3)), MAANDEN[m.group(2).lower()], int(m.group(1)))
    except ValueError:
        return None


def extensie(url):
    pad = urlparse(url).path.lower()
    for ext in (".mp3", ".m4a", ".ogg", ".wav"):
        if pad.endswith(ext):
            return ext
    return ".mp3"


# ---------------------------------------------------------------- Amersfoort

def amersfoort():
    url = "https://www.gergemamersfoort.nl/kerkdiensten/preken-naluisteren"
    soup = BeautifulSoup(haal_pagina(url), "html.parser")
    preken = []
    for rij in soup.find_all("tr"):
        cellen = rij.find_all("td")
        link = rij.find("a", href=AUDIO_ATTR_RE)
        if len(cellen) < 4 or not link:
            continue
        mp3 = urljoin(url, link["href"])
        if re.search(r"/mp3/\?", mp3):  # lege regel zonder opname
            continue
        datumtijd, tekst, thema, predikant = [c.get_text(" ", strip=True) for c in cellen[:4]]
        m = re.match(r"(\d{2})-(\d{2})-(\d{2})\s+(\d{2})[:.](\d{2})", datumtijd)
        datum, tijd = None, ""
        if m:
            try:
                datum = datetime.date(2000 + int(m.group(3)), int(m.group(2)), int(m.group(1)))
                tijd = f"{m.group(4)}.{m.group(5)}"
            except ValueError:
                pass
        titel = " - ".join(x for x in (thema, predikant, tekst) if x)
        preken.append({"kerk": "Amersfoort", "datum": datum, "tijd": tijd, "titel": titel, "url": mp3})
    return preken


# ---------------------------------------------------------------- Rijssen

def rijssen():
    url = "https://www.gergemrijssen.nl/terugluisteren/"
    soup = BeautifulSoup(haal_pagina(url), "html.parser")

    preken, gezien = [], set()
    gemeente = "Rijssen"
    buffer, laatste = [], ""

    def voeg_toe(audio_url):
        nonlocal laatste
        audio_url = urljoin(url, audio_url.replace("\\/", "/"))
        # Alleen echte opnames, geen golfvorm-bestanden e.d.
        if "/opname/" not in audio_url or audio_url in gezien:
            return
        gezien.add(audio_url)
        if buffer:
            laatste = " ".join(buffer)
            buffer.clear()
        datum = nl_datum(laatste)
        tekst = DATUM_RE.sub("", laatste).strip()
        tekst = re.sub(r"^(zondag|maandag|dinsdag|woensdag|donderdag|vrijdag|zaterdag)\s*", "", tekst, flags=re.I)
        naam = audio_url.lower()
        tijd = ""
        if "morgendienst" in naam:
            tijd = "09.30"
            m = re.search(r"morgendienst\s*:?\s*(.*?)(?=avonddienst|$)", tekst, re.I | re.S)
            if m and m.group(1).strip():
                tekst = m.group(1)
        elif "avonddienst" in naam:
            tijd = "17.00"
            m = re.search(r"avonddienst\s*:?\s*(.*)$", tekst, re.I | re.S)
            if m and m.group(1).strip():
                tekst = m.group(1)
        if "weekdienst" in naam or "zendingsdienst" in naam:
            tijd = "19.30"
        titel = tekst.strip() or Path(unquote(urlparse(audio_url).path)).stem
        preken.append({"kerk": gemeente, "datum": datum, "tijd": tijd, "titel": titel, "url": audio_url})

    for el in soup.find_all(True):
        if el.name == "h2":
            kop = el.get_text(" ", strip=True)
            if "rijssen-" in kop.lower():
                gemeente = kop.split("|")[0].strip()
                buffer, laatste = [], ""
            continue
        if el.name == "p":
            t = el.get_text(" ", strip=True)
            if t:
                buffer.append(t)
        if el.name == "script" and el.string:
            for u in AUDIO_URL_RE.findall(el.string):
                voeg_toe(u)
            continue
        for waarde in el.attrs.values():
            for w in (waarde if isinstance(waarde, list) else [waarde]):
                if isinstance(w, str) and AUDIO_ATTR_RE.search(w):
                    voeg_toe(w)
    return preken


# ---------------------------------------------------------------- rooster (kerktijden.nl)

KERKTIJDEN_IDS = {"Rijssen-Noord": 257, "Rijssen-West": 285, "Rijssen-Zuid": 284}
KERKTIJDEN_API = "https://api.kerktijden.nl/api/gathering/GetGatheringsForWidget"


def persoon_naam(p):
    delen = [p.get("initials") or p.get("firstname") or "", p.get("insertion") or "", p.get("lastname") or ""]
    naam = " ".join(d for d in delen if d).strip()
    return ("Ds. " + naam) if naam else ""


def werk_rooster_bij(rooster):
    """Slaat de komende diensten met voorganger op; het rooster toont geen verleden."""
    for gemeente, cid in KERKTIJDEN_IDS.items():
        try:
            r = requests.get(KERKTIJDEN_API, params={"communityId": cid, "weeks": 4},
                             headers=HEADERS, timeout=30)
            r.raise_for_status()
            diensten = r.json()
        except Exception as e:
            print(f"[rooster {gemeente}] FOUT: {e}")
            continue
        for g in diensten if isinstance(diensten, list) else []:
            if g.get("cancelled") or not g.get("startTime"):
                continue
            soorten = [t.get("name", "") for t in g.get("gatheringTypes") or []]
            namen = [persoon_naam(p) for p in g.get("persons") or []
                     if any(rol.get("name") == "Voorganger" for rol in p.get("roles") or [])]
            namen = [n for n in namen if n]
            if namen:
                wie = " en ".join(namen)
            elif any("lees" in s.lower() for s in soorten):
                wie = "Leesdienst"
            else:
                continue
            rooster[f"{gemeente}|{g['startTime'][:16]}"] = wie
    # alleen het laatste jaar bewaren
    grens = (datetime.date.today() - datetime.timedelta(days=365)).isoformat()
    for sleutel in [k for k in rooster if k.split("|")[1][:10] < grens]:
        del rooster[sleutel]
    return rooster


def zoek_voorganger(rooster, preek):
    if not preek["datum"] or preek["kerk"] not in KERKTIJDEN_IDS:
        return ""
    dag = preek["datum"].isoformat()
    diensten = sorted((k.split("|")[1][11:16], v) for k, v in rooster.items()
                      if k.startswith(preek["kerk"] + "|" + dag))
    if not diensten:
        return ""
    if preek["tijd"] == "09.30":   # morgendienst: eerste dienst voor 12 uur
        kandidaten = [v for t, v in diensten if t < "12:00"]
        return kandidaten[0] if kandidaten else ""
    kandidaten = [v for t, v in diensten if t >= "16:00"]   # avond- of weekdienst
    return kandidaten[-1] if kandidaten else ""


BRONNEN = [("Amersfoort", amersfoort), ("Rijssen", rijssen)]


# ---------------------------------------------------------------- feed

from email.utils import format_datetime
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

NL = ZoneInfo("Europe/Amsterdam")
HIER = Path(__file__).resolve().parent
AFLEVERINGEN = HIER / "afleveringen.json"
FEED = HIER / "feed.xml"
ROOSTER = HIER / "voorgangers.json"
MAX_AFLEVERINGEN = 400
ICOON_URL = "https://gerbenvanveldhuizen-svg.github.io/preken-feed/icoon.png"


def publicatietijd(preek):
    if preek["datum"]:
        uur, minuut = 12, 0
        if preek["tijd"]:
            uur, minuut = (int(x) for x in preek["tijd"].split("."))
        return datetime.datetime(preek["datum"].year, preek["datum"].month, preek["datum"].day,
                                 uur, minuut, tzinfo=NL)
    return datetime.datetime.now(NL)


def schrijf_feed(afleveringen):
    items = []
    for a in afleveringen:
        pub = datetime.datetime.fromisoformat(a["pub"])
        url_attr = escape(a["url"], {'"': "&quot;"})
        type_ = "audio/mp4" if a["url"].lower().split("?")[0].endswith(".m4a") else "audio/mpeg"
        items.append(f"""  <item>
   <title>{escape(a['kerk'] + ': ' + a['titel'])}</title>
   <description>{escape(a['kerk'] + ' - ' + a['titel'])}</description>
   <guid isPermaLink="false">{escape(a['guid'])}</guid>
   <pubDate>{format_datetime(pub)}</pubDate>
   <enclosure url="{url_attr}" length="0" type="{type_}"/>
  </item>""")
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
 <channel>
  <title>Preken Amersfoort en Rijssen</title>
  <link>https://www.gergemamersfoort.nl/kerkdiensten/preken-naluisteren</link>
  <description>Persoonlijke feed met links naar preken van Ger. Gem. Amersfoort en Ger. Gem. Rijssen.</description>
  <language>nl</language>
  <itunes:block>Yes</itunes:block>
  <itunes:image href="{ICOON_URL}"/>
  <image><url>{ICOON_URL}</url><title>Preken Amersfoort en Rijssen</title><link>https://www.gergemamersfoort.nl/kerkdiensten/preken-naluisteren</link></image>
  <lastBuildDate>{format_datetime(datetime.datetime.now(NL))}</lastBuildDate>
{chr(10).join(items)}
 </channel>
</rss>
"""
    FEED.write_text(xml, encoding="utf-8")


def main():
    afleveringen = []
    if AFLEVERINGEN.exists():
        afleveringen = json.loads(AFLEVERINGEN.read_text(encoding="utf-8"))
    bekend = {a["guid"] for a in afleveringen}
    bekend |= {f'{a["kerk"]}|{a["url"]}|{a["pub"][:16]}' for a in afleveringen}

    rooster = {}
    if ROOSTER.exists():
        rooster = json.loads(ROOSTER.read_text(encoding="utf-8"))
    rooster = werk_rooster_bij(rooster)
    ROOSTER.write_text(json.dumps(rooster, indent=1, ensure_ascii=False, sort_keys=True), encoding="utf-8")

    nieuw = 0
    for naam, functie in BRONNEN:
        try:
            preken = functie()
        except Exception as e:
            print(f"[{naam}] FOUT bij ophalen: {e}")
            continue
        print(f"[{naam}] {len(preken)} preken gevonden")
        for preek in preken:
            wie = zoek_voorganger(rooster, preek)
            if wie and wie.split()[-1].lower() not in preek["titel"].lower():
                preek["titel"] = f"{wie} - {preek['titel']}"
            pub = publicatietijd(preek).isoformat()
            sleutel = f'{preek["kerk"]}|{preek["url"]}|{pub[:16]}'
            guid = preek["url"] + "|" + preek["titel"]
            status = "bekend"
            if guid not in bekend and sleutel not in bekend:
                afleveringen.append({
                    "guid": guid, "kerk": preek["kerk"], "titel": schoon(preek["titel"], 200),
                    "url": preek["url"], "pub": pub,
                })
                bekend.add(guid)
                bekend.add(sleutel)
                nieuw += 1
                status = "NIEUW"
            print(f"   {status:6} {preek['kerk']}: {preek['titel'][:80]}")
            print(f"          {preek['url']}")

    afleveringen.sort(key=lambda a: a["pub"], reverse=True)
    afleveringen = afleveringen[:MAX_AFLEVERINGEN]
    AFLEVERINGEN.write_text(json.dumps(afleveringen, indent=1, ensure_ascii=False), encoding="utf-8")
    schrijf_feed(afleveringen)
    print(f"Klaar: {nieuw} nieuw, {len(afleveringen)} in de feed.")


if __name__ == "__main__":
    main()
