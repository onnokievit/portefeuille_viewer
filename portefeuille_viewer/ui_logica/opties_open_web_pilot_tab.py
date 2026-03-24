from __future__ import annotations

import json
import os
from datetime import date, datetime
from decimal import Decimal

import polars as pl
from PySide6.QtCore import QObject, QPoint, QTimer, Slot
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QFileDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from portefeuille_viewer.config.settings_manager import get_settings
from portefeuille_viewer.data.repository import (
    build_uniek_id,
    fetch_open_optie_comments,
    upsert_open_optie_comment,
    update_open_optie_comment_color,
)
from portefeuille_viewer.data.snapshot_store import SNAPSHOT_STORE
from portefeuille_viewer.signals import signals

try:
    from PySide6.QtWebChannel import QWebChannel
    from PySide6.QtWebEngineWidgets import QWebEngineView
except Exception:  # pragma: no cover
    QWebChannel = None
    QWebEngineView = None


class OptiesOpenWebPilotTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._js_ready = False
        self._is_active = False
        self._pending_js_calls: list[tuple[str, object]] = []
        self._needs_snapshot = False
        self._needs_patch = False
        self._needs_meta = False
        self._active_render_ms = max(100, int(os.getenv("UI_WEB_ACTIVE_RENDER_MS", "1000")))
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(self._active_render_ms)
        self._render_timer.timeout.connect(self._flush_scheduled_render)
        self._row_id_to_uniek_id: dict[str, str] = {}
        self._legacy_cols = [
            "itm",
            "broker",
            "asset_rollup",
            "optie_call_put",
            "optie_exp_date",
            "optie_strike",
            "Koers",
            "afwijking_pct",
            "koers_prev",
            "pct_change_prev",
            "aantal_bezit",
            "premie",
            "totaal_resultaat_optie",
            "time_value",
            "optie_comment",
            "optie_comment_updated_at",
        ]

        layout = QVBoxLayout(self)
        if QWebEngineView is None:
            layout.addWidget(QLabel("QtWebEngine niet beschikbaar in deze runtime."))
            return
        self.web = QWebEngineView(self)
        self.web.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.web)
        if QWebChannel is not None:
            self.channel = QWebChannel(self.web.page())
            self.bridge = _OptiesOpenWebBridge(self)
            self.channel.registerObject("optiesBridge", self.bridge)
            self.web.page().setWebChannel(self.channel)
        self.web.loadFinished.connect(self._on_web_loaded)
        self.web.setHtml(self._html_template())
        signals.snapshotUpdated.connect(self._on_snapshot_updated)

    def _on_web_loaded(self, ok: bool):
        self._js_ready = bool(ok)
        if not self._js_ready:
            return
        for func_name, payload in self._pending_js_calls:
            self._run_js(func_name, payload)
        self._pending_js_calls.clear()
        self._publish_full_snapshot()
        self._publish_meta()
        self._needs_snapshot = False
        self._needs_patch = False
        self._needs_meta = False

    def _on_snapshot_updated(self, snapshot_key: str):
        if snapshot_key == "snapshot_opties_open_projection_v2":
            self._needs_snapshot = True
            self._needs_patch = False
            self._schedule_render()
        elif snapshot_key == "snapshot_opties_open_projection_v2_patch":
            self._needs_patch = True
            self._schedule_render()
        elif snapshot_key == "snapshot_opties_open_projection_v2_meta":
            self._needs_meta = True
            self._schedule_render()

    def set_active(self, active: bool):
        self._is_active = bool(active)
        if not self._is_active:
            self._render_timer.stop()
            return
        if not self._js_ready:
            return
        self._needs_snapshot = True
        self._needs_patch = False
        self._needs_meta = True
        self._render_timer.stop()
        self._flush_scheduled_render()

    def _schedule_render(self):
        if not self._is_active or not self._js_ready:
            return
        if not self._render_timer.isActive():
            self._render_timer.start()

    def _flush_scheduled_render(self):
        if not self._is_active or not self._js_ready:
            return
        if self._needs_snapshot:
            self._publish_full_snapshot()
            self._needs_snapshot = False
            self._needs_patch = False
        elif self._needs_patch:
            # Re-render full because web view uses a legacy-shaped transformed rowset.
            self._publish_full_snapshot()
            self._needs_patch = False
        if self._needs_meta:
            self._publish_meta()
            self._needs_meta = False

    def _publish_full_snapshot(self):
        df = getattr(SNAPSHOT_STORE, "snapshot_opties_open_projection_v2", None)
        if df is None:
            return
        try:
            rows, cols = self._build_legacy_rows(df)
        except Exception:
            rows = []
            cols = list(self._legacy_cols)
        self._call_js("renderSnapshot", {"rows": rows, "cols": cols})

    def _publish_meta(self):
        meta = getattr(SNAPSHOT_STORE, "snapshot_opties_open_projection_v2_meta", None)
        if not isinstance(meta, dict):
            return
        out = dict(meta)
        tv_meta = getattr(SNAPSHOT_STORE, "snapshot_optie_timevalue_meta", None)
        unresolved_count = 0
        unresolved_series = []
        try:
            if hasattr(tv_meta, "is_empty") and not tv_meta.is_empty():
                row = tv_meta.to_dicts()[0]
                unresolved_count = int(row.get("unresolved_count") or 0)
                raw = row.get("unresolved_series")
                if isinstance(raw, str) and raw.strip():
                    unresolved_series = json.loads(raw)
                elif isinstance(raw, list):
                    unresolved_series = raw
        except Exception:
            unresolved_count = 0
            unresolved_series = []
        out["unresolved_count"] = unresolved_count
        out["unresolved_series"] = unresolved_series
        self._call_js("renderMeta", out)

    def _build_legacy_rows(self, df: pl.DataFrame) -> tuple[list[dict], list[str]]:
        if df is None or df.is_empty():
            self._row_id_to_uniek_id = {}
            return [], list(self._legacy_cols)

        out = df.clone()
        if "itm" not in out.columns and "ITM_OTM" in out.columns:
            out = out.with_columns(
                pl.when(pl.col("ITM_OTM").cast(pl.Int64, strict=False) != 0)
                .then(pl.lit("ITM"))
                .otherwise(pl.lit("OTM"))
                .alias("itm")
            )
        if "aantal_bezit" not in out.columns and "SomVantransactie_aantal" in out.columns:
            out = out.with_columns(pl.col("SomVantransactie_aantal").alias("aantal_bezit"))
        if "premie" not in out.columns and "SomVantransactie_euro_totaal" in out.columns:
            out = out.with_columns(pl.col("SomVantransactie_euro_totaal").alias("premie"))
        if "totaal_resultaat_optie" not in out.columns and "opt_total_result" in out.columns:
            out = out.with_columns(pl.col("opt_total_result").alias("totaal_resultaat_optie"))
        if "afwijking_pct" not in out.columns and {"Koers", "optie_strike"}.issubset(set(out.columns)):
            out = out.with_columns(
                (
                    (pl.col("Koers").cast(pl.Float64, strict=False) - pl.col("optie_strike").cast(pl.Float64, strict=False))
                    / pl.col("optie_strike").cast(pl.Float64, strict=False)
                    * 100.0
                ).alias("afwijking_pct")
            )
        if "koers_prev" not in out.columns:
            out = out.with_columns(pl.lit(None).cast(pl.Float64).alias("koers_prev"))
        if "pct_change_prev" not in out.columns:
            out = out.with_columns(pl.lit(None).cast(pl.Float64).alias("pct_change_prev"))

        # Join latest koers_prev from v2-compatible source: historical_close snapshot
        try:
            prev_df = getattr(SNAPSHOT_STORE, "repository_snapshot_historical_close", None)
            if isinstance(prev_df, pl.DataFrame) and not prev_df.is_empty():
                p = prev_df
                if "datum" in p.columns:
                    p = p.with_columns(
                        pl.coalesce(
                            [
                                pl.col("datum").cast(pl.Date, strict=False),
                                pl.col("datum").cast(pl.Utf8).str.strptime(pl.Date, "%Y-%m-%d", strict=False),
                                pl.col("datum").cast(pl.Utf8).str.strptime(pl.Date, "%d/%m/%Y", strict=False),
                            ]
                        ).alias("datum")
                    )
                p = p.filter(pl.col("datum") < date.today())
                latest = (
                    p.sort(["asset_rollup", "datum"])
                    .group_by("asset_rollup")
                    .agg(pl.col("close_price").drop_nulls().last().alias("koers_prev_latest"))
                )
                out = out.drop("koers_prev", strict=False).join(latest, on="asset_rollup", how="left")
                out = out.with_columns(pl.col("koers_prev_latest").alias("koers_prev")).drop("koers_prev_latest")
        except Exception:
            pass

        if {"Koers", "koers_prev"}.issubset(set(out.columns)):
            out = out.with_columns(
                pl.when(
                    pl.col("koers_prev").cast(pl.Float64, strict=False).is_not_null()
                    & (pl.col("koers_prev").cast(pl.Float64, strict=False) != 0)
                )
                .then(
                    (pl.col("Koers").cast(pl.Float64, strict=False) / pl.col("koers_prev").cast(pl.Float64, strict=False))
                    - 1.0
                )
                .otherwise(None)
                .alias("pct_change_prev")
            )

        if "uniek_id" not in out.columns:
            out = out.with_columns(
                pl.struct(["broker", "asset_rollup", "optie_exp_date", "optie_call_put", "optie_strike"])
                .map_elements(
                    lambda s: build_uniek_id(
                        {
                            "broker": s.get("broker"),
                            "asset_rollup": s.get("asset_rollup"),
                            "asset_type": "optie",
                            "optie_exp_date": s.get("optie_exp_date"),
                            "optie_call_put": s.get("optie_call_put"),
                            "optie_strike": s.get("optie_strike"),
                        }
                    ),
                    return_dtype=pl.Utf8,
                )
                .alias("uniek_id")
            )

        if "optie_comment" not in out.columns:
            out = out.with_columns(pl.lit("").alias("optie_comment"))
        if "optie_comment_color" not in out.columns:
            out = out.with_columns(pl.lit("").alias("optie_comment_color"))
        if "optie_comment_textcolor" not in out.columns:
            out = out.with_columns(pl.lit("").alias("optie_comment_textcolor"))
        if "optie_comment_updated_at" not in out.columns:
            out = out.with_columns(pl.lit(None).alias("optie_comment_updated_at"))

        # Attach signed time value per option row from the live timevalue snapshot.
        def _norm_broker(v) -> str:
            return str(v or "").strip().lower()

        def _norm_asset(v) -> str:
            return str(v or "").strip().upper()

        def _norm_cp(v) -> str:
            return str(v or "").strip().lower()

        def _norm_exp(v) -> str:
            if v is None:
                return ""
            if hasattr(v, "isoformat"):
                try:
                    return str(v.isoformat())[:10]
                except Exception:
                    pass
            s = str(v).strip()
            if not s:
                return ""
            if "T" in s:
                s = s.split("T", 1)[0]
            if " " in s and len(s) >= 10:
                s = s[:10]
            if len(s) == 10 and s[4] == "-" and s[7] == "-":
                return s
            if len(s) == 10 and s[2] == "-" and s[5] == "-":
                return f"{s[6:10]}-{s[3:5]}-{s[0:2]}"
            return s

        def _norm_strike(v) -> float:
            try:
                return round(float(v), 6)
            except Exception:
                return 0.0

        tv_lookup: dict[tuple[str, str, str, str, float], tuple[str, float]] = {}
        try:
            tv = getattr(SNAPSHOT_STORE, "snapshot_optie_timevalue_live", None)
            if isinstance(tv, pl.DataFrame) and not tv.is_empty():
                req = {"broker", "asset", "c_p", "exp", "strike", "ccy", "time_total"}
                if req.issubset(set(tv.columns)):
                    for tr in tv.to_dicts():
                        key = (
                            _norm_broker(tr.get("broker")),
                            _norm_asset(tr.get("asset")),
                            _norm_cp(tr.get("c_p")),
                            _norm_exp(tr.get("exp")),
                            _norm_strike(tr.get("strike")),
                        )
                        ccy = str(tr.get("ccy") or "").strip().upper()
                        try:
                            ttot = float(tr.get("time_total") or 0.0)
                        except Exception:
                            ttot = 0.0
                        tv_lookup[key] = (ccy, ttot)
        except Exception:
            tv_lookup = {}


        try:
            ids = [str(x) for x in out["uniek_id"].to_list() if x]
            cdf = fetch_open_optie_comments(ids)
            if cdf is not None and not cdf.is_empty():
                out = out.join(cdf, on="uniek_id", how="left", suffix="_db")
                out = out.with_columns(
                    [
                        pl.coalesce([pl.col("optie_comment_db"), pl.col("optie_comment")]).fill_null("").alias("optie_comment"),
                        pl.coalesce([pl.col("optie_comment_color_db"), pl.col("optie_comment_color")]).fill_null("").alias("optie_comment_color"),
                        pl.coalesce([pl.col("optie_comment_textcolor_db"), pl.col("optie_comment_textcolor")]).fill_null("").alias("optie_comment_textcolor"),
                        pl.coalesce([pl.col("optie_comment_updated_at_db"), pl.col("optie_comment_updated_at")]).alias("optie_comment_updated_at"),
                    ]
                ).drop(
                    [
                        "optie_comment_db",
                        "optie_comment_color_db",
                        "optie_comment_textcolor_db",
                        "optie_comment_updated_at_db",
                    ],
                    strict=False,
                )
        except Exception:
            pass

        select_cols = ["row_id"] + [c for c in self._legacy_cols if c in out.columns] + [
            c for c in ("uniek_id", "optie_comment_color", "optie_comment_textcolor") if c in out.columns
        ]
        out = out.select(select_cols)

        row_map: dict[str, str] = {}
        rows = out.to_dicts()
        for r in rows:
            rid = str(r.get("row_id") or "")
            uid = str(r.get("uniek_id") or "")
            if rid and uid:
                row_map[rid] = uid
            key = (
                _norm_broker(r.get("broker")),
                _norm_asset(r.get("asset_rollup")),
                _norm_cp(r.get("optie_call_put")),
                _norm_exp(r.get("optie_exp_date")),
                _norm_strike(r.get("optie_strike")),
            )
            ccy, ttot = tv_lookup.get(key, ("", 0.0))
            r["timevalue_ccy"] = ccy
            r["timevalue_total_signed"] = ttot
            r["time_value"] = ttot
        self._row_id_to_uniek_id = row_map
        return rows, list(self._legacy_cols)

    def _save_comment_for_row(self, row_id: str, comment: str) -> None:
        rid = str(row_id or "").strip()
        if not rid:
            return
        uid = self._row_id_to_uniek_id.get(rid)
        if not uid:
            return

        existing_color = ""
        existing_text = ""
        try:
            cdf = fetch_open_optie_comments([uid])
            if cdf is not None and not cdf.is_empty():
                row = cdf.row(0, named=True)
                existing_color = str(row.get("optie_comment_color") or "")
                existing_text = str(row.get("optie_comment_textcolor") or "")
        except Exception:
            pass

        upsert_open_optie_comment(
            uniek_id=uid,
            comment=str(comment or ""),
            color=existing_color,
            textcolor=existing_text,
            updated_at=datetime.now(),
        )
        QTimer.singleShot(0, self._publish_full_snapshot)

    def _set_comment_color_for_row(self, row_id: str, color: str, textcolor: str) -> None:
        rid = str(row_id or "").strip()
        if not rid:
            return
        uid = self._row_id_to_uniek_id.get(rid)
        if not uid:
            return
        try:
            cdf = fetch_open_optie_comments([uid])
            has_comment_row = cdf is not None and not cdf.is_empty()
        except Exception:
            has_comment_row = False

        if not has_comment_row:
            # Ensure row exists, then color update can target latest entry.
            upsert_open_optie_comment(
                uniek_id=uid,
                comment="",
                color=str(color or ""),
                textcolor=str(textcolor or ""),
                updated_at=datetime.now(),
            )
        else:
            update_open_optie_comment_color(
                uniek_id=uid,
                color=str(color or ""),
                textcolor=str(textcolor or ""),
            )
        QTimer.singleShot(0, self._publish_full_snapshot)

    def _open_comment_color_menu_for_row(self, row_id: str, x: int, y: int) -> None:
        rid = str(row_id or "").strip()
        if not rid:
            return
        uid = self._row_id_to_uniek_id.get(rid)
        if not uid:
            return

        current_comment = ""
        current_color = ""
        try:
            cdf = fetch_open_optie_comments([uid])
            if cdf is not None and not cdf.is_empty():
                row = cdf.row(0, named=True)
                current_comment = str(row.get("optie_comment") or "")
                current_color = str(row.get("optie_comment_color") or "")
        except Exception:
            pass

        menu = QMenu(self)
        color_defs = get_settings().get_comment_colors() or []
        for _prio, label, bg_hex, _fg_hex in color_defs:
            act = QAction(label, menu)
            act.setData(bg_hex)
            menu.addAction(act)
        menu.addSeparator()
        act_custom = QAction("Kies kleur...", menu)
        menu.addAction(act_custom)

        global_pos = self.web.mapToGlobal(QPoint(int(x), int(y)))
        chosen = menu.exec(global_pos)
        if not chosen:
            return
        if chosen == act_custom:
            color = QColorDialog.getColor(QColor(current_color) if current_color else QColor("#ffffff"), self, "Kies kleur")
            if not color.isValid():
                return
            hexval = color.name()
        else:
            hexval = str(chosen.data() or "")

        fg_by_bg = get_settings().get_comment_color_text_map()
        textcolor = str(fg_by_bg.get(hexval, ""))

        try:
            latest = fetch_open_optie_comments([uid])
            if latest is None or latest.is_empty():
                upsert_open_optie_comment(uid, current_comment, hexval, textcolor, datetime.now())
            else:
                update_open_optie_comment_color(uid, hexval, textcolor)
        finally:
            QTimer.singleShot(0, self._publish_full_snapshot)

    def _call_js(self, func_name: str, payload: object):
        if not hasattr(self, "web"):
            return
        if not self._js_ready:
            self._pending_js_calls.append((func_name, payload))
            return
        self._run_js(func_name, payload)

    def _run_js(self, func_name: str, payload: object):
        js_payload = json.dumps(payload, ensure_ascii=False, default=self._json_default)
        self.web.page().runJavaScript(f"window.{func_name}({js_payload});")

    def _export_snapshot(self):
        df = getattr(SNAPSHOT_STORE, "snapshot_opties_open_projection_v2", None)
        if df is None or (hasattr(df, "is_empty") and df.is_empty()):
            QMessageBox.information(self, "Export", "Geen projection snapshot beschikbaar.")
            return
        fname, _ = QFileDialog.getSaveFileName(
            self,
            "Export Opties Open Projection Snapshot",
            "opties_open_projection_snapshot.xlsx",
            "Excel Files (*.xlsx);;CSV Files (*.csv)",
        )
        if not fname:
            return
        try:
            pdf = df.to_pandas()
            if fname.lower().endswith(".csv"):
                pdf.to_csv(fname, index=False)
            else:
                if not fname.lower().endswith(".xlsx"):
                    fname = f"{fname}.xlsx"
                pdf.to_excel(fname, index=False)
            QMessageBox.information(self, "Export", f"Export voltooid:\n{fname}")
        except Exception as exc:
            QMessageBox.warning(self, "Export mislukt", str(exc))

    @staticmethod
    def _json_default(value):
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        return str(value)

    def _html_template(self) -> str:
        return """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8"/>
    <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
    <style>
      html, body { height:100%; margin:0; padding:0; overflow:hidden; }
      * { box-sizing: border-box; }
      body { font-family: Segoe UI, Arial, sans-serif; padding:12px; background:#f5f6f8; display:flex; flex-direction:column; }
      .meta { margin: 0 0 10px 0; color:#44536b; font-size:12px; }
      .filters { display:flex; gap:8px; margin:0 0 8px 0; flex-wrap:wrap; align-items:center; }
      .filters input:not([type="checkbox"]) { font-size:12px; padding:4px 6px; border:1px solid #c7d1de; border-radius:6px; min-width:150px; }
      .filters button { font-size:12px; padding:4px 8px; border:1px solid #b8c3d3; background:#f4f7fb; border-radius:6px; cursor:pointer; }
      .tv-inline { display:flex; align-items:center; gap:6px; margin-left:4px; }
      .tv-code { font-size:12px; color:#33485f; font-weight:600; min-width:28px; text-align:right; }
      .tv-mini {
        font-size:12px;
        font-weight:700;
        color:#223247;
        background:#eef2f7;
        border:1px solid #c7d1de;
        border-radius:6px;
        padding:4px 8px;
        min-width:110px;
        text-align:right;
        line-height:1.2;
      }
      .search-inline { display:flex; align-items:center; gap:2px; margin-right:12px; }
      .search-inline input { margin-right:0; }
      .filters label.chk {
        display:flex;
        align-items:center;
        gap:2px;
        font-size:12px;
        color:#33485f;
        padding:0;
        margin:0;
        white-space:nowrap;
      }
      .filters label.chk input[type="checkbox"] { margin:0; }
      .unresolved {
        display:none;
        margin: 0 0 8px 0;
        border:1px solid #e1b66b;
        background:#fff8eb;
        border-radius:6px;
        padding:6px 8px;
        font-size:12px;
        color:#6a4a14;
      }
      .unresolved summary { cursor:pointer; font-weight:600; }
      .unresolved ul { margin:6px 0 0 14px; padding:0; }
      .unresolved li { margin:2px 0; }
      .dropdown { position:relative; display:inline-block; }
      .drop-panel { position:absolute; top:30px; left:0; z-index:20; background:#fff; border:1px solid #c7d1de; border-radius:8px; padding:10px; min-width:380px; box-shadow:0 6px 18px rgba(0,0,0,.14); display:none; }
      .drop-panel.open { display:block; }
      .drop-panel .row { display:flex; gap:6px; margin-top:6px; }
      .drop-title { font-size:13px; color:#6a778a; margin-bottom:6px; }
      .drop-list { max-height:240px; overflow:auto; border:1px solid #e2e6ec; border-radius:6px; padding:6px; margin-top:6px; }
      .drop-item { display:flex; gap:6px; align-items:center; font-size:12px; margin:2px 0; }
      .drop-item span { white-space:nowrap; }
      .table-wrap { border:1px solid #d8dde6; border-radius:8px; overflow-y:auto; overflow-x:hidden; background:#fff; flex:1 1 auto; min-height:0; }
      table { width:100%; border-collapse:collapse; font-size:12px; table-layout: fixed; }
      thead th { position: sticky; top: 0; z-index: 2; background:#eef2f7; color:#223247; font-weight:700; border-bottom:1px solid #d8dde6; padding:6px 8px; text-align:left; cursor:pointer; white-space:nowrap; }
      tbody td { border-top:1px solid #eef1f5; padding:4px 8px; white-space:nowrap; overflow: hidden; text-overflow: ellipsis; }
      tbody tr:nth-child(even) { background:#fafbfd; }
      td.num { text-align:right; font-variant-numeric: tabular-nums; }
      td.bg-pos { background:#c6f7c6; }
      td.bg-neg { background:#f7c6c6; }
      td.fg-pos { color:#007800; font-weight:600; }
      td.fg-neg { color:#dc0000; font-weight:600; }
      td.itm-put { background:#ffc8c8; }
      td.itm-call { background:#c8ffc8; }
      tr.row-selected td { outline:1px solid rgba(70,90,120,.35); outline-offset:-1px; }
      td.cell-active { box-shadow: inset 0 0 0 2px rgba(40,120,220,.65); }
      th.sorted-asc::after { content: " \\2191"; }
      th.sorted-desc::after { content: " \\2193"; }
    </style>
  </head>
  <body>
    <div class="meta" id="meta">Opties Projection v- | rows: 0</div>
    <div class="filters">
      <div class="search-inline">
        <input id="f_global" placeholder="Zoek alle kolommen..." />
        <label class="chk"><input id="f_global_in_comment" type="checkbox" />Zoek in comment</label>
      </div>
      <input id="f_asset" placeholder="Filter asset_rollup" />
      <input id="f_broker" placeholder="Filter broker" />
      <div class="dropdown">
        <button id="btn_exp">Expiratie</button>
        <div id="exp_panel" class="drop-panel">
          <div class="drop-title">Filter: optie_exp_date</div>
          <input id="exp_search" placeholder="Zoek datum..." style="width:100%;font-size:12px;padding:4px 6px;border:1px solid #c7d1de;border-radius:6px;" />
          <label class="drop-item" style="margin-top:6px;"><input id="exp_all_cb" type="checkbox" /><span>(Alles selecteren)</span></label>
          <div class="row">
            <button id="exp_ok">OK</button>
            <button id="exp_wissen">Wissen</button>
            <button id="exp_cancel">Cancel</button>
          </div>
          <div id="exp_list" class="drop-list"></div>
        </div>
      </div>
      <button id="btn_clear_filters">Wis filters</button>
      <div class="tv-inline"><span class="tv-code">EUR</span><div class="tv-mini" id="tv_total_eur">0,00</div></div>
      <div class="tv-inline"><span class="tv-code">USD</span><div class="tv-mini" id="tv_total_usd">0,00</div></div>
      <button id="btn_export_snapshot">Export snapshot</button>
    </div>
    <details class="unresolved" id="unresolved_box">
      <summary id="unresolved_summary">Unresolved: 0</summary>
      <ul id="unresolved_list"></ul>
    </details>
    <div class="table-wrap" id="table_wrap" tabindex="0">
      <table id="tbl"><thead><tr id="thead-row"></tr></thead><tbody id="tbody"></tbody></table>
    </div>
    <script>
      const state = { cols: [], rows: new Map(), sortCol: "asset_rollup", sortDir: "asc", hasSnapshot:false, filters:{global:"",asset_rollup:"",broker:""}, includeCommentInGlobal:false, bridge:null, expOptions:[], expSelected:new Set(), expDraft:new Set(), selectedRowId:null, selectedColIdx:0, renderedRowIds:[] };
      function _fmtDate(v){
        if(v===null||v===undefined) return "";
        const s=String(v);
        const m=s.match(/^(\\d{4})-(\\d{2})-(\\d{2})/);
        if(m) return `${m[3]}-${m[2]}-${m[1]}`;
        return s;
      }
      function _canonExp(v){
        if(v===null||v===undefined) return "";
        const s=String(v);
        const m=s.match(/^(\\d{4})-(\\d{2})-(\\d{2})/);
        if(m) return `${m[1]}-${m[2]}-${m[3]}`;
        return s;
      }
      function _dateVariants(v){
        if(v===null||v===undefined) return [];
        const s=String(v);
        const m=s.match(/^(\\d{4})-(\\d{2})-(\\d{2})/);
        if(!m) return [s.toLowerCase()];
        const yyyy=m[1], mm=m[2], dd=m[3];
        return [
          `${dd}-${mm}-${yyyy}`.toLowerCase(),
          `${mm}-${dd}-${yyyy}`.toLowerCase(),
          `${yyyy}-${mm}-${dd}`.toLowerCase(),
          `${dd}-${mm}`.toLowerCase(),
          `${mm}-${dd}`.toLowerCase(),
          `${dd}/${mm}/${yyyy}`.toLowerCase(),
          `${mm}/${dd}/${yyyy}`.toLowerCase(),
          `${dd}/${mm}`.toLowerCase(),
          `${mm}/${dd}`.toLowerCase(),
        ];
      }
      function fmt(v,col){
        if(v===null||v===undefined) return "";
        if(col==="optie_exp_date") return _fmtDate(v);
        if(typeof v==="number") return Number.isFinite(v)?v.toFixed(2):"";
        return String(v);
      }
      function fmtNumber(v, d=2){
        const n=Number(v??0);
        if(!Number.isFinite(n)) return "";
        return n.toLocaleString("nl-NL",{minimumFractionDigits:d, maximumFractionDigits:d});
      }
      function isNum(v){ return typeof v==="number" && Number.isFinite(v); }
      function isITMRow(row){ const itm=row.itm; if(String(itm??"").toUpperCase()==="ITM") return true; const flag=row.ITM_OTM; return isNum(flag) && Number(flag)!==0; }
      function callPut(row){ return String(row.optie_call_put??"").toLowerCase(); }
      function startInlineCommentEdit(td, row, seedText=null){
        if(!td) return;
        const original = String(row.optie_comment ?? "");
        const input = document.createElement("input");
        input.type = "text";
        input.value = (seedText===null || seedText===undefined) ? original : String(seedText);
        input.style.width = "100%";
        input.style.border = "1px solid #5f8dd3";
        input.style.borderRadius = "4px";
        input.style.fontSize = "12px";
        input.style.padding = "2px 4px";
        input.style.background = "#fff";
        input.style.color = "#000";
        td.innerHTML = "";
        td.appendChild(input);
        input.focus();
        input.select();

        let done = false;
        const finish = (save) => {
          if(done) return;
          done = true;
          const next = input.value ?? "";
          if(save && state.bridge && state.bridge.saveComment){
            state.bridge.saveComment(String(row.row_id || ""), String(next));
            // Optimistic local update so row/cell state remains consistent
            // even before the next projection patch arrives.
            row.optie_comment = String(next);
          } else {
            row.optie_comment = String(original);
          }
          const rid = String(row.row_id || "");
          state.selectedRowId = rid || state.selectedRowId;
          state.selectedColIdx = Math.max(0, state.cols.indexOf("optie_comment"));
          renderBody();
          // Return keyboard navigation focus to the table after edit.
          setTimeout(() => {
            const wrap = document.getElementById("table_wrap");
            if(wrap){
              wrap.focus();
              _activeCellEl()?.scrollIntoView({block:"nearest", inline:"nearest"});
            }
          }, 0);
        };
        input.addEventListener("keydown", (e) => {
          if(e.key === "Enter"){
            e.preventDefault();
            finish(true);
          } else if(e.key === "Escape"){
            e.preventDefault();
            finish(false);
          }
        });
        input.addEventListener("blur", () => finish(true));
      }
      function cellClasses(row,col,val){ const out=[]; const signCols=new Set(["totaal_resultaat_optie","pct_change_prev","afwijking_pct"]); if(signCols.has(col) && isNum(val)){ if(val>0){ out.push("bg-pos","fg-pos"); } else if(val<0){ out.push("bg-neg","fg-neg"); } } const itmCols=new Set(["itm","broker","asset_rollup","optie_call_put","optie_strike","optie_exp_date"]); if(itmCols.has(col) && isITMRow(row)){ const cp=callPut(row); if(cp==="put") out.push("itm-put"); else if(cp==="call") out.push("itm-call"); } return out.join(" "); }
      function compareRows(a,b,col,dir){ const av=a[col], bv=b[col]; let c=0; if(isNum(av)&&isNum(bv)) c=av-bv; else c=String(av??"").localeCompare(String(bv??"")); return dir==="asc"?c:-c; }
      function contains(h,n){ if(!n) return true; return String(h??"").toLowerCase().includes(String(n).toLowerCase()); }
      function globalMatch(row, raw){
        if(!raw) return true;
        const terms = String(raw).split(",").map(t=>t.trim().toLowerCase()).filter(Boolean);
        if(terms.length===0) return true;
        for(const term of terms){
          let termHit = false;
          for(const c of state.cols){
            if(c==="optie_comment" && !state.includeCommentInGlobal) continue;
            if(c==="optie_exp_date"){
              const variants = _dateVariants(row[c]);
              if(variants.some(x=>x.includes(term))){ termHit = true; break; }
            } else if(String(row[c]??"").toLowerCase().includes(term)){ termHit = true; break; }
          }
          if(!termHit) return false; // AND over terms
        }
        return true;
      }
      function visibleRows(){ const rows=Array.from(state.rows.values()); return rows.filter(r=>{ if(!contains(r.asset_rollup,state.filters.asset_rollup)) return false; if(!contains(r.broker,state.filters.broker)) return false; if(state.expSelected.size>0){ const d=_canonExp(r.optie_exp_date); if(!state.expSelected.has(d)) return false; } if(!globalMatch(r,state.filters.global)) return false; return true;});}
      const WIDTHS = {
        itm:52, broker:85, asset_rollup:95, optie_call_put:48, optie_exp_date:95,
        optie_strike:70, Koers:70, koers_prev:70, pct_change_prev:82, afwijking_pct:82,
        aantal_bezit:78, premie:88, totaal_resultaat_optie:100, optie_comment_updated_at:170
      };
      function _calcWidths(){
        const wrap=document.querySelector('.table-wrap');
        const viewport=(wrap && wrap.clientWidth)?wrap.clientWidth:1600;
        const gap = 24;
        const minComment = 120;
        let totalFixed = state.cols
          .filter(c=>c!=="optie_comment")
          .reduce((acc,c)=>acc+(WIDTHS[c]||90),0);
        let available = Math.max(240, viewport-gap);
        let comment = Math.max(minComment, available-totalFixed);
        let over = (totalFixed + comment) - available;
        const out = {};
        if(over > 0){
          const shrinkable = state.cols.filter(c=>c!=="optie_comment");
          const pool = shrinkable.reduce((acc,c)=>acc+(WIDTHS[c]||90),0);
          const ratio = pool > 0 ? Math.max(0.55, (pool - over) / pool) : 1.0;
          for(const c of shrinkable){
            const base = (WIDTHS[c]||90);
            out[c] = Math.max(42, Math.floor(base * ratio));
          }
          totalFixed = shrinkable.reduce((acc,c)=>acc+(out[c]||0),0);
          comment = Math.max(80, available-totalFixed);
        } else {
          for(const c of state.cols){
            if(c!=="optie_comment") out[c] = (WIDTHS[c]||90);
          }
        }
        out.optie_comment = Math.max(80, comment);
        return out;
      }
      function renderHeader(){ const tr=document.getElementById("thead-row"); tr.innerHTML=""; const W=_calcWidths(); state.cols.forEach(col=>{ const th=document.createElement("th"); th.textContent=col; const w=W[col]||90; th.style.width=w+"px"; th.style.minWidth=w+"px"; th.style.maxWidth=w+"px"; if(col===state.sortCol) th.className=state.sortDir==="asc"?"sorted-asc":"sorted-desc"; th.onclick=()=>{ if(state.sortCol===col) state.sortDir=state.sortDir==="asc"?"desc":"asc"; else {state.sortCol=col; state.sortDir="asc";} renderHeader(); renderBody(); }; tr.appendChild(th); }); }
      function sortedRows(){ const rows=visibleRows(); rows.sort((a,b)=>compareRows(a,b,state.sortCol,state.sortDir)); return rows; }
      function renderBody(){
        const body=document.getElementById("tbody");
        body.innerHTML="";
        const rows=sortedRows();
        state.renderedRowIds = rows.map(r=>String(r.row_id||""));
        if(state.selectedRowId && !state.renderedRowIds.includes(state.selectedRowId)){
          state.selectedRowId = null;
        }
        const W=_calcWidths();
        for(const row of rows){
          const rowId = String(row.row_id??"");
          const tr=document.createElement("tr");
          tr.id="r_"+rowId;
          if(state.selectedRowId===rowId) tr.classList.add("row-selected");
          for(let colIdx=0; colIdx<state.cols.length; colIdx++){
            const col=state.cols[colIdx];
            const td=document.createElement("td");
            td.id="c_"+rowId+"_"+col;
            const v=row[col];
            td.textContent=fmt(v,col);
            const w=W[col]||90;
            td.style.width=w+"px"; td.style.minWidth=w+"px"; td.style.maxWidth=w+"px";
            if(isNum(v)) td.classList.add("num");
            const cc=cellClasses(row,col,v);
            if(cc) td.className=(td.className?td.className+" ":"")+cc;
            if(state.selectedRowId===rowId && state.selectedColIdx===colIdx){
              td.classList.add("cell-active");
            }
            td.onclick=(ev)=>{
              state.selectedRowId=rowId;
              state.selectedColIdx=colIdx;
              document.getElementById("table_wrap")?.focus();
              renderBody();
              if(col==="optie_comment" && ev && ev.detail>=2){
                const active = _activeCellEl();
                if(active) startInlineCommentEdit(active, row);
              }
            };
            if(col==="optie_comment"){
              const bg=row.optie_comment_color||"";
              const fg=row.optie_comment_textcolor||"";
              if(bg) td.style.background=bg;
              if(fg) td.style.color=fg;
              td.ondblclick=()=>startInlineCommentEdit(td, row);
              td.oncontextmenu=(e)=>{ e.preventDefault(); if(state.bridge && state.bridge.openCommentColorMenu){ state.bridge.openCommentColorMenu(String(row.row_id||""), e.clientX||0, e.clientY||0); } };
            }
            tr.appendChild(td);
          }
          body.appendChild(tr);
        }
        renderTimevalueSummary(rows);
      }
      function renderTimevalueSummary(rows){
        let eur=0.0, usd=0.0;
        for(const r of (rows||[])){
          const ccy = String(r.timevalue_ccy || r.ccy || "").toUpperCase();
          const vRaw = Number(r.timevalue_total_signed ?? r.time_value ?? 0);
          const v = Number.isFinite(vRaw) ? vRaw : 0.0;
          if(ccy==="EUR") eur += v;
          else if(ccy==="USD") usd += v;
        }
        const e=document.getElementById("tv_total_eur");
        const u=document.getElementById("tv_total_usd");
        if(e) e.textContent = fmtNumber(eur,2);
        if(u) u.textContent = fmtNumber(usd,2);
      }
      function _activeCellEl(){
        if(!state.selectedRowId || state.cols.length===0) return null;
        const col = state.cols[Math.max(0, Math.min(state.selectedColIdx, state.cols.length-1))];
        return document.getElementById("c_"+state.selectedRowId+"_"+col);
      }
      function _ensureSelection(){
        if(!state.selectedRowId && state.renderedRowIds.length>0){
          state.selectedRowId = state.renderedRowIds[0];
          state.selectedColIdx = Math.max(0, Math.min(state.selectedColIdx, state.cols.length-1));
        }
      }
      function _onTableKeyDown(e){
        const tag = (document.activeElement?.tagName || "").toLowerCase();
        if(tag === "input" || tag === "textarea") return;
        if(state.renderedRowIds.length===0 || state.cols.length===0) return;
        _ensureSelection();
        const rowIdx = Math.max(0, state.renderedRowIds.indexOf(state.selectedRowId));
        const colIdx = Math.max(0, Math.min(state.selectedColIdx, state.cols.length-1));
        if(["ArrowUp","ArrowDown","ArrowLeft","ArrowRight","Enter"].includes(e.key)){
          e.preventDefault();
        }
        if(e.key==="ArrowUp"){
          state.selectedRowId = state.renderedRowIds[Math.max(0,rowIdx-1)];
          renderBody();
          _activeCellEl()?.scrollIntoView({block:"nearest", inline:"nearest"});
          return;
        }
        if(e.key==="ArrowDown"){
          state.selectedRowId = state.renderedRowIds[Math.min(state.renderedRowIds.length-1,rowIdx+1)];
          renderBody();
          _activeCellEl()?.scrollIntoView({block:"nearest", inline:"nearest"});
          return;
        }
        if(e.key==="ArrowLeft"){
          state.selectedColIdx = Math.max(0,colIdx-1);
          renderBody();
          _activeCellEl()?.scrollIntoView({block:"nearest", inline:"nearest"});
          return;
        }
        if(e.key==="ArrowRight"){
          state.selectedColIdx = Math.min(state.cols.length-1,colIdx+1);
          renderBody();
          _activeCellEl()?.scrollIntoView({block:"nearest", inline:"nearest"});
          return;
        }
        const col = state.cols[colIdx];
        if(col!=="optie_comment") return;
        const row = state.rows.get(state.selectedRowId);
        if(!row) return;
        if(e.key==="Enter"){
          const td = _activeCellEl();
          if(td) startInlineCommentEdit(td, row);
          return;
        }
        if(e.key.length===1 && !e.ctrlKey && !e.metaKey && !e.altKey){
          e.preventDefault();
          const td = _activeCellEl();
          if(td) startInlineCommentEdit(td, row, e.key);
        }
      }
      function _renderExpList(){
        const q=(document.getElementById("exp_search")?.value||"").toLowerCase();
        const host=document.getElementById("exp_list");
        const allCb=document.getElementById("exp_all_cb");
        if(!host) return;
        host.innerHTML="";
        const opts=state.expOptions.filter(x=>!q || x.toLowerCase().includes(q));
        for(const v of opts){
          const row=document.createElement("label");
          row.className="drop-item";
          const cb=document.createElement("input");
          cb.type="checkbox";
          cb.checked=state.expDraft.has(v);
          cb.addEventListener("change",()=>{ if(cb.checked) state.expDraft.add(v); else state.expDraft.delete(v); _syncAllCb(); });
          const txt=document.createElement("span");
          txt.textContent=v;
          row.appendChild(cb); row.appendChild(txt);
          host.appendChild(row);
        }
        if(allCb){
          allCb.checked = state.expDraft.size>0 && state.expDraft.size===state.expOptions.length;
          allCb.indeterminate = state.expDraft.size>0 && state.expDraft.size<state.expOptions.length;
        }
      }
      function _syncAllCb(){
        const allCb=document.getElementById("exp_all_cb");
        if(!allCb) return;
        allCb.checked = state.expDraft.size>0 && state.expDraft.size===state.expOptions.length;
        allCb.indeterminate = state.expDraft.size>0 && state.expDraft.size<state.expOptions.length;
      }
      function _syncExpButton(){
        const btn=document.getElementById("btn_exp");
        if(!btn) return;
        if(state.expSelected.size===0) btn.textContent="Expiratie";
        else btn.textContent=`Expiratie (${state.expSelected.size})`;
      }
      function bindFilters(){ const map=[["f_global","global"],["f_asset","asset_rollup"],["f_broker","broker"]]; for(const [id,key] of map){ const el=document.getElementById(id); if(!el) continue; el.addEventListener("input",()=>{state.filters[key]=el.value||""; renderBody();}); }
        document.getElementById("f_global_in_comment")?.addEventListener("change",(e)=>{ state.includeCommentInGlobal = !!e.target.checked; renderBody(); });
        const btn=document.getElementById("btn_exp"), panel=document.getElementById("exp_panel");
        btn?.addEventListener("click",(e)=>{ e.preventDefault(); if(!panel) return; const opening=!panel.classList.contains("open"); panel.classList.toggle("open"); if(opening){ state.expDraft = new Set(Array.from(state.expSelected)); _renderExpList(); } });
        document.getElementById("exp_search")?.addEventListener("input",()=>_renderExpList());
        document.getElementById("exp_all_cb")?.addEventListener("change",(e)=>{ if(e.target.checked){ state.expDraft = new Set(state.expOptions); } else { state.expDraft = new Set(); } _renderExpList(); });
        document.getElementById("exp_ok")?.addEventListener("click",(e)=>{ e.preventDefault(); state.expSelected = new Set(Array.from(state.expDraft)); panel?.classList.remove("open"); _syncExpButton(); renderBody(); });
        document.getElementById("exp_wissen")?.addEventListener("click",(e)=>{ e.preventDefault(); state.expDraft = new Set(); state.expSelected = new Set(); panel?.classList.remove("open"); _syncExpButton(); renderBody(); });
        document.getElementById("exp_cancel")?.addEventListener("click",(e)=>{ e.preventDefault(); state.expDraft = new Set(Array.from(state.expSelected)); panel?.classList.remove("open"); });
        document.addEventListener("click",(e)=>{ if(!panel) return; const wrap=e.target?.closest(".dropdown"); if(!wrap){ state.expDraft = new Set(Array.from(state.expSelected)); panel.classList.remove("open"); } });
        const clear=document.getElementById("btn_clear_filters"); if(clear){ clear.addEventListener("click",()=>{ for(const [id,key] of map){ const el=document.getElementById(id); if(el) el.value=""; state.filters[key]=""; } const cb=document.getElementById("f_global_in_comment"); if(cb){ cb.checked=false; } state.includeCommentInGlobal=false; state.expSelected = new Set(); state.expDraft = new Set(); _syncExpButton(); renderBody();});}}
      function bindActions(){
        const btn=document.getElementById("btn_export_snapshot");
        if(btn && state.bridge && state.bridge.exportSnapshot){
          btn.addEventListener("click",()=>state.bridge.exportSnapshot());
        }
        document.getElementById("table_wrap")?.addEventListener("keydown", _onTableKeyDown);
      }
      window.renderMeta = function(meta){
        const el=document.getElementById("meta"); if(!el||!meta) return;
        const v=meta.version??"-"; const r=meta.rows??0; const c=meta.changes??0; const u=meta.updated_at??"-"; const reason=meta.reason??"-";
        const m=meta.metrics||{}; const ml=m.last||{}; const ms=m.summary||{};
        const txt=`Opties Projection v${v} | rows:${r} | changes:${c} | updated:${u} | reason:${reason} | perf rec:${Number(ml.recompute_ms??0).toFixed(1)}ms pub:${Number(ml.publish_ms??0).toFixed(1)}ms tot:${Number(ml.total_ms??0).toFixed(1)}ms p95:${Number(ms.total_ms_p95??0).toFixed(1)}ms`;
        el.textContent=txt;
        const box=document.getElementById("unresolved_box");
        const sum=document.getElementById("unresolved_summary");
        const list=document.getElementById("unresolved_list");
        const items=Array.isArray(meta.unresolved_series)?meta.unresolved_series:[];
        const cnt=Number(meta.unresolved_count??items.length??0);
        if(!box||!sum||!list){ return; }
        if(cnt<=0){ box.style.display="none"; list.innerHTML=""; return; }
        box.style.display="block";
        sum.textContent=`Unresolved optie series: ${cnt}`;
        list.innerHTML="";
        for(const it of items){
          const li=document.createElement("li");
          const asset=String(it.asset||"");
          const exp=String(it.exp||"");
          const cp=String(it.c_p||"");
          const strike=String(it.strike??"");
          const ccy=String(it.ccy||"");
          const reasonTxt=String(it.reason||"");
          const hint=String(it.hint||"");
          li.textContent = `${asset} ${exp} ${cp} ${strike} ${ccy} | ${reasonTxt}${hint ? " | "+hint : ""}`;
          list.appendChild(li);
        }
      };
      window.renderSnapshot = function(payload){ const rows=(payload&&payload.rows)?payload.rows:[]; state.rows.clear(); if(rows.length===0){ state.cols=[]; state.hasSnapshot=false; state.expOptions=[]; state.expSelected=new Set(); state.expDraft=new Set(); state.selectedRowId=null; state.selectedColIdx=0; _syncExpButton(); renderHeader(); renderBody(); renderTimevalueSummary([]); return; } for(const row of rows){ if(!row||!row.row_id) continue; state.rows.set(String(row.row_id), row); } const payloadCols=(payload&&Array.isArray(payload.cols))?payload.cols:[]; state.cols=payloadCols.length?payloadCols:["itm","broker","asset_rollup","optie_call_put","optie_exp_date","optie_strike","Koers","afwijking_pct","koers_prev","pct_change_prev","aantal_bezit","premie","totaal_resultaat_optie","time_value","optie_comment","optie_comment_updated_at"]; if(!state.cols.includes(state.sortCol)) state.sortCol=state.cols.includes("asset_rollup")?"asset_rollup":state.cols[0]; const keep=state.expSelected; state.expOptions=Array.from(new Set(Array.from(state.rows.values()).map(r=>_canonExp(r.optie_exp_date)).filter(Boolean))).sort(); state.expSelected=new Set(Array.from(keep).filter(v=>state.expOptions.includes(v))); state.expDraft = new Set(Array.from(state.expSelected)); state.hasSnapshot=true; _syncExpButton(); _renderExpList(); _ensureSelection(); renderHeader(); renderBody(); };
      window.applyPatch = function(payload){};
      if (window.qt && window.QWebChannel) { new QWebChannel(qt.webChannelTransport, function(channel) { state.bridge = channel.objects.optiesBridge || null; }); }
      window.addEventListener("resize", () => { if(state.hasSnapshot){ renderHeader(); renderBody(); }});
      bindFilters();
      bindActions();
    </script>
  </body>
</html>
"""


class _OptiesOpenWebBridge(QObject):
    def __init__(self, tab: OptiesOpenWebPilotTab):
        super().__init__(tab)
        self._tab = tab

    @Slot(str, str)
    def saveComment(self, row_id: str, comment: str) -> None:
        self._tab._save_comment_for_row(row_id, comment)

    @Slot()
    def exportSnapshot(self) -> None:
        self._tab._export_snapshot()

    @Slot(str, int, int)
    def openCommentColorMenu(self, row_id: str, x: int, y: int) -> None:
        self._tab._open_comment_color_menu_for_row(row_id, x, y)
