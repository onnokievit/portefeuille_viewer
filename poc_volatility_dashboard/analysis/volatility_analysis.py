from __future__ import annotations

from dataclasses import dataclass
from math import isnan

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class RegressionResult:
    slope: float
    intercept: float
    r_value: float
    p_value: float
    std_error: float

    @property
    def r_squared(self) -> float:
        return self.r_value * self.r_value


@dataclass(frozen=True)
class VolatilityAnalysis:
    volatility_data: pd.DataFrame
    analysis_df: pd.DataFrame
    forward_regression: RegressionResult
    diff_regression: RegressionResult
    high_regression: RegressionResult | None
    low_regression: RegressionResult | None
    intersection_x: float
    current_iv: float
    current_percentile: float
    regime: str
    mean_reversion_signal: str
    notes: list[str]


def prepare_volatility_data(
    raw_df: pd.DataFrame,
    *,
    scale_mode: str = "db_raw",
    annualization_days: int = 252,
) -> pd.DataFrame:
    if "implied_vol" not in raw_df.columns:
        raise ValueError("Data must contain an implied_vol column")
    df = raw_df.copy()
    df["implied_vol"] = pd.to_numeric(df["implied_vol"], errors="coerce")
    df = df.dropna(subset=["implied_vol"]).sort_index()
    if scale_mode == "sqrt_annualize":
        df["implied_vol"] = df["implied_vol"] * np.sqrt(float(annualization_days))
    elif scale_mode != "db_raw":
        raise ValueError(f"Unknown scale_mode: {scale_mode}")
    df["iv_percentile"] = df["implied_vol"].rolling(window=252, min_periods=20).rank(pct=True)
    df["iv_percentile"] = df["iv_percentile"].fillna(df["implied_vol"].rank(pct=True))
    return df


def analyze_volatility(volatility_data: pd.DataFrame, *, forward_days: int = 30) -> VolatilityAnalysis:
    if len(volatility_data) < max(30, forward_days + 5):
        raise ValueError("Insufficient implied-volatility history for analysis")

    forward_vol = (
        volatility_data["implied_vol"]
        .rolling(window=forward_days, min_periods=1)
        .mean()
        .shift(-forward_days)
    )
    analysis_df = pd.DataFrame(
        {
            "current_vol": volatility_data["implied_vol"],
            "forward_vol": forward_vol,
            "vol_diff": forward_vol - volatility_data["implied_vol"],
            "vol_percentile": volatility_data["iv_percentile"],
        }
    ).dropna()

    if len(analysis_df) < 30:
        raise ValueError("Insufficient non-null forward volatility pairs")

    forward_reg = linregress(analysis_df["current_vol"], analysis_df["forward_vol"])
    diff_reg = linregress(analysis_df["current_vol"], analysis_df["vol_diff"])

    if abs(forward_reg.slope - 1.0) > 1e-12:
        intersection_x = forward_reg.intercept / (1.0 - forward_reg.slope)
    else:
        intersection_x = float(analysis_df["current_vol"].median())

    high_mask = analysis_df["current_vol"] > intersection_x
    low_mask = ~high_mask
    high_reg = (
        linregress(analysis_df.loc[high_mask, "current_vol"], analysis_df.loc[high_mask, "vol_diff"])
        if int(high_mask.sum()) > 10
        else None
    )
    low_reg = (
        linregress(analysis_df.loc[low_mask, "current_vol"], analysis_df.loc[low_mask, "vol_diff"])
        if int(low_mask.sum()) > 10
        else None
    )

    current_iv = float(volatility_data["implied_vol"].iloc[-1])
    current_percentile = float(volatility_data["iv_percentile"].iloc[-1])
    regime, signal = classify_regime(current_percentile)
    notes = build_notes(
        forward_reg=forward_reg,
        diff_reg=diff_reg,
        high_reg=high_reg,
        low_reg=low_reg,
        high_count=int(high_mask.sum()),
        low_count=int(low_mask.sum()),
        intersection_x=intersection_x,
    )

    return VolatilityAnalysis(
        volatility_data=volatility_data,
        analysis_df=analysis_df,
        forward_regression=forward_reg,
        diff_regression=diff_reg,
        high_regression=high_reg,
        low_regression=low_reg,
        intersection_x=float(intersection_x),
        current_iv=current_iv,
        current_percentile=current_percentile,
        regime=regime,
        mean_reversion_signal=signal,
        notes=notes,
    )


def linregress(x: pd.Series, y: pd.Series) -> RegressionResult:
    try:
        from scipy import stats

        slope, intercept, r_value, p_value, std_error = stats.linregress(x, y)
        return RegressionResult(
            slope=float(slope),
            intercept=float(intercept),
            r_value=float(r_value),
            p_value=float(p_value),
            std_error=float(std_error),
        )
    except Exception:
        x_arr = np.asarray(x, dtype=float)
        y_arr = np.asarray(y, dtype=float)
        slope, intercept = np.polyfit(x_arr, y_arr, 1)
        corr = np.corrcoef(x_arr, y_arr)[0, 1] if len(x_arr) > 1 else np.nan
        return RegressionResult(
            slope=float(slope),
            intercept=float(intercept),
            r_value=0.0 if isnan(corr) else float(corr),
            p_value=float("nan"),
            std_error=float("nan"),
        )


def classify_regime(percentile: float) -> tuple[str, str]:
    if percentile > 0.8:
        return "HIGH VOLATILITY", "EXPECT MEAN REVERSION DOWN"
    if percentile > 0.6:
        return "ABOVE AVERAGE", "NEUTRAL"
    if percentile > 0.4:
        return "NORMAL", "NEUTRAL"
    if percentile > 0.2:
        return "BELOW AVERAGE", "NEUTRAL"
    return "LOW VOLATILITY", "EXPECT MEAN REVERSION UP"


def build_notes(
    *,
    forward_reg: RegressionResult,
    diff_reg: RegressionResult,
    high_reg: RegressionResult | None,
    low_reg: RegressionResult | None,
    high_count: int,
    low_count: int,
    intersection_x: float,
) -> list[str]:
    notes = [
        "Regression 1 - Forward IV on Current IV:",
        f"  Slope: {forward_reg.slope:.4f}, Intercept: {forward_reg.intercept:.4f}",
        f"  R^2: {forward_reg.r_squared:.4f}, P-value: {format_float(forward_reg.p_value)}",
        f"  Intersection with y=x at IV = {intersection_x:.4f}",
        "Regression 2 - IV Difference on Current IV:",
        f"  Slope: {diff_reg.slope:.4f}, Intercept: {diff_reg.intercept:.4f}",
        f"  R^2: {diff_reg.r_squared:.4f}, P-value: {format_float(diff_reg.p_value)}",
        "Regime Analysis:",
    ]
    if high_reg is None:
        notes.append("  HIGH VOL regime: insufficient data")
    else:
        notes.extend(
            [
                f"  HIGH VOL regime data points: {high_count}",
                f"    Slope: {high_reg.slope:.4f}, R^2: {high_reg.r_squared:.4f}, P-value: {format_float(high_reg.p_value)}",
            ]
        )
    if low_reg is None:
        notes.append("  LOW VOL regime: insufficient data")
    else:
        notes.extend(
            [
                f"  LOW VOL regime data points: {low_count}",
                f"    Slope: {low_reg.slope:.4f}, R^2: {low_reg.r_squared:.4f}, P-value: {format_float(low_reg.p_value)}",
            ]
        )
    notes.append(
        "INSIGHT: Forward volatility tends to mean-revert (slope < 1)"
        if forward_reg.slope < 1
        else "INSIGHT: Forward volatility tends to trend (slope > 1)"
    )
    notes.append(
        "INSIGHT: High current volatility predicts lower future volatility"
        if diff_reg.slope < 0
        else "INSIGHT: High current volatility predicts higher future volatility"
    )
    return notes


def format_float(value: float) -> str:
    if value != value:
        return "n/a"
    return f"{value:.4f}"

