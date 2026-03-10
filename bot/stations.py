"""Station name resolver with fuzzy matching and Turkish normalization."""

from __future__ import annotations

import difflib
import re
import unicodedata


POPULAR_STATIONS: list[tuple[str, str]] = [
    ("Ankara", "ANKARA GAR"),
    ("İst. Halkalı", "İSTANBUL(HALKALI)"),
    ("İst. Pendik", "İSTANBUL(PENDİK)"),
    ("İst. Söğütlüçeşme", "İSTANBUL(SÖĞÜTLÜÇEŞME)"),
    ("Eskişehir", "ESKİŞEHİR"),
    ("Konya", "KONYA"),
    ("Kayseri", "KAYSERİ"),
    ("Sivas", "SİVAS"),
    ("Ankara YHT", "ANKARA YHT GARI"),
    ("Karaman", "KARAMAN"),
    ("Eryaman YHT", "ERYAMAN YHT"),
    ("Polatlı YHT", "POLATLI YHT"),
]


class StationResolver:
    POPULAR_ALIASES: dict[str, str] = {
        "ankara": "ANKARA GAR",
        "ankara gar": "ANKARA GAR",
        "ankara yht": "ANKARA YHT GARI",
        "istanbul": "İSTANBUL(HALKALI)",
        "istanbul halkali": "İSTANBUL(HALKALI)",
        "halkali": "İSTANBUL(HALKALI)",
        "pendik": "İSTANBUL(PENDİK)",
        "istanbul pendik": "İSTANBUL(PENDİK)",
        "sogutlucesme": "İSTANBUL(SÖĞÜTLÜÇEŞME)",
        "bostanci": "İSTANBUL(BOSTANCI)",
        "bakirkoy": "İSTANBUL(BAKIRKÖY)",
        "sirkeci": "İSTANBUL(SİRKECİ)",
        "konya": "KONYA",
        "eskisehir": "ESKİŞEHİR",
        "eskisehir ht": "ESKİŞEHİR HT",
        "izmir": "İZMİR (BASMANE)",
        "basmane": "İZMİR (BASMANE)",
        "adana": "ADANA",
        "kayseri": "KAYSERİ",
        "sivas": "SİVAS",
        "erzurum": "ERZURUM",
        "denizli": "DENİZLİ",
        "mersin": "MERSİN",
        "karaman": "KARAMAN",
        "polatli": "POLATLI YHT",
        "burdur": "BURDUR",
        "isparta": "ISPARTA",
        "balikesir": "BALIKESİR",
        "bandirma": "BANDIRMA GAR",
        "diyarbakir": "DİYARBAKIR",
        "elazig": "ELAZIĞ",
        "malatya": "MALATYA",
        "van": "VAN",
        "kars": "KARS",
        "erzincan": "ERZİNCAN",
        "gaziantep": "GAZİANTEP",
        "osmaniye": "OSMANİYE",
        "edirne": "EDİRNE",
        "selcuklu": "SELÇUKLU YHT (KONYA)",
    }

    # Turkish character mappings for ASCII normalization
    _TR_MAP = str.maketrans(
        "çğıöşüÇĞİÖŞÜ",
        "cgiosuCGIOSU",
    )

    def __init__(self, stations: dict[str, int]):
        self._stations = stations
        # Normalized name → original name lookup
        self._norm_to_orig: dict[str, str] = {
            self.normalize(name): name for name in stations
        }

    def normalize(self, name: str) -> str:
        """Uppercase, strip, collapse whitespace, ASCII-fold Turkish chars."""
        s = name.strip().upper()
        s = s.translate(self._TR_MAP)
        s = re.sub(r"\s+", " ", s)
        return s

    def exact_match(self, query: str) -> str | None:
        """Return exact station name if alias or direct match found."""
        q_lower = query.strip().lower()
        if q_lower in self.POPULAR_ALIASES:
            return self.POPULAR_ALIASES[q_lower]

        # Direct match against station names (case-insensitive)
        q_norm = self.normalize(query)
        if q_norm in self._norm_to_orig:
            return self._norm_to_orig[q_norm]

        return None

    def resolve(self, query: str, n: int = 5) -> list[str]:
        """Return top n fuzzy matches for query. Returns original station names."""
        # Try exact match first
        exact = self.exact_match(query)
        if exact:
            return [exact]

        q_norm = self.normalize(query)
        matches = difflib.get_close_matches(
            q_norm, self._norm_to_orig.keys(), n=n, cutoff=0.4
        )
        return [self._norm_to_orig[m] for m in matches]
