# Montréal Independent Music Calendar

Website: https://k10sj02.github.io/montreal-independent-music-calendar/

Subscription: https://k10sj02.github.io/montreal-independent-music-calendar/montreal-independent-music.ics

An automatically refreshed calendar for independent, experimental, community, and electronic music events in Montréal. It includes Casa del Popolo, La Sala Rossa, La Sotterenea, P'tit Ours, CKUT, raves and Resident Advisor-linked events indexed by boomboom, Le Système, plus dated Suoni per il Popolo, Ursa, and Akousma listings when published.

The source uses `America/Toronto`, stable event identifiers, cancellation retention, official links, and a 60-day window. Venue listings are selected from Has Things' Montréal dataset under ODbL 1.0 with attribution stored in every event; CKUT events come from CKUT's official event page. Electronic events come from boomboom's Montréal index, whose detail pages link to the original ticket listing, including Resident Advisor when available.

PHI is not yet automatically included: its listening installations often publish date ranges and variable daily sessions rather than individual start times. The calendar does not invent one time for those ranges.

## Local use

```sh
python -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
pytest
montreal-independent-music-calendar
```
