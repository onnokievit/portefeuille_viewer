"""Bounded, session-aware market-data scheduling; no Qt or database dependency.

Only the worker calls step(). IB callbacks and the UI may update/read the
registry concurrently. A requested stream is never counted as confirmed data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from threading import RLock
import time
from zoneinfo import ZoneInfo


DATA_TYPES = {1: "Live", 2: "Frozen", 3: "Delayed", 4: "Delayed frozen"}



@dataclass
class MarketSchedule:
    timezone: str = ""
    intervals: list = field(default_factory=list)
    covered: set = field(default_factory=set)

    @classmethod
    def parse(cls, hours: str, timezone: str):
        aliases = {"EST": "America/New_York", "CST": "America/Chicago",
                   "MET": "Europe/Amsterdam", "Hongkong": "Asia/Hong_Kong"}
        try:
            zone = ZoneInfo(aliases.get(timezone, timezone))
        except (KeyError, ValueError):
            return cls(timezone=timezone)
        result = cls(timezone=zone.key)
        for day in (hours or "").split(";"):
            try:
                date_text, periods = day.split(":", 1)
                base = datetime.strptime(date_text, "%Y%m%d")
                if periods != "CLOSED":
                    for period in periods.split(","):
                        start, end = period.split("-")
                        def point(value):
                            if ":" in value:
                                return datetime.strptime(value, "%Y%m%d:%H%M").replace(tzinfo=zone)
                            return datetime.strptime(date_text + value, "%Y%m%d%H%M").replace(tzinfo=zone)
                        first, last = point(start), point(end)
                        if last <= first:
                            last += timedelta(days=1)
                        result.intervals.append((first.timestamp(), last.timestamp()))
                result.covered.add(base.date())
            except (ValueError, TypeError):
                continue
        return result

    def state(self, now):
        if not self.timezone or not self.covered:
            return "unknown", None
        if any(start <= now < end for start, end in self.intervals):
            return "open", None
        day = datetime.fromtimestamp(now, ZoneInfo(self.timezone)).date()
        if day not in self.covered:
            return "unknown", None
        upcoming = [start for start, _end in self.intervals if start > now]
        return "closed", min(upcoming) if upcoming else None


@dataclass
class Subscription:
    spec: dict
    req_id: int | None = None
    status: str = "waiting"
    requested_at: float = 0
    last_served: float = 0
    last_tick: float = 0
    session_tick: float = 0
    retry_at: float = 0
    failures: int = 0
    data_type: int | None = None
    fields: dict = field(default_factory=dict)
    error: str = ""
    schedule: MarketSchedule = field(default_factory=MarketSchedule)
    schedule_checked: float = 0
    details_pending: float = 0
    details_req_id: int | None = None
    fallback: bool = False


class SubscriptionManager:
    def __init__(self, transport, *, capacity=100, batch_size=10,
                 rotation_seconds=30, stale_seconds=180, clock=time.time):
        self.transport = transport
        self.clock = clock
        self.lock = RLock()
        self.records = {}
        self.sources = {}
        self.by_request = {}
        self.pending_cancels = []
        self.focus = set()
        self.connected = False
        self.capacity = max(1, int(capacity))
        self.effective_capacity = self.capacity
        self.batch_size = max(1, int(batch_size))
        self.rotation_seconds = max(5, float(rotation_seconds))
        self.stale_seconds = max(30, float(stale_seconds))
        self.last_rotation = self.clock()
        self.next_action = 0
        self.block_until = 0

    def configure(self, capacity, batch_size, rotation_seconds, stale_seconds):
        with self.lock:
            self.capacity = max(1, int(capacity))
            self.effective_capacity = self.capacity
            self.batch_size = max(1, int(batch_size))
            self.rotation_seconds = max(5, float(rotation_seconds))
            self.stale_seconds = max(30, float(stale_seconds))

    def set_source(self, name, specs):
        with self.lock:
            self.sources[name] = {spec["key"]: spec for spec in specs}
            wanted = {}
            for source in self.sources.values():
                wanted.update(source)
            for key in list(self.records):
                if key not in wanted:
                    self._release(self.records[key])
                    record = self.records.pop(key)
                    if record.details_req_id is not None:
                        self.transport.forget_details(record.details_req_id)
            for key, spec in wanted.items():
                if key in self.records:
                    self.records[key].spec = spec
                else:
                    self.records[key] = Subscription(spec=dict(spec))

    def set_focus(self, keys):
        with self.lock:
            self.focus = set(keys)

    def reset(self, connected):
        with self.lock:
            self.connected = connected
            self.by_request.clear()
            self.pending_cancels.clear()
            for record in self.records.values():
                record.req_id = None
                record.status = "waiting"
                record.session_tick = 0
                if record.details_req_id is not None:
                    self.transport.forget_details(record.details_req_id)
                record.details_req_id = None
                record.details_pending = 0
            self.last_rotation = self.clock()

    def pause(self, paused):
        with self.lock:
            self.connected = not paused

    def _release(self, record, status="waiting"):
        if record.req_id is not None:
            self.by_request.pop(record.req_id, None)
            self.pending_cancels.append(record.req_id)
        record.req_id = None
        record.session_tick = 0
        record.status = status

    def counts(self):
        """Cheap connection summary; never copy the full registry per tick."""
        with self.lock:
            normal = [r for r in self.records.values() if r.spec["kind"] != "option"]
            options = [r for r in self.records.values() if r.spec["kind"] == "option"]
            return {"desired_subscriptions": len(normal), "desired_option_subscriptions": len(options),
                    "active_subscriptions": sum(r.status == "receiving" for r in normal),
                    "active_option_subscriptions": sum(r.status == "receiving" for r in options)}

    def market_type(self, req_id, data_type):
        with self.lock:
            record = self.records.get(self.by_request.get(req_id))
            if record:
                record.data_type = int(data_type)

    def tick(self, req_id, name, value, *, delayed=False):
        with self.lock:
            record = self.records.get(self.by_request.get(req_id))
            if not record:
                return False
            now = self.clock()
            record.last_tick = record.session_tick = now
            record.status = "receiving"
            record.failures = 0
            record.fields[name] = {"value": value, "received_at": now,
                                   "data_type": 3 if delayed else record.data_type}
            if delayed:
                record.data_type = 3
            return True

    def processed(self, req_id, price, source):
        with self.lock:
            record = self.records.get(self.by_request.get(req_id))
            if record:
                record.fields["display"] = {"value": price, "source": source,
                    "received_at": self.clock(), "data_type": record.data_type}

    def details(self, key, req_id, details):
        with self.lock:
            record = self.records.get(key)
            if not record or record.details_req_id != req_id:
                return
            # Use extended trading hours for shares, contract-specific hours for
            # derivatives. Unknown/expired schedules never imply "closed".
            record.schedule = MarketSchedule.parse(
                str(getattr(details, "tradingHours", "") or ""),
                str(getattr(details, "timeZoneId", "") or ""))
            contract = getattr(details, "contract", None)
            if contract is not None:
                record.spec["description"] = getattr(contract, "localSymbol", "")
                record.spec["resolved_conid"] = getattr(contract, "conId", None)

    def details_end(self, key, req_id):
        with self.lock:
            record = self.records.get(key)
            if record and record.details_req_id == req_id:
                record.details_pending = 0
                record.details_req_id = None

    def error(self, req_id, code, message):
        with self.lock:
            now = self.clock()
            record = self.records.get(self.by_request.get(req_id))
            if code == 100:
                self.block_until = now + 10
            if not record:
                return
            record.error = f"{code}: {message}"
            self.transport.event(f"error request={req_id} instrument={record.spec['symbol']} {record.error}")
            if code == 101:
                occupied = sum(r.req_id is not None for r in self.records.values())
                self.effective_capacity = max(1, min(self.effective_capacity - 1, occupied - 1))
                self._release(record, "rejected")
                record.retry_at = now + self.rotation_seconds
            elif code == 200 and not record.fallback:
                # One bounded contract fallback; the new request uses the same
                # capacity/pacing controls as every other subscription.
                meta = record.spec["meta"]
                if record.spec["kind"] == "option" or meta.get("cid"):
                    record.fallback = True
                    record.schedule_checked = 0
                    self._release(record, "retry")
                    record.retry_at = now + 1
                else:
                    self._reject(record, now)
            elif code in {200, 354, 420, 10168, 10186}:
                self._reject(record, now)
            # 10089/10090 can accompany usable delayed/partial data: retain
            # the stream and display the warning instead of retrying forever.

    def _reject(self, record, now):
        record.failures += 1
        self._release(record, "rejected")
        record.retry_at = now + min(900, 30 * 2 ** min(record.failures, 5))

    def step(self):
        with self.lock:
            now = self.clock()
            if not self.connected or now < self.next_action or now < self.block_until:
                return
            # One network action per 100 ms; callbacks never sleep or send a
            # batch. Cancellations always precede replacement subscriptions.
            self.next_action = now + 0.1
            if self.pending_cancels:
                req_id = self.pending_cancels.pop(0)
                try:
                    self.transport.cancel(req_id)
                except Exception:
                    self.pending_cancels.insert(0, req_id)
                    raise
                return
            records = list(self.records.values())
            eligible = []
            active = []
            for r in records:
                session, _opening = r.schedule.state(now)
                if r.details_pending and now - r.details_pending > 20:
                    self.transport.forget_details(r.details_req_id)
                    r.details_pending = 0
                    r.details_req_id = None
                if session == "closed":
                    if r.req_id is not None:
                        self._release(r, "closed")
                    elif r.status not in {"rejected", "retry"}:
                        r.status = "closed"
                    continue
                if r.req_id is not None:
                    active.append(r)
                    since = r.session_tick or r.requested_at
                    if now - since > self.stale_seconds:
                        r.status = "quiet"
                    # Silence alone is not proof of failure. A bounded probe
                    # releases the slot and later retries through the queue.
                    if now - since > self.stale_seconds * 2:
                        self._release(r, "retry")
                        r.retry_at = now + self.rotation_seconds
                        return
                elif now >= r.retry_at:
                    if r.status not in {"rejected", "retry"}:
                        r.status = "waiting"
                    eligible.append(r)
            if self.pending_cancels:
                return
            if len(active) > self.effective_capacity:
                self._release(min(active, key=lambda r: r.requested_at))
                return
            # Temporary focus preempts one slot, but cannot create a permanent
            # user-defined core. Normal rotation remains fair for all others.
            eligible.sort(key=lambda r: (r.spec["key"] not in self.focus, r.last_served))
            focus_waiting = eligible and eligible[0].spec["key"] in self.focus
            rotation_due = now - self.last_rotation >= self.rotation_seconds
            if eligible and len(active) >= self.effective_capacity and (rotation_due or focus_waiting):
                victims = sorted((r for r in active if r.spec["key"] not in self.focus),
                                 key=lambda r: r.requested_at)
                amount = 1 if focus_waiting and not rotation_due else min(self.batch_size, len(eligible))
                for r in victims[:amount]:
                    self._release(r)
                self.last_rotation = now
                return
            if eligible and len(active) < self.effective_capacity:
                r = eligible[0]
                req_id = self.transport.next_id()
                r.req_id = req_id
                r.requested_at = r.last_served = now
                r.session_tick = 0
                r.status = "requested"
                r.data_type = None
                self.by_request[req_id] = r.spec["key"]
                try:
                    self.transport.start(req_id, r.spec, r.fallback)
                except Exception as exc:
                    self.error(req_id, 200, str(exc))
                return
            # Enrich schedules gradually, at most four requests outstanding.
            pending = sum(bool(r.details_pending) for r in records)
            candidates = [r for r in records if not r.details_pending and
                          (not r.schedule_checked or now - r.schedule_checked > 21600)]
            if pending < 4 and candidates:
                r = min(candidates, key=lambda r: r.schedule_checked)
                r.schedule_checked = r.details_pending = now
                r.details_req_id = self.transport.next_id()
                try:
                    self.transport.details(r.details_req_id, r.spec, r.fallback)
                except Exception:
                    self.details_end(r.spec["key"], r.details_req_id)

    def snapshot(self):
        with self.lock:
            now = self.clock()
            rows = []
            waiting = sorted((r for r in self.records.values() if r.req_id is None
                              and r.schedule.state(now)[0] != "closed"), key=lambda r: r.last_served)
            ranks = {r.spec["key"]: i for i, r in enumerate(waiting)}
            for r in self.records.values():
                session, opening = r.schedule.state(now)
                row = {**r.spec, "req_id": r.req_id, "status": r.status,
                       "requested_at": r.requested_at, "last_tick": r.last_tick,
                       "data_type": DATA_TYPES.get(r.data_type, "Onbekend"),
                       "session": session, "next_open": opening, "error": r.error,
                       "timezone": r.schedule.timezone, "fields": {k: dict(v) for k, v in r.fields.items()}}
                if r.req_id is not None:
                    row["next_turn"] = None
                elif session == "closed":
                    row["next_turn"] = opening
                else:
                    rank = ranks.get(r.spec["key"], 0)
                    row["next_turn"] = max(now, r.retry_at, self.last_rotation +
                        self.rotation_seconds * (1 + rank // min(self.batch_size, self.effective_capacity)))
                rows.append(row)
            return {"capacity": self.capacity, "effective_capacity": self.effective_capacity,
                    "batch_size": self.batch_size, "rotation_seconds": self.rotation_seconds,
                    "stale_seconds": self.stale_seconds, "connected": self.connected,
                    "occupied": sum(r.req_id is not None for r in self.records.values()),
                    "receiving": sum(r.req_id is not None and bool(r.session_tick) for r in self.records.values()),
                    "rows": rows}
