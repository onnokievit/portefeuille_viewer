import pyodbc
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from portefeuille_viewer.data.repository import get_stockdata_connection  # noqa: E402

TEMP_TABLE = "temp_stock_prices_temp"

def delete_all_records():
    try:
        # Establish a connection to the database
        with get_stockdata_connection() as conn:
            conn.autocommit = True  # No need for explicit commit
            cur = conn.cursor()

            # SQL query to delete all records from the table
            delete_query = f"DELETE FROM {TEMP_TABLE}"
            cur.execute(delete_query)
            print(f"All records deleted from {TEMP_TABLE}")
    except pyodbc.Error as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    delete_all_records()
