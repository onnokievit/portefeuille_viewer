"""Versioned, bounded dashboard layout preferences (no database access)."""
BLOCK_IDS = ('payoff', 'indicator', 'payoff_table', 'price', 'result', 'quantity',
             'puts', 'calls', 'holdings', 'test_orders', 'market', 'earnings')


def validate_layout(value):
    if not isinstance(value, dict) or value.get('version') not in (1, 2, 3):
        raise ValueError('Onbekende indelingsversie')
    blocks = value.get('blocks')
    if not isinstance(blocks, list) or len(blocks) != len(BLOCK_IDS):
        raise ValueError('Onvolledige dashboardindeling')
    seen = set()
    clean = []
    for block in blocks:
        if not isinstance(block, dict) or block.get('id') not in BLOCK_IDS or block['id'] in seen:
            raise ValueError('Onbekend of dubbel blok')
        seen.add(block['id'])
        dimensions = {key: block.get(key) for key in ('x', 'y', 'w', 'h')}
        if any(type(v) is not int for v in dimensions.values()):
            raise ValueError('Ongeldige blokafmetingen')
        if value['version'] == 1:
            dimensions['x'] *= 10
            dimensions['w'] *= 10
        if value['version'] in (1, 2):
            dimensions['y'] *= 10
            dimensions['h'] *= 10
        x,y,w,h = (dimensions[k] for k in ('x','y','w','h'))
        if not (0 <= x < 240 and 0 <= y <= 5000 and 40 <= w <= 240 and 30 <= h <= 800 and x+w <= 240):
            raise ValueError('Blok valt buiten het raster')
        clean.append(dict(id=block['id'], **dimensions))
    for i,a in enumerate(clean):
        for b in clean[i+1:]:
            if a['x'] < b['x']+b['w'] and b['x'] < a['x']+a['w'] and a['y'] < b['y']+b['h'] and b['y'] < a['y']+a['h']:
                raise ValueError('Blokken overlappen')
    return dict(version=3, blocks=clean)
