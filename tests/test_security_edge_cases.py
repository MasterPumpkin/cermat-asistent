"""
Testovací sada pro bezpečnost (SQL Injection) a hraniční stavy (Edge Cases).
"""

import sqlite3
import numpy as np
import pandas as pd
import pytest

from cermat_asistent.db import init_db, seed_all_real_data, seed_demo_data
from cermat_asistent.predictor import CermatTrendPredictor
from cermat_asistent.service import CermatBackendService


@pytest.fixture
def conn():
    connection = init_db(":memory:")
    seed_demo_data(connection)
    yield connection
    connection.close()


@pytest.fixture
def service(conn):
    return CermatBackendService(conn)


@pytest.fixture
def predictor():
    return CermatTrendPredictor()


class TestSQLInjectionSecurity:
    """Ověření odolnosti vůči SQL Injection útokům."""

    def test_sql_injection_in_kraj_filter(self, service):
        payload = "' OR '1'='1'; DROP TABLE skoly; --"
        res = service.evaluate_schools_for_user(30, 30, kraj_filter=payload)
        assert isinstance(res, dict)
        assert isinstance(res["evaluated_schools"], pd.DataFrame)
        # Ověření, že tabulka stále existuje
        tables = pd.read_sql(
            "SELECT name FROM sqlite_master WHERE type='table'", service.conn
        )
        assert "skoly" in tables["name"].values

    def test_sql_injection_in_obor_filter(self, service):
        payload = "Informační technologie' UNION SELECT * FROM skoly --"
        res = service.evaluate_schools_for_user(30, 30, obor_filter=payload)
        assert isinstance(res["evaluated_schools"], pd.DataFrame)

    def test_sql_injection_in_mesta_filter(self, service):
        payload = ["Kutná Hora' OR 1=1 --", "'; DELETE FROM skoly_historie; --"]
        res = service.evaluate_schools_for_user(30, 30, mesta_filter=payload)
        assert isinstance(res["evaluated_schools"], pd.DataFrame)

    def test_sql_injection_in_redizo(self, service):
        payload = "600012345' OR '1'='1"
        res = service.calculate_required_points_for_school(
            redizo=payload, kod_oboru="79-41-K/41"
        )
        assert isinstance(res, dict)

    def test_sql_injection_in_get_mesta_for_kraj(self, service):
        payload = "Středočeský' OR '1'='1"
        mesta = service.get_mesta_for_kraj(payload)
        assert isinstance(mesta, list)


class TestInputBoundsAndSanitization:
    """Ověření hraničních vstupů a ošetření chybných typů."""

    def test_negative_points(self, service):
        res = service.get_user_percentile(-10.0, -50.0)
        assert res["base_test_pr"] == 0.0
        assert res["effective_pr"] >= 0.0

    def test_overflow_points(self, service):
        res = service.get_user_percentile(9999.0, 8888.0)
        assert res["effective_pr"] <= 100.0

    def test_nan_points(self, service):
        res = service.get_user_percentile(float("nan"), float("nan"))
        assert not np.isnan(res["effective_pr"])
        assert 0.0 <= res["effective_pr"] <= 100.0

    def test_invalid_prospech_category(self, service):
        res = service.get_user_percentile(30, 30, prospech_category="HACK_CATEGORY")
        assert res["prospech_delta"] == 0.0

    def test_reverse_calc_fixed_cjl_bounds(self, service):
        res_neg = service.calculate_required_points_for_school(
            "600012345", "79-41-K/41", fixed_cjl_points=-100.0
        )
        assert res_neg["req_cjl_points"] == 0.0

        res_over = service.calculate_required_points_for_school(
            "600012345", "79-41-K/41", fixed_cjl_points=999.0
        )
        assert res_over["req_cjl_points"] == 50.0


class TestPredictorEdgeCases:
    """Ověření matematického enginu při neočekávaných datech."""

    def test_predictor_with_nan_in_history(self, predictor):
        df_nan = pd.DataFrame(
            {
                "rok": [2024, 2025, 2026],
                "min_percentil": [50.0, np.nan, 60.0],
                "index_pretlaku": [1.0, 1.2, np.nan],
                "kapacita": [30, 30, 30],
            }
        )
        res = predictor.predict(df_nan)
        assert not np.isnan(res["pr_pred"])
        assert not np.isnan(res["ci_lower"])
        assert not np.isnan(res["ci_upper"])

    def test_predictor_with_zero_capacity(self, predictor):
        df_zero_cap = pd.DataFrame(
            {
                "rok": [2024, 2025, 2026],
                "min_percentil": [40.0, 45.0, 50.0],
                "index_pretlaku": [0.0, 0.0, 0.0],
                "kapacita": [0, 0, 0],
            }
        )
        res = predictor.predict(df_zero_cap)
        assert res["status"] == "OK"
        assert not np.isnan(res["pr_pred"])

    def test_nonexistent_school_eval(self, service):
        res = service.calculate_required_points_for_school(
            "999999999", "99-99-Z/99"
        )
        assert isinstance(res, dict)
        assert res["target_pr"] == 60.0  # Fallback pro neexistující školu
