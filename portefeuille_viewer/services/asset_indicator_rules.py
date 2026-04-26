"""Pure rule engine for asset indicator scores and action mapping.

The functions in this module are deliberately independent from Qt, databases
and SNAPSHOT_STORE. Services should transform snapshots into these inputs, call
the rules, and publish the resulting codes/scores.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from portefeuille_viewer.services.asset_indicator_contract import (
    ASSET_INDICATOR_ASSET_MODES,
    ASSET_INDICATOR_DATA_QUALITY_CODES,
    ASSET_INDICATOR_PRIMARY_ACTIONS,
    ASSET_INDICATOR_SECONDARY_ACTIONS,
)


@dataclass(frozen=True)
class DirectionInput:
    close: float | None
    sma_20: float | None = None
    sma_50: float | None = None
    sma_200: float | None = None
    sma_50_prev: float | None = None
    ema_9: float | None = None
    ema_26: float | None = None
    ema_50: float | None = None
    ema_200: float | None = None
    ema_9_prev: float | None = None
    ema_26_prev: float | None = None
    close_5d_ago: float | None = None
    close_20d_ago: float | None = None
    close_60d_ago: float | None = None
    high_90d: float | None = None
    low_90d: float | None = None
    high_52w: float | None = None
    low_52w: float | None = None


@dataclass(frozen=True)
class VolumeInput:
    price_changes_3d: tuple[float | None, float | None, float | None] = (None, None, None)
    relative_volumes_3d: tuple[float | None, float | None, float | None] = (None, None, None)
    relative_volume_20d: float | None = None
    volume_weighted_price_change: float | None = None


@dataclass(frozen=True)
class ActionInput:
    direction_score: float | None
    volume_score: float | None
    long_term_direction_score: float | None = None
    short_term_direction_score: float | None = None
    range_position_pct: float | None = None
    trend_phase: str | None = None
    theta_score: float | None = None
    vulnerability_score: float | None = None
    liquidity_score: float | None = None
    data_quality: str = "ok"


@dataclass(frozen=True)
class ActionDecision:
    asset_mode: str
    primary_action: str
    secondary_action: str
    covered_call_delta_min: float | None
    covered_call_delta_max: float | None
    short_put_delta_min: float | None
    short_put_delta_max: float | None
    confidence_score: float
    reason_1: str
    reason_2: str
    reason_3: str


def _is_number(value: float | None) -> bool:
    return value is not None and isfinite(float(value))


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _pct_change(current: float | None, previous: float | None) -> float | None:
    if not _is_number(current) or not _is_number(previous) or float(previous) == 0.0:
        return None
    return float(current) / float(previous) - 1.0


def validate_action_codes() -> None:
    """Fail fast when local rules emit codes outside the shared contract."""
    required_modes = {
        "bullish_accumulation",
        "bullish_trend",
        "bullish_pullback",
        "range_theta_candidate",
        "range_theta",
        "bottoming",
        "overextended",
        "bearish_distribution",
        "high_risk_avoid",
        "insufficient_data",
    }
    required_primary = {
        "long_houden",
        "schrijf_puts",
        "covered_calls_ver_otm",
        "theta_harvest",
        "risico_verlagen",
        "niets_doen",
        "geen_advies_onvoldoende_data",
    }
    required_secondary = {
        "geen_call_dichtbij",
        "puts_alleen_bij_pullback",
        "geen_naked_puts",
        "volume_waarschuwt",
        "covered_calls_en_puts_toegestaan",
        "wachten_op_stabilisatie",
        "puts_dicht_bij_koers_toegestaan",
        "deeper_otm_put_reduced_position_sizing",
    }
    required_quality = {"ok", "partial", "insufficient"}

    missing = (
        required_modes.difference(ASSET_INDICATOR_ASSET_MODES)
        | required_primary.difference(ASSET_INDICATOR_PRIMARY_ACTIONS)
        | required_secondary.difference(ASSET_INDICATOR_SECONDARY_ACTIONS)
        | required_quality.difference(ASSET_INDICATOR_DATA_QUALITY_CODES)
    )
    if missing:
        raise ValueError(f"Asset indicator contract misses rule codes: {sorted(missing)}")


def price_volume_day_score(price_change: float | None, relative_volume: float | None) -> int:
    """Return the single-day price/volume score from the design note."""
    if not _is_number(price_change):
        return 0
    rv = float(relative_volume) if _is_number(relative_volume) else 1.0
    pc = float(price_change)

    if pc > 0.005 and rv > 1.2:
        return 2
    if pc > 0.005:
        return 1
    if pc < -0.005 and rv > 1.2:
        return -2
    if pc < -0.005:
        return -1
    return 0


def calculate_direction_score(data: DirectionInput) -> float | None:
    """Calculate a first-version direction score from -100 to +100."""
    long_term = calculate_long_term_direction_score(data)
    short_term = calculate_short_term_direction_score(data)
    if long_term is None and short_term is None:
        return None
    if long_term is None:
        return short_term
    if short_term is None:
        return long_term
    return round(_clamp((float(long_term) * 0.65) + (float(short_term) * 0.35), -100.0, 100.0), 2)


def calculate_long_term_direction_score(data: DirectionInput) -> float | None:
    """Calculate structural trend direction, deliberately slower than short-term direction."""
    if not _is_number(data.close):
        return None

    close = float(data.close)
    score = 0.0
    signals = 0

    if _is_number(data.sma_50):
        signals += 1
        score += 20.0 if close > float(data.sma_50) else -20.0

    if _is_number(data.sma_200):
        signals += 1
        score += 20.0 if close > float(data.sma_200) else -20.0

    if _is_number(data.sma_20) and _is_number(data.sma_50) and _is_number(data.sma_200):
        sma_20 = float(data.sma_20)
        sma_50 = float(data.sma_50)
        sma_200 = float(data.sma_200)
        if close > sma_20 > sma_50 > sma_200:
            score += 20.0
        elif close < sma_20 < sma_50 < sma_200:
            score -= 20.0

    if _is_number(data.sma_50) and _is_number(data.sma_50_prev):
        signals += 1
        slope_50 = _pct_change(data.sma_50, data.sma_50_prev)
        if slope_50 is not None:
            if slope_50 > 0.002:
                score += 10.0
            elif slope_50 < -0.002:
                score -= 10.0

    if _is_number(data.ema_50) and _is_number(data.ema_200):
        signals += 1
        ema_50 = float(data.ema_50)
        ema_200 = float(data.ema_200)
        if close > ema_50 > ema_200:
            score += 15.0
        elif close < ema_50 < ema_200:
            score -= 15.0
        elif close > ema_200:
            score += 5.0
        elif close < ema_200:
            score -= 5.0

    if _is_number(data.ema_9) and _is_number(data.ema_26):
        signals += 1
        ema_9 = float(data.ema_9)
        ema_26 = float(data.ema_26)
        if close > ema_9 > ema_26:
            score += 10.0
        elif close < ema_9 < ema_26:
            score -= 10.0
        elif ema_9 > ema_26:
            score += 4.0
        elif ema_9 < ema_26:
            score -= 4.0

    momentum_60d = _pct_change(close, data.close_60d_ago)
    if momentum_60d is not None:
        signals += 1
        if momentum_60d > 0.10:
            score += 15.0
        elif momentum_60d > 0.03:
            score += 8.0
        elif momentum_60d < -0.10:
            score -= 15.0
        elif momentum_60d < -0.03:
            score -= 8.0

    if _is_number(data.high_52w) and float(data.high_52w) > 0.0:
        signals += 1
        drawdown = close / float(data.high_52w) - 1.0
        if drawdown > -0.05:
            score += 8.0
        elif drawdown < -0.35:
            score -= 15.0
        elif drawdown < -0.20:
            score -= 8.0

    if _is_number(data.low_52w) and _is_number(data.high_52w) and float(data.high_52w) > float(data.low_52w):
        cycle_pos = (close - float(data.low_52w)) / (float(data.high_52w) - float(data.low_52w))
        if cycle_pos > 0.75:
            score += 5.0
        elif cycle_pos < 0.25:
            score -= 5.0

    if signals < 3:
        return None
    return round(_clamp(score, -100.0, 100.0), 2)


def calculate_short_term_direction_score(data: DirectionInput) -> float | None:
    """Calculate tactical direction using fast EMAs and recent momentum."""
    if not _is_number(data.close):
        return None

    close = float(data.close)
    score = 0.0
    signals = 0

    if _is_number(data.sma_20):
        signals += 1
        score += 18.0 if close > float(data.sma_20) else -18.0

    if _is_number(data.ema_9) and _is_number(data.ema_26):
        signals += 1
        ema_9 = float(data.ema_9)
        ema_26 = float(data.ema_26)
        if close > ema_9 > ema_26:
            score += 25.0
        elif close < ema_9 < ema_26:
            score -= 25.0
        elif ema_9 > ema_26:
            score += 10.0
        elif ema_9 < ema_26:
            score -= 10.0

    if (
        _is_number(data.ema_9)
        and _is_number(data.ema_26)
        and _is_number(data.ema_9_prev)
        and _is_number(data.ema_26_prev)
    ):
        signals += 1
        ema_spread = float(data.ema_9) - float(data.ema_26)
        ema_spread_prev = float(data.ema_9_prev) - float(data.ema_26_prev)
        if ema_spread > 0 and ema_spread > ema_spread_prev:
            score += 12.0
        elif ema_spread < 0 and ema_spread < ema_spread_prev:
            score -= 12.0

    momentum_5d = _pct_change(close, data.close_5d_ago)
    if momentum_5d is not None:
        signals += 1
        if momentum_5d > 0.03:
            score += 15.0
        elif momentum_5d > 0.01:
            score += 8.0
        elif momentum_5d < -0.03:
            score -= 15.0
        elif momentum_5d < -0.01:
            score -= 8.0

    momentum_20d = _pct_change(close, data.close_20d_ago)
    if momentum_20d is not None:
        signals += 1
        if momentum_20d > 0.05:
            score += 20.0
        elif momentum_20d > 0.01:
            score += 10.0
        elif momentum_20d < -0.05:
            score -= 20.0
        elif momentum_20d < -0.01:
            score -= 10.0

    if signals < 2:
        return None
    return round(_clamp(score, -100.0, 100.0), 2)


def calculate_range_position_pct(data: DirectionInput) -> float | None:
    """Return where close sits in the recent range: 0 low, 100 high."""
    if not _is_number(data.close):
        return None
    high = data.high_90d if _is_number(data.high_90d) else data.high_52w
    low = data.low_90d if _is_number(data.low_90d) else data.low_52w
    if not _is_number(high) or not _is_number(low) or float(high) <= float(low):
        return None
    pct = ((float(data.close) - float(low)) / (float(high) - float(low))) * 100.0
    return round(_clamp(pct, 0.0, 100.0), 2)


def classify_trend_phase(
    long_term_direction_score: float | None,
    short_term_direction_score: float | None,
    range_position_pct: float | None,
    data_quality: str = "ok",
) -> str:
    """Classify direction into a non-linear trading regime label."""
    if data_quality == "insufficient" or not _is_number(long_term_direction_score):
        return "insufficient_data"

    long_term = float(long_term_direction_score)
    short_term = float(short_term_direction_score) if _is_number(short_term_direction_score) else 0.0
    range_pos = float(range_position_pct) if _is_number(range_position_pct) else None

    if long_term <= -55.0 and short_term <= -20.0:
        return "bearish_distribution"
    if long_term <= -35.0 and short_term > 20.0:
        return "long_term_bear_relief_rally"

    if long_term >= 45.0:
        if range_pos is not None and range_pos <= 10.0:
            return "long_term_bull_bottom_10pct_range"
        if range_pos is not None and range_pos >= 90.0:
            return "long_term_bull_top_10pct_range"
        if short_term < -15.0:
            return "long_term_bull_retrace"
        if short_term >= 20.0:
            return "long_term_bull_short_term_bull"
        return "long_term_bull_retrace"

    if -35.0 < long_term < 45.0:
        if range_pos is not None and range_pos <= 30.0:
            return "range_lower_band"
        if range_pos is not None and range_pos >= 70.0:
            return "range_upper_band"
        return "range_mid"

    return "bearish_distribution"


def calculate_volume_score(data: VolumeInput) -> float | None:
    """Calculate a first-version volume confirmation score from -100 to +100."""
    day_scores = [
        price_volume_day_score(price_change, relative_volume)
        for price_change, relative_volume in zip(data.price_changes_3d, data.relative_volumes_3d)
        if _is_number(price_change)
    ]
    if not day_scores and not _is_number(data.relative_volume_20d):
        return None

    score = 0.0
    if day_scores:
        score += (sum(day_scores) / 6.0) * 70.0

    if _is_number(data.relative_volume_20d):
        rv = float(data.relative_volume_20d)
        if rv > 2.0:
            score += 12.0
        elif rv > 1.2:
            score += 7.0
        elif rv < 0.7:
            score -= 5.0

    if _is_number(data.volume_weighted_price_change):
        vwm = float(data.volume_weighted_price_change)
        if vwm > 0.03:
            score += 15.0
        elif vwm > 0.01:
            score += 8.0
        elif vwm < -0.03:
            score -= 15.0
        elif vwm < -0.01:
            score -= 8.0

    return round(_clamp(score, -100.0, 100.0), 2)


def classify_asset_mode(
    direction_score: float | None,
    volume_score: float | None,
    vulnerability_score: float | None = None,
    data_quality: str = "ok",
    trend_phase: str | None = None,
) -> str:
    if data_quality == "insufficient" or not _is_number(direction_score):
        return "insufficient_data"

    if trend_phase:
        if trend_phase == "bearish_distribution":
            return "bearish_distribution"
        if trend_phase == "long_term_bear_relief_rally":
            return "bottoming"
        if trend_phase in {"long_term_bull_retrace", "long_term_bull_bottom_10pct_range"}:
            return "bullish_pullback"
        if trend_phase == "long_term_bull_top_10pct_range":
            return "overextended"
        if trend_phase == "long_term_bull_short_term_bull":
            volume = float(volume_score) if _is_number(volume_score) else 0.0
            return "bullish_accumulation" if volume >= 40.0 else "bullish_trend"
        if trend_phase in {"range_lower_band", "range_mid", "range_upper_band"}:
            return "range_theta_candidate"

    direction = float(direction_score)
    volume = float(volume_score) if _is_number(volume_score) else 0.0
    vulnerability = float(vulnerability_score) if _is_number(vulnerability_score) else 0.0

    if vulnerability >= 85.0:
        return "high_risk_avoid"
    if direction >= 60.0 and volume >= 40.0:
        return "bullish_accumulation"
    if direction >= 75.0 and volume <= -30.0:
        return "bullish_pullback"
    if direction >= 35.0:
        return "bullish_trend"
    if direction <= -40.0 and volume <= -30.0:
        return "bearish_distribution"
    if direction <= -25.0 and volume > -20.0:
        return "bottoming"
    if direction >= 45.0 and volume < -20.0:
        return "overextended"
    return "range_theta_candidate"


def map_scores_to_action(data: ActionInput) -> ActionDecision:
    """Map scores to stable mode/action codes and short reasons."""
    validate_action_codes()

    data_quality = data.data_quality if data.data_quality in ASSET_INDICATOR_DATA_QUALITY_CODES else "partial"
    direction = float(data.direction_score) if _is_number(data.direction_score) else None
    volume = float(data.volume_score) if _is_number(data.volume_score) else 0.0
    theta = float(data.theta_score) if _is_number(data.theta_score) else 0.0
    vulnerability = float(data.vulnerability_score) if _is_number(data.vulnerability_score) else 0.0

    mode = classify_asset_mode(direction, volume, vulnerability, data_quality, data.trend_phase)

    if mode == "insufficient_data":
        return ActionDecision(
            asset_mode=mode,
            primary_action="geen_advies_onvoldoende_data",
            secondary_action="wachten_op_stabilisatie",
            covered_call_delta_min=None,
            covered_call_delta_max=None,
            short_put_delta_min=None,
            short_put_delta_max=None,
            confidence_score=0.0,
            reason_1="Onvoldoende koers- of indicatorhistorie",
            reason_2="Service kan nog geen betrouwbaar regime bepalen",
            reason_3="Wacht op volledige brondata",
        )

    if vulnerability >= 80.0:
        return ActionDecision(
            asset_mode="high_risk_avoid",
            primary_action="risico_verlagen",
            secondary_action="geen_naked_puts",
            covered_call_delta_min=None,
            covered_call_delta_max=None,
            short_put_delta_min=None,
            short_put_delta_max=None,
            confidence_score=_confidence(direction, volume, theta, vulnerability, data_quality),
            reason_1="Vulnerability is hoog",
            reason_2="Geen extra naked short premium",
            reason_3="Gebruik alleen kleine of defined-risk posities",
        )

    if direction is not None and direction >= 60.0 and volume >= 40.0:
        return ActionDecision(
            asset_mode=mode,
            primary_action="long_houden",
            secondary_action="geen_call_dichtbij",
            covered_call_delta_min=0.05,
            covered_call_delta_max=0.15,
            short_put_delta_min=0.15,
            short_put_delta_max=0.25,
            confidence_score=_confidence(direction, volume, theta, vulnerability, data_quality),
            reason_1="Direction is sterk positief",
            reason_2="Volume bevestigt accumulatie",
            reason_3="Upside niet agressief wegschrijven",
        )

    if direction is not None and direction >= 60.0 and volume >= -20.0:
        return ActionDecision(
            asset_mode=mode,
            primary_action="schrijf_puts",
            secondary_action="puts_dicht_bij_koers_toegestaan",
            covered_call_delta_min=0.10,
            covered_call_delta_max=0.20,
            short_put_delta_min=0.25,
            short_put_delta_max=0.40,
            confidence_score=_confidence(direction, volume, theta, vulnerability, data_quality),
            reason_1="Stabiele bullish trend",
            reason_2="Volume waarschuwt niet tegen de trend",
            reason_3="Put-premie oogsten is passend zonder exposure af te bouwen",
        )

    if direction is not None and direction >= 60.0 and volume < -20.0:
        return ActionDecision(
            asset_mode=mode,
            primary_action="schrijf_puts",
            secondary_action="deeper_otm_put_reduced_position_sizing",
            covered_call_delta_min=0.10,
            covered_call_delta_max=0.20,
            short_put_delta_min=0.15,
            short_put_delta_max=0.25,
            confidence_score=_confidence(direction, volume, theta, vulnerability, data_quality),
            reason_1="Bullish trend met recente pullback of zwakker volume",
            reason_2="Exposure kan blijven, maar nieuwe short puts vragen reduced position sizing",
            reason_3="Gebruik een deeper OTM put in plaats van dicht bij de koers",
        )

    if direction is not None and direction >= 30.0 and theta >= 60.0:
        return ActionDecision(
            asset_mode=mode,
            primary_action="covered_calls_ver_otm",
            secondary_action="puts_alleen_bij_pullback",
            covered_call_delta_min=0.15,
            covered_call_delta_max=0.25,
            short_put_delta_min=0.15,
            short_put_delta_max=0.25,
            confidence_score=_confidence(direction, volume, theta, vulnerability, data_quality),
            reason_1="Trend is positief",
            reason_2="Theta is aantrekkelijk",
            reason_3="Premie oogsten met ruimte voor groei",
        )

    if direction is not None and -25.0 <= direction <= 25.0 and theta >= 60.0 and vulnerability < 60.0:
        return ActionDecision(
            asset_mode="range_theta",
            primary_action="theta_harvest",
            secondary_action="covered_calls_en_puts_toegestaan",
            covered_call_delta_min=0.25,
            covered_call_delta_max=0.40,
            short_put_delta_min=0.20,
            short_put_delta_max=0.30,
            confidence_score=_confidence(direction, volume, theta, vulnerability, data_quality),
            reason_1="Direction is neutraal",
            reason_2="Theta is aantrekkelijk",
            reason_3="Range-regime ondersteunt premie oogsten",
        )

    if direction is not None and -25.0 <= direction <= 25.0:
        return ActionDecision(
            asset_mode="range_theta_candidate",
            primary_action="niets_doen",
            secondary_action="wachten_op_stabilisatie",
            covered_call_delta_min=None,
            covered_call_delta_max=None,
            short_put_delta_min=None,
            short_put_delta_max=None,
            confidence_score=_confidence(direction, volume, theta, vulnerability, data_quality),
            reason_1="Direction is choppy of neutraal",
            reason_2="Theta-data is nog onvoldoende om theta harvest te adviseren",
            reason_3="Kandidaat voor theta-strategie zodra premie/IV aantrekkelijk is",
        )

    if direction is not None and direction <= -40.0 and volume <= -40.0:
        return ActionDecision(
            asset_mode="bearish_distribution",
            primary_action="risico_verlagen",
            secondary_action="geen_naked_puts",
            covered_call_delta_min=0.35,
            covered_call_delta_max=0.50,
            short_put_delta_min=None,
            short_put_delta_max=None,
            confidence_score=_confidence(direction, volume, theta, vulnerability, data_quality),
            reason_1="Direction is bearish",
            reason_2="Volume wijst op distributie",
            reason_3="Geen naked puts in verzwakking",
        )

    if direction is not None and direction >= 10.0 and volume <= -30.0:
        return ActionDecision(
            asset_mode=mode,
            primary_action="niets_doen",
            secondary_action="volume_waarschuwt",
            covered_call_delta_min=None,
            covered_call_delta_max=None,
            short_put_delta_min=None,
            short_put_delta_max=None,
            confidence_score=_confidence(direction, volume, theta, vulnerability, data_quality),
            reason_1="Direction is nog positief",
            reason_2="Volume bevestigt de stijging niet",
            reason_3="Wacht op betere bevestiging",
        )

    return ActionDecision(
        asset_mode=mode,
        primary_action="niets_doen",
        secondary_action="wachten_op_stabilisatie",
        covered_call_delta_min=None,
        covered_call_delta_max=None,
        short_put_delta_min=None,
        short_put_delta_max=None,
        confidence_score=_confidence(direction, volume, theta, vulnerability, data_quality),
        reason_1="Geen sterk regime",
        reason_2="Scores geven geen duidelijke actie",
        reason_3="Wacht op betere risk/reward",
    )


def _confidence(
    direction_score: float | None,
    volume_score: float | None,
    theta_score: float | None,
    vulnerability_score: float | None,
    data_quality: str,
) -> float:
    available = sum(
        1
        for value in (direction_score, volume_score, theta_score, vulnerability_score)
        if _is_number(value)
    )
    base = (available / 4.0) * 70.0
    if data_quality == "ok":
        base += 20.0
    elif data_quality == "partial":
        base += 5.0

    if _is_number(direction_score) and abs(float(direction_score)) >= 60.0:
        base += 5.0
    if _is_number(volume_score) and abs(float(volume_score)) >= 40.0:
        base += 5.0

    return round(_clamp(base, 0.0, 100.0), 2)
