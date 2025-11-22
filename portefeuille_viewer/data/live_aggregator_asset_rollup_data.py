import polars as pl
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE

def build_live_aggregator_asset_rollup():
    # Haal basis asset info op
    df_assets = SNAPSHOT_STORE.snapshot_asset_rollup_data
    if df_assets is None or df_assets.height == 0:
        return pl.DataFrame({})

    # Haal posities op
    df_aandelen = SNAPSHOT_STORE.repository_snapshot_aandelen
    df_sprinters = SNAPSHOT_STORE.repository_snapshot_open_sprinters
    df_opties = SNAPSHOT_STORE.repository_snapshot_load_open_opties

    # Bepaal per asset of deze actief is
    def is_active(asset):
        # Aandelen > 100 of < -100
        if df_aandelen is not None and df_aandelen.height > 0:
            pos = df_aandelen.filter(pl.col('asset_rollup') == asset)
            if pos.height > 0 and (pos['aantal_bezit'].max() > 99 or pos['aantal_bezit'].min() < -99):
                return 'active'
        # Sprinters in bezit
        if df_sprinters is not None and df_sprinters.height > 0:
            pos = df_sprinters.filter(pl.col('asset_rollup') == asset)
            if pos.height > 0:
                return 'active'
        # Opties in bezit/short
        if df_opties is not None and df_opties.height > 0:
            pos = df_opties.filter(pl.col('asset_rollup') == asset)
            if pos.height > 0:
                return 'active'
        return 'inactive'

    # Voeg status toe
    df_assets = df_assets.with_columns([
        pl.col('asset_rollup').map_elements(is_active).alias('status')
    ])

    # Je kunt hier ook regio, sector, waarde/groei etc. selecteren
    # Bijvoorbeeld: df_assets.select(['asset_rollup', 'regio', 'sector', 'waarde_groei', 'status'])
    SNAPSHOT_STORE.live_aggregator_asset_rollup_data = df_assets
    return df_assets