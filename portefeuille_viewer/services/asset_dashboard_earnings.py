"""Read next earnings dates from already stored financial facts. No Yahoo calls."""
from datetime import date, datetime
import json

from portefeuille_viewer.data.stockdata_worker import stockdata_job
from portefeuille_viewer.data.shared_database import connect_stockdata


def _day(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def next_earnings(records, today=None):
    today = today or date.today()
    schedules, publications = {}, {}
    for row in records:
        try:
            body = json.loads(row.get("payload_json") or "{}")
        except (ValueError, TypeError):
            continue
        if body.get("__wyse_envelope__", {}).get("operation") == "delete":
            continue
        asset = str(row.get("subject_key") or "")
        if not asset:
            continue
        value, context = body.get("value"), body.get("context") or {}
        observed = str(row.get("last_seen") or row.get("changed_at") or "")
        source = str(row.get("source") or "")
        if row.get("metric") == "earnings_schedule" and isinstance(value, dict):
            raw_dates = value.get("dates") or [value.get("date_start"), value.get("date_end")]
            dates = sorted({day for raw in raw_dates if (day := _day(raw)) is not None and day >= today})
            # A newer source schedule supersedes old quarter/rolling schedule rows,
            # even when the newest schedule no longer contains a future date.
            item = (observed, dates, source)
            if asset not in schedules or observed > schedules[asset][0]:
                schedules[asset] = item
            elif observed == schedules[asset][0]:
                schedules[asset] = (observed, sorted(set(schedules[asset][1]+dates)), source)
        elif row.get("metric") == "earnings_source_row" and isinstance(value, dict):
            # Never promote an already reported earnings row to a future estimate.
            actual = value.get("Reported EPS", value.get("epsActual"))
            day = _day(context.get("date") or context.get("timestamp_source"))
            if day and day >= today and actual is None:
                publications.setdefault(asset, []).append((day, observed, source))
    result = {}
    for asset in schedules.keys() | publications.keys():
        if asset in schedules:
            observed, dates, source = schedules[asset]
            if not dates:
                continue
            day = dates[0]
        else:
            day, observed, source = min(publications[asset])
        result[asset] = {"date": day.isoformat(), "source": source, "observed": observed}
    return result


@stockdata_job
def load_next_earnings(path):
    """Runs on the existing STOCKDATA owner worker; bounded to two event metrics."""
    with connect_stockdata(path) as conn:
        cur = conn.execute("SELECT subject_key,source,metric,payload_json,last_seen,changed_at "
                           "FROM financial_facts_current WHERE subject_type='asset' "
                           "AND (metric='earnings_schedule' OR metric='earnings_source_row')")
        columns = [column[0] for column in cur.description]
        return next_earnings([dict(zip(columns, row)) for row in cur.fetchall()])
