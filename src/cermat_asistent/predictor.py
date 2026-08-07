"""
Predikční engine pro odhad minimálního požadovaného percentilu (PR_min)
pro nadcházející ročník.

Obsahuje:
- CermatTrendPredictor: Třída pro výpočet bodového odhadu, intervalů
  spolehlivosti a ošetření hraničních stavů (edge cases).

Matematický model:
    PR_pred = PR_vážený + α·Slope(PR) + β·ΔI + ΔK

Kde:
    - PR_vážený: Exponenciálně vážený průměr historických percentilů
    - Slope(PR): Směrnice lineární regrese z časové řady
    - ΔI: Změna přetlaku 1. priorit mezi posledními ročníky
    - ΔK: Korekce za skokovou změnu kapacity
    - α, β: Váhové koeficienty citlivosti modelu
"""

from typing import Any

import numpy as np
import pandas as pd

from cermat_asistent.config import (
    PREDICTOR_ALPHA,
    PREDICTOR_BETA,
    PREDICTOR_MIN_MARGIN,
)


class CermatTrendPredictor:
    """
    Predikční modul s ošetřením nejistoty a edge-cases.

    Vstup: DataFrame s historií jedné školy/oboru ('rok', 'min_percentil',
           'index_pretlaku', 'kapacita').
    Výstup: Dict s predikovaným percentilem, intervalem spolehlivosti a statusem.
    """

    def __init__(
        self,
        alpha: float = PREDICTOR_ALPHA,
        beta: float = PREDICTOR_BETA,
        min_margin: float = PREDICTOR_MIN_MARGIN,
    ):
        self.alpha = alpha
        self.beta = beta
        self.min_margin = min_margin

    def predict(self, history_df: pd.DataFrame) -> dict[str, Any]:
        """
        Vypočítá predikci pro nadcházející ročník na základě historické řady.

        Returns:
            Dict s klíči: pr_pred, ci_lower, ci_upper, margin, status, explanation
        """
        # ----- EDGE CASE: Žádná data -----
        if history_df.empty:
            return {
                "pr_pred": 50.0,
                "ci_lower": 40.0,
                "ci_upper": 60.0,
                "margin": 10.0,
                "status": "BEZ_DAT",
                "explanation": "Chybí jakákoliv historická data. Použit oborový průměr.",
            }

        df = history_df.sort_values(by="rok").copy()
        n_years = len(df)

        last_row = df.iloc[-1]
        last_year = int(last_row["rok"])
        last_pr = float(last_row["min_percentil"])

        # ----- EDGE CASE: Pouze 1 rok dat (nový obor / škola) -----
        if n_years == 1:
            margin = max(8.0, self.min_margin * 2.5)
            return {
                "pr_pred": round(last_pr, 1),
                "ci_lower": round(max(0.0, last_pr - margin), 1),
                "ci_upper": round(min(100.0, last_pr + margin), 1),
                "margin": round(margin, 1),
                "status": "NOVY_OBOR",
                "explanation": (
                    f"K dispozici je pouze ročník {last_year}. "
                    f"Pásmo nejistoty je širší (±{margin:.1f} %)."
                ),
            }

        years = df["rok"].values.astype(float)
        prs = np.nan_to_num(df["min_percentil"].values.astype(float), nan=0.0)
        pretlaky = np.nan_to_num(df["index_pretlaku"].values.astype(float), nan=0.0)
        kapacity = np.nan_to_num(df["kapacita"].values.astype(float), nan=0.0)

        # ----- Korekce na změnu kapacity (> 15 %) -----
        cap_ratio = (
            float(kapacity[-1] / kapacity[-2])
            if (len(kapacity) > 1 and kapacity[-2] > 0)
            else 1.0
        )
        capacity_adj = 0.0
        if abs(cap_ratio - 1.0) >= 0.15:
            capacity_adj = -15.0 * (cap_ratio - 1.0)

        # 1. Směrnice trendu (Slope) – lineární regrese
        try:
            slope = float(np.polyfit(years, prs, 1)[0])
            if np.isnan(slope):
                slope = 0.0
        except Exception:
            slope = 0.0

        # 2. Exponenciálně vážený průměr (novější ročník má větší váhu)
        weights = np.arange(1, n_years + 1, dtype=float)
        weights /= weights.sum()
        weighted_pr = float(np.average(prs, weights=weights))

        # 3. Změna přetlaku mezi posledními 2 ročníky
        delta_pretlak = (
            float(pretlaky[-1] - pretlaky[-2]) if len(pretlaky) > 1 else 0.0
        )

        # 4. Bodový odhad (Point Estimate) - vychází z posledního známého ročníku
        pr_pred = last_pr + (self.alpha * slope) + (self.beta * delta_pretlak) + capacity_adj
        pr_pred = float(np.clip(pr_pred, 0.0, 100.0))

        # 5. Výpočet Intervalu Spolehlivosti (Margin of Error)
        if n_years > 2:
            std_err = float(np.std(prs, ddof=1))
        else:
            std_err = abs(prs[-1] - prs[-2]) / 2.0

        margin = self.min_margin + (0.8 * std_err) + (1.5 * abs(delta_pretlak))
        if abs(cap_ratio - 1.0) >= 0.15:
            margin += 2.5  # Přirážka za změnu kapacity

        ci_lower = float(np.clip(pr_pred - margin, 0.0, 100.0))
        ci_upper = float(np.clip(pr_pred + margin, 0.0, 100.0))

        # 6. Generování textového vysvětlení
        reasons: list[str] = []
        if abs(slope) > 1.5:
            direction = "růst" if slope > 0 else "pokles"
            reasons.append(f"historický trend ({direction} {abs(slope):.1f} %/rok)")
        if abs(delta_pretlak) > 0.2:
            direction = "nárůst" if delta_pretlak > 0 else "pokles"
            reasons.append(f"{direction} přetlaku (Δ {delta_pretlak:+.2f}x)")
        if abs(cap_ratio - 1.0) >= 0.15:
            direction = "zvýšení" if cap_ratio > 1 else "snížení"
            reasons.append(f"změna kapacity ({direction} o {abs(cap_ratio - 1) * 100:.0f} %)")

        explanation = (
            "Předpověď vychází ze stabilního vývoje."
            if not reasons
            else "Predikce reflektuje: " + ", ".join(reasons) + "."
        )

        return {
            "pr_pred": round(pr_pred, 1),
            "ci_lower": round(ci_lower, 1),
            "ci_upper": round(ci_upper, 1),
            "margin": round(margin, 1),
            "status": "OK",
            "explanation": explanation,
        }
