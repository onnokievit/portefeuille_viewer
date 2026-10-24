"""GUI-thread bookkeeping for covered snapshots and shared-domain refreshes."""

LIVE_SOURCES = {
    'aandelen_v2': 'aggregator_snapshot_aandelen_live',
    'opties_open_v2': 'aggregator_snapshot_load_open_opties_from_tx_live',
    'optie_tijdswaarde_v2': 'snapshot_optie_timevalue_live',
    'sprinters_open_v2': 'aggregator_snapshot_open_sprinters_live',
}


class SnapshotCoverage:
    def __init__(self):
        self.covered = {}

    def mark(self, names, store):
        for name in names:
            if name in LIVE_SOURCES:
                self.covered[name] = getattr(store, LIVE_SOURCES[name], None)

    def needs_refresh(self, name, store):
        return name not in self.covered or self.covered[name] is not getattr(store, LIVE_SOURCES[name], None)

    def clear(self):
        self.covered.clear()


def shared_refresh_plan(domains):
    domains = set(domains)
    metadata = 'asset_rollup_data' in domains
    corporate = bool(domains & {'stock_splits', 'option_price_factor_overrides'})
    aggregators = set()
    if metadata or corporate:
        aggregators.update({'aandelen', 'opties', 'sprinters'})
    if 'optie_referentie_data' in domains:
        aggregators.add('opties')
    if 'sprinters_referentie_data' in domains:
        aggregators.add('sprinters')
    # Keep all projection consumers refreshed for shared reference changes;
    # avoid rebuilding unrelated input aggregators and subscription universes.
    return dict(metadata=metadata, aggregators=aggregators,
                portfolio=bool(aggregators), projections=bool(domains),
                subscriptions=metadata,
                option_rebuild=metadata or corporate or bool(domains & {
                    'option_series_master', 'optie_referentie_data', 'historical_data_correct'}),
                catchup='historical_data_correct' in domains)
