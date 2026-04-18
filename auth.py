import json
import logging
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

TOKEN_FILE = Path("token.json")

SANDBOX = os.getenv("USE_SANDBOX", "false").lower() == "true"
AUTH_BASE = "https://allegro.pl.allegrosandbox.pl" if SANDBOX else "https://allegro.pl"
CLIENT_ID = os.getenv("ALLEGRO_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("ALLEGRO_CLIENT_SECRET", "")
REDIRECT_URI = os.getenv("ALLEGRO_REDIRECT_URI", "http://localhost")


class AllegroAuth:
    def __init__(self):
        self._token: dict = {}
        self._load_token()

    def _load_token(self):
        if TOKEN_FILE.exists():
            try:
                self._token = json.loads(TOKEN_FILE.read_text())
                logger.debug("Załadowano token z %s", TOKEN_FILE)
            except (json.JSONDecodeError, OSError):
                self._token = {}

    def _save_token(self, token: dict):
        self._token = token
        TOKEN_FILE.write_text(json.dumps(token, indent=2))
        logger.debug("Token zapisany do %s", TOKEN_FILE)

    def _is_expired(self) -> bool:
        if not self._token.get("access_token"):
            return True
        expires_at = self._token.get("expires_at", 0)
        return time.time() >= expires_at - 60  # 60s margines

    def _do_refresh(self):
        refresh_token = self._token.get("refresh_token")
        if not refresh_token:
            raise RuntimeError("Brak refresh_token – uruchom ponownie autoryzację: python auth.py")

        resp = requests.post(
            f"{AUTH_BASE}/auth/oauth/token",
            auth=(CLIENT_ID, CLIENT_SECRET),
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "redirect_uri": REDIRECT_URI,
            },
            timeout=15,
        )
        resp.raise_for_status()
        token = resp.json()
        token["expires_at"] = time.time() + token.get("expires_in", 3600)
        self._save_token(token)
        logger.info("Token odświeżony pomyślnie")

    def get_access_token(self) -> str:
        if self._is_expired():
            self._do_refresh()
        return self._token["access_token"]

    def authorize(self):
        """
        Autoryzacja przez Authorization Code Flow.
        1. Otwiera URL w przeglądarce (lub pokazuje go użytkownikowi).
        2. Po zatwierdzeniu Allegro przekierowuje na http://localhost?code=XXX
           – strona nie załaduje się, ale kod jest widoczny w pasku adresu.
        3. Użytkownik wkleja pełny URL lub sam kod.
        """
        import urllib.parse

        auth_url = (
            f"{AUTH_BASE}/auth/oauth/authorize"
            f"?response_type=code"
            f"&client_id={urllib.parse.quote(CLIENT_ID)}"
            f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
        )

        print("\n=== AUTORYZACJA ALLEGRO ===")
        print("1. Otwórz poniższy link w przeglądarce i zaloguj się:")
        print(f"\n   {auth_url}\n")
        print("2. Po zatwierdzeniu przeglądarka przekieruje na adres zaczynający się od:")
        print(f"   {REDIRECT_URI}?code=...")
        print("   (Strona prawdopodobnie nie załaduje się – to normalne)")
        print("3. Skopiuj CAŁY URL z paska adresu (lub samo 'code=...' z końca) i wklej poniżej.")
        raw = input("\nURL / kod: ").strip()

        # Wyciągnij kod z URL lub przyjmij jako surowy kod
        code = raw
        if "code=" in raw:
            parsed = urllib.parse.urlparse(raw)
            params = urllib.parse.parse_qs(parsed.query)
            code = params.get("code", [raw])[0]

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
            raise RuntimeError(f"Błąd wymiany kodu: HTTP {resp.status_code} – {resp.text}")

        token = resp.json()
        token["expires_at"] = time.time() + token.get("expires_in", 3600)
        self._save_token(token)
        print("Autoryzacja zakończona sukcesem! Token zapisany w token.json")

    # Zachowana kompatybilność wsteczna
    def device_flow_authorize(self):
        self.authorize()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    AllegroAuth().authorize()
