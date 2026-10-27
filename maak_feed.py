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
    html = haal_pagina(url)
    soup = BeautifulSoup(html, "html.parser")

    preken, gezien = [], set()
    gemeente = "Rijssen"
    buffer, laatste_tekst = [], ""

    def voeg_toe(audio_url, eigen_titel=""):
        nonlocal laatste_tekst
        audio_url = urljoin(url, audio_url)
        if audio_url in gezien:
            return
        gezien.add(audio_url)
        if buffer:
            laatste_tekst = " ".join(buffer)
            buffer.clear()
        tekst = eigen_titel or laatste_tekst
        datum = nl_datum(tekst) or nl_datum(laatste_tekst)
        titel = DATUM_RE.sub("", tekst)
        titel = re.sub(r"^(zondag|woensdag|maandag|dinsdag|donderdag|vrijdag|zaterdag)\s*", "", titel.strip(), flags=re.I)
        if not titel.strip():
            titel = Path(unquote(urlparse(audio_url).path)).stem
        preken.append({"kerk": gemeente, "datum": datum, "tijd": "", "titel": titel, "url": audio_url})

    for el in soup.find_all(True):
        if el.name == "h2":
            kop = el.get_text(" ", strip=True)
            if "rijssen-" in kop.lower():
                gemeente = kop.split("|")[0].strip()
                buffer, laatste_tekst = [], ""
            continue
        if el.name == "p":
            t = el.get_text(" ", strip=True)
            if t:
                buffer.append(t)
        if el.name == "script" and el.string:
            for u in AUDIO_URL_RE.findall(el.string):
                voeg_toe(u.replace("\\/", "/"))
            continue
        for attr, waarde in el.attrs.items():
            waarden = waarde if isinstance(waarde, list) else [waarde]
            for w in waarden:
                if isinstance(w, str) and AUDIO_ATTR_RE.search(w):
                    eigen = el.get("data-title") or el.get("title") or ""
                    voeg_toe(w, eigen)

    # Vangnet: audio-adressen die nergens anders gevonden zijn
    gemeente = "Rijssen"
    for u in AUDIO_URL_RE.findall(html):
        voeg_toe(u.replace("\\/", "/"))
    return preken


BRONNEN = [("Amersfoort", amersfoort), ("Rijssen", rijssen)]


# ---------------------------------------------------------------- feed

from email.utils import format_datetime
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

NL = ZoneInfo("Europe/Amsterdam")
HIER = Path(__file__).resolve().parent
AFLEVERINGEN = HIER / "afleveringen.json"
FEED = HIER / "feed.xml"
MAX_AFLEVERINGEN = 400


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

    nieuw = 0
    for naam, functie in BRONNEN:
        try:
            preken = functie()
        except Exception as e:
            print(f"[{naam}] FOUT bij ophalen: {e}")
            continue
        print(f"[{naam}] {len(preken)} preken gevonden")
        for preek in preken:
            guid = preek["url"] + "|" + preek["titel"]
            status = "bekend"
            if guid not in bekend:
                afleveringen.append({
                    "guid": guid, "kerk": preek["kerk"], "titel": schoon(preek["titel"], 200),
                    "url": preek["url"], "pub": publicatietijd(preek).isoformat(),
                })
                bekend.add(guid)
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
