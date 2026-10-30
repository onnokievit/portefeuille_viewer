"""Versioned, bounded dashboard layout preferences (no database access)."""
BLOCK_IDS = ('payoff', 'indicator', 'payoff_table', 'price', 'result', 'quantity',
             'puts', 'calls', 'holdings', 'test_orders', 'market', 'earnings', 'asset_info')


def validate_layout(value):
    if not isinstance(value, dict) or value.get('version') not in (1, 2, 3, 4, 5, 6):
        raise ValueError('Onbekende indelingsversie')
    blocks = value.get('blocks')
    if not isinstance(blocks, list) or len(blocks) not in (len(BLOCK_IDS)-1, len(BLOCK_IDS)):
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
        if not (0 <= x < 240 and 0 <= y <= 5000 and 40 <= w <= 240 and ((48 if value['version']>=6 else 40 if value['version']>=5 else 18) if block['id']=='asset_info' else 30) <= h <= 800 and x+w <= 240):
            raise ValueError('Blok valt buiten het raster')
        clean.append(dict(id=block['id'], **dimensions))
    for i,a in enumerate(clean):
        for b in clean[i+1:]:
            if a['x'] < b['x']+b['w'] and b['x'] < a['x']+a['w'] and a['y'] < b['y']+b['h'] and b['y'] < a['y']+a['h']:
                raise ValueError('Blokken overlappen')
    if 'asset_info' not in seen:
        clean=add_asset_info(clean)
    if value['version']<6:
        clean=ensure_asset_height(clean)
    if {b['id'] for b in clean}!=set(BLOCK_IDS) or any(b['y']>5000 for b in clean):
        raise ValueError('Onvolledige dashboardindeling')
    return dict(version=6, blocks=clean)


def add_asset_info(blocks):
    blocks=[dict(b) for b in blocks]
    table=next(b for b in blocks if b['id']=='payoff_table')
    position=table['y']+table['h']
    for block in blocks:
        if block['y']>=position:block['y']+=48
    chart=next(b for b in blocks if b['id']=='payoff')
    if chart['y']<position:
        chart.update(x=table['x'],w=table['w'],y=position+48)
    blocks.append(dict(id='asset_info',x=table['x'],y=position,w=table['w'],h=48))
    placed=[]
    for block in sorted(blocks,key=lambda b:(b['y'],b['x'])):
        while True:
            collision=next((b for b in placed if block['x']<b['x']+b['w'] and b['x']<block['x']+block['w'] and block['y']<b['y']+b['h'] and b['y']<block['y']+block['h']),None)
            if collision is None:break
            block['y']=collision['y']+collision['h']
        placed.append(block)
    return blocks


def ensure_asset_height(blocks):
    blocks=[dict(b) for b in blocks]
    info=next(b for b in blocks if b['id']=='asset_info')
    extra=max(0,48-info['h']);end=info['y']+info['h']
    if extra:
        for block in blocks:
            if block is not info and block['y']>=end:block['y']+=extra
        info['h']=48
    return blocks
