import logging
import os
from typing import Optional

import requests
from dotenv import load_dotenv

from auth import AllegroAuth

load_dotenv()

logger = logging.getLogger(__name__)

SANDBOX = os.getenv("USE_SANDBOX", "false").lower() == "true"
API_BASE = (
    "https://api.allegro.pl.allegrosandbox.pl" if SANDBOX else "https://api.allegro.pl"
)


class AllegroAPIError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code


class AllegroAPI:
    def __init__(self, auth: AllegroAuth):
        self._auth = auth

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._auth.get_access_token()}",
            "Accept": "application/vnd.allegro.public.v1+json",
            "Content-Type": "application/vnd.allegro.public.v1+json",
        }

    def _get(self, path: str, params: dict = None) -> dict:
        resp = requests.get(
            f"{API_BASE}{path}",
            headers=self._headers(),
            params=params or {},
            timeout=20,
        )
        self._raise_for_status(resp)
        return resp.json()

    def _patch(self, path: str, body: dict) -> dict:
        resp = requests.patch(
            f"{API_BASE}{path}",
            headers=self._headers(),
            json=body,
            timeout=20,
        )
        self._raise_for_status(resp)
        return resp.json()

    @staticmethod
    def _raise_for_status(resp: requests.Response):
        if resp.status_code >= 400:
            try:
                msg = resp.json()
            except Exception:
                msg = resp.text
            raise AllegroAPIError(resp.status_code, str(msg))

    # ------------------------------------------------------------------ offers

    def get_user_offers(
        self,
        publication_status: str = "ACTIVE",
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """Zwraca listę ofert zalogowanego sprzedającego."""
        data = self._get(
            "/sale/offers",
            params={
                "publication.status": publication_status,
                "limit": limit,
                "offset": offset,
            },
        )
        return data.get("offers", [])

    def get_all_user_offers(
        self, publication_status: str = "ACTIVE", max_offers: int = 500
    ) -> list[dict]:
        """Pobiera wszystkie oferty stronicując po max_offers."""
        offers: list[dict] = []
        offset = 0
        batch = 100
        while len(offers) < max_offers:
            page = self.get_user_offers(
                publication_status=publication_status,
                limit=min(batch, max_offers - len(offers)),
                offset=offset,
            )
            if not page:
                break
            offers.extend(page)
            offset += len(page)
            if len(page) < batch:
                break
        return offers

    def get_offer(self, offer_id: str) -> dict:
        """Pobiera pełne dane oferty wraz z compatibilityList."""
        return self._get(f"/sale/offers/{offer_id}")

    # ------------------------------------------------------- compatibility list

    def get_supported_compatibility_categories(self) -> list[dict]:
        """Zwraca kategorie obsługujące listę zgodności ('pasuje do')."""
        data = self._get("/sale/compatibility-list/supported-categories")
        return data.get("supportedCategories", [])

    def search_compatible_products(
        self,
        phrase: str,
        group_id: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict]:
        """
        Wyszukuje pojazdy w katalogu Allegro.

        Zwraca listę obiektów z polami: id, text (opis pojazdu).
        """
        params: dict = {
            "phrase": phrase,
            "type": "COMPATIBLE_PRODUCT",
            "language": "pl-PL",
            "limit": limit,
        }
        if group_id:
            # Szukanie w konkretnej grupie (np. samochody osobowe)
            data = self._get(
                f"/sale/compatibility-list/groups/{group_id}/compatible-products",
                params=params,
            )
        else:
            data = self._get("/sale/compatible-products", params=params)

        return data.get("compatibleProducts", data.get("items", []))

    def get_compatibility_groups(self, category_id: str) -> list[dict]:
        """Pobiera grupy zgodności dla danej kategorii."""
        data = self._get(
            "/sale/compatibility-list/groups",
            params={"category.id": category_id},
        )
        return data.get("groups", [])

    def update_compatibility_list(
        self, offer_id: str, vehicle_ids: list[str]
    ) -> dict:
        """
        Aktualizuje pole 'pasuje do' (compatibilityList) w ofercie.

        vehicle_ids – lista ID pojazdów z katalogu Allegro
                      (uzyskane przez search_compatible_products).
        """
        if not vehicle_ids:
            logger.warning("Pusta lista pojazdów dla oferty %s – pomijam", offer_id)
            return {}

        items = [{"id": vid} for vid in vehicle_ids]
        body = {
            "compatibilityList": {
                "items": items,
                "inputMethod": "BY_USER",
            }
        }
        logger.debug(
            "Aktualizuję 'pasuje do' oferty %s: %d pojazdów", offer_id, len(vehicle_ids)
        )
        return self._patch(f"/sale/offers/{offer_id}", body)

    def has_compatibility_list(self, offer: dict) -> bool:
        """Sprawdza czy oferta już ma wypełnione 'pasuje do'."""
        items = (
            offer.get("compatibilityList", {}).get("items", [])
        )
        return len(items) > 0
