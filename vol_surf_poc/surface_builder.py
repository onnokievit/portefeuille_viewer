"""
Build plotly charts from option IV data.

Three chart types:
  - 3D Surface  : interpolated IV surface (strike/moneyness/delta × DTE → IV)
  - Smile Lines : per-expiry IV curves
  - Heatmap     : 2D colour grid (strike/moneyness × DTE)

X-axis modes : "strike" | "moneyness" | "delta"
Right filter : "C" (calls) | "P" (puts) | "B" (both)
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from scipy.interpolate import RBFInterpolator

# ── constants ─────────────────────────────────────────────────────────────────

X_LABEL = {"strike": "Strike", "moneyness": "Moneyness (K/S)", "delta": "|Delta|"}
_CALL_COLORS = ["#1f77b4", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2"]
_PUT_COLORS  = ["#aec7e8", "#98df8a", "#ff9896", "#c5b0d5", "#c49c94", "#f7b6d2"]

_PLOTLY_CDN = "cdn"          # set to "require" if offline

# ── helpers ───────────────────────────────────────────────────────────────────

def _x_col(df: pd.DataFrame, x_mode: str) -> pd.Series:
    if x_mode == "moneyness":
        return df["moneyness"]
    if x_mode == "delta":
        return df["delta"].abs()
    return df["strike"]


def _filter_right(df: pd.DataFrame, right: str) -> pd.DataFrame:
    if right in ("C", "P"):
        return df[df["right"] == right].copy()
    return df.copy()


def _interpolate_surface(
    x: np.ndarray, y: np.ndarray, z: np.ndarray,
    nx: int = 60, ny: int = 30
) -> tuple[np.ndarray, np.ndarray, np.ndarray] | tuple[None, None, None]:
    """RBF interpolation of scattered (x, y) → z onto a regular grid."""
    mask = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    x, y, z = x[mask], y[mask], z[mask]
    if len(x) < 6:
        return None, None, None
    try:
        rbf = RBFInterpolator(
            np.column_stack([x, y]), z,
            kernel="thin_plate_spline",
            smoothing=0.8,
        )
    except Exception as exc:
        print(f"  [surface] RBF failed: {exc}")
        return None, None, None

    xi = np.linspace(x.min(), x.max(), nx)
    yi = np.linspace(y.min(), y.max(), ny)
    xi_g, yi_g = np.meshgrid(xi, yi)
    zi_g = rbf(np.column_stack([xi_g.ravel(), yi_g.ravel()])).reshape(xi_g.shape)
    zi_g = np.clip(zi_g, 0, None)          # IV can't be negative
    return xi, yi, zi_g


def _base_layout(**kwargs) -> dict:
    return dict(margin=dict(l=50, r=30, t=40, b=50), **kwargs)


# ── chart builders ────────────────────────────────────────────────────────────

def build_3d_surface(
    df: pd.DataFrame, x_mode: str = "moneyness", right: str = "C"
) -> str:
    """Return full HTML string with an interactive 3D vol surface."""
    fig = go.Figure()
    xl  = X_LABEL[x_mode]

    sides = (
        [("C", "Blues", "Calls"), ("P", "Reds", "Puts")]
        if right == "B"
        else [(right, "Blues" if right == "C" else "Reds",
               "Calls" if right == "C" else "Puts")]
    )

    any_data = False
    for r, cscale, name in sides:
        sub = _filter_right(df, r)
        if x_mode == "delta":
            sub = sub.dropna(subset=["delta"])
        if sub.empty:
            continue

        x = _x_col(sub, x_mode).values.astype(float)
        y = sub["dte"].values.astype(float)
        z = sub["iv"].values.astype(float)

        xi, yi, zi = _interpolate_surface(x, y, z)
        if xi is None:
            continue

        any_data = True
        fig.add_trace(go.Surface(
            x=xi, y=yi, z=zi,
            colorscale=cscale,
            opacity=0.80 if right == "B" else 1.0,
            name=name,
            showscale=True,
            colorbar=dict(title="IV %", thickness=15, len=0.6),
        ))

    if not any_data:
        fig.add_annotation(text="Geen data beschikbaar", showarrow=False,
                           font=dict(size=18), xref="paper", yref="paper", x=0.5, y=0.5)

    title = {"C": "Calls", "P": "Puts", "B": "Calls + Puts"}[right]
    fig.update_layout(
        **_base_layout(height=650),
        title=f"Vol Surface — {title}  [{x_mode}]",
        scene=dict(
            xaxis_title=xl,
            yaxis_title="DTE (dagen)",
            zaxis_title="Implied Volatility (%)",
            camera=dict(eye=dict(x=1.6, y=-1.5, z=1.0)),
        ),
    )
    return fig.to_html(include_plotlyjs=_PLOTLY_CDN, full_html=True)


def build_smile_lines(
    df: pd.DataFrame, x_mode: str = "moneyness", right: str = "C"
) -> str:
    """Return full HTML with per-expiry smile curves."""
    fig = go.Figure()
    xl  = X_LABEL[x_mode]

    sub = _filter_right(df, right)
    if x_mode == "delta":
        sub = sub.dropna(subset=["delta"])

    if sub.empty:
        fig.add_annotation(text="Geen data beschikbaar", showarrow=False,
                           font=dict(size=18), xref="paper", yref="paper", x=0.5, y=0.5)
        return fig.to_html(include_plotlyjs=_PLOTLY_CDN, full_html=True)

    expiries = sorted(sub["expiry"].unique())
    rights_to_plot = (
        [("C", "solid", _CALL_COLORS), ("P", "dash", _PUT_COLORS)]
        if right == "B"
        else [(right, "solid", _CALL_COLORS)]
    )

    for i, exp in enumerate(expiries):
        sub_e = sub[sub["expiry"] == exp].sort_values("strike")
        dte   = int(sub_e["dte"].iloc[0])
        label = f"{exp[:4]}-{exp[4:6]}-{exp[6:]} ({dte}d)"

        for r, dash, palette in rights_to_plot:
            sub_r = sub_e[sub_e["right"] == r]
            if sub_r.empty:
                continue
            x = _x_col(sub_r, x_mode)
            suffix = " C" if r == "C" else " P"
            fig.add_trace(go.Scatter(
                x=x, y=sub_r["iv"],
                mode="lines+markers",
                name=label + (suffix if right == "B" else ""),
                line=dict(color=palette[i % len(palette)], dash=dash, width=2),
                marker=dict(size=5),
                hovertemplate=(
                    f"{xl}: %{{x:.4f}}<br>IV: %{{y:.2f}}%<br>{label}{suffix}<extra></extra>"
                ),
            ))

    fig.update_layout(
        **_base_layout(height=580),
        title="Volatility Smile per Expiry",
        xaxis_title=xl,
        yaxis_title="Implied Volatility (%)",
        hovermode="x unified",
        legend=dict(font=dict(size=10), groupclick="toggleitem"),
    )
    return fig.to_html(include_plotlyjs=_PLOTLY_CDN, full_html=True)


def build_heatmap(
    df: pd.DataFrame, x_mode: str = "moneyness", right: str = "C"
) -> str:
    """Return full HTML with IV heatmap(s) — one panel per right when right='B'."""
    xl = X_LABEL[x_mode]
    sides = (
        [("C", "Calls"), ("P", "Puts")]
        if right == "B"
        else [(right, "Calls" if right == "C" else "Puts")]
    )
    n_cols = len(sides)
    fig = make_subplots(
        rows=1, cols=n_cols,
        subplot_titles=[s[1] for s in sides],
        shared_yaxes=True,
        horizontal_spacing=0.08,
    )

    any_data = False
    for col_i, (r, _name) in enumerate(sides, start=1):
        sub = _filter_right(df, r)
        if x_mode == "delta":
            sub = sub.dropna(subset=["delta"])
        if sub.empty:
            continue

        x = _x_col(sub, x_mode).values.astype(float)
        y = sub["dte"].values.astype(float)
        z = sub["iv"].values.astype(float)

        xi, yi, zi = _interpolate_surface(x, y, z)
        if xi is None:
            continue

        any_data = True
        z_min = max(0.0, float(z.min()) - 1)
        z_max = float(z.max()) + 1

        fig.add_trace(
            go.Heatmap(
                x=xi, y=yi, z=zi,
                colorscale="RdYlGn_r",
                zmin=z_min, zmax=z_max,
                colorbar=dict(
                    title="IV %", len=0.75, thickness=14,
                    x=1.01 if col_i == n_cols else (0.44 if n_cols > 1 else 1.01),
                ),
                hovertemplate=f"{xl}: %{{x:.4f}}<br>DTE: %{{y}}d<br>IV: %{{z:.2f}}%<extra></extra>",
            ),
            row=1, col=col_i,
        )
        fig.update_xaxes(title_text=xl, row=1, col=col_i)

    if not any_data:
        fig.add_annotation(text="Geen data beschikbaar", showarrow=False,
                           font=dict(size=18), xref="paper", yref="paper", x=0.5, y=0.5)

    fig.update_yaxes(title_text="DTE (dagen)", row=1, col=1)
    fig.update_layout(
        **_base_layout(height=520),
        title=f"IV Heatmap  [{x_mode}]",
    )
    return fig.to_html(include_plotlyjs=_PLOTLY_CDN, full_html=True)
