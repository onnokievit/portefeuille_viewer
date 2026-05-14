from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

try:
    from scipy.interpolate import RBFInterpolator
except Exception:  # pragma: no cover - optional fallback for lean environments
    RBFInterpolator = None


X_LABEL = {"strike": "Strike", "moneyness": "Moneyness (K/S)", "delta": "|Delta|"}
_PLOTLY_CDN = "cdn"


def prepare_surface_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "iv" not in out.columns and "model_iv" in out.columns:
        out["iv"] = out["model_iv"]
    if "iv" in out.columns:
        out["iv"] = pd.to_numeric(out["iv"], errors="coerce")
        # IB model_iv is often 0.xx. Store/chart as percent.
        mask = out["iv"].between(0, 10)
        out.loc[mask, "iv"] = out.loc[mask, "iv"] * 100.0
    for col in ("strike", "moneyness", "delta", "dte"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    if "expiry" in out.columns:
        out["expiry"] = out["expiry"].astype(str).str.replace("-", "", regex=False).str[:8]
    return out.dropna(subset=["iv", "dte", "strike"])


def build_3d_surface(df: pd.DataFrame, x_mode: str = "moneyness", right: str = "C") -> str:
    data = prepare_surface_frame(df)
    fig = go.Figure()
    any_data = False
    for side, colorscale, name in _sides(right):
        sub = _filter(data, side, x_mode)
        if sub.empty:
            continue
        xi, yi, zi = _interpolate(_x(sub, x_mode), sub["dte"], sub["iv"])
        if xi is None:
            fig.add_trace(_scatter3d(sub, x_mode, name))
            any_data = True
            continue
        fig.add_trace(
            go.Surface(
                x=xi,
                y=yi,
                z=zi,
                colorscale=colorscale,
                opacity=0.82 if right == "B" else 1.0,
                name=name,
                showscale=True,
                colorbar=dict(title="IV %", thickness=15, len=0.65),
            )
        )
        any_data = True
    if not any_data:
        _empty(fig)
    fig.update_layout(
        height=650,
        margin=dict(l=50, r=30, t=45, b=45),
        title=f"Vol Surface [{x_mode}]",
        scene=dict(
            xaxis_title=X_LABEL.get(x_mode, "X"),
            yaxis_title="DTE",
            zaxis_title="IV %",
            camera=dict(eye=dict(x=1.6, y=-1.5, z=1.0)),
        ),
    )
    return fig.to_html(include_plotlyjs=_PLOTLY_CDN, full_html=True)


def build_smile_lines(df: pd.DataFrame, x_mode: str = "moneyness", right: str = "C") -> str:
    data = prepare_surface_frame(df)
    fig = go.Figure()
    any_data = False
    for side, _colorscale, name in _sides(right):
        sub = _filter(data, side, x_mode)
        for expiry, group in sub.groupby("expiry", dropna=True):
            group = group.sort_values("strike")
            dte = int(group["dte"].iloc[0]) if len(group) else 0
            fig.add_trace(
                go.Scatter(
                    x=_x(group, x_mode),
                    y=group["iv"],
                    mode="lines+markers",
                    name=f"{expiry} {side} ({dte}d)",
                    hovertemplate=f"{X_LABEL.get(x_mode, 'X')}: %{{x:.4f}}<br>IV: %{{y:.2f}}%<extra>{name}</extra>",
                )
            )
            any_data = True
    if not any_data:
        _empty(fig)
    fig.update_layout(
        height=580,
        margin=dict(l=50, r=30, t=45, b=45),
        title="Volatility Smile per Expiry",
        xaxis_title=X_LABEL.get(x_mode, "X"),
        yaxis_title="IV %",
        hovermode="x unified",
    )
    return fig.to_html(include_plotlyjs=_PLOTLY_CDN, full_html=True)


def build_heatmap(df: pd.DataFrame, x_mode: str = "moneyness", right: str = "C") -> str:
    data = prepare_surface_frame(df)
    sides = _sides(right)
    fig = make_subplots(rows=1, cols=len(sides), subplot_titles=[s[2] for s in sides], shared_yaxes=True)
    any_data = False
    for idx, (side, _colorscale, _name) in enumerate(sides, start=1):
        sub = _filter(data, side, x_mode)
        xi, yi, zi = _interpolate(_x(sub, x_mode), sub["dte"], sub["iv"]) if not sub.empty else (None, None, None)
        if xi is None:
            continue
        fig.add_trace(
            go.Heatmap(
                x=xi,
                y=yi,
                z=zi,
                colorscale="RdYlGn_r",
                colorbar=dict(title="IV %", thickness=14),
            ),
            row=1,
            col=idx,
        )
        fig.update_xaxes(title_text=X_LABEL.get(x_mode, "X"), row=1, col=idx)
        any_data = True
    if not any_data:
        _empty(fig)
    fig.update_yaxes(title_text="DTE", row=1, col=1)
    fig.update_layout(height=540, margin=dict(l=50, r=30, t=45, b=45), title=f"IV Heatmap [{x_mode}]")
    return fig.to_html(include_plotlyjs=_PLOTLY_CDN, full_html=True)


def build_metric_heatmap(
    df: pd.DataFrame,
    metric: str,
    title: str,
    x_mode: str = "moneyness",
    right: str = "B",
) -> str:
    data = df.copy()
    if metric not in data.columns:
        fig = go.Figure()
        _empty(fig)
        fig.update_layout(title=f"{title} - kolom ontbreekt: {metric}")
        return fig.to_html(include_plotlyjs=_PLOTLY_CDN, full_html=True)
    for col in (metric, "strike", "moneyness", "delta", "dte"):
        if col in data.columns:
            data[col] = pd.to_numeric(data[col], errors="coerce")
    sides = _sides(right)
    fig = make_subplots(rows=1, cols=len(sides), subplot_titles=[s[2] for s in sides], shared_yaxes=True)
    any_data = False
    for idx, (side, _colorscale, _name) in enumerate(sides, start=1):
        sub = _filter(data, side, x_mode).dropna(subset=[metric])
        xi, yi, zi = _interpolate(_x(sub, x_mode), sub["dte"], sub[metric]) if not sub.empty else (None, None, None)
        if xi is None:
            if sub.empty:
                continue
            fig.add_trace(
                go.Scatter(
                    x=_x(sub, x_mode),
                    y=sub["dte"],
                    mode="markers",
                    marker=dict(size=7, color=sub[metric], colorscale="Viridis", showscale=True),
                    name=side,
                ),
                row=1,
                col=idx,
            )
        else:
            fig.add_trace(
                go.Heatmap(x=xi, y=yi, z=zi, colorscale="Viridis", colorbar=dict(title=metric, thickness=14)),
                row=1,
                col=idx,
            )
        fig.update_xaxes(title_text=X_LABEL.get(x_mode, "X"), row=1, col=idx)
        any_data = True
    if not any_data:
        _empty(fig)
    fig.update_yaxes(title_text="DTE", row=1, col=1)
    fig.update_layout(height=540, margin=dict(l=50, r=30, t=45, b=45), title=f"{title} [{x_mode}]")
    return fig.to_html(include_plotlyjs=_PLOTLY_CDN, full_html=True)


def build_gex_by_strike(df: pd.DataFrame, gamma_flip: float | None = None, spot: float | None = None) -> str:
    data = df.copy()
    if data.empty or "strike" not in data.columns or "net_dealer_gex_1pct" not in data.columns:
        fig = go.Figure()
        fig.add_annotation(text="Geen GEX data beschikbaar", showarrow=False, xref="paper", yref="paper", x=0.5, y=0.5)
        fig.update_layout(height=560, margin=dict(l=55, r=30, t=45, b=45), title="Dealer Gamma Exposure per Strike")
        return fig.to_html(include_plotlyjs=_PLOTLY_CDN, full_html=True)

    for col in ("strike", "net_dealer_gex_1pct", "cumulative_dealer_gex_1pct"):
        if col in data.columns:
            data[col] = pd.to_numeric(data[col], errors="coerce")
    data = data.sort_values("strike").dropna(subset=["strike", "net_dealer_gex_1pct"])

    colors = np.where(data["net_dealer_gex_1pct"] >= 0, "#2E7D32", "#C62828")
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(
            x=data["strike"],
            y=data["net_dealer_gex_1pct"],
            marker_color=colors,
            name="Net dealer GEX 1%",
            hovertemplate="Strike: %{x:.2f}<br>Net GEX: %{y:,.0f}<extra></extra>",
        ),
        secondary_y=False,
    )
    if "cumulative_dealer_gex_1pct" in data.columns:
        fig.add_trace(
            go.Scatter(
                x=data["strike"],
                y=data["cumulative_dealer_gex_1pct"],
                mode="lines+markers",
                line=dict(color="#1565C0", width=2),
                marker=dict(size=5),
                name="Cumulative GEX",
                hovertemplate="Strike: %{x:.2f}<br>Cum GEX: %{y:,.0f}<extra></extra>",
            ),
            secondary_y=True,
        )
    if gamma_flip is not None and np.isfinite(gamma_flip):
        fig.add_vline(
            x=float(gamma_flip),
            line_width=2,
            line_dash="dash",
            line_color="#6A1B9A",
            annotation_text=f"Gamma flip {float(gamma_flip):.2f}",
            annotation_position="top left",
        )
    if spot is not None and np.isfinite(spot):
        fig.add_vline(
            x=float(spot),
            line_width=2,
            line_dash="dot",
            line_color="#424242",
            annotation_text=f"Spot {float(spot):.2f}",
            annotation_position="bottom left",
        )
    left_range, right_range = _aligned_zero_axis_ranges(
        data["net_dealer_gex_1pct"],
        data["cumulative_dealer_gex_1pct"] if "cumulative_dealer_gex_1pct" in data.columns else pd.Series(dtype=float),
    )
    fig.update_yaxes(title_text="Net dealer GEX per 1% move", range=left_range, zeroline=True, secondary_y=False)
    fig.update_yaxes(title_text="Cumulative dealer GEX", range=right_range, zeroline=True, secondary_y=True)
    fig.update_layout(
        height=560,
        margin=dict(l=55, r=45, t=45, b=45),
        title="Dealer Gamma Exposure per Strike",
        xaxis_title="Strike",
        bargap=0.08,
        hovermode="x unified",
    )
    return fig.to_html(include_plotlyjs=_PLOTLY_CDN, full_html=True)


def _aligned_zero_axis_ranges(left_values: pd.Series, right_values: pd.Series) -> tuple[list[float] | None, list[float] | None]:
    left_min, left_max = _padded_axis_limits(left_values)
    right_min, right_max = _padded_axis_limits(right_values)
    if left_min is None or right_min is None:
        return None, None

    zero_pos = (0.0 - left_min) / (left_max - left_min)
    zero_pos = min(max(zero_pos, 0.05), 0.95)

    right_min, right_max = _range_with_zero_position(right_min, right_max, zero_pos)
    return [left_min, left_max], [right_min, right_max]


def _padded_axis_limits(values: pd.Series) -> tuple[float | None, float | None]:
    numeric = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if numeric.empty:
        return None, None
    low = min(float(numeric.min()), 0.0)
    high = max(float(numeric.max()), 0.0)
    if np.isclose(low, high):
        pad = max(abs(high), 1.0) * 0.1
        return low - pad, high + pad
    pad = (high - low) * 0.05
    return low - pad, high + pad


def _range_with_zero_position(data_min: float, data_max: float, zero_pos: float) -> tuple[float, float]:
    below = max(abs(min(data_min, 0.0)), 1e-9)
    above = max(max(data_max, 0.0), 1e-9)
    span = max(below / zero_pos, above / (1.0 - zero_pos))
    return -span * zero_pos, span * (1.0 - zero_pos)


def build_gex_heatmap(df: pd.DataFrame) -> str:
    data = df.copy()
    metric = "dealer_gex_1pct"
    required = {"strike", "dte", metric}
    if data.empty or not required.issubset(data.columns):
        fig = go.Figure()
        fig.add_annotation(text="Geen GEX data beschikbaar", showarrow=False, xref="paper", yref="paper", x=0.5, y=0.5)
        fig.update_layout(height=540, margin=dict(l=50, r=30, t=45, b=45), title="GEX Heatmap")
        return fig.to_html(include_plotlyjs=_PLOTLY_CDN, full_html=True)

    for col in ("strike", "dte", metric):
        data[col] = pd.to_numeric(data[col], errors="coerce")
    data = data.dropna(subset=["strike", "dte", metric])
    if data.empty:
        fig = go.Figure()
        fig.add_annotation(text="Geen GEX data beschikbaar", showarrow=False, xref="paper", yref="paper", x=0.5, y=0.5)
        fig.update_layout(height=540, margin=dict(l=50, r=30, t=45, b=45), title="GEX Heatmap")
        return fig.to_html(include_plotlyjs=_PLOTLY_CDN, full_html=True)

    pivot = (
        data.groupby(["dte", "strike"], dropna=True)[metric]
        .sum()
        .reset_index()
        .pivot(index="dte", columns="strike", values=metric)
        .sort_index()
    )
    z_abs = np.nanmax(np.abs(pivot.to_numpy(dtype=float))) if pivot.size else 0.0
    z_lim = float(z_abs) if np.isfinite(z_abs) and z_abs > 0 else 1.0
    fig = go.Figure(
        go.Heatmap(
            x=pivot.columns.astype(float),
            y=pivot.index.astype(float),
            z=pivot.to_numpy(dtype=float),
            colorscale="RdBu",
            zmid=0,
            zmin=-z_lim,
            zmax=z_lim,
            colorbar=dict(title="GEX 1%", thickness=14),
            hovertemplate="Strike: %{x:.2f}<br>DTE: %{y:.0f}<br>GEX: %{z:,.0f}<extra></extra>",
        )
    )
    fig.update_layout(
        height=540,
        margin=dict(l=50, r=30, t=45, b=45),
        title="Dealer GEX Heatmap",
        xaxis_title="Strike",
        yaxis_title="DTE",
    )
    return fig.to_html(include_plotlyjs=_PLOTLY_CDN, full_html=True)


def _sides(right: str) -> list[tuple[str, str, str]]:
    if right == "C":
        return [("C", "Blues", "Calls")]
    if right == "P":
        return [("P", "Reds", "Puts")]
    return [("C", "Blues", "Calls"), ("P", "Reds", "Puts")]


def _filter(df: pd.DataFrame, right: str, x_mode: str) -> pd.DataFrame:
    sub = df[df["right"].astype(str).str.upper() == right].copy()
    if x_mode == "delta":
        sub = sub.dropna(subset=["delta"])
    elif x_mode == "moneyness":
        sub = sub.dropna(subset=["moneyness"])
    return sub


def _x(df: pd.DataFrame, x_mode: str):
    if df.empty:
        return pd.Series(dtype=float)
    if x_mode == "moneyness":
        return df["moneyness"]
    if x_mode == "delta":
        return df["delta"].abs()
    return df["strike"]


def _interpolate(x, y, z):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    z = np.asarray(z, dtype=float)
    mask = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    x, y, z = x[mask], y[mask], z[mask]
    if len(x) < 6:
        return None, None, None
    xi = np.linspace(x.min(), x.max(), 60)
    yi = np.linspace(y.min(), y.max(), 30)
    xi_g, yi_g = np.meshgrid(xi, yi)
    if RBFInterpolator is None:
        return None, None, None
    try:
        rbf = RBFInterpolator(np.column_stack([x, y]), z, kernel="thin_plate_spline", smoothing=0.8)
        zi_g = rbf(np.column_stack([xi_g.ravel(), yi_g.ravel()])).reshape(xi_g.shape)
        return xi, yi, np.clip(zi_g, 0, None)
    except Exception:
        return None, None, None


def _scatter3d(df: pd.DataFrame, x_mode: str, name: str):
    return go.Scatter3d(
        x=_x(df, x_mode),
        y=df["dte"],
        z=df["iv"],
        mode="markers",
        name=name,
        marker=dict(size=4, color=df["iv"], colorscale="Viridis", showscale=True),
    )


def _empty(fig) -> None:
    fig.add_annotation(text="Geen IV data beschikbaar", showarrow=False, xref="paper", yref="paper", x=0.5, y=0.5)
