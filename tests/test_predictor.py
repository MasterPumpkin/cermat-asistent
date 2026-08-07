"""Testy pro CermatTrendPredictor."""

import numpy as np
import pandas as pd
import pytest

from cermat_asistent.predictor import CermatTrendPredictor


@pytest.fixture
def predictor():
    return CermatTrendPredictor()


@pytest.fixture
def df_3_years_growing():
    """3 roky rostoucího trendu."""
    return pd.DataFrame({
        "rok": [2024, 2025, 2026],
        "min_percentil": [62.0, 65.5, 69.0],
        "index_pretlaku": [1.4, 1.65, 2.1],
        "kapacita": [60, 60, 60],
    })


@pytest.fixture
def df_3_years_stable():
    """3 roky stabilního stavu."""
    return pd.DataFrame({
        "rok": [2024, 2025, 2026],
        "min_percentil": [70.0, 71.0, 70.5],
        "index_pretlaku": [1.5, 1.5, 1.5],
        "kapacita": [60, 60, 60],
    })


@pytest.fixture
def df_1_year():
    """Pouze 1 rok dat (nový obor)."""
    return pd.DataFrame({
        "rok": [2026],
        "min_percentil": [55.0],
        "index_pretlaku": [1.2],
        "kapacita": [60],
    })


@pytest.fixture
def df_capacity_change():
    """Skoková změna kapacity v posledním roce (+50 %)."""
    return pd.DataFrame({
        "rok": [2024, 2025, 2026],
        "min_percentil": [75.0, 78.0, 77.0],
        "index_pretlaku": [2.2, 2.5, 1.8],
        "kapacita": [60, 60, 90],
    })


class TestEdgeCases:
    """Testy hraničních stavů."""

    def test_empty_dataframe(self, predictor):
        """Bez dat → fallback na 50 % s širokým CI."""
        result = predictor.predict(pd.DataFrame())
        assert result["status"] == "BEZ_DAT"
        assert result["pr_pred"] == 50.0
        assert result["margin"] == 10.0

    def test_single_year(self, predictor, df_1_year):
        """1 rok dat → status NOVY_OBOR, široké pásmo."""
        result = predictor.predict(df_1_year)
        assert result["status"] == "NOVY_OBOR"
        assert result["pr_pred"] == 55.0
        assert result["margin"] >= 7.5  # min_margin * 2.5

    def test_capacity_change_status(self, predictor, df_capacity_change):
        """Změna kapacity o 50 % → status OK, ale zmínka v explanation."""
        result = predictor.predict(df_capacity_change)
        assert result["status"] == "OK"
        assert "kapacity" in result["explanation"]


class TestPredictionRange:
    """Testy, že predikce zůstává v rozumném rozsahu."""

    def test_prediction_in_range(self, predictor, df_3_years_growing):
        """Predikce musí být v rozsahu 0–100."""
        result = predictor.predict(df_3_years_growing)
        assert 0.0 <= result["pr_pred"] <= 100.0
        assert 0.0 <= result["ci_lower"] <= 100.0
        assert 0.0 <= result["ci_upper"] <= 100.0

    def test_ci_lower_lte_ci_upper(self, predictor, df_3_years_growing):
        """Spodní hranice CI musí být ≤ horní."""
        result = predictor.predict(df_3_years_growing)
        assert result["ci_lower"] <= result["ci_upper"]

    def test_margin_positive(self, predictor, df_3_years_growing):
        """Margin musí být kladný."""
        result = predictor.predict(df_3_years_growing)
        assert result["margin"] > 0


class TestTrendDirection:
    """Testy, že predikce reaguje na trend správným směrem."""

    def test_growing_trend_higher_than_last(self, predictor, df_3_years_growing):
        """Rostoucí trend → predikce vyšší než poslední hodnota."""
        result = predictor.predict(df_3_years_growing)
        last_pr = df_3_years_growing["min_percentil"].iloc[-1]
        assert result["pr_pred"] > last_pr

    def test_stable_trend_close_to_last(self, predictor, df_3_years_stable):
        """Stabilní trend → predikce blízko poslední hodnoty."""
        result = predictor.predict(df_3_years_stable)
        last_pr = df_3_years_stable["min_percentil"].iloc[-1]
        assert abs(result["pr_pred"] - last_pr) < 5.0

    def test_capacity_increase_lowers_prediction(self, predictor, df_capacity_change):
        """Zvýšení kapacity o 50 % → snížení predikce oproti prosté extrapolaci."""
        result = predictor.predict(df_capacity_change)
        # Bez korekce by predikce byla výrazně vyšší
        assert result["pr_pred"] < 78.0  # Korekce by měla stáhnout predikci dolů


class TestExplanation:
    """Testy textového vysvětlení."""

    def test_stable_explanation(self, predictor, df_3_years_stable):
        """Stabilní stav → vysvětlení by mělo obsahovat 'stabilní'."""
        result = predictor.predict(df_3_years_stable)
        assert "stabilní" in result["explanation"].lower()

    def test_growing_trend_explanation(self, predictor, df_3_years_growing):
        """Rostoucí trend → vysvětlení by mělo obsahovat info o trendu."""
        result = predictor.predict(df_3_years_growing)
        explanation = result["explanation"].lower()
        assert "trend" in explanation or "přetlaku" in explanation
