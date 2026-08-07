"""
ETL Pipeline pro načtení, očištění a transformaci datových souborů Cermat (data.cermat.cz).

Funkce:
- normalize_column_name: Odstranění diakritiky, převod na snake_case
- clean_czech_numeric: České čárky a prázdné symboly → float
- unify_columns: Schema mapping přes COLUMN_ALIASES
- parse_cermat_skoly: Naparsování CSV s přehledem škol
- parse_cermat_uchazeci: Naparsování anonymizované matice uchazečů
- build_percentile_map: Výpočet Mid-Percentile Rank pro daný ročník
- transform_uchazeci_to_long: Převod široké matice na tidy long formát
"""

import re
import unicodedata

import numpy as np
import pandas as pd

from cermat_asistent.config import COLUMN_ALIASES


def normalize_column_name(col_name: str) -> str:
    """
    Převede název sloupce na standardní snake_case bez české diakritiky.

    Příklad: 'Min. body ČJL (2025)' → 'min_body_cjl_2025'
    """
    nfkd = unicodedata.normalize("NFKD", str(col_name))
    text = "".join(c for c in nfkd if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def clean_czech_numeric(series: pd.Series) -> pd.Series:
    """
    Převede české číselné řetězce s čárkou (např. '38,5', '-', 'N/A') na float.
    """
    if series.dtype in [np.float64, np.int64]:
        return series

    cleaned = (
        series.astype(str)
        .str.strip()
        .str.replace(",", ".", regex=False)
        .replace(["-", "N/A", "nan", "None", "", "null"], np.nan)
    )
    return pd.to_numeric(cleaned, errors="coerce")


def unify_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Převede různé názvy sloupců z různých ročníků na jednotné názvy
    pomocí COLUMN_ALIASES slovníku.
    """
    # Nejprve normalizujeme (diakritika, snake_case)
    cleaned_cols = {col: normalize_column_name(col) for col in df.columns}
    df = df.rename(columns=cleaned_cols)

    # Mapování podle slovníku aliasů
    rename_dict: dict[str, str] = {}
    for standard_name, aliases in COLUMN_ALIASES.items():
        for col in df.columns:
            if col in aliases:
                rename_dict[col] = standard_name
                break

    return df.rename(columns=rename_dict)


def parse_cermat_skoly(
    file_path: str, encoding: str = "utf-8", sep: str = ";"
) -> pd.DataFrame:
    """
    Naparsuje a vyčistí datový soubor Cermat s přehledem škol a oborů.
    """
    df = pd.read_csv(file_path, encoding=encoding, sep=sep, dtype=str)
    df = unify_columns(df)

    # Standardizace REDIZO (9místný kód s vodícími nulami)
    if "redizo" in df.columns:
        df["redizo"] = (
            df["redizo"]
            .astype(str)
            .str.replace(r"\.0$", "", regex=True)
            .str.zfill(9)
        )

    # Čištění číselných sloupců
    numeric_keywords = ["kapacita", "pocet", "body", "percentil", "prihlasky"]
    numeric_cols = [
        c for c in df.columns if any(k in c for k in numeric_keywords)
    ]
    for col in numeric_cols:
        df[col] = clean_czech_numeric(df[col])

    # Vypočítané sloupce
    if "body_cjl" in df.columns and "body_mat" in df.columns:
        df["min_body_celkem"] = df["body_cjl"].fillna(0) + df["body_mat"].fillna(0)

    return df


def parse_cermat_uchazeci(
    file_path: str, encoding: str = "utf-8", sep: str = ";"
) -> pd.DataFrame:
    """
    Naparsuje a vyčistí anonymizovanou matici uchazečů.
    """
    df = pd.read_csv(file_path, encoding=encoding, sep=sep, dtype=str)
    df = unify_columns(df)

    # Standardizace REDIZO pro prioritní školy (1, 2, 3)
    redizo_cols = [c for c in df.columns if "redizo" in c]
    for col in redizo_cols:
        df[col] = (
            df[col]
            .astype(str)
            .str.replace(r"\.0$", "", regex=True)
            .str.zfill(9)
        )
        df[col] = df[col].replace("000000nan", np.nan)

    # Čištění bodových zisků
    point_cols = [c for c in df.columns if "body" in c]
    for col in point_cols:
        df[col] = clean_czech_numeric(df[col])

    if "body_cjl" in df.columns and "body_mat" in df.columns:
        df["body_celkem"] = df["body_cjl"].fillna(0) + df["body_mat"].fillna(0)

    return df


def transform_uchazeci_to_long(df_uchazeci: pd.DataFrame) -> pd.DataFrame:
    """
    Transformuje širokou matici přihlášek (1., 2., 3. volba) na tidy long formát.
    Vhodné pro SQL databáze a relační analýzy přelivu uchazečů.
    """
    long_rows = []

    for _, row in df_uchazeci.iterrows():
        for priority in [1, 2, 3]:
            redizo_col = f"redizo_{priority}"
            obor_col = f"obor_{priority}"

            if redizo_col in row and pd.notna(row[redizo_col]):
                long_rows.append(
                    {
                        "anon_id": row.get("anon_id"),
                        "priorita": priority,
                        "redizo": row[redizo_col],
                        "kod_oboru": row.get(obor_col, np.nan),
                        "body_cjl": row.get("body_cjl"),
                        "body_mat": row.get("body_mat"),
                        "body_celkem": row.get("body_celkem"),
                        "stav_prijeti": row.get("stav_prijeti"),
                    }
                )

    return pd.DataFrame(long_rows)


def build_percentile_map(
    scores: np.ndarray, max_points: int = 50
) -> pd.DataFrame:
    """
    Vypočítá Mid-Percentile Rank pro distribuci bodů.

    Vrací DataFrame s sloupci: body, cetnost, percentil
    """
    scores = np.asarray(scores, dtype=float)
    possible_scores = np.arange(0, max_points + 1)
    counts = np.bincount(scores.astype(int), minlength=max_points + 1)
    total_n = len(scores)

    cumsum_below = np.cumsum(counts) - counts
    mid_percentiles = (cumsum_below + 0.5 * counts) / total_n * 100.0

    return pd.DataFrame(
        {
            "body": possible_scores,
            "cetnost": counts,
            "percentil": mid_percentiles.round(2),
        }
    )
