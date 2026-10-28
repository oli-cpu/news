#!/usr/bin/env python3
"""
news.studer.website – Zeitplan-Wächter
======================================

GitHub startet geplante Workflows nur „ungefähr“ (oft verspätet, manchmal gar
nicht) und kennt nur UTC. Darum läuft der Workflow mehrmals rund um die
Wunschzeiten an, und dieses Script entscheidet, ob wirklich aktualisiert wird:

  * manuell gestartet oder neuer Code (push)  → immer
  * sonst nur, wenn gerade ein Update-Fenster offen ist (z.B. 05:00–08:00 Uhr
    Schweizer Zeit) UND für dieses Fenster noch kein Update online ist.

So gibt es pro Termin genau ein Update – egal ob es von GitHub selbst, vom
Ersatz-Termin oder von einem externen Wecker (cron-job.org, Heimserver)
ausgelöst wurde. Sommer-/Winterzeit wird automatisch berücksichtigt.

Einstellungen in config.json → "schedule":
  { "times": ["05:00", "12:00"], "timezone": "Europe/Zurich", "windowHours": 3 }

Ergebnis: schreibt run=true/false nach $GITHUB_OUTPUT.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore


def decide(cfg: dict, event: str, source: str, now_utc: datetime, deployed_generated: datetime | None) -> tuple[bool, str]:
    if event == "push":
        return True, "neuer Code (push)"
    if event == "workflow_dispatch" and source != "cron":
        return True, "manuell gestartet"

    sch = cfg.get("schedule", {})
    tz = ZoneInfo(sch.get("timezone", "Europe/Zurich")) if ZoneInfo else timezone(timedelta(hours=1))
    window = timedelta(hours=float(sch.get("windowHours", 3)))
    now = now_utc.astimezone(tz)

    for t in sch.get("times", ["05:00", "12:00"]):
        hh, mm = (int(x) for x in t.split(":"))
        slot = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        early = timedelta(minutes=15)          # ein Wecker darf etwas zu früh klingeln
        if slot - early <= now < slot + window:
            if deployed_generated and deployed_generated.astimezone(tz) >= slot - early:
                return False, f"Update für {t} Uhr ist schon online (Stand {deployed_generated.astimezone(tz):%H:%M})"
            return True, f"Update-Fenster {t} Uhr offen (jetzt {now:%H:%M} {now.tzname()})"
    return False, f"kein Update-Fenster offen (jetzt {now:%H:%M} {now.tzname()})"


def deployed_time(cfg: dict) -> datetime | None:
    url = os.environ.get("NEWS_URL") or (f"https://{cfg['site']['domain']}/news.json" if cfg.get("site", {}).get("domain") else "")
    if not url:
        return None
    try:
        req = urllib.request.Request(f"{url}?gate={int(datetime.now().timestamp())}",
                                     headers={"User-Agent": "StuderNews-Gate/1.0", "Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
        return datetime.fromisoformat(data["generated"])
    except Exception as e:  # noqa: BLE001
        print(f"Hinweis: aktuelle news.json nicht lesbar ({type(e).__name__}) – aktualisiere sicherheitshalber")
        return None


def main() -> int:
    with open(os.environ.get("CONFIG", "config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    event = os.environ.get("EVENT", "workflow_dispatch")
    source = os.environ.get("SOURCE", "") or "manual"
    run, why = decide(cfg, event, source, datetime.now(timezone.utc),
                      None if event == "push" or (event == "workflow_dispatch" and source != "cron") else deployed_time(cfg))
    print(f"{'▶ AKTUALISIEREN' if run else '⏭ ÜBERSPRINGEN'}: {why}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"run={'true' if run else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
