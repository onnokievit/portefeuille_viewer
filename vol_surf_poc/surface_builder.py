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
