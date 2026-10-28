"""Bridge to the existing per-asset STOCKDATA settings cache and close-time flush."""
import math

DEFAULT_CONTROLS = dict(step_pct=2., step_tick=.5, shift=0., decimals=2)


def validate_controls(values):
    step,tick,shift,decimals=(float(values[key]) for key in ("step_pct","step_tick","shift","decimals"))
    if not all(math.isfinite(v) for v in (step,tick,shift,decimals)):
        raise ValueError("Ongeldige instelling")
    if not (0<=step<=99.99 and .01<=tick<=99.99 and -9999<=shift<=9999 and 0<=decimals<=6 and decimals.is_integer()):
        raise ValueError("Instelling valt buiten het toegestane bereik")
    return dict(step_pct=round(step,2),step_tick=round(tick,2),shift=round(shift,2),decimals=int(decimals))


class DashboardPayoffControls:
    def __init__(self, legacy_tab):
        self.tab=legacy_tab

    def get(self, asset):
        tab=self.tab;cfg=tab._step_settings_by_asset.get(asset) or {};defaults=tab._step_defaults
        return dict(
            step_pct=min(99.99,max(0.,tab._safe_step_value(cfg.get("step_size"),defaults["step_size"]))),
            step_tick=min(99.99,max(.01,tab._safe_step_tick(cfg.get("step_size_tick"),defaults["step_size_tick"]))),
            shift=round(min(9999.,max(-9999.,tab._safe_chart_shift(cfg.get("chart_shift"),defaults["chart_shift"]))),2),
            decimals=tab._safe_price_decimals(cfg.get("price_decimals"),tab._infer_default_price_decimals(asset)),
        )

    def save(self, asset, values):
        if not asset:
            raise ValueError("Selecteer eerst een asset")
        cfg=validate_controls(values)
        if cfg==self.get(asset):
            return cfg
        self.tab._step_settings_by_asset[asset]=dict(step_size=cfg["step_pct"],step_size_tick=cfg["step_tick"],
            chart_shift=cfg["shift"],price_decimals=cfg["decimals"])
        self.tab._step_settings_dirty=True
        return cfg
