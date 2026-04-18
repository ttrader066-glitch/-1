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

    def device_flow_authorize(self):
        """Interaktywna autoryzacja przez device flow – uruchom raz, żeby uzyskać token."""
        resp = requests.post(
            f"{AUTH_BASE}/auth/oauth/device",
            auth=(CLIENT_ID, CLIENT_SECRET),
            data={"client_id": CLIENT_ID},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        print("\n=== AUTORYZACJA ALLEGRO ===")
        print(f"Otwórz stronę: {data['verification_uri_complete']}")
        print(f"I wpisz kod:   {data['user_code']}")
        print("Czekam na potwierdzenie...\n")

        device_code = data["device_code"]
        interval = data.get("interval", 5)
        expires_in = data.get("expires_in", 600)
        deadline = time.time() + expires_in

        while time.time() < deadline:
            time.sleep(interval)
            token_resp = requests.post(
                f"{AUTH_BASE}/auth/oauth/token",
                auth=(CLIENT_ID, CLIENT_SECRET),
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "device_code": device_code,
                },
                timeout=15,
            )
            if token_resp.status_code == 200:
                token = token_resp.json()
                token["expires_at"] = time.time() + token.get("expires_in", 3600)
                self._save_token(token)
                print("Autoryzacja zakończona sukcesem!")
                return
            body = token_resp.json()
            error = body.get("error", "")
            if error == "authorization_pending":
                continue
            if error == "slow_down":
                interval += 5
                continue
            raise RuntimeError(f"Błąd autoryzacji: {error} – {body.get('error_description', '')}")

        raise TimeoutError("Czas autoryzacji minął. Spróbuj ponownie.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    AllegroAuth().device_flow_authorize()
