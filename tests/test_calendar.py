import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from icalendar import Calendar

from montreal_independent_music_calendar import build_calendar, ckut_events, has_things_events, merge_state


class FakeFetcher:
    def __init__(self, pages): self.pages = pages
    def get(self, url):
        return next(value for key, value in self.pages.items() if key in url)


def test_has_things_filters_independent_venues():
    data = {"items":[
        {"id":"1","title":"Noise Night","startsAt":"2026-10-12T00:00:00Z","endsAt":None,"status":"scheduled","venue":{"slug":"casa-del-popolo","name":"Casa del Popolo"},"sources":["Casa del Popolo listings"],"tags":[],"url":"https://example.test/1"},
        {"id":"2","title":"Arena Pop","startsAt":"2026-10-12T01:00:00Z","endsAt":None,"status":"scheduled","venue":{"slug":"bell-centre","name":"Bell Centre"},"sources":[],"tags":[],"url":"https://example.test/2"}],"nextOffset":None}
    got = has_things_events(FakeFetcher({"api/events":json.dumps(data)}), date(2026,10,10), date(2026,10,20))
    assert [event.title for event in got] == ["Noise Night"]
    assert got[0].start == "2026-10-11T20:00:00-04:00"


def test_ckut_event_and_overnight_end():
    listing = '''<div class="grid-item"><a href="https://ckut.ca/events/wefunk/"><div class="tags"><small>23/10/2026</small><small>10:00 pm - 3:00 am</small></div><h2>WEFUNK party</h2><div class="featured-blog-description">Party</div></a></div>'''
    detail = '<div class="side-bar-info">CKUT, La Sala Rossa<small>DATE</small></div>'
    got = ckut_events(FakeFetcher({"/events/wefunk":detail,"events/":listing}), date(2026,10,10), date(2026,11,1))
    assert got[0].venue == "La Sala Rossa"
    assert datetime.fromisoformat(got[0].end).date() == date(2026,10,24)


def test_ics_and_stable_state(tmp_path: Path):
    data = {"items":[{"id":"1","title":"Noise Night","startsAt":"2026-10-12T00:00:00Z","endsAt":None,"status":"scheduled","venue":{"slug":"casa-del-popolo","name":"Casa del Popolo"},"sources":[],"tags":[],"url":"https://example.test/1"}],"nextOffset":None}
    event = has_things_events(FakeFetcher({"api/events":json.dumps(data)}), date(2026,10,10), date(2026,10,20))[0]
    now = datetime(2026,10,10,12,tzinfo=ZoneInfo("America/Toronto"))
    events = merge_state([event], tmp_path / "state.json", now)
    parsed = Calendar.from_ical(build_calendar(events, now))
    item = parsed.walk("VEVENT")[0]
    assert str(item["UID"]) == event.uid
    assert item.decoded("DTSTART").tzinfo.key == "America/Toronto"
