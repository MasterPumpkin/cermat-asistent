"""
Cermat Asistent – PDF export

Generuje jednostránkový PDF report s profilem uchazeče,
vyhodnocenými školami a DiPSy strategií.
"""

from __future__ import annotations

import io
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from fpdf import FPDF


# ---------------------------------------------------------------------------
# Pomocné konstanty
# ---------------------------------------------------------------------------
_MODULE_DIR = Path(__file__).parent
_LOCAL_FONT_DIR = _MODULE_DIR / "fonts"
_SYS_FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")

_FONT_REGULAR = (
    _LOCAL_FONT_DIR / "DejaVuSans.ttf"
    if (_LOCAL_FONT_DIR / "DejaVuSans.ttf").exists()
    else _SYS_FONT_DIR / "DejaVuSans.ttf"
)
_FONT_BOLD = (
    _LOCAL_FONT_DIR / "DejaVuSans-Bold.ttf"
    if (_LOCAL_FONT_DIR / "DejaVuSans-Bold.ttf").exists()
    else _SYS_FONT_DIR / "DejaVuSans-Bold.ttf"
)

# Barvy
_HDR_BG = (52, 73, 94)  # tmavě modrá
_HDR_FG = (255, 255, 255)
_ROW_ALT = (245, 247, 250)
_GREEN = (46, 204, 113)
_YELLOW = (241, 196, 15)
_RED = (231, 76, 60)

# Emoji → textové náhrady (DejaVu Sans emoji nepodporuje)
_EMOJI_MAP = {
    "🟢": "[+]",
    "🟡": "[~]",
    "🔴": "[-]",
    "🎓": "",
    "⚠️": "(!)",
    "📌": ">",
    "⭐": "*",
    "📄": "",
    "💡": "",
    "🎯": "",
    "⚖️": "",
    "🛡️": "",
}


def _strip_emoji(text: str) -> str:
    """Nahradí emoji znaky textovými ekvivalenty pro PDF."""
    for emoji, replacement in _EMOJI_MAP.items():
        text = text.replace(emoji, replacement)
    return text


def _remove_accents(text: str) -> str:
    """Odstraní česká znaménka (háčky, čárky) pro případ nouzového fontu Helvetica."""
    nfkd_form = unicodedata.normalize("NFKD", text)
    return "".join([c for c in nfkd_form if not unicodedata.combining(c)])


def _chance_color(label: str) -> tuple[int, int, int]:
    if "Jistota" in label or "Vysoká" in label:
        return _GREEN
    if "Reálná" in label or "Střední" in label:
        return _YELLOW
    return _RED


# ---------------------------------------------------------------------------
# Hlavní generátor
# ---------------------------------------------------------------------------
def generate_pdf_report(
    pr_info: dict[str, float],
    df_schools: pd.DataFrame,
    recommendation: dict[str, Any],
    plan_b_items: list[dict[str, Any]],
    cjl: int,
    mat: int,
    prospech: str,
    kraj: str,
    mesta: list[str] | None = None,
) -> bytes:
    """Vrátí PDF report jako bytes."""

    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)

    # Registrace fontu s českou diakritikou
    is_unicode_font = False
    if Path(_FONT_REGULAR).exists() and Path(_FONT_BOLD).exists():
        try:
            pdf.add_font("deja", "", str(_FONT_REGULAR))
            pdf.add_font("deja", "B", str(_FONT_BOLD))
            font_family = "deja"
            is_unicode_font = True
        except Exception:
            font_family = "Helvetica"
    else:
        font_family = "Helvetica"

    def txt(s: str) -> str:
        s_clean = _strip_emoji(s)
        if not is_unicode_font:
            return _remove_accents(s_clean)
        return s_clean

    pdf.add_page()

    # === HLAVIČKA ===
    pdf.set_font(font_family, "B", 18)
    pdf.set_text_color(*_HDR_BG)
    pdf.cell(0, 12, txt("Cermat Asistent - Report uchazeče"), new_x="LMARGIN", new_y="NEXT")

    pdf.set_font(font_family, "", 8)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(
        0, 5,
        txt(
            f"Vygenerováno: {datetime.now().strftime('%d. %m. %Y %H:%M')}  |  "
            f"Data: Cermat 2024-2026  |  cermat-asistent v0.1.0"
        ),
        new_x="LMARGIN", new_y="NEXT",
    )
    pdf.ln(3)

    # === PROFIL UCHAZEČE ===
    pdf.set_font(font_family, "B", 11)
    pdf.set_text_color(*_HDR_BG)
    pdf.cell(0, 7, txt("Profil uchazeče"), new_x="LMARGIN", new_y="NEXT")

    pdf.set_font(font_family, "", 9)
    pdf.set_text_color(0, 0, 0)

    mesta_str = ", ".join(mesta) if mesta else "-"
    profile_lines = [
        f"ČJL: {cjl} b.  |  MAT: {mat} b.  |  Celkem: {cjl + mat} / 100 b.",
        f"Percentil (efektivní): {pr_info['effective_pr']:.1f} %  "
        f"(základ z testů: {pr_info['base_test_pr']:.1f} %, korekce: {pr_info['prospech_delta']:+.1f} %)",
        f"Prospěch: {prospech}  |  Kraj: {kraj}  |  Preferovaná města: {mesta_str}",
    ]
    for line in profile_lines:
        pdf.cell(0, 5, txt(line), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # === DiPSy STRATEGIE ===
    if recommendation:
        pdf.set_font(font_family, "B", 11)
        pdf.set_text_color(*_HDR_BG)
        pdf.cell(0, 7, txt("Doporučená DiPSy strategie (1.-3. priorita)"), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(font_family, "", 9)
        pdf.set_text_color(0, 0, 0)

        for label, key in [
            ("1. Vysněná", "p1_target"),
            ("2. Reálná", "p2_real"),
            ("3. Jistota", "p3_safe"),
        ]:
            p = recommendation[key]
            pdf.cell(
                0, 5,
                txt(f"  {label}:  {p['nazev_skoly']} ({p['mesto']}) - {p['obor']}  [{p['chance_label']}]"),
                new_x="LMARGIN", new_y="NEXT",
            )
        pdf.ln(3)

    # === TABULKA ŠKOL ===
    if not df_schools.empty:
        pdf.set_font(font_family, "B", 11)
        pdf.set_text_color(*_HDR_BG)
        pdf.cell(0, 7, txt("Přehled vyhodnocených škol"), new_x="LMARGIN", new_y="NEXT")

        # Sloupce a šířky (landscape A4 = 297 mm, okraje 2×10 = 277 mm k dispozici)
        col_widths = [18, 75, 55, 30, 22, 22, 22, 33]
        col_headers = [
            "Šance", "Škola", "Obor", "Město",
            "Predikce", "CI dolní", "CI horní", "Důvod",
        ]

        # Záhlaví tabulky
        pdf.set_font(font_family, "B", 7)
        pdf.set_fill_color(*_HDR_BG)
        pdf.set_text_color(*_HDR_FG)
        for w, h in zip(col_widths, col_headers):
            pdf.cell(w, 6, txt(h), border=1, fill=True, align="C")
        pdf.ln()

        # Řádky
        pdf.set_font(font_family, "", 7)
        pdf.set_text_color(0, 0, 0)

        for i, (_, row) in enumerate(df_schools.iterrows()):
            if i >= 25:
                pdf.set_font(font_family, "", 7)
                pdf.cell(0, 5, txt(f"  ... a dalších {len(df_schools) - 25} škol (zobrazeny v aplikaci)"), new_x="LMARGIN", new_y="NEXT")
                break

            if i % 2 == 1:
                pdf.set_fill_color(*_ROW_ALT)
                fill = True
            else:
                fill = False

            vals = [
                str(row.get("chance_label", "")),
                str(row.get("nazev_skoly", ""))[:38],
                str(row.get("obor", ""))[:28],
                str(row.get("mesto", "")),
                f"{row.get('pred_min_percentil', 0):.1f} %",
                f"{row.get('ci_lower', 0):.1f} %",
                f"{row.get('ci_upper', 0):.1f} %",
                str(row.get("explanation", ""))[:18],
            ]
            for w, v in zip(col_widths, vals):
                pdf.cell(w, 5, txt(v), border=1, fill=fill, align="C")
            pdf.ln()

        pdf.ln(3)

    # === PLÁN B ===
    if plan_b_items:
        pdf.set_font(font_family, "B", 11)
        pdf.set_text_color(*_HDR_BG)
        pdf.cell(0, 7, txt("Plán B - příbuzné alternativy"), new_x="LMARGIN", new_y="NEXT")

        pdf.set_font(font_family, "", 8)
        pdf.set_text_color(0, 0, 0)

        for item in plan_b_items[:5]:
            pdf.cell(
                0, 5,
                txt(
                    f"  Místo: {item['original_school']} -> {item['alt_school']} ({item['alt_mesto']}) "
                    f"- {item['alt_obor']}  [{item['alt_chance']}]"
                ),
                new_x="LMARGIN", new_y="NEXT",
            )

    # === PATIČKA ===
    pdf.ln(5)
    pdf.set_font(font_family, "", 7)
    pdf.set_text_color(160, 160, 160)
    pdf.cell(
        0, 4,
        txt(
            "(!) Predikce slouží pouze jako orientační odhad. "
            "Zdroj dat: data.cermat.cz (2024-2026)."
        ),
        new_x="LMARGIN", new_y="NEXT",
    )

    # Výstup do bytes
    buf = io.BytesIO()
    pdf.output(buf)
    return buf.getvalue()
