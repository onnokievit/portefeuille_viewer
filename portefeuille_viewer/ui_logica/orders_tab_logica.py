import re
from datetime import datetime
import polars as pl


class OrdersTabLogica:
	@staticmethod
	def _clean(x):
		return "" if x is None else str(x).strip()

	@staticmethod
	def _date_for_id(x):
		d = OrdersTabLogica._parse_date(x)
		return f"{d.day}-{d.month}-{d.year}" if d else ""

	@staticmethod
	def _norm_dec_for_id(x):
		if x in (None, ""):
			return ""
		s = str(x).strip().replace(",", ".")
		try:
			f = float(s)
			return str(int(f)) if f.is_integer() else f"{f}".rstrip("0").rstrip(".")
		except ValueError:
			return s

	@staticmethod
	def _parse_date(x):
		from datetime import date, datetime
		if x in (None, ""):
			return None
		if isinstance(x, datetime):
			return x.date()
		if isinstance(x, date):
			return x
		s = str(x).strip().replace("\\", "/").replace("-", "/")
		p = s.split("/")
		try:
			if len(p) == 3:
				if len(p[0]) <= 2 and len(p[1]) <= 2:
					d, m, y = int(p[0]), int(p[1]), int(p[2])
					y = (2000+y) if y < 100 else y
					return date(y, m, d)
				if len(p[0]) == 4:
					y, m, d = int(p[0]), int(p[1]), int(p[2])
					return date(y, m, d)
		except Exception:
			return None
		return None

	@staticmethod
	def build_uniek_id(values: dict) -> str:
		broker = OrdersTabLogica._clean(values.get("broker"))
		at = OrdersTabLogica._clean(values.get("asset_type")).lower()
		if at == "optie":
			rollup = OrdersTabLogica._clean(values.get("asset_rollup"))
			exp    = OrdersTabLogica._date_for_id(values.get("optie_exp_date"))
			cp     = OrdersTabLogica._clean(values.get("optie_call_put")).lower()
			strike = OrdersTabLogica._norm_dec_for_id(values.get("optie_strike"))
			return f"{broker}-{rollup}-{at}-{exp}-{cp}-{strike}"
		if at == "sprinter":
			detail = OrdersTabLogica._clean(values.get("asset_detail"))
			return f"{broker}-{detail}-{at}"
		if at == "aandeel":
			rollup = OrdersTabLogica._clean(values.get("asset_rollup"))
			return f"{broker}-{rollup}-{at}"
		rollup = OrdersTabLogica._clean(values.get("asset_rollup"))
		return f"{broker}-{rollup}-{at}"

	@staticmethod
	def is_pairable(order: dict) -> bool:
		oorspr = (order.get("transactie_oorsprong") or "").upper()
		return oorspr in {"DOORROL", "ASSIGN", "EXPIRE", "EXERCISE"}
	@staticmethod
	def add_transaction_to_snapshot(snapshot, record_id, get_connection, pl):
		"""
		Voeg een nieuw record toe aan de snapshot na een INSERT.
		"""
		if snapshot is None:
			return
		try:
			with get_connection() as conn:
				sql = "SELECT * FROM transacties_bron_data_org WHERE Id = ?"
				new_df = pl.read_database(sql, conn, execute_options={"parameters": [record_id]})
			if new_df.is_empty():
				return
			mask = snapshot["Id"] != record_id
			snapshot = snapshot.filter(mask)
			snapshot = pl.concat([snapshot, new_df])
			return snapshot
		except Exception as e:
			print(f"Fout bij toevoegen aan snapshot: {e}")
			return snapshot

	@staticmethod
	def update_transaction_in_snapshot(snapshot, record_id, get_connection, pl):
		"""
		Update een bestaand record in snapshot na een UPDATE.
		"""
		if snapshot is None:
			return
		try:
			with get_connection() as conn:
				sql = "SELECT * FROM transacties_bron_data_org WHERE Id = ?"
				updated_df = pl.read_database(sql, conn, execute_options={"parameters": [record_id]})
			if updated_df.is_empty():
				return
			mask = snapshot["Id"] != record_id
			snapshot = pl.concat([snapshot.filter(mask), updated_df])
			return snapshot
		except Exception as e:
			print(f"Fout bij updaten snapshot: {e}")
			return snapshot

	@staticmethod
	def delete_transactions_from_snapshot(snapshot, ids_to_delete, pl):
		"""
		Verwijder transacties met specifieke Id's uit snapshot.
		"""
		if snapshot is None:
			return
		try:
			snapshot = snapshot.filter(~pl.col("Id").is_in(ids_to_delete))
			return snapshot
		except Exception as e:
			print(f"Fout bij verwijderen uit snapshot: {e}")
			return snapshot

	@staticmethod
	def apply_snapshot_filters(df_pl, filter_q, col_filters):
		"""
		Pas tekst- en kolomfilters toe op een Polars DataFrame.
		"""
		if not col_filters and not filter_q:
			return df_pl
		if filter_q:
			q = filter_q.strip().lower()
			df_pl = df_pl.filter(
				pl.col("broker").cast(pl.Utf8).str.to_lowercase().str.contains(q) |
				pl.col("asset_rollup").cast(pl.Utf8).str.to_lowercase().str.contains(q) |
				pl.col("asset_detail").cast(pl.Utf8).str.to_lowercase().str.contains(q, literal=True) |
				pl.col("uniek_id").cast(pl.Utf8).str.to_lowercase().str.contains(q)
			)
		for col, filt_dict in (col_filters or {}).items():
			if col not in df_pl.columns:
				continue
			if "in" in filt_dict and filt_dict["in"]:
				df_pl = df_pl.filter(pl.col(col).is_in(list(filt_dict["in"])))
			elif "eq" in filt_dict:
				df_pl = df_pl.filter(pl.col(col) == filt_dict["eq"])
			elif "contains" in filt_dict:
				df_pl = df_pl.filter(
					pl.col(col).cast(pl.Utf8).str.to_lowercase().str.contains(filt_dict["contains"].lower())
				)
		return df_pl

	@staticmethod
	def apply_snapshot_sorting(df_pl, sort_col, sort_dir):
		"""
		Sorteer een Polars DataFrame op kolom en richting.
		"""
		if not sort_col or sort_col not in df_pl.columns:
			return df_pl
		descending = (sort_dir == "DESC")
		return df_pl.sort(sort_col, descending=descending)
	@staticmethod
	def tweede_order_nodig(oorsprong: str) -> bool:
		"""
		Bepaalt of een tweede orderregel nodig is op basis van oorsprong.
		"""
		return oorsprong in {"DOORROL", "ASSIGN", "EXPIRE", "EXERCISE"}

	@staticmethod
	def koppel_orders(eerste_order: dict, tweede_order: dict, build_uniek_id, is_pairable):
		"""
		Koppelt twee orders via transactie_oorsprong_detail als beide pairable zijn.
		Past dicts in-place aan.
		"""
		uniek1 = build_uniek_id(eerste_order)
		uniek2 = build_uniek_id(tweede_order) if tweede_order else None
		if tweede_order and is_pairable(eerste_order) and is_pairable(tweede_order):
			eerste_order["transactie_oorsprong_detail"] = uniek2
			tweede_order["transactie_oorsprong_detail"] = uniek1
		else:
			eerste_order["transactie_oorsprong_detail"] = None
			if tweede_order:
				tweede_order["transactie_oorsprong_detail"] = None
		return eerste_order, tweede_order

	@staticmethod
	def valideer_orders(order1: dict, order2: dict, vereiste_velden: list) -> list:
		"""
		Valideert of alle vereiste velden in order1 en order2 aanwezig zijn en niet leeg.
		Geeft lijst met foutmeldingen terug (leeg als alles ok).
		"""
		fouten = []
		for idx, order in enumerate([order1, order2], start=1):
			if order is None:
				continue
			for veld in vereiste_velden:
				if not order.get(veld):
					fouten.append(f"Order {idx}: '{veld}' is verplicht.")
		return fouten
	@staticmethod
	def bepaal_zichtbaarheid_order_fields(asset_type: str):
		"""
		Bepaalt welke velden zichtbaar moeten zijn voor een orderrij op basis van asset_type.
		Geeft een dict terug met veldnamen als key en True/False als waarde.
		"""
		# Basis: alles uit behalve standaardvelden
		zichtbaarheid = {
			'detail': False,
			'lbl_exp': False, 'exp': False,
			'lbl_strike': False, 'strike': False,
			'lbl_cp': False, 'cp': False
		}
		if asset_type == 'sprinter':
			for k in zichtbaarheid:
				zichtbaarheid[k] = True
		elif asset_type == 'optie':
			for k in ['lbl_exp','exp','lbl_strike','strike','lbl_cp','cp']:
				zichtbaarheid[k] = True
		return zichtbaarheid

	@staticmethod
	def bepaal_order2_visibility(oorsprong: str):
		"""
		Bepaalt of order2 zichtbaar moet zijn op basis van oorsprong.
		"""
		return oorsprong in ["DOORROL", "ASSIGN", "EXPIRE", "EXERCISE"]

	@staticmethod
	def auto_fill_year(date_str: str):
		"""
		Zet een datum als 1/2/23 om naar 1-02-23 (dd-mm-yy). Geeft string terug of None.
		"""
		s = (date_str or "").strip()
		if not s:
			return None
		s_norm = s.replace("\\", "/").replace("-", "/")
		m = re.match(r'^\s*(\d{1,2})\s*/\s*(\d{1,2})(?:\s*/\s*(\d{2,4}))?\s*$', s_norm)
		if not m:
			return None
		d, mth = int(m.group(1)), int(m.group(2))
		y = m.group(3)
		y2 = (datetime.now().year % 100) if y is None else (int(y) if len(y) == 2 else int(y) % 100)
		return f"{d}-{mth:02d}-{y2:02d}"

	@staticmethod
	def valideer_combo_in_list(waarde: str, lijst: list, veldnaam: str, allow_empty: bool = True):
		"""
		Staat alleen waarden toe die precies in de lijst voorkomen (case-insensitive).
		Geeft (True, canonieke_waarde) of (False, foutmelding) terug.
		"""
		text = (waarde or "").strip()
		if text == "":
			if allow_empty:
				return True, None
			return False, f"{veldnaam}: waarde is verplicht."
		canonical = None
		for it in lijst:
			if it.lower() == text.lower():
				canonical = it
				break
		if canonical is None:
			return False, f"{veldnaam}: '{text}' staat niet in de lijst. Kies een bestaande waarde. dit is orders widget."
		return True, canonical

	@staticmethod
	def maak_order_dict(inputs: dict):
		"""
		Zet invoerwaarden om naar een order-dict. Verwacht dict met keys als 'broker', 'asset_type', etc.
		Geeft dict terug met juiste velden voor opslag.
		"""
		# inputs: dict met alle relevante velden als string
		at = inputs.get('asset_type')
		def parse_float(val):
			try:
				return float(val)
			except Exception:
				return None
		def parse_int(val):
			try:
				return int(val)
			except Exception:
				return None
		return {
			'transactie_oorsprong': inputs.get('cb_oorsprong'),
			'broker': inputs.get('broker'),
			'asset_rollup': inputs.get('asset_rollup'),
			'asset_type': at,
			'asset_detail': inputs.get('detail') if at == 'sprinter' else None,
			'transactie_type': inputs.get('trans_type'),
			'aantal': parse_int(inputs.get('aantal')),
			'transactie_prijs': parse_float(inputs.get('prijs')),
			'transactie_fee': -abs(parse_float(inputs.get('fee'))) if inputs.get('fee') else None,
			'optie_strike': parse_float(inputs.get('strike')) if at in ['optie','sprinter'] else None,
			'optie_exp_date': inputs.get('exp') if at in ['optie','sprinter'] else None,
			'optie_call_put': inputs.get('cp') if at in ['optie','sprinter'] else None,
		}

