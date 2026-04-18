import re
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Słowniki marek i wzorce generacji
# ---------------------------------------------------------------------------

CAR_MAKES: list[tuple[str, str]] = [
    # (wzorzec regex, znormalizowana nazwa)
    (r"\bBMW\b", "BMW"),
    (r"\bAudi\b", "Audi"),
    (r"\bVolkswagen\b|\bVW\b", "Volkswagen"),
    (r"\bOpel\b", "Opel"),
    (r"\bFord\b", "Ford"),
    (r"\bToyota\b", "Toyota"),
    (r"\bSkoda\b|Škoda", "Skoda"),
    (r"\bRenault\b", "Renault"),
    (r"\bPeugeot\b", "Peugeot"),
    (r"\bCitro[eë]n\b", "Citroen"),
    (r"\bFiat\b", "Fiat"),
    (r"\bSeat\b|\bSEAT\b", "SEAT"),
    (r"\bHonda\b", "Honda"),
    (r"\bMazda\b", "Mazda"),
    (r"\bHyundai\b", "Hyundai"),
    (r"\bKia\b", "Kia"),
    (r"\bNissan\b", "Nissan"),
    (r"\bSuzuki\b", "Suzuki"),
    (r"\bMitsubishi\b", "Mitsubishi"),
    (r"\bVolvo\b", "Volvo"),
    (r"\bSaab\b", "Saab"),
    (r"\bPorsche\b", "Porsche"),
    (r"\bMercedes(?:-Benz)?\b|\bMB\b", "Mercedes-Benz"),
    (r"\bLand\s*Rover\b", "Land Rover"),
    (r"\bRange\s*Rover\b", "Range Rover"),
    (r"\bJeep\b", "Jeep"),
    (r"\bChrysler\b", "Chrysler"),
    (r"\bDodge\b", "Dodge"),
    (r"\bAlfa\s*Romeo\b", "Alfa Romeo"),
    (r"\bLancia\b", "Lancia"),
    (r"\bSubaru\b", "Subaru"),
    (r"\bDacia\b", "Dacia"),
    (r"\bChevrolet\b", "Chevrolet"),
    (r"\bDaewoo\b", "Daewoo"),
    (r"\bIsuzu\b", "Isuzu"),
    (r"\bLexus\b", "Lexus"),
    (r"\bMINI\b|\bMini\b", "MINI"),
    (r"\bSmart\b", "Smart"),
    (r"\bJaguar\b", "Jaguar"),
    (r"\bInfiniti\b", "Infiniti"),
    (r"\bAcura\b", "Acura"),
]

# Generacje pojazdów: pasuje do modelu gdy tuż po nazwie modelu stoi kod
GENERATION_PATTERN = re.compile(
    r"\b("
    # BMW
    r"E\d{2}|F\d{2}|G\d{2}|"
    # Opel/VW generacje słowne
    r"[A-HJ-Z]\b|"
    # numeryczne generacje (Golf 4, Golf IV)
    r"I{1,3}V?|VI{0,3}|[1-9](?:st|nd|rd|th)?"
    r")\b",
    re.IGNORECASE,
)

YEAR_RANGE_PATTERN = re.compile(
    r"\b((?:19|20)\d{2})\s*[-–—/]\s*((?:19|20)\d{2})\b"
)
SINGLE_YEAR_PATTERN = re.compile(r"\b((?:19|20)\d{2})\b")

# Słowa kluczowe sugerujące, że to oferta moto-części
MOTO_KEYWORDS = re.compile(
    r"\b(pasuje do|do|kompatybilny|kompatybilna|zamiennik|"
    r"filtr|klocki|tarcza|rozrz[aą]d|pas|pasek|spr[eę]\u017cyna|amortyzator|"
    r"alternator|rozrusznik|chłodnica|t\u0142umik|wydech|reflektor|lusterko)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Struktury danych
# ---------------------------------------------------------------------------

@dataclass
class VehicleInfo:
    make: str
    model: str = ""
    generation: str = ""
    year_from: Optional[int] = None
    year_to: Optional[int] = None
    confidence: float = 0.0
    raw_fragment: str = ""

    def search_phrase(self) -> str:
        """Buduje frazę do wyszukiwania w katalogu Allegro."""
        parts = [self.make]
        if self.model:
            parts.append(self.model)
        if self.generation:
            parts.append(self.generation)
        return " ".join(parts)

    def __str__(self) -> str:
        year_str = ""
        if self.year_from and self.year_to:
            year_str = f" {self.year_from}-{self.year_to}"
        elif self.year_from:
            year_str = f" {self.year_from}"
        return f"{self.make} {self.model} {self.generation}{year_str}".strip()


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class VehicleParser:
    def __init__(self):
        self._make_patterns = [
            (re.compile(pat, re.IGNORECASE), norm) for pat, norm in CAR_MAKES
        ]

    def extract_vehicles(self, title: str, description: str = "") -> list[VehicleInfo]:
        """
        Wyciąga informacje o pojazdach z tytułu i opisu oferty.
        Zwraca posortowaną po pewności listę VehicleInfo.
        """
        text = f"{title} {description}"
        text = re.sub(r"<[^>]+>", " ", text)  # usuń HTML
        text = re.sub(r"\s+", " ", text).strip()

        vehicles: list[VehicleInfo] = []
        for make_re, make_norm in self._make_patterns:
            for m in make_re.finditer(text):
                snippet = text[m.start() : m.start() + 120]
                info = self._parse_after_make(make_norm, snippet)
                if info:
                    vehicles.append(info)

        # deduplikacja po (make, model, generation, year_from)
        seen: set[tuple] = set()
        unique: list[VehicleInfo] = []
        for v in vehicles:
            key = (v.make, v.model, v.generation, v.year_from)
            if key not in seen:
                seen.add(key)
                unique.append(v)

        return sorted(unique, key=lambda v: v.confidence, reverse=True)

    def _parse_after_make(self, make: str, snippet: str) -> Optional[VehicleInfo]:
        """Parsuje fragment tekstu zaczynający się (mniej więcej) od marki."""
        # Wyczyść fragment: usuń markę z początku
        rest = re.sub(r"^[A-Za-z\-]+\s*", "", snippet, count=1).strip()

        model, generation, year_from, year_to = "", "", None, None
        confidence = 0.5  # marka znaleziona = bazowa pewność

        # Model: pierwsze 1-2 tokeny po marce (nie rok, nie liczba silnika)
        model_match = re.match(
            r"^([A-Za-z][A-Za-z0-9\-\.]*(?:\s+[A-Za-z][A-Za-z0-9\-\.]*)?)",
            rest,
        )
        if model_match:
            candidate = model_match.group(1).strip()
            # Odrzuć samą liczbę (np. "1.9", "2.0") lub rok
            if not re.fullmatch(r"\d[\d\.]+", candidate) and not re.fullmatch(
                r"(?:19|20)\d{2}", candidate
            ):
                model = candidate
                confidence += 0.2
                rest = rest[model_match.end() :].strip()

        # Generacja (E46, F30, G, IV, ...)
        gen_match = GENERATION_PATTERN.search(rest[:40])
        if gen_match:
            generation = gen_match.group(0)
            confidence += 0.1

        # Lata
        yr_range = YEAR_RANGE_PATTERN.search(snippet)
        if yr_range:
            year_from = int(yr_range.group(1))
            year_to = int(yr_range.group(2))
            confidence += 0.2
        else:
            yr_single = SINGLE_YEAR_PATTERN.search(snippet)
            if yr_single:
                year_from = int(yr_single.group(1))
                confidence += 0.1

        # Jeśli nie ma modelu i roku – mało pewne
        if not model and not year_from:
            confidence -= 0.2

        if confidence < 0.3:
            return None

        return VehicleInfo(
            make=make,
            model=model,
            generation=generation,
            year_from=year_from,
            year_to=year_to,
            confidence=min(confidence, 1.0),
            raw_fragment=snippet[:80],
        )


# ---------------------------------------------------------------------------
# Szybki test CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = VehicleParser()
    tests = [
        "Filtr oleju BMW 3 E46 316i 318i 320i 1999-2005",
        "Klocki hamulcowe Opel Astra G 1.4 1.6 1998-2004",
        "Rozrząd Toyota Corolla E12 1.4 2002-2007",
        "Tarcza hamulcowa VW Golf 4 1.9 TDI 1997-2004",
        "Amortyzator tylny Mercedes-Benz W203 C-Klasa 2000-2007",
    ]
    for t in tests:
        results = parser.extract_vehicles(t)
        print(f"\nTytuł: {t}")
        for v in results:
            print(f"  -> {v}  (pewność: {v.confidence:.2f})  fraza: '{v.search_phrase()}'")
