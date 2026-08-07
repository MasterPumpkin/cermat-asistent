"""
Centrální konfigurační soubor projektu Cermat Asistent.

Obsahuje:
- Mapa příbuzných oborů KKOV (pro Plán B)
- Korekční tabulka za školní prospěch
- Slovník aliasů pro schema drift v Cermat CSV
- Defaultní parametry predikčního enginu
"""

# ---------------------------------------------------------------------------
# Mapa příbuzných oborů podle kódů KKOV
# Klíč: kód oboru, Hodnota: seznam příbuzných kódů oborů s typicky nižším přetlakem
# ---------------------------------------------------------------------------
RELATED_OBORY_MAP: dict[str, list[str]] = {
    "18-20-M/01": ["78-42-M/01", "26-41-M/01", "26-45-M/01"],  # IT → Lyceum, Elektrotechnika, Telekomunikace
    "79-41-K/41": ["78-42-M/01", "78-42-M/02"],                 # Gymnázium → Technické / Ekonomické lyceum
    "79-41-K/61": ["78-42-M/01", "78-42-M/02"],                 # Gymnázium 6leté → Lycea
    "23-41-M/01": ["26-41-M/01", "78-42-M/01"],                 # Strojírenství → Elektrotechnika, Lyceum
    "63-41-M/02": ["78-42-M/02", "63-41-M/01"],                 # Obchodní akademie → Ekonomické lyceum
    "26-41-M/01": ["18-20-M/01", "23-41-M/01"],                 # Elektrotechnika → IT, Strojírenství
}

# ---------------------------------------------------------------------------
# Korekční mapa za školní prospěch (vysvědčení z 8. a 9. třídy)
# Hodnota: posun efektivního percentilu uchazeče v procentních bodech
# ---------------------------------------------------------------------------
PROSPECH_BONUS_MAP: dict[str, float] = {
    "1.0": 4.0,        # Samé jedničky → výrazný bonus na školní části
    "1.1-1.3": 0.0,    # Výborný průměr → odpovídá standardu přijatých
    "1.4-1.8": -3.0,   # Průměrný prospěch → mírná ztráta na konkurenci
    "1.9+": -6.0,      # Horší prospěch → nutnost dohonit body v JPZ testech
}

# ---------------------------------------------------------------------------
# Slovník aliasů pro sjednocení měnících se názvů sloupců v Cermat CSV
# Klíč: standardizovaný název, Hodnota: seznam možných variant v CSV
# ---------------------------------------------------------------------------
COLUMN_ALIASES: dict[str, list[str]] = {
    "redizo": ["redizo", "izo", "kod_skoly", "red_izo"],
    "nazev_skoly": ["nazev_skoly", "nazev", "skola", "nazev_zarizeni"],
    "kod_oboru": ["kod_oboru", "obor_kod", "kkov"],
    "nazev_oboru": ["nazev_oboru", "obor", "obor_nazev"],
    "kraj": ["kraj", "region"],
    "mesto": ["mesto", "obec", "sidlo"],
    "kapacita": ["kapacita", "kapacita_oboru", "pocet_mist"],
    "body_cjl": ["body_cjl", "cjl_body", "body_cj", "cj_body"],
    "body_mat": ["body_mat", "mat_body", "m_body", "ma_body"],
    "stav_prijeti": ["stav_prijeti", "prijat", "vysledek", "status"],
}

# ---------------------------------------------------------------------------
# Defaultní parametry predikčního enginu (CermatTrendPredictor)
# Kalibrováno empirickým backtestem na reálných datech Cermat 2024–2026
# ---------------------------------------------------------------------------
PREDICTOR_ALPHA: float = 0.50      # Váha historického trendu bodů (vyvážená reakce na trend)
PREDICTOR_BETA: float = 1.00        # Váha změny přetlaku 1. priorit (stabilní momentum)
PREDICTOR_MIN_MARGIN: float = 5.00  # Šířka pásma nejistoty (reálná variabilita Cermat)

# ---------------------------------------------------------------------------
# Databáze
# ---------------------------------------------------------------------------
DEFAULT_DB_PATH: str = "cermat.db"
