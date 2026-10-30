"""Portable dashboard presentation preferences; never includes connections or positions."""
from copy import deepcopy
from datetime import date
from portefeuille_viewer.services.asset_dashboard_layout import validate_layout
from portefeuille_viewer.services.asset_dashboard_columns import validate_columns

FORMAT='portefeuille-viewer-dashboard'


def export_preferences(settings):
    return dict(format=FORMAT,version=1,theme=settings.get_asset_dashboard_theme(),
        period=settings.get_asset_dashboard_period(),modes={mode:dict(
            layout=settings.get_asset_dashboard_layout(mode),
            columns=settings.get_asset_dashboard_position_columns(mode)) for mode in ('desktop','laptop')})


def validate_preferences(value):
    if not isinstance(value,dict) or value.get('format')!=FORMAT or value.get('version')!=1:
        raise ValueError('Dit is geen ondersteund dashboardinstellingenbestand')
    theme=value.get('theme')
    if theme not in {'dark','sand'}:
        raise ValueError('Onbekend dashboardthema')
    period=value.get('period')
    if not isinstance(period,dict):raise ValueError('Ongeldige datumselectie')
    start,end=(date.fromisoformat(period[key]) for key in ('start','end'))
    if start>end:raise ValueError('Ongeldige datumselectie')
    modes=value.get('modes')
    if not isinstance(modes,dict) or set(modes)!={'desktop','laptop'}:
        raise ValueError('Desktop- en laptopinstellingen ontbreken')
    clean={}
    for mode,entry in modes.items():
        if not isinstance(entry,dict) or set(entry)!={'layout','columns'}:
            raise ValueError('Ongeldige scherminstellingen')
        clean[mode]=dict(layout=validate_layout(entry['layout']) if entry['layout'] is not None else None,
                        columns=validate_columns(entry['columns']) if entry['columns'] is not None else None)
    return dict(format=FORMAT,version=1,theme=theme,period=dict(start=start.isoformat(),end=end.isoformat()),modes=clean)


def import_preferences(settings,value):
    import json
    clean=validate_preferences(value)  # Validate every field before changing any preference.
    original=settings.config
    replacement=deepcopy(original)
    for section in ('ui','app'):
        if not replacement.has_section(section):replacement.add_section(section)
    replacement.set('ui','asset_dashboard_theme',clean['theme'])
    for key,day in clean['period'].items():replacement.set('app','asset_dashboard_'+key+'_date',day)
    for mode,entry in clean['modes'].items():
        for prefix,field in (('asset_dashboard_layout_','layout'),('asset_dashboard_position_columns_','columns')):
            key=prefix+mode
            if entry[field] is None:replacement.remove_option('ui',key)
            else:replacement.set('ui',key,json.dumps(entry[field],separators=(',',':')))
    settings.config=replacement
    try:settings.save()
    except Exception:
        settings.config=original
        raise
    return clean
