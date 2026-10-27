"""Shared, exact-contract discovery for automatic and manual option resolution."""
from dataclasses import dataclass, field
from datetime import date
import math
import threading

from ibapi.contract import Contract


# Options-only overrides. Never change the symbol used for underlying prices.
OPTION_PRODUCTS = {'EURUSD-FUT': dict(symbol='EUR', sec_type='FOP', exchange='CME', multiplier=125000.0)}


def clean(value):return str(value or '').strip()


def number(value):
    try:
        result=float(value)
        return result if math.isfinite(result) else None
    except (TypeError,ValueError):return None


@dataclass
class ResolveSpec:
    asset: str
    symbol: str
    currency: str
    expiry: date
    strike: float
    right: str
    asset_type: str = ''
    references: list[dict] = field(default_factory=list)
    exchange: str = ''
    trading_class: str = ''
    multiplier: float | None = None

    @property
    def product(self):return OPTION_PRODUCTS.get(self.asset.upper(), {})
    @property
    def option_symbol(self):return self.product.get('symbol',self.symbol)


def reference_map(rows):
    result={}
    for row in rows:
        try:week=int(row.get('opt_week') or 0)
        except (ValueError,TypeError):week=0
        result.setdefault((clean(row.get('asset_rollup')).upper(),week),[]).append(row)
    return result


def references_for(mapping, asset, week):
    rows=mapping.get((asset.upper(),week),[])+ (mapping.get((asset.upper(),0),[]) if week else [])
    unique={}
    for row in rows:
        key=(clean(row.get('opt_exchange')).upper(),clean(row.get('opt_tradingclass')).upper(),number(row.get('opt_multiplier')))
        unique.setdefault(key,row)
    return list(unique.values())


def request_contracts(spec):
    product=spec.product
    kinds=[product['sec_type']] if product else (['FOP'] if spec.asset_type.upper() in ('FUT','FUTURE') else ['OPT'])
    if not spec.asset_type and not product:kinds.append('FOP')
    exchanges=[product['exchange']] if product else list(dict.fromkeys(
        [clean(r.get('opt_exchange')).upper() for r in spec.references if clean(r.get('opt_exchange'))]
        +([spec.exchange.upper()] if spec.exchange else [])))
    classes=list(dict.fromkeys([clean(r.get('opt_tradingclass')) for r in spec.references if clean(r.get('opt_tradingclass'))]
        +([spec.trading_class] if spec.trading_class else [])))
    for kind in kinds:
        routes=exchanges or (['SMART','FTA'] if kind=='OPT' else [])
        for exchange in routes:
            if kind=='FOP' and exchange in ('SMART','FTA') and product:continue
            for tc in ['']+classes:
                c=Contract();c.symbol=spec.option_symbol;c.secType=kind;c.exchange=exchange
                c.currency=spec.currency;c.lastTradeDateOrContractMonth=spec.expiry.strftime('%Y%m%d')
                c.strike=spec.strike;c.right=spec.right
                c.tradingClass=tc
                multiplier=product.get('multiplier')
                if multiplier is None:
                    values={number(r.get('opt_multiplier')) for r in spec.references};values.discard(None)
                    multiplier=next(iter(values)) if len(values)==1 else (spec.multiplier if not values else None)
                if multiplier is not None:c.multiplier=format(multiplier,'.12g')
                yield c


def normalize(detail):
    c=getattr(detail,'contract',detail)
    return dict(conid=int(getattr(c,'conId',0) or 0),local_symbol=clean(getattr(c,'localSymbol','')),
        trading_class=clean(getattr(c,'tradingClass','')),exchange_code=clean(getattr(c,'exchange','')),
        multiplier=number(getattr(c,'multiplier',None)),underlying_symbol=clean(getattr(c,'symbol','')),
        sec_type=clean(getattr(c,'secType','')),last_trade_date=clean(getattr(c,'lastTradeDateOrContractMonth','')),
        strike=number(getattr(c,'strike',None)),right=clean(getattr(c,'right','')),currency=clean(getattr(c,'currency','')))


def valid_candidate(spec, candidate):
    expected=spec.product
    kind=expected.get('sec_type') or ('FOP' if spec.asset_type.upper() in ('FUT','FUTURE')
        else ('OPT' if spec.asset_type else None))
    multipliers={number(r.get('opt_multiplier')) for r in spec.references};multipliers.discard(None)
    if expected:multipliers={expected['multiplier']}
    elif not multipliers and spec.multiplier:multipliers={float(spec.multiplier)}
    return bool(candidate.get('conid',0)>0 and candidate.get('local_symbol') and
        candidate.get('underlying_symbol')==spec.option_symbol and candidate.get('currency')==spec.currency and
        candidate.get('sec_type') in ([kind] if kind else ['OPT','FOP']) and
        candidate.get('last_trade_date','')[:8]==spec.expiry.strftime('%Y%m%d') and
        candidate.get('right')==spec.right and
        candidate.get('strike') is not None and math.isclose(candidate['strike'],spec.strike,rel_tol=0,abs_tol=1e-9) and
        candidate.get('multiplier') is not None and candidate['multiplier']>0 and
        (not multipliers or candidate['multiplier'] in multipliers) and
        (not expected or candidate.get('exchange_code')==expected['exchange']))


@dataclass
class ResolveResult:
    candidates: list[dict] = field(default_factory=list)
    reason: str = 'no_contract_details'
    diagnostics: list[str] = field(default_factory=list)

    @property
    def message(self):
        labels={'no_contract_details':'Geen passend contract gevonden','timeout':'IBKR-contractaanvraag niet volledig beantwoord',
            'ambiguous':'Meerdere passende contracten; kies handmatig','resolved':'Contract gevonden','not_connected':'IBKR niet verbonden'}
        return labels.get(self.reason,self.reason)+(': '+'; '.join(self.diagnostics[-4:]) if self.diagnostics else '')


def resolve(ib, spec, timeout=3.0):
    result=ResolveResult();found={};incomplete=False
    if callable(getattr(ib, 'is_ready', None)) and not ib.is_ready():
        result.reason='not_connected'
        return result
    for contract in request_contracts(spec):
        rows=[];errors=[];done=threading.Event()
        def on_detail(detail, rows=rows):rows.append(detail)
        def on_end(done=done):done.set()
        def on_error(code,message,errors=errors,done=done):
            errors.append(f'IBKR {code}: {message}');done.set()
        try:ib.request_contract_details(contract,on_detail,on_end,on_error=on_error)
        except Exception as error:
            result.diagnostics.append(type(error).__name__+': '+str(error));result.reason='not_connected';return result
        complete=done.wait(timeout)
        label=f'{contract.symbol}/{contract.secType}/{contract.exchange}/{contract.tradingClass or "alle klassen"}'
        if not complete:
            incomplete=True;result.diagnostics.append(label+': timeout');continue
        if errors:
            result.diagnostics.append(label+': '+'; '.join(errors));continue
        accepted=[]
        for detail in rows:
            candidate=normalize(detail)
            if valid_candidate(spec,candidate):found[candidate['conid']]=candidate;accepted.append(candidate)
        if accepted and not contract.tradingClass:
            # Complete, fully specified broad request enumerated all classes on
            # this route. Multiple exact matches must remain a manual choice.
            break
    result.candidates=list(found.values())
    if incomplete:result.reason='timeout'
    elif len(found)==1:result.reason='resolved'
    elif len(found)>1:result.reason='ambiguous'
    return result
