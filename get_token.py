"""
Uruchom ten skrypt NA SWOIM KOMPUTERZE (nie na serwerze):
    python get_token.py

Skrypt:
1. Startuje lokalny serwer HTTP na porcie 8080
2. Otwiera przeglądarkę z linkiem do autoryzacji Allegro
3. Przechwytuje kod po przekierowaniu
4. Wymienia kod na token i zapisuje go do token.json

W Allegro Developer Portal ustaw Redirect URI na:
    http://localhost:8080/
"""

import http.server
import json
import os
import sys
import threading
import time
import urllib.parse
import webbrowser

import requests
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID     = os.getenv("ALLEGRO_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("ALLEGRO_CLIENT_SECRET", "")
USE_SANDBOX   = os.getenv("USE_SANDBOX", "false").lower() == "true"
PORT          = int(os.getenv("LOCAL_AUTH_PORT", "8080"))
REDIRECT_URI  = f"http://localhost:{PORT}/"

AUTH_BASE = "https://allegro.pl.allegrosandbox.pl" if USE_SANDBOX else "https://allegro.pl"
TOKEN_FILE = "token.json"

_captured_code: list[str] = []


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if "code" in params:
            _captured_code.append(params["code"][0])
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<h2>Autoryzacja OK! Mo\xc5\xbcesz zamkn\xc4\x85\xc4\x87 t\xc4\x99 kart\xc4\x99.</h2>"
            )
        elif "error" in params:
            err = params.get("error", ["?"])[0]
            desc = params.get("error_description", [""])[0]
            self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"<h2>B\u0142\u0105d: {err} – {desc}</h2>".encode())
            _captured_code.append(f"__error__{err}")
        else:
            self.send_response(200)
            self.end_headers()

    def log_message(self, *_):
        pass  # wycisz logi HTTP


def _start_server():
    server = http.server.HTTPServer(("localhost", PORT), _CallbackHandler)
    server.timeout = 1
    deadline = time.time() + 300  # max 5 minut oczekiwania
    while not _captured_code and time.time() < deadline:
        server.handle_request()
    server.server_close()


def main():
    if not CLIENT_ID or not CLIENT_SECRET:
        sys.exit("Brak ALLEGRO_CLIENT_ID / ALLEGRO_CLIENT_SECRET w .env")

    auth_url = (
        f"{AUTH_BASE}/auth/oauth/authorize"
        f"?response_type=code"
        f"&client_id={urllib.parse.quote(CLIENT_ID)}"
        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
    )

    print(f"Uruchamiam serwer na http://localhost:{PORT}/ ...")
    t = threading.Thread(target=_start_server, daemon=True)
    t.start()

    print(f"Otwieram przeglądarkę...\n{auth_url}\n")
    webbrowser.open(auth_url)
    print("Czekam na autoryzację w przeglądarce (max 5 minut)...")

    t.join(timeout=310)

    if not _captured_code:
        sys.exit("Timeout – przeglądarka nie odpowiedziała w ciągu 5 minut.")

    code = _captured_code[0]
    if code.startswith("__error__"):
        sys.exit(f"Allegro zwróciło błąd: {code[9:]}")

    print("Kod otrzymany, wymieniam na token...")
    resp = requests.post(
        f"{AUTH_BASE}/auth/oauth/token",
        auth=(CLIENT_ID, CLIENT_SECRET),
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
        },
        timeout=15,
    )
    if resp.status_code != 200:
        sys.exit(f"Błąd wymiany kodu: HTTP {resp.status_code} – {resp.text}")

    token = resp.json()
    token["expires_at"] = time.time() + token.get("expires_in", 3600)

    with open(TOKEN_FILE, "w") as f:
        json.dump(token, f, indent=2)

    print(f"\nToken zapisany do {TOKEN_FILE}")
    print("Skopiuj token.json na serwer do katalogu agenta.")


if __name__ == "__main__":
    main()
