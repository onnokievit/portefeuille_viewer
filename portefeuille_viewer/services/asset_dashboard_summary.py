"""Summary badge colours delegated to the existing Single Asset Analyse policy."""
from PySide6.QtGui import QColor


def summary_colors(legacy, asset, row):
    if legacy is None:return {}
    current,previous=row.get('koers'),row.get('koers_prev')
    try:price_delta=float(current)-float(previous) if current is not None and previous is not None else None
    except (ValueError,TypeError):price_delta=None
    colors={'koers':legacy._color_green_red(price_delta),'koers_prev':QColor(221,235,247),
            'pct_change':legacy._color_green_red(row.get('pct_change')),
            'net_change':legacy._color_green_red(row.get('net_change'))}
    for key in ('portfolio_total_waarde_lineair_pct','portfolio_total_waarde_delta_pct'):
        colors[key]=legacy._get_portfolio_value_pct_color(asset,key)
    return {key:value.name() if value is not None else '' for key,value in colors.items()}
