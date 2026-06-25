"""Send the daily Anatel data-status email via iCloud SMTP.

Every run sends an email regardless of change. The SUBJECT flags whether any
panel refreshed within RECENT_WINDOW_DAYS (default 4); the BODY always shows
the current state of every watched panel, with the recently-refreshed ones
highlighted at the top.
"""
import os
import smtplib
import ssl
import sys
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from typing import Dict, List, Optional

# Timezone: prefer IANA, fall back to fixed BRT (-03:00) if tzdata is missing.
try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try:
        LOCAL_TZ = ZoneInfo("America/Sao_Paulo")
    except ZoneInfoNotFoundError:
        LOCAL_TZ = timezone(timedelta(hours=-3))
except Exception:
    LOCAL_TZ = timezone(timedelta(hours=-3))

SMTP_HOST     = "smtp.mail.me.com"
SMTP_PORT_TLS = 587
SMTP_PORT_SSL = 465
# RULE (2026-06-25): PRODUCTION = work address only. The personal test inbox
# (rafaelxoliver4@gmail.com) is for TESTS ONLY and must NEVER share a recipient
# list with the work address. Tests override RECIPIENTS to the gmail address.
RECIPIENTS    = ["rafael.oliveira@ubs.com"]

# A panel refreshed within this many days is "recent" → flagged in the subject.
RECENT_WINDOW_DAYS = 4


def load_env() -> None:
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or "=" not in line or line.startswith("#"):
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _parse_iso(iso: str) -> Optional[datetime]:
    if not iso:
        return None
    try:
        s = iso.rstrip("Z").split(".")[0]
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _fmt_ts(iso: str) -> str:
    """Format an ISO-8601 UTC timestamp as 'DD MMM YYYY, HH:MM BRT'."""
    dt = _parse_iso(iso)
    if not dt:
        return iso or "—"
    return dt.astimezone(LOCAL_TZ).strftime("%d %b %Y, %H:%M BRT")


def _days_since(iso: str, now_utc: datetime) -> Optional[float]:
    dt = _parse_iso(iso)
    if not dt:
        return None
    return (now_utc - dt).total_seconds() / 86400.0


def _classify(panels: List[Dict]) -> List[Dict]:
    """Annotate each panel with `days_old` and `is_recent`."""
    now_utc = datetime.now(timezone.utc)
    out = []
    for p in panels:
        days = _days_since(p.get("current", ""), now_utc)
        out.append({
            **p,
            "days_old":  days,
            "is_recent": (days is not None) and (days <= RECENT_WINDOW_DAYS),
        })
    return out


def _build_subject(annotated: List[Dict]) -> str:
    """Subject pattern:
        'Anatel — Portabilidade atualizada (2d) | Acessos: estável'  (recent)
        'Anatel Daily — sem atualizacoes nos ultimos N dias'         (none)
    """
    today = datetime.now(LOCAL_TZ).strftime("%d %b")
    recent = [p for p in annotated if p["is_recent"]]
    if not recent:
        return f"Anatel Daily {today} — sem atualizacoes nos ultimos {RECENT_WINDOW_DAYS} dias"

    parts = []
    for p in recent:
        days = p["days_old"]
        days_str = "hoje" if days is not None and days < 1 else f"{int(round(days))}d"
        parts.append(f"{p['short']} ({days_str})")
    label = " + ".join(parts)
    return f"Anatel ATUALIZADO {today} — {label}"


def render_html(annotated: List[Dict]) -> str:
    now    = datetime.now(LOCAL_TZ)
    recent = [p for p in annotated if p["is_recent"]]
    stale  = [p for p in annotated if not p["is_recent"]]

    p = ['<div style="font-family:Arial,Helvetica,sans-serif;font-size:11pt;'
         'color:#1c1c1c;line-height:1.5;max-width:760px">']
    p.append(f'<h2 style="color:#1A2B4A;margin:0 0 4px 0;font-size:18pt">'
             f'Anatel Daily — {now.strftime("%d %b %Y")}</h2>')

    if recent:
        p.append(f'<p style="color:#1B7340;margin:0 0 12px 0;font-size:11pt;font-weight:bold">'
                 f'✓ {len(recent)} painel(is) com atualizacao nos ultimos '
                 f'{RECENT_WINDOW_DAYS} dias</p>')
    else:
        p.append(f'<p style="color:#9AAAB8;margin:0 0 12px 0;font-size:11pt">'
                 f'Sem atualizacoes detectadas nos ultimos {RECENT_WINDOW_DAYS} dias.</p>')
    p.append('<hr style="border:0;border-top:1.5px solid #1A2B4A;margin:0 0 12px 0"/>')

    def _block(panel: Dict, highlight: bool) -> List[str]:
        out = []
        bg = "#eaf6ed" if highlight else "transparent"
        bd = "4px solid #1B7340" if highlight else "4px solid #C8D4E3"
        out.append(
            f'<div style="background:{bg};border-left:{bd};'
            f'padding:10px 14px;margin:0 0 12px 0">'
        )
        title    = escape(panel.get("title", ""))
        days     = panel.get("days_old")
        cur_iso  = panel.get("current", "")
        prev_iso = panel.get("previous", "")
        urls     = panel.get("urls", []) or []
        error    = panel.get("error")

        days_str = ""
        if highlight and days is not None:
            d_int = int(round(days))
            if d_int <= 0:
                days_str = ' <span style="color:#1B7340;font-weight:bold">(hoje)</span>'
            else:
                days_str = f' <span style="color:#1B7340;font-weight:bold">({d_int}d atrás)</span>'
        elif days is not None:
            d_int = int(round(days))
            days_str = f' <span style="color:#9AAAB8">({d_int}d atrás)</span>'

        out.append(
            f'<p style="margin:0 0 4px 0;font-size:12pt;font-weight:bold;'
            f'color:#1A2B4A">{title}{days_str}</p>'
        )
        if error:
            out.append(f'<p style="color:#b00020;margin:2px 0;font-size:10pt">'
                       f'⚠ Erro ao consultar: {escape(error)}</p>')
        else:
            out.append(
                f'<p style="margin:2px 0;font-size:10pt">'
                f'<span style="color:#6B7E99">Atualizado em:</span> '
                f'<strong>{escape(_fmt_ts(cur_iso))}</strong>'
                f'</p>'
            )
            if prev_iso and prev_iso != cur_iso:
                out.append(
                    f'<p style="margin:2px 0;font-size:9.5pt;color:#9AAAB8">'
                    f'Atualizacao anterior: {escape(_fmt_ts(prev_iso))}'
                    f'</p>'
                )
        if urls:
            out.append('<ul style="margin:6px 0 0 0;padding-left:22px">')
            for url in urls:
                safe = escape(url, quote=True)
                out.append(
                    f'<li style="margin:2px 0;font-size:10pt">'
                    f'<a href="{safe}" style="color:#1c1c1c">{escape(url)}</a></li>'
                )
            out.append('</ul>')
        out.append('</div>')
        return out

    if recent:
        p.append('<p style="font-size:11pt;font-weight:bold;color:#1B7340;'
                 'margin:8px 0 6px 0">Atualizacoes recentes</p>')
        for pan in recent:
            p.extend(_block(pan, highlight=True))

    if stale:
        p.append('<p style="font-size:11pt;font-weight:bold;color:#6B7E99;'
                 'margin:18px 0 6px 0">Sem mudanca recente</p>')
        for pan in stale:
            p.extend(_block(pan, highlight=False))

    p.append('<hr style="border:0;border-top:0.5px solid #C8D4E3;margin-top:20px"/>')
    p.append(f'<p style="color:#9AAAB8;font-size:8pt;margin-top:10px">'
             f'Auto-gerado {now.strftime("%Y-%m-%d %H:%M %Z")} · '
             f'Anatel Monitor (Qlik qLastReloadTime)</p>')
    p.append('</div>')
    return "\n".join(p)


def _try_send_tls(msg, user, pw, recipients):
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT_TLS, timeout=30) as s:
        s.ehlo()
        s.starttls(context=ssl.create_default_context())
        s.ehlo()
        s.login(user, pw)
        s.send_message(msg, from_addr=user, to_addrs=recipients)
    return f"STARTTLS:{SMTP_PORT_TLS}"


def _try_send_ssl(msg, user, pw, recipients):
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT_SSL, timeout=30,
                          context=ssl.create_default_context()) as s:
        s.ehlo()
        s.login(user, pw)
        s.send_message(msg, from_addr=user, to_addrs=recipients)
    return f"SSL:{SMTP_PORT_SSL}"


def send(panels: List[Dict], dry_run: bool = False) -> str:
    """Send the daily Anatel digest. Always sends (even on no-change days)."""
    if not panels:
        return "no-panels"

    load_env()
    user = os.environ.get("FROM_EMAIL", "").strip()
    pw   = os.environ.get("EMAIL_APP_PASSWORD", "").strip()
    if not user or not pw:
        raise RuntimeError("FROM_EMAIL or EMAIL_APP_PASSWORD missing from .env")

    annotated = _classify(panels)
    subject   = _build_subject(annotated)
    html      = render_html(annotated)

    if dry_run:
        out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "_email_preview.html")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(f"<!-- subject: {subject} -->\n" + html)
        return f"dry-run wrote {out_path}  |  subject: {subject!r}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = user
    msg["To"]      = ", ".join(RECIPIENTS)
    msg.attach(MIMEText(html, "html", "utf-8"))

    last_err = None
    for name, fn in [("TLS(587)", _try_send_tls), ("SSL(465)", _try_send_ssl)]:
        try:
            return f"OK via {fn(msg, user, pw, RECIPIENTS)}  |  subject: {subject!r}"
        except Exception as e:
            last_err = (name, type(e).__name__, str(e))
            print(f"FAIL via {name}: {type(e).__name__}: {e}", file=sys.stderr)

    raise RuntimeError(f"All SMTP paths failed; last error: {last_err}")


if __name__ == "__main__":
    sample = [
        {
            "short":    "Portabilidade",
            "title":    "Portabilidade Numérica",
            "previous": "2026-04-15T18:00:00Z",
            "current":  "2026-05-01T20:00:00Z",  # 2 days ago → recent
            "urls":     ["https://informacoes.anatel.gov.br/paineis/portabilidade",
                         "https://dados.gov.br/dados/conjuntos-dados/portabilidade-numerica"],
        },
        {
            "short":    "Acessos",
            "title":    "Acessos — Telefonia Móvel & Banda Larga Fixa",
            "previous": "2026-04-02T20:05:00Z",
            "current":  "2026-04-02T20:05:00Z",  # 1 month ago → stale
            "urls":     ["https://informacoes.anatel.gov.br/paineis/acessos",
                         "https://informacoes.anatel.gov.br/paineis/acessos/telefonia-movel",
                         "https://informacoes.anatel.gov.br/paineis/acessos/banda-larga-fixa"],
        },
    ]
    print(send(sample, dry_run=True))
