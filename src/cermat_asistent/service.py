"""
Backend služba – CermatBackendService.

Hlavní orchestrační modul aplikace:
- Převod bodů uchazeče na percentil (s korekcí za prospěch)
- Vyhodnocení všech škol v DB pro profil uchazeče
- Sestavení doporučení 1.–2.–3. priority (s deduplikací)
- Plán B – alternativní obory s nižším přetlakem
- Reverzní kalkulačka – kolik bodů potřebuji na vybranou školu
"""

import sqlite3
from typing import Any

import numpy as np
import pandas as pd

from cermat_asistent.config import (
    PROSPECH_BONUS_MAP,
    RELATED_OBORY_MAP,
)
from cermat_asistent.predictor import CermatTrendPredictor


class CermatBackendService:
    """Hlavní backendová služba pro vyhodnocení přihlášek uchazeče."""

    def __init__(self, db_conn: sqlite3.Connection):
        self.conn = db_conn
        self.predictor = CermatTrendPredictor()

    # ------------------------------------------------------------------
    # Převod bodů na percentil
    # ------------------------------------------------------------------
    def get_user_percentile(
        self,
        cjl_points: float,
        mat_points: float,
        prospech_category: str = "1.1-1.3",
        target_year: int = 2026,
    ) -> dict[str, float]:
        """
        Převede body z testů na percentil a aplikuje korekci za vysvědčení.

        Returns:
            Dict s klíči: base_test_pr, prospech_delta, effective_pr
        """
        try:
            cjl_pts = float(cjl_points)
            if np.isnan(cjl_pts):
                cjl_pts = 0.0
        except (ValueError, TypeError):
            cjl_pts = 0.0

        try:
            mat_pts = float(mat_points)
            if np.isnan(mat_pts):
                mat_pts = 0.0
        except (ValueError, TypeError):
            mat_pts = 0.0

        cjl_pts = float(np.clip(cjl_pts, 0.0, 50.0))
        mat_pts = float(np.clip(mat_pts, 0.0, 50.0))

        df_pct = pd.read_sql(
            "SELECT predmet, body, percentil FROM percentily_historie WHERE rok = ?",
            self.conn,
            params=(target_year,),
        )

        if df_pct.empty:
            base_pr = float(cjl_pts + mat_pts)
        else:
            cjl_df = df_pct[df_pct["predmet"] == "cjl"].sort_values("body")
            mat_df = df_pct[df_pct["predmet"] == "mat"].sort_values("body")

            cjl_pct = float(np.interp(cjl_pts, cjl_df["body"], cjl_df["percentil"]))
            mat_pct = float(np.interp(mat_pts, mat_df["body"], mat_df["percentil"]))
            base_pr = (cjl_pct + mat_pct) / 2.0

        prospech_delta = PROSPECH_BONUS_MAP.get(prospech_category, 0.0)
        effective_pr = float(np.clip(base_pr + prospech_delta, 0.0, 100.0))

        return {
            "base_test_pr": round(base_pr, 1),
            "prospech_delta": prospech_delta,
            "effective_pr": round(effective_pr, 1),
        }

    # ------------------------------------------------------------------
    # Kompletní vyhodnocení škol
    # ------------------------------------------------------------------
    def evaluate_schools_for_user(
        self,
        user_cjl: float,
        user_mat: float,
        prospech_category: str = "1.1-1.3",
        kraj_filter: str = "Všechny",
        kategorie_filter: str = "Všechny",
        obor_filter: str = "Všechny",
        mesta_filter: list[str] | None = None,
        target_year: int = 2026,
    ) -> dict[str, Any]:
        """
        Kompletní vyhodnocení všech škol v databázi pro zadaný profil uživatele.

        Returns:
            Dict s klíči: pr_info, evaluated_schools (DataFrame),
            recommendation, plan_b
        """
        pr_info = self.get_user_percentile(
            user_cjl, user_mat, prospech_category, target_year
        )
        user_pr = pr_info["effective_pr"]

        query = """
        SELECT
            s.redizo, s.nazev_skoly, s.kraj, s.mesto,
            o.kod_oboru, o.nazev_oboru, o.kategorie_oboru,
            h.rok, h.kapacita, h.prihlasky_p1, h.index_pretlaku, h.min_percentil
        FROM skoly s
        JOIN skoly_historie h ON s.redizo = h.redizo
        JOIN obory o ON o.kod_oboru = h.kod_oboru
        """
        df_hist = pd.read_sql(query, self.conn)

        # Regionální filtr se aplikuje na celou skládanou historii
        if kraj_filter != "Všechny":
            df_hist = df_hist[df_hist["kraj"] == kraj_filter]

        if df_hist.empty:
            return {
                "pr_info": pr_info,
                "evaluated_schools": pd.DataFrame(),
                "recommendation": {},
                "plan_b": [],
            }

        # Vyhodnocení VŠECH škol v regionu pro daného uchazeče
        grouped = df_hist.groupby(["redizo", "kod_oboru"])
        evaluated_all: list[dict[str, Any]] = []

        mesta_set = set(mesta_filter) if mesta_filter else set()

        for (redizo, kod_oboru), group in grouped:
            school_info = group.sort_values("rok").iloc[-1]  # Poslední ročník
            pred_res = self.predictor.predict(group)

            pr_pred = pred_res["pr_pred"]
            ci_lower = pred_res["ci_lower"]
            ci_upper = pred_res["ci_upper"]

            if user_pr >= ci_upper:
                category, badge, label = "Safe", "🟢", "Vysoká (Jistota)"
            elif user_pr >= ci_lower:
                category, badge, label = "Realistic", "🟡", "Střední (Reálná)"
            else:
                category, badge, label = "Reach", "🔴", "Nízká (Riziková)"

            is_pref_loc = (school_info["mesto"] in mesta_set) if mesta_set else True

            evaluated_all.append(
                {
                    "redizo": redizo,
                    "kod_oboru": kod_oboru,
                    "nazev_skoly": school_info["nazev_skoly"],
                    "mesto": school_info["mesto"],
                    "kraj": school_info["kraj"],
                    "obor": school_info["nazev_oboru"],
                    "kategorie": school_info["kategorie_oboru"],
                    "kapacita_latest": int(school_info["kapacita"]),
                    "pretlak_latest": float(school_info["index_pretlaku"]),
                    "last_min_percentil": float(school_info["min_percentil"]),
                    "pred_min_percentil": pr_pred,
                    "ci_lower": ci_lower,
                    "ci_upper": ci_upper,
                    "margin": pred_res["margin"],
                    "chance_category": category,
                    "chance_label": f"{badge} {label}",
                    "explanation": pred_res["explanation"],
                    "is_preferred_location": is_pref_loc,
                }
            )

        df_all_eval = pd.DataFrame(evaluated_all)

        # Filtrovaný podmnožinový DataFrame pro hlavní UI tabulku
        df_eval = df_all_eval.copy()
        if kategorie_filter != "Všechny":
            df_eval = df_eval[df_eval["kategorie"] == kategorie_filter]
        if obor_filter != "Všechny":
            df_eval = df_eval[df_eval["obor"] == obor_filter]

        # Prioritizace podle preferovaných měst a řazení od nejnáročnější školy
        if mesta_set and not df_eval.empty:
            df_eval = df_eval.sort_values(
                by=["is_preferred_location", "pred_min_percentil"],
                ascending=[False, False],
            )
        elif not df_eval.empty:
            df_eval = df_eval.sort_values(
                by="pred_min_percentil", ascending=False
            )

        recommendation = self._build_dipsy_recommendation(df_eval)
        plan_b = self._find_plan_b_alternatives(
            df_eval, df_all_eval, mesta_set=mesta_set
        )

        return {
            "pr_info": pr_info,
            "evaluated_schools": df_eval,
            "recommendation": recommendation,
            "plan_b": plan_b,
        }

    # ------------------------------------------------------------------
    # Doporučení 1.–2.–3. priority (s deduplikací)
    # ------------------------------------------------------------------
    def _build_dipsy_recommendation(
        self, df_eval: pd.DataFrame
    ) -> dict[str, Any]:
        """Sestaví optimální trojici přihlášek s respektováním pravidel DiPSy."""
        if df_eval.empty:
            return {}

        df_sorted = df_eval.sort_values(
            by=["is_preferred_location", "pred_min_percentil"],
            ascending=[False, False],
        )
        used_keys: set[tuple[str, str]] = set()

        def _pick_candidate(
            candidates: pd.DataFrame, fallback_idx: int
        ) -> pd.Series:
            for _, row in candidates.iterrows():
                key = (row["redizo"], row["kod_oboru"])
                if key not in used_keys:
                    used_keys.add(key)
                    return row
            # Fallback – vezmi z celého seznamu
            for idx in range(len(df_sorted)):
                real_idx = (fallback_idx + idx) % len(df_sorted)
                row = df_sorted.iloc[real_idx]
                key = (row["redizo"], row["kod_oboru"])
                if key not in used_keys:
                    used_keys.add(key)
                    return row
            return df_sorted.iloc[0]

        # 1. Priorita: Vysněná / Náročná (Reach nebo Realistic)
        reach_candidates = df_sorted[
            df_sorted["chance_category"].isin(["Reach", "Realistic"])
        ]
        p1 = _pick_candidate(reach_candidates, fallback_idx=0)

        # 2. Priorita: Reálná
        real_candidates = df_sorted[
            df_sorted["chance_category"] == "Realistic"
        ]
        p2 = _pick_candidate(real_candidates, fallback_idx=len(df_sorted) // 2)

        # 3. Priorita: Jistota (Safe)
        safe_candidates = df_sorted[
            df_sorted["chance_category"] == "Safe"
        ]
        p3 = _pick_candidate(safe_candidates, fallback_idx=len(df_sorted) - 1)

        return {
            "p1_target": p1.to_dict(),
            "p2_real": p2.to_dict(),
            "p3_safe": p3.to_dict(),
        }

    # ------------------------------------------------------------------
    # Plán B – alternativní obory
    # ------------------------------------------------------------------
    def _find_plan_b_alternatives(
        self,
        df_eval: pd.DataFrame,
        df_all_eval: pd.DataFrame,
        mesta_set: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Vyhledá bezpečné alternativní obory pro obory s nízkou šancí s prioritou preferovaných měst."""
        plan_b_list: list[dict[str, Any]] = []

        if df_eval.empty or df_all_eval.empty:
            return plan_b_list

        reach_schools = df_eval[df_eval["chance_category"] == "Reach"]
        if reach_schools.empty:
            return plan_b_list

        seen_plan_b_keys: set[tuple[str, str, str]] = set()

        for _, reach_item in reach_schools.iterrows():
            target_code = reach_item["kod_oboru"]
            target_kategorie = reach_item["kategorie"]
            related_codes = RELATED_OBORY_MAP.get(target_code, [])

            cand_mask = (
                (df_all_eval["chance_category"].isin(["Safe", "Realistic"]))
                & (df_all_eval["pred_min_percentil"] < reach_item["pred_min_percentil"])
                & (
                    (df_all_eval["kod_oboru"].isin(related_codes))
                    | (df_all_eval["kategorie"] == "Lyceum")
                    | (
                        (target_kategorie in ["Gymnázium", "SOŠ"])
                        & (df_all_eval["kategorie"].isin(["Lyceum", "SOŠ"]))
                    )
                )
            )
            candidates = df_all_eval[cand_mask].copy()

            if mesta_set:
                candidates["is_pref_mesto"] = candidates["mesto"].isin(mesta_set)
                candidates = candidates.sort_values(
                    by=["is_pref_mesto", "pred_min_percentil"],
                    ascending=[False, False],
                )
            else:
                candidates = candidates.sort_values(
                    by="pred_min_percentil", ascending=False
                )

            for _, cand in candidates.head(2).iterrows():
                dedup_key = (
                    reach_item["redizo"],
                    cand["redizo"],
                    cand["kod_oboru"],
                )
                if dedup_key in seen_plan_b_keys:
                    continue
                seen_plan_b_keys.add(dedup_key)

                pr_diff = round(
                    reach_item["pred_min_percentil"]
                    - cand["pred_min_percentil"],
                    1,
                )
                plan_b_list.append(
                    {
                        "original_school": f"{reach_item['nazev_skoly']} ({reach_item['mesto']})",
                        "original_obor": reach_item["obor"],
                        "alt_school": cand["nazev_skoly"],
                        "alt_obor": cand["obor"],
                        "alt_mesto": cand["mesto"],
                        "alt_chance": cand["chance_label"],
                        "alt_pred_pr": cand["pred_min_percentil"],
                        "reason": (
                            f"Příbuzný obor s o {pr_diff} % nižší "
                            f"bodovou náročností."
                        ),
                    }
                )
                plan_b_list.append(
                    {
                        "original_school": f"{reach_item['nazev_skoly']} ({reach_item['mesto']})",
                        "original_obor": reach_item["obor"],
                        "alt_school": cand["nazev_skoly"],
                        "alt_obor": cand["obor"],
                        "alt_mesto": cand["mesto"],
                        "alt_chance": cand["chance_label"],
                        "alt_pred_pr": cand["pred_min_percentil"],
                        "reason": (
                            f"Příbuzný obor s o {pr_diff} % nižší "
                            f"bodovou náročností."
                        ),
                    }
                )

        return plan_b_list

    # ------------------------------------------------------------------
    # Reverzní kalkulačka
    # ------------------------------------------------------------------
    def calculate_required_points_for_school(
        self,
        redizo: str,
        kod_oboru: str,
        safety_level: str = "Safe",
        fixed_cjl_points: float | None = None,
        target_year: int = 2026,
    ) -> dict[str, Any]:
        """
        Vypočítá potřebný počet bodů z ČJL a MAT pro dosažení požadované školy.

        Args:
            safety_level: "Safe" (horní hranice CI) nebo "Realistic" (bodový odhad)
            fixed_cjl_points: Pokud zadáno, dopočítá se pouze MAT
        """
        df_school = pd.read_sql(
            "SELECT * FROM skoly_historie WHERE redizo = ? AND kod_oboru = ?",
            self.conn,
            params=(redizo, kod_oboru),
        )
        pred_res = self.predictor.predict(df_school)

        # Cílový percentil podle zvolené míry jistoty
        target_pr = (
            pred_res["ci_upper"] if safety_level == "Safe" else pred_res["pr_pred"]
        )

        # Načtení percentilové mapy
        df_pct = pd.read_sql(
            "SELECT predmet, body, percentil FROM percentily_historie WHERE rok = ?",
            self.conn,
            params=(target_year,),
        )

        if df_pct.empty:
            return {
                "target_pr": target_pr,
                "req_cjl_points": 0.0,
                "req_mat_points": 0.0,
                "total_points": 0.0,
                "mode": "Chybí data",
            }

        cjl_df = df_pct[df_pct["predmet"] == "cjl"].sort_values("body")
        mat_df = df_pct[df_pct["predmet"] == "mat"].sort_values("body")

        if fixed_cjl_points is None:
            # Režim A: Vyvážený výkon (stejný percentil v obou předmětech)
            req_cjl_pts = float(
                np.interp(target_pr, cjl_df["percentil"], cjl_df["body"])
            )
            req_mat_pts = float(
                np.interp(target_pr, mat_df["percentil"], mat_df["body"])
            )

            return {
                "target_pr": round(target_pr, 1),
                "req_cjl_points": round(req_cjl_pts, 1),
                "req_mat_points": round(req_mat_pts, 1),
                "total_points": round(req_cjl_pts + req_mat_pts, 1),
                "mode": "Vyvážený",
            }
        else:
            # Režim B: Pevná ČJL, dopočet MAT
            try:
                fixed_cjl_pts = float(fixed_cjl_points)
                if np.isnan(fixed_cjl_pts):
                    fixed_cjl_pts = 0.0
            except (ValueError, TypeError):
                fixed_cjl_pts = 0.0
            fixed_cjl_pts = float(np.clip(fixed_cjl_pts, 0.0, 50.0))

            cjl_pr = float(
                np.interp(fixed_cjl_pts, cjl_df["body"], cjl_df["percentil"])
            )
            needed_mat_pr = max(0.0, min(100.0, 2 * target_pr - cjl_pr))
            req_mat_pts = float(
                np.interp(needed_mat_pr, mat_df["percentil"], mat_df["body"])
            )

            return {
                "target_pr": round(target_pr, 1),
                "req_cjl_points": fixed_cjl_pts,
                "req_mat_points": round(req_mat_pts, 1),
                "total_points": round(fixed_cjl_pts + req_mat_pts, 1),
                "mode": "Kompenzační",
            }

    # ------------------------------------------------------------------
    # Pomocné metody pro UI
    # ------------------------------------------------------------------
    def get_available_filters(
        self, kategorie_filter: str = "Všechny"
    ) -> dict[str, list[str]]:
        """Vrací dostupné hodnoty pro UI filtry (kraje, kategorie oborů, obory)."""
        kraje = pd.read_sql(
            "SELECT DISTINCT kraj FROM skoly ORDER BY kraj", self.conn
        )
        kategorie = pd.read_sql(
            "SELECT DISTINCT kategorie_oboru FROM obory ORDER BY kategorie_oboru",
            self.conn,
        )

        query = "SELECT DISTINCT nazev_oboru FROM obory"
        params = []
        if kategorie_filter != "Všechny":
            query += " WHERE kategorie_oboru = ?"
            params.append(kategorie_filter)
        query += " ORDER BY nazev_oboru"

        obory = pd.read_sql(query, self.conn, params=params)

        return {
            "kraje": kraje["kraj"].tolist(),
            "kategorie": kategorie["kategorie_oboru"].dropna().tolist(),
            "obory": obory["nazev_oboru"].dropna().tolist(),
        }

    def get_mesta_for_kraj(self, kraj: str) -> list[str]:
        """Vrací abecední seznam měst v daném kraji."""
        if kraj == "Všechny":
            df = pd.read_sql(
                "SELECT DISTINCT mesto FROM skoly ORDER BY mesto", self.conn
            )
        else:
            df = pd.read_sql(
                "SELECT DISTINCT mesto FROM skoly WHERE kraj = ? ORDER BY mesto",
                self.conn,
                params=(kraj,),
            )
        return df["mesto"].dropna().tolist()

    def get_school_history(
        self, redizo: str, kod_oboru: str | None = None
    ) -> pd.DataFrame:
        """Načte historii školy pro Plotly graf."""
        if kod_oboru:
            return pd.read_sql(
                "SELECT rok, min_percentil, index_pretlaku, kapacita, prihlasky_p1 "
                "FROM skoly_historie WHERE redizo = ? AND kod_oboru = ? ORDER BY rok",
                self.conn,
                params=(redizo, kod_oboru),
            )
        return pd.read_sql(
            "SELECT rok, min_percentil, index_pretlaku, kapacita, prihlasky_p1 "
            "FROM skoly_historie WHERE redizo = ? ORDER BY rok",
            self.conn,
            params=(redizo,),
        )

    # ------------------------------------------------------------------
    # Backtest – „Přijali by mě v roce X?"
    # ------------------------------------------------------------------
    def backtest_for_year(
        self,
        user_cjl: float,
        user_mat: float,
        prospech_category: str = "1.1-1.3",
        backtest_year: int = 2025,
        kraj_filter: str = "Všechny",
        kategorie_filter: str = "Všechny",
        obor_filter: str = "Všechny",
        mesta_filter: list[str] | None = None,
    ) -> pd.DataFrame:
        """
        Vyhodnotí profil uchazeče oproti skutečným hranicím z daného roku.

        Žádná predikce – čistá historická fakta.
        Vrací DataFrame se sloupci: nazev_skoly, mesto, obor,
        skutecny_pr_min, user_pr, prijat (bool), chance_label.
        """
        pr_info = self.get_user_percentile(
            user_cjl, user_mat, prospech_category, backtest_year
        )
        user_pr = pr_info["effective_pr"]

        query = """
        SELECT
            s.redizo, s.nazev_skoly, s.kraj, s.mesto,
            o.kod_oboru, o.nazev_oboru, o.kategorie_oboru,
            h.min_percentil, h.index_pretlaku, h.kapacita
        FROM skoly s
        JOIN skoly_historie h ON s.redizo = h.redizo
        JOIN obory o ON o.kod_oboru = h.kod_oboru
        WHERE h.rok = ?
        """
        df = pd.read_sql(query, self.conn, params=(backtest_year,))

        if df.empty:
            return pd.DataFrame()

        # Filtry
        if kraj_filter != "Všechny":
            df = df[df["kraj"] == kraj_filter]
        if kategorie_filter != "Všechny":
            df = df[df["kategorie_oboru"] == kategorie_filter]
        if obor_filter != "Všechny":
            df = df[df["nazev_oboru"] == obor_filter]

        if df.empty:
            return pd.DataFrame()

        # Preferovaná města
        mesta_set = set(mesta_filter) if mesta_filter else set()

        results: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            skutecny = float(row["min_percentil"])
            prijat = user_pr >= skutecny

            if prijat:
                label = "🟢 Přijat/a"
            else:
                label = f"🔴 Nepřijat/a (chybí {skutecny - user_pr:.1f} %)"

            is_pref = (row["mesto"] in mesta_set) if mesta_set else True

            results.append({
                "nazev_skoly": row["nazev_skoly"],
                "mesto": row["mesto"],
                "obor": row["nazev_oboru"],
                "skutecny_pr_min": round(skutecny, 1),
                "user_pr": round(user_pr, 1),
                "prijat": prijat,
                "chance_label": label,
                "pretlak": round(float(row["index_pretlaku"]), 2),
                "is_preferred_location": is_pref,
            })

        df_out = pd.DataFrame(results)

        # Řazení: preferovaná města první, pak od nejnáročnějších
        df_out = df_out.sort_values(
            ["is_preferred_location", "skutecny_pr_min"],
            ascending=[False, False],
        ).reset_index(drop=True)

        return df_out

    def get_available_backtest_years(self) -> list[int]:
        """Vrací seznam dostupných roků pro backtest."""
        df = pd.read_sql(
            "SELECT DISTINCT rok FROM skoly_historie ORDER BY rok DESC",
            self.conn,
        )
        return df["rok"].tolist()

    def get_full_school_info(self, redizo: str) -> dict[str, Any]:
        """
        Vrací kompletní detailní kartu školy (všechny vyučované obory, vývoj kapacit a přihlášek).
        """
        query_school = "SELECT redizo, nazev_skoly, kraj, mesto FROM skoly WHERE redizo = ?"
        df_sch = pd.read_sql(query_school, self.conn, params=(redizo,))
        if df_sch.empty:
            return {}

        sch_info = df_sch.iloc[0].to_dict()

        query_obory = """
        SELECT
            o.kod_oboru, o.nazev_oboru, o.kategorie_oboru,
            h.rok, h.kapacita, h.prihlasky_p1, h.index_pretlaku, h.min_percentil
        FROM skoly_historie h
        JOIN obory o ON o.kod_oboru = h.kod_oboru
        WHERE h.redizo = ?
        ORDER BY o.nazev_oboru, h.rok ASC
        """
        df_hist = pd.read_sql(query_obory, self.conn, params=(redizo,))

        return {
            "info": sch_info,
            "history": df_hist,
        }

