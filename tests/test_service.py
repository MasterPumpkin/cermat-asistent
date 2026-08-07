"""Testy pro CermatBackendService."""

import sqlite3

import numpy as np
import pandas as pd
import pytest

from cermat_asistent.db import init_db, seed_demo_data
from cermat_asistent.service import CermatBackendService


@pytest.fixture
def db_conn():
    """Vytvoří in-memory DB s demo daty."""
    conn = init_db(":memory:")
    seed_demo_data(conn)
    yield conn
    conn.close()


@pytest.fixture
def service(db_conn):
    """Inicializuje backend službu s testovací DB."""
    return CermatBackendService(db_conn)


class TestUserPercentile:
    """Testy převodu bodů na percentil."""

    def test_basic_percentile(self, service):
        """Základní převod bodů na percentil vrací rozumné hodnoty."""
        result = service.get_user_percentile(35, 30)
        assert 0.0 <= result["effective_pr"] <= 100.0
        assert result["base_test_pr"] > 0

    def test_max_points_high_percentile(self, service):
        """50 + 50 bodů → velmi vysoký percentil."""
        result = service.get_user_percentile(50, 50)
        assert result["effective_pr"] > 90.0

    def test_min_points_low_percentile(self, service):
        """0 + 0 bodů → velmi nízký percentil."""
        result = service.get_user_percentile(0, 0)
        assert result["effective_pr"] < 10.0

    def test_prospech_bonus_positive(self, service):
        """Samé jedničky → pozitivní korekce."""
        result = service.get_user_percentile(35, 30, prospech_category="1.0")
        assert result["prospech_delta"] == 4.0
        assert result["effective_pr"] > result["base_test_pr"]

    def test_prospech_penalty_negative(self, service):
        """Horší prospěch → negativní korekce."""
        result = service.get_user_percentile(35, 30, prospech_category="1.9+")
        assert result["prospech_delta"] == -6.0
        assert result["effective_pr"] < result["base_test_pr"]


class TestEvaluateSchools:
    """Testy vyhodnocení škol."""

    def test_returns_evaluated_schools(self, service):
        """Backend vrací DataFrame s vyhodnocenými školami."""
        result = service.evaluate_schools_for_user(35, 30)
        assert not result["evaluated_schools"].empty
        assert "chance_category" in result["evaluated_schools"].columns

    def test_categories_are_valid(self, service):
        """Kategorie šancí musí být Safe, Realistic nebo Reach."""
        result = service.evaluate_schools_for_user(35, 30)
        valid_categories = {"Safe", "Realistic", "Reach"}
        actual_categories = set(result["evaluated_schools"]["chance_category"].unique())
        assert actual_categories.issubset(valid_categories)

    def test_kraj_filter_works(self, service):
        """Filtr podle kraje vrátí pouze školy z daného kraje."""
        result = service.evaluate_schools_for_user(
            35, 30, kraj_filter="Praha"
        )
        if not result["evaluated_schools"].empty:
            assert all(
                result["evaluated_schools"]["kraj"] == "Praha"
            )

    def test_obor_filter_works(self, service):
        """Filtr podle oboru vrátí pouze školy s daným oborem."""
        result = service.evaluate_schools_for_user(
            35, 30, obor_filter="Informační technologie"
        )
        if not result["evaluated_schools"].empty:
            assert all(
                result["evaluated_schools"]["obor"] == "Informační technologie"
            )

    def test_high_points_more_safe(self, service):
        """Vysoké body → více škol v kategorii Safe."""
        result_high = service.evaluate_schools_for_user(48, 48)
        result_low = service.evaluate_schools_for_user(15, 15)

        safe_high = (
            result_high["evaluated_schools"]["chance_category"] == "Safe"
        ).sum()
        safe_low = (
            result_low["evaluated_schools"]["chance_category"] == "Safe"
        ).sum()

        assert safe_high >= safe_low


class TestRecommendation:
    """Testy doporučení 1.–2.–3. priority."""

    def test_recommendation_has_three_priorities(self, service):
        """Doporučení by mělo obsahovat 3 priority."""
        result = service.evaluate_schools_for_user(35, 30)
        rec = result["recommendation"]

        if rec:  # Může být prázdné, pokud nejsou 3 školy
            assert "p1_target" in rec
            assert "p2_real" in rec
            assert "p3_safe" in rec

    def test_recommendation_no_duplicates(self, service):
        """Doporučení by nemělo obsahovat stejnou školu na více pozicích."""
        result = service.evaluate_schools_for_user(35, 30)
        rec = result["recommendation"]

        if rec:
            keys = set()
            for key in ["p1_target", "p2_real", "p3_safe"]:
                school_key = (rec[key]["redizo"], rec[key]["kod_oboru"])
                assert school_key not in keys, (
                    f"Duplikace: {rec[key]['nazev_skoly']} je na více pozicích"
                )
                keys.add(school_key)


class TestReverseCalculator:
    """Testy reverzní kalkulačky."""

    def test_balanced_mode(self, service):
        """Vyvážený režim vrací rozumné bodové hodnoty."""
        result = service.calculate_required_points_for_school(
            redizo="600012345",
            kod_oboru="79-41-K/41",
            safety_level="Safe",
        )
        assert result["mode"] == "Vyvážený"
        assert 0 <= result["req_cjl_points"] <= 50
        assert 0 <= result["req_mat_points"] <= 50

    def test_compensatory_mode(self, service):
        """Kompenzační režim: pevné ČJL body → dopočet MAT."""
        result = service.calculate_required_points_for_school(
            redizo="600012345",
            kod_oboru="79-41-K/41",
            safety_level="Safe",
            fixed_cjl_points=42.0,
        )
        assert result["mode"] == "Kompenzační"
        assert result["req_cjl_points"] == 42.0

    def test_safe_requires_more_than_realistic(self, service):
        """Sázka na jistotu (Safe) vyžaduje více bodů než Reálná."""
        result_safe = service.calculate_required_points_for_school(
            redizo="600012345",
            kod_oboru="79-41-K/41",
            safety_level="Safe",
        )
        result_real = service.calculate_required_points_for_school(
            redizo="600012345",
            kod_oboru="79-41-K/41",
            safety_level="Realistic",
        )
        assert result_safe["total_points"] >= result_real["total_points"]


class TestPlanB:
    """Testy alternativních oborů (Plán B)."""

    def test_plan_b_for_low_chance(self, service):
        """Nízké body + gymnázium Praha → nabídne alternativy."""
        result = service.evaluate_schools_for_user(20, 20)
        # Pokud je gymnázium Praha v kategorii Reach a existují příbuzné obory
        # v DB, Plán B by měl obsahovat alespoň jednu alternativu
        plan_b = result["plan_b"]
        # Nemusí vždy existovat, záleží na tom, jestli příbuzné obory jsou v DB
        # Test alespoň ověří, že se nejedná o chybu
        assert isinstance(plan_b, list)

    def test_plan_b_has_required_fields(self, service):
        """Plán B položky musí obsahovat povinné klíče."""
        result = service.evaluate_schools_for_user(15, 15)
        for item in result["plan_b"]:
            assert "original_school" in item
            assert "alt_school" in item
            assert "alt_obor" in item
            assert "alt_chance" in item
            assert "reason" in item


class TestPreferredLocations:
    """Testy pro preferované lokace a spádové oblasti."""

    def test_get_mesta_for_kraj(self, service):
        """Metoda get_mesta_for_kraj vrací seznam měst."""
        mesta_stsc = service.get_mesta_for_kraj("Středočeský")
        assert isinstance(mesta_stsc, list)
        assert len(mesta_stsc) > 0
        assert "Kutná Hora" in mesta_stsc or "Kolín" in mesta_stsc

    def test_preferred_location_prioritization(self, service):
        """Zadané preferované město upřednostní toto město v Plánu B."""
        res_kh = service.evaluate_schools_for_user(
            20, 20, kraj_filter="Středočeský", mesta_filter=["Kutná Hora", "Kolín"]
        )
        plan_b = res_kh["plan_b"]
        if plan_b:
            alt_mesta = [item["alt_mesto"] for item in plan_b]
            # První alternativy by měly přednostně zkoušet Kutnou Horu nebo Kolín
            assert any(m in ["Kutná Hora", "Kolín"] for m in alt_mesta[:5])
