"""Daily Anatel data-update monitor.

Pings each tracked Qlik Sense app, reads its `qLastReloadTime`, compares
against the last-seen value in state.json, and emails an alert if any of
them advanced. Designed to run unattended via Windows Task Scheduler.

CLI:
  python monitor.py                     # daily run: scrape + email
  python monitor.py --force             # email regardless of change (manual trigger)
  python monitor.py --dry-email         # render HTML preview, don't send
  python monitor.py --no-state          # don't persist state (useful for testing)
  python monitor.py --week-window-only  # exit early unless today is in first
                                        # 7 or last 7 days of the month — used
                                        # by the 18:00 BRT evening trigger.
"""

import calendar
import json
import os
import sys
import traceback
from datetime import datetime
from typing import Dict, List

from qlik_client import get_app_layout
from email_alert import send as send_email, LOCAL_TZ

HERE       = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(HERE, "state.json")
LOG_PATH   = os.path.join(HERE, "monitor.log")

# Each entry: (key, qlik_app_id, short_label, full_title, list of dashboard URLs)
WATCHED = [
    (
        "portabilidade",
        "7a857d55-dace-4bcd-a531-6545854aec70",
        "Portabilidade",
        "Portabilidade Numérica",
        [
            "https://informacoes.anatel.gov.br/paineis/portabilidade",
            "https://dados.gov.br/dados/conjuntos-dados/portabilidade-numerica",
        ],
    ),
    (
        "acessos",
        "b00f5b60-c868-4b2e-b235-74ffc5c04a5a",
        "Acessos",
        "Acessos — Telefonia Móvel & Banda Larga Fixa",
        [
            "https://informacoes.anatel.gov.br/paineis/acessos",
            "https://informacoes.anatel.gov.br/paineis/acessos/telefonia-movel",
            "https://informacoes.anatel.gov.br/paineis/acessos/banda-larga-fixa",
        ],
    ),
]


def _load_state() -> Dict[str, Dict]:
    if not os.path.exists(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(state: Dict) -> None:
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_PATH)


def _log(msg: str) -> None:
    line = f"[{datetime.now(LOCAL_TZ).strftime('%Y-%m-%d %H:%M:%S %Z')}] {msg}"
    print(line)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def check_all() -> List[Dict]:
    """Query every watched app, return the list of currently-known reload times."""
    out = []
    for key, app_id, short, title, urls in WATCHED:
        try:
            layout = get_app_layout(app_id)
            cur    = layout.get("qLastReloadTime") or ""
            qtitle = layout.get("qTitle") or ""
            out.append({
                "key": key, "app_id": app_id, "short": short, "title": title,
                "qtitle": qtitle, "urls": urls, "current": cur,
                "error": None,
            })
        except Exception as e:
            out.append({
                "key": key, "app_id": app_id, "short": short, "title": title,
                "qtitle": "", "urls": urls, "current": "",
                "error": f"{type(e).__name__}: {e}",
            })
    return out


def _is_first_or_last_week(now: datetime) -> bool:
    """True if `now` falls in the first 7 days or the last 7 calendar days
    of its month. Used by the evening trigger to decide whether to run."""
    day = now.day
    if day <= 7:
        return True
    _, last_day = calendar.monthrange(now.year, now.month)
    return day > (last_day - 7)  # e.g. 31-day month → last 7 = days 25..31


def main():
    force            = "--force"             in sys.argv
    dry_email        = "--dry-email"         in sys.argv
    no_state         = "--no-state"          in sys.argv
    week_window_only = "--week-window-only"  in sys.argv

    now = datetime.now(LOCAL_TZ)

    if week_window_only and not _is_first_or_last_week(now):
        _log(f"Skipping evening run — {now.strftime('%Y-%m-%d')} is not in "
             f"first/last week of the month (--week-window-only).")
        sys.exit(0)

    _log(f"Monitor starting (force={force} dry_email={dry_email} "
         f"week_window_only={week_window_only})")

    state     = _load_state()
    results   = check_all()
    new_state = dict(state)
    panels    = []
    error_count = 0
    change_count = 0

    for r in results:
        key  = r["key"]
        prev = (state.get(key) or {}).get("last_reload", "")
        cur  = r["current"]
        if r["error"]:
            error_count += 1
            _log(f"  [ERR] {key}: {r['error']}")
        else:
            _log(f"  {key:18s} prev={prev or '(none)'}  current={cur}")
            new_state[key] = {
                "last_reload": cur,
                "qtitle":      r["qtitle"],
                "checked_at":  datetime.now(LOCAL_TZ).isoformat(timespec="seconds"),
            }
            if prev and cur and cur != prev:
                change_count += 1

        panels.append({
            "key":      r["key"],
            "short":    r["short"],
            "title":    r["title"],
            "previous": prev,
            "current":  cur,
            "urls":     r["urls"],
            "error":    r["error"],
        })

    # Daily mode: ALWAYS email — subject + highlight reflect 4-day recency.
    try:
        status = send_email(panels, dry_run=dry_email)
        _log(f"  EMAIL: {status}  (changes_since_last_run={change_count})")
    except Exception as e:
        _log(f"  [ERR] email: {type(e).__name__}: {e}")
        traceback.print_exc()

    if not no_state:
        _save_state(new_state)
        _log(f"  State persisted to {STATE_PATH}")

    _log(f"Monitor finished. errors={error_count} changes={change_count}")
    sys.exit(0 if error_count == 0 else 1)


if __name__ == "__main__":
    main()
