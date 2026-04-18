"""
Allegro Vehicle Compatibility Agent
------------------------------------
Bot cyklicznie pobiera aktywne oferty sprzedającego, szuka tych bez
wypełnionego pola 'pasuje do', parsuje tytuł/opis w poszukiwaniu danych
pojazdu, a następnie uzupełnia parametr kompatybilności przez Allegro API.

Uruchomienie:
    python agent.py            # tryb jednorazowy (--once)
    python agent.py --once     # przetwórz oferty raz i zakończ
    python agent.py --daemon   # start schedulera (co SCHEDULE_INTERVAL_MINUTES minut)
    python agent.py --auth     # tylko autoryzacja (device flow)
"""

import argparse
import logging
import os
import sys
import time
from typing import Optional

from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv

from allegro_api import AllegroAPI, AllegroAPIError
from auth import AllegroAuth
from vehicle_parser import VehicleInfo, VehicleParser

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("agent.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("allegro_agent")

MAX_OFFERS = int(os.getenv("MAX_OFFERS_PER_RUN", "50"))
MIN_CONFIDENCE = float(os.getenv("MIN_MATCH_CONFIDENCE", "0.7"))
SCHEDULE_INTERVAL = int(os.getenv("SCHEDULE_INTERVAL_MINUTES", "30"))


# ---------------------------------------------------------------------------
# Główna klasa agenta
# ---------------------------------------------------------------------------


class CompatibilityAgent:
    def __init__(self):
        self._auth = AllegroAuth()
        self._api = AllegroAPI(self._auth)
        self._parser = VehicleParser()

    # ---------------------------------------------------------------- helpers

    def _find_allegro_vehicle_ids(
        self, vehicles: list[VehicleInfo], category_id: Optional[str]
    ) -> list[str]:
        """
        Dla każdego sparsowanego pojazdu szuka jego ID w katalogu Allegro.
        Zwraca deduplikowaną listę ID do wpisania w 'pasuje do'.
        """
        ids: list[str] = []
        seen: set[str] = set()

        # Pobierz grupę kompatybilności dla danej kategorii
        group_id: Optional[str] = None
        if category_id:
            try:
                groups = self._api.get_compatibility_groups(category_id)
                if groups:
                    group_id = groups[0]["id"]
                    logger.debug("Używam grupy kompatybilności: %s", group_id)
            except AllegroAPIError as exc:
                logger.debug("Nie można pobrać grup dla kategorii %s: %s", category_id, exc)

        for vehicle in vehicles:
            if vehicle.confidence < MIN_CONFIDENCE:
                logger.debug("Pomijam %s – za niska pewność (%.2f)", vehicle, vehicle.confidence)
                continue

            phrase = vehicle.search_phrase()
            logger.debug("Szukam w katalogu Allegro: '%s'", phrase)

            try:
                results = self._api.search_compatible_products(
                    phrase=phrase,
                    group_id=group_id,
                    limit=10,
                )
            except AllegroAPIError as exc:
                logger.warning("Błąd wyszukiwania '%s': %s", phrase, exc)
                continue

            if not results:
                logger.debug("Brak wyników dla frazy '%s'", phrase)
                continue

            # Filtruj po roku (jeśli wiemy)
            matched = self._filter_by_year(results, vehicle)
            if not matched:
                matched = results[:3]  # fallback: weź pierwsze 3

            for item in matched:
                vid = item.get("id")
                if vid and vid not in seen:
                    seen.add(vid)
                    ids.append(vid)
                    logger.debug(
                        "Dopasowano pojazd: %s (id=%s)", item.get("text", "?"), vid
                    )

        return ids

    @staticmethod
    def _filter_by_year(items: list[dict], vehicle: VehicleInfo) -> list[dict]:
        """Filtruje wyniki katalogu po zakresie lat."""
        if not vehicle.year_from:
            return []
        filtered = []
        for item in items:
            text = item.get("text", "")
            # Szukaj roku w opisie pojazdu z katalogu
            import re
            years_in_text = re.findall(r"\b((?:19|20)\d{2})\b", text)
            if not years_in_text:
                filtered.append(item)  # nie wiadomo – zostaw
                continue
            yr_nums = [int(y) for y in years_in_text]
            item_min, item_max = min(yr_nums), max(yr_nums)
            year_to = vehicle.year_to or vehicle.year_from
            # Zakresy muszą się pokrywać
            if vehicle.year_from <= item_max and year_to >= item_min:
                filtered.append(item)
        return filtered

    # --------------------------------------------------------------- core loop

    def process_offer(self, offer: dict) -> bool:
        """
        Przetwarza jedną ofertę.
        Zwraca True jeśli zaktualizowano 'pasuje do'.
        """
        offer_id = offer.get("id", "?")
        title = offer.get("name", "")

        # Pobierz pełne dane (z compatibilityList i opisem)
        try:
            full_offer = self._api.get_offer(offer_id)
        except AllegroAPIError as exc:
            logger.error("Nie można pobrać oferty %s: %s", offer_id, exc)
            return False

        if self._api.has_compatibility_list(full_offer):
            logger.info("Oferta %s ('%s') – 'pasuje do' już wypełnione, pomijam", offer_id, title[:50])
            return False

        description = self._extract_description_text(full_offer)
        vehicles = self._parser.extract_vehicles(title, description)

        if not vehicles:
            logger.info("Oferta %s – nie znaleziono pojazdów w tytule/opisie", offer_id)
            return False

        logger.info(
            "Oferta %s ('%s') – znalezione pojazdy: %s",
            offer_id,
            title[:50],
            ", ".join(str(v) for v in vehicles),
        )

        category_id = (
            full_offer.get("category", {}).get("id")
        )
        vehicle_ids = self._find_allegro_vehicle_ids(vehicles, category_id)

        if not vehicle_ids:
            logger.warning(
                "Oferta %s – nie znaleziono ID pojazdów w katalogu Allegro dla: %s",
                offer_id,
                ", ".join(v.search_phrase() for v in vehicles),
            )
            return False

        try:
            self._api.update_compatibility_list(offer_id, vehicle_ids)
            logger.info(
                "Oferta %s – zaktualizowano 'pasuje do': %d pojazdów",
                offer_id,
                len(vehicle_ids),
            )
            return True
        except AllegroAPIError as exc:
            logger.error("Błąd aktualizacji oferty %s: %s", offer_id, exc)
            return False

    @staticmethod
    def _extract_description_text(offer: dict) -> str:
        """Wyciąga czysty tekst z sekcji description oferty."""
        sections = (
            offer.get("description", {}).get("sections", [])
        )
        texts: list[str] = []
        for section in sections:
            for item in section.get("items", []):
                if item.get("type") == "TEXT":
                    texts.append(item.get("content", ""))
        return " ".join(texts)

    def run_once(self) -> dict:
        """
        Pobiera oferty i przetwarza te bez 'pasuje do'.
        Zwraca słownik ze statystykami.
        """
        logger.info("=== START PRZEBIEGU – MAX %d ofert ===", MAX_OFFERS)
        stats = {"checked": 0, "updated": 0, "skipped": 0, "errors": 0}

        try:
            offers = self._api.get_all_user_offers(max_offers=MAX_OFFERS)
        except AllegroAPIError as exc:
            logger.error("Nie można pobrać ofert: %s", exc)
            stats["errors"] += 1
            return stats

        logger.info("Pobrano %d ofert", len(offers))
        stats["checked"] = len(offers)

        for offer in offers:
            try:
                updated = self.process_offer(offer)
            except Exception as exc:
                logger.exception("Nieoczekiwany błąd przy ofercie %s: %s", offer.get("id"), exc)
                stats["errors"] += 1
                continue

            if updated:
                stats["updated"] += 1
            else:
                stats["skipped"] += 1

            # Delikatny throttling – nie zalewaj API
            time.sleep(0.5)

        logger.info(
            "=== KONIEC PRZEBIEGU – sprawdzono: %d, zaktualizowano: %d, "
            "pominięto: %d, błędy: %d ===",
            stats["checked"],
            stats["updated"],
            stats["skipped"],
            stats["errors"],
        )
        return stats

    def start_scheduler(self):
        """Uruchamia scheduler – działa w pętli aż do CTRL+C."""
        logger.info(
            "Scheduler uruchomiony – przebieg co %d minut", SCHEDULE_INTERVAL
        )
        scheduler = BlockingScheduler(timezone="Europe/Warsaw")
        scheduler.add_job(
            self.run_once,
            trigger="interval",
            minutes=SCHEDULE_INTERVAL,
            id="compatibility_agent",
            max_instances=1,
            coalesce=True,
        )
        # Pierwsze uruchomienie od razu
        self.run_once()
        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Scheduler zatrzymany")


# ---------------------------------------------------------------------------
# Punkt wejścia
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Allegro Vehicle Compatibility Agent"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--once",
        action="store_true",
        default=True,
        help="Przetwórz oferty jednorazowo (domyślnie)",
    )
    group.add_argument(
        "--daemon",
        action="store_true",
        help="Uruchom scheduler (cykliczne przebiegi)",
    )
    group.add_argument(
        "--auth",
        action="store_true",
        help="Tylko autoryzacja przez device flow",
    )
    args = parser.parse_args()

    if args.auth:
        AllegroAuth().device_flow_authorize()
        return

    agent = CompatibilityAgent()

    if args.daemon:
        agent.start_scheduler()
    else:
        agent.run_once()


if __name__ == "__main__":
    main()
