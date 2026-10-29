"""Column proportions for position tables; calls and puts share one definition."""
import math

COUNTS = {'options':16,'stocks':5,'sprinters':9}


def validate_columns(value):
    if not isinstance(value,dict) or value.get('version')!=1 or not isinstance(value.get('tables'),dict):
        raise ValueError('Onbekende kolominstelling')
    tables=value['tables']
    if set(tables)!=set(COUNTS):
        raise ValueError('Onvolledige kolominstellingen')
    result={}
    for kind,count in COUNTS.items():
        weights=tables[kind]
        if not isinstance(weights,list) or len(weights)!=count:
            raise ValueError('Onjuist aantal kolommen')
        if any(type(v) not in (int,float) or not math.isfinite(v) or not 0<v<1 for v in weights):
            raise ValueError('Ongeldige kolombreedte')
        if abs(sum(weights)-1)>.000001:
            raise ValueError('Ongeldige verdeling van de kolommen')
        result[kind]=list(weights)
    return dict(version=1,tables=result)
