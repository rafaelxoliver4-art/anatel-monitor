"""Minimal Qlik Sense engine-API client.

The Anatel public dashboards are powered by Qlik Sense apps hosted at
dados.anatel.gov.br/qap. The Qlik engine speaks JSON-RPC over a WebSocket;
the engine accepts anonymous sessions for these public apps. We only need
one call per app: GetAppLayout, which returns metadata including the
authoritative `qLastReloadTime` — the moment the dataset was last refreshed.

This module uses the stdlib `urllib` for the bootstrap session cookie and
`websocket-client` (pip install websocket-client) for the WebSocket itself.
"""

import json
import ssl
import urllib.request
from typing import Optional, Tuple

try:
    import websocket  # websocket-client
except ImportError as e:
    raise ImportError(
        "Missing dependency 'websocket-client'. Run: pip install websocket-client"
    ) from e

QLIK_HOST = "dados.anatel.gov.br"
QLIK_PATH = "/qap"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _get_session_cookie(timeout: int = 15) -> str:
    """Hit the Qlik Hub anonymously to obtain an X-Qlik-Session cookie."""
    url = f"https://{QLIK_HOST}{QLIK_PATH}/sense/app/about"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        cookies = r.headers.get_all("Set-Cookie") or []
    for c in cookies:
        head = c.split(";", 1)[0].strip()
        if head.startswith("X-Qlik-Session-qap="):
            return head
        if head.startswith("X-Qlik-Session="):
            return head
    return ""  # Some Qlik deployments don't require the cookie for anonymous read


def _ws_url(app_id: str) -> str:
    return f"wss://{QLIK_HOST}{QLIK_PATH}/app/{app_id}"


def get_app_layout(app_id: str, timeout: int = 25) -> dict:
    """Open the app, ask for its layout, return the qLayout dict.

    Raises RuntimeError on protocol error.
    """
    cookie = _get_session_cookie(timeout=timeout)
    headers = [f"User-Agent: {USER_AGENT}"]
    if cookie:
        headers.append(f"Cookie: {cookie}")

    ws = websocket.create_connection(
        _ws_url(app_id),
        timeout=timeout,
        sslopt={"cert_reqs": ssl.CERT_REQUIRED},
        header=headers,
        origin=f"https://{QLIK_HOST}",
    )
    try:
        # The engine first sends an "OnConnected" notification — drain it.
        ws.recv()

        # 1) OpenDoc on the global handle (-1) → returns app handle in qReturn.qHandle
        ws.send(json.dumps({
            "jsonrpc": "2.0", "id": 1, "handle": -1,
            "method": "OpenDoc", "params": [app_id],
        }))
        app_handle = None
        for _ in range(10):
            msg = json.loads(ws.recv())
            if msg.get("id") == 1:
                ret = (msg.get("result") or {}).get("qReturn") or {}
                app_handle = ret.get("qHandle")
                if app_handle is None:
                    err = msg.get("error") or {}
                    raise RuntimeError(
                        f"OpenDoc failed for {app_id}: {err.get('message')}"
                    )
                break
        if app_handle is None:
            raise RuntimeError(f"OpenDoc: no response for {app_id}")

        # 2) GetAppLayout on the app handle → contains qLastReloadTime, qTitle
        ws.send(json.dumps({
            "jsonrpc": "2.0", "id": 2, "handle": app_handle,
            "method": "GetAppLayout", "params": [],
        }))
        for _ in range(10):
            msg = json.loads(ws.recv())
            if msg.get("id") == 2:
                layout = (msg.get("result") or {}).get("qLayout")
                if layout is None:
                    err = msg.get("error") or {}
                    raise RuntimeError(
                        f"GetAppLayout failed for {app_id}: {err.get('message')}"
                    )
                return layout
        raise RuntimeError(f"GetAppLayout: no response for {app_id}")
    finally:
        try:
            ws.close()
        except Exception:
            pass


def get_last_reload(app_id: str) -> Tuple[str, Optional[str]]:
    """Return (qTitle, qLastReloadTime ISO-8601) for the given app.

    qLastReloadTime is the moment the engine last reloaded the dataset —
    the authoritative "data refresh" signal.
    """
    layout = get_app_layout(app_id)
    title = layout.get("qTitle") or ""
    reload_time = layout.get("qLastReloadTime")
    return title, reload_time


if __name__ == "__main__":
    # Quick smoke test against the 3 known Anatel apps.
    apps = [
        ("portabilidade",        "7a857d55-dace-4bcd-a531-6545854aec70"),
        ("portabilidade-tabela", "a7b26c74-e381-486e-ae82-d910ccb04726"),
        ("acessos-suite",        "b00f5b60-c868-4b2e-b235-74ffc5c04a5a"),
    ]
    for label, app_id in apps:
        try:
            title, reload_time = get_last_reload(app_id)
            print(f"  {label:25s}  {title!r}  last_reload={reload_time}")
        except Exception as e:
            print(f"  {label:25s}  ERROR: {type(e).__name__}: {e}")
