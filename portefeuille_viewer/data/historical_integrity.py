"""Reject ambiguous daily source rows before modifying historical prices."""


def assert_unambiguous_source(connection, table, columns):
    groups = connection.cursor().execute(
        f'SELECT [symbol],[datum],Count(*) FROM [{table}] GROUP BY [symbol],[datum] HAVING Count(*)>1'
    ).fetchall()
    nulls = connection.cursor().execute(
        f'SELECT Count(*) FROM [{table}] WHERE [symbol] IS NULL OR [datum] IS NULL'
    ).fetchone()[0]
    if nulls:
        raise ValueError(f'{table}: daily price source contains NULL symbol/date')
    fields = ','.join('[' + col + ']' for col in columns)
    for symbol, day, count in groups:
        rows = connection.cursor().execute(
            f'SELECT {fields} FROM [{table}] WHERE [symbol]=? AND [datum]=?', symbol, day
        ).fetchall()
        if any(tuple(row) != tuple(rows[0]) for row in rows[1:]):
            raise ValueError(f'{table}: conflicting daily prices for {symbol} on {day}; no merge performed')
