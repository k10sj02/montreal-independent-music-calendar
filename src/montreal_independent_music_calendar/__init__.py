from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
from icalendar import Calendar, Event

TIMEZONE = ZoneInfo("America/Toronto")
HAS_THINGS = "https://montreal.hasthings.com/api/events"
CKUT = "https://ckut.ca/events/"
BOOMBOOM = "https://boomboom.today/"
USER_AGENT = "MontrealIndependentMusicCalendar/1.0 (+https://github.com/k10sj02/montreal-independent-music-calendar)"
VENUES = {
    "casa-del-popolo": ("Casa del Popolo", "4873 boul. Saint-Laurent, Montréal, QC"),
    "la-sala-rossa": ("La Sala Rossa", "4848 boul. Saint-Laurent, Montréal, QC"),
    "la-sotterenea": ("La Sotterenea", "4848 boul. Saint-Laurent, Montréal, QC"),
    "ptit-ours": ("P'tit Ours", "5589 av. du Parc, Montréal, QC"),
}
DISCOVERY = re.compile(r"\b(?:Suoni Per Il Popolo|CKUT|Ursa(?: Mtl)?|Akousma)\b", re.I)
FRENCH_MONTHS = {"janv": 1, "févr": 2, "mars": 3, "avr": 4, "mai": 5, "juin": 6, "juil": 7, "août": 8, "sept": 9, "oct": 10, "nov": 11, "déc": 12}
BOOMBOOM_DUPLICATE_VENUES = {"casa del popolo", "la sala rossa", "la sotterenea", "p'tit ours"}
BOOMBOOM_ADDRESSES = {
    "système": "7119 rue Saint-Hubert, Montréal, QC H2S 2N1",
    "le système": "7119 rue Saint-Hubert, Montréal, QC H2S 2N1",
    "bar datcha": "98 av. Laurier O, Montréal, QC",
    "sans soleil": "52 rue Saint-Zotique E, Montréal, QC",
    "salon daomé": "4465 boul. Saint-Laurent, Montréal, QC",
}


@dataclass(frozen=True)
class MusicEvent:
    source: str
    source_id: str
    title: str
    start: str
    end: str | None
    venue: str
    address: str
    url: str
    description: str = ""
    status: str = "CONFIRMED"

    @property
    def uid(self) -> str:
        raw = f"{self.source}|{self.source_id}".encode()
        return hashlib.sha256(raw).hexdigest()[:28] + "@montreal-independent-music"


class Fetcher:
    def __init__(self):
        self.client = httpx.Client(timeout=45, follow_redirects=True, headers={"User-Agent": USER_AGENT, "Accept-Language": "fr-CA,fr;q=.9,en;q=.8"})

    def get(self, url: str) -> str:
        response = self.client.get(url)
        response.raise_for_status()
        return response.text


def has_things_events(fetcher: Fetcher, start: date, end: date) -> list[MusicEvent]:
    params = {"from": start.isoformat(), "to": end.isoformat(), "category": "music", "limit": 500}
    payload = json.loads(fetcher.get(f"{HAS_THINGS}?{urlencode(params)}"))
    items = list(payload.get("items", []))
    if payload.get("nextOffset") is not None:
        params["offset"] = payload["nextOffset"]
        items.extend(json.loads(fetcher.get(f"{HAS_THINGS}?{urlencode(params)}")).get("items", []))
    output: list[MusicEvent] = []
    for item in items:
        venue_data = item.get("venue") or {}
        slug = venue_data.get("slug", "")
        haystack = " | ".join([item.get("title", ""), venue_data.get("name", ""), *(item.get("sources") or []), *(t.get("label", "") for t in item.get("tags") or [])])
        if slug not in VENUES and not DISCOVERY.search(haystack):
            continue
        when = datetime.fromisoformat(item["startsAt"].replace("Z", "+00:00")).astimezone(TIMEZONE)
        finish = item.get("endsAt")
        finish_dt = datetime.fromisoformat(finish.replace("Z", "+00:00")).astimezone(TIMEZONE) if finish else None
        venue, address = VENUES.get(slug, (venue_data.get("name") or "Montréal", "Montréal, QC"))
        tags = [t.get("label", "") for t in item.get("tags") or [] if t.get("kind") != "provider"]
        output.append(MusicEvent(
            source="has-things", source_id=item["id"], title=item["title"],
            start=when.isoformat(), end=finish_dt.isoformat() if finish_dt else None,
            venue=venue, address=address, url=item.get("ticketUrl") or item.get("url") or "https://montreal.hasthings.com/",
            description=" · ".join(tags + ["Data: Has Things (hasthings.com), ODbL 1.0"]),
            status="CANCELLED" if item.get("status") == "cancelled" else "CONFIRMED",
        ))
    return output


def ckut_events(fetcher: Fetcher, start: date, end: date) -> list[MusicEvent]:
    soup = BeautifulSoup(fetcher.get(CKUT), "html.parser")
    output: list[MusicEvent] = []
    for card in soup.select(".grid-item"):
        link = card.find("a", href=True)
        small = card.find_all("small")
        title_node = card.find("h2")
        if not link or len(small) < 2 or not title_node:
            continue
        match = re.search(r"(\d{2}/\d{2}/\d{4})", small[0].get_text(" ", strip=True))
        times = re.search(r"(\d{1,2}:\d{2}\s*[ap]m)\s*-\s*(\d{1,2}:\d{2}\s*[ap]m)", small[1].get_text(" ", strip=True), re.I)
        if not match or not times:
            continue
        day = datetime.strptime(match.group(1), "%d/%m/%Y").date()
        if not start <= day <= end:
            continue
        begins = datetime.combine(day, datetime.strptime(times.group(1).replace(" ", "").upper(), "%I:%M%p").time(), TIMEZONE)
        finishes = datetime.combine(day, datetime.strptime(times.group(2).replace(" ", "").upper(), "%I:%M%p").time(), TIMEZONE)
        if finishes <= begins:
            finishes += timedelta(days=1)
        detail = BeautifulSoup(fetcher.get(link["href"]), "html.parser")
        sidebar = detail.select_one(".side-bar-info")
        venue = "CKUT event"
        if sidebar:
            match_venue = re.search(r"CKUT,\s*([^\n]+)", sidebar.get_text("\n", strip=True), re.I)
            if match_venue:
                venue = match_venue.group(1).strip()
        address = next((value[1] for value in VENUES.values() if value[0].lower() == venue.lower()), "Montréal, QC")
        description_node = card.select_one(".featured-blog-description")
        output.append(MusicEvent(
            source="ckut", source_id=link["href"].rstrip("/").rsplit("/", 1)[-1],
            title=title_node.get_text(" ", strip=True), start=begins.isoformat(), end=finishes.isoformat(),
            venue=venue, address=address, url=link["href"],
            description=description_node.get_text(" ", strip=True) if description_node else "",
        ))
    return output


def boomboom_events(fetcher: Fetcher, start: date, end: date) -> list[MusicEvent]:
    """Read Montréal's electronic-event index, which includes RA-linked events."""
    soup = BeautifulSoup(fetcher.get(BOOMBOOM), "html.parser")
    output: list[MusicEvent] = []
    for card in soup.select("#event-list .event"):
        title_link = card.select_one("h3 a[href^='/events/']")
        meta = card.select_one(".meta")
        venue_node = card.select_one(".meta .location")
        if not title_link or not meta or not venue_node:
            continue
        title = title_link.get_text(" ", strip=True)
        venue = venue_node.get_text(" ", strip=True)
        if venue.casefold() in BOOMBOOM_DUPLICATE_VENUES:
            continue
        # A rare spam listing can enter this community index; reject obvious
        # service advertisements while retaining daytime and outdoor parties.
        if re.search(r"voyant|marabout|retour affectif|paiement après résultat", title, re.I):
            continue
        match = re.search(r"\b(\d{1,2})\s+(janv|févr|mars|avr|mai|juin|juil|août|sept|oct|nov|déc)\.\s+(\d{4})\s+(\d{1,2}):(\d{2})", meta.get_text(" ", strip=True), re.I)
        if not match:
            continue
        day, month, year, hour, minute = match.groups()
        begins = datetime(int(year), FRENCH_MONTHS[month.lower()], int(day), int(hour), int(minute), tzinfo=TIMEZONE)
        if not start <= begins.date() <= end:
            continue
        path = title_link["href"]
        event_id = path.rstrip("/").rsplit("/", 1)[-1]
        address = BOOMBOOM_ADDRESSES.get(venue.casefold(), "Montréal, QC")
        output.append(MusicEvent(
            source="boomboom", source_id=event_id, title=title,
            start=begins.isoformat(), end=None, venue=venue, address=address,
            url=f"https://boomboom.today{path}",
            description="Electronic / nightlife listing. The event page links to the original ticket source, including Resident Advisor when available.",
        ))
    if not output:
        raise RuntimeError("No current electronic events found")
    return output


def merge_state(current: list[MusicEvent], state_path: Path, now: datetime) -> list[MusicEvent]:
    old = {}
    if state_path.exists():
        try:
            old = json.loads(state_path.read_text()).get("events", {})
        except (OSError, json.JSONDecodeError):
            pass
    merged = {event.uid: {**asdict(event), "missing_runs": 0} for event in current}
    successful = {event.source for event in current}
    for uid, item in old.items():
        if uid in merged:
            continue
        try:
            begins = datetime.fromisoformat(item["start"])
        except (KeyError, ValueError):
            continue
        missing = int(item.get("missing_runs", 0)) + 1
        if begins >= now - timedelta(days=1) and (item.get("source") not in successful or missing < 2):
            merged[uid] = {**item, "missing_runs": missing}
        elif begins >= now - timedelta(days=1):
            merged[uid] = {**item, "status": "CANCELLED", "missing_runs": missing}
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"updated": now.isoformat(), "events": merged}, ensure_ascii=False, indent=2) + "\n")
    return [MusicEvent(**{k: v for k, v in item.items() if k != "missing_runs"}) for item in merged.values()]


def build_calendar(events: list[MusicEvent], generated: datetime) -> bytes:
    calendar = Calendar()
    calendar.add("prodid", "-//Montréal Independent Music Calendar//EN")
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    calendar.add("method", "PUBLISH")
    calendar.add("x-wr-calname", "Montréal Independent Music")
    calendar.add("x-wr-timezone", "America/Toronto")
    calendar.add("refresh-interval", timedelta(hours=6), parameters={"VALUE": "DURATION"})
    for item in sorted(events, key=lambda event: (event.start, event.title)):
        component = Event()
        component.add("uid", item.uid)
        component.add("dtstamp", generated)
        component.add("dtstart", datetime.fromisoformat(item.start).astimezone(TIMEZONE))
        if item.end:
            component.add("dtend", datetime.fromisoformat(item.end).astimezone(TIMEZONE))
        component.add("summary", item.title)
        component.add("location", ", ".join(filter(None, [item.venue, item.address])))
        component.add("description", "\n".join(filter(None, [item.description, f"Source: {item.url}"])))
        component.add("url", item.url)
        component.add("status", item.status)
        component.add("categories", "Independent Music,Experimental Music")
        calendar.add_component(component)
    return calendar.to_ical()


def main() -> None:
    root = Path.cwd()
    now = datetime.now(TIMEZONE)
    final_day = now.date() + timedelta(days=60)
    fetcher = Fetcher()
    sources, errors = {}, {}
    collected: list[MusicEvent] = []
    for name, loader in (("venues-and-festivals", has_things_events), ("ckut", ckut_events), ("electronic-and-raves", boomboom_events)):
        try:
            events = loader(fetcher, now.date(), final_day)
            collected.extend(events)
            sources[name] = len(events)
        except Exception as exc:
            errors[name] = str(exc)
    if not collected:
        raise RuntimeError("No current events found; refusing to publish an empty calendar")
    by_uid = {event.uid: event for event in collected}
    events = merge_state(list(by_uid.values()), root / "data/state.json", now)
    public = root / "public"
    public.mkdir(exist_ok=True)
    (public / "montreal-independent-music.ics").write_bytes(build_calendar(events, now))
    status = {"generated": now.isoformat(), "count": sum(e.status != "CANCELLED" for e in events), "cancelled": sum(e.status == "CANCELLED" for e in events), "sources": sources, "errors": errors}
    (public / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(status, ensure_ascii=False))
