"""Static call-site inventory; no imports of app modules and no database access."""
import ast
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'development_notes_todo' / 'inventaris_databaseverbindingen_1.6.md'
NAMES = {'get_connection', 'get_stockdata_connection', 'connect_stockdata', '_connect',
    '_connect_stockdb', '_connect_option_last_prices_db', 'connect_access',
    '_get_connection_with_retry', '_connect_access_readonly'}


def main():
    rows, skipped = [], []
    class Calls(ast.NodeVisitor):
        def __init__(self, path):
            self.path, self.scope = path, []

        def visit_FunctionDef(self, node):
            self.scope.append(node.name)
            self.generic_visit(node)
            self.scope.pop()
        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Call(self, node):
            name = ast.unparse(node.func)
            short = name.rsplit('.', 1)[-1]
            if short in NAMES or (short == 'connect' and any(k in name for k in ['odbc', 'sqlite'])):
                route = 'factory/direct: controleren'
                if any(k in short for k in ['stock', 'option_last_prices']):
                    route = 'STOCKDATA'
                elif short == 'get_connection' and self.path.parts[0] in {'portefeuille_viewer', 'state_engine'}:
                    route = 'userdatabase'
                rows.append((self.path.as_posix(), node.lineno, '.'.join(self.scope) or '<module>', name, route))
            self.generic_visit(node)

    for path in ROOT.rglob('*.py'):
        rel = path.relative_to(ROOT)
        if any(p in {'.git', '__pycache__', '.pytest_cache', 'graphify-out', '.venv',
                      'venv', 'node_modules', '.claude', '.codex', 'devtools'} for p in rel.parts):
            continue
        try:
            Calls(rel).visit(ast.parse(path.read_text(encoding='utf-8-sig')))
        except (SyntaxError, UnicodeError):
            skipped.append(rel.as_posix())
    rows.sort()
    counts = Counter(row[4] for row in rows)
    lines = ['# Inventaris databaseverbindingen Portefeuille Viewer 1.6', '',
        'Gegenereerd met `python -m devtools.inventory_database_connections`. '
        'Statische AST-inventaris; tests en graphify-uitvoer uitgesloten. '
        'Dit zijn aanroepplaatsen, geen aantallen verbindingen per minuut.', '',
        f'Totaal: {len(rows)} aanroepplaatsen in {len({r[0] for r in rows})} bestanden.', '',
        'Categorieën: '+', '.join(f'{k}: {v}' for k, v in counts.items())+'.', '',
        '| Bestand | Regel | Functie | Aanroep | Route |', '|---|---:|---|---|---|']
    lines.extend(f'| `{p}` | {line} | `{scope}` | `{name}` | {route} |'
                 for p, line, scope, name, route in rows)
    lines.extend(['', '## Grenzen van de inventaris', '',
        'Aliassen en dynamische factories vragen handmatige controle. Factory/direct moet '
        'met de verbindingsstring worden beoordeeld. Ook losse hulpscripts staan in de lijst; '
        'een aanroepplaats bewijst niet dat een timer deze gebruikt. DAO/ADO-COM en verbindingen '
        'binnen dependencies staan niet in deze lijst. Zie het uitvoeringsverslag voor '
        'de beoordeelde groepen en de daadwerkelijk omgezette paden.', '',
        'Niet geparseerd: '+(', '.join(skipped) or 'geen')+'.', ''])
    OUTPUT.write_text('\n'.join(lines), encoding='utf-8')
    print(f'{len(rows)} aanroepplaatsen, {len({r[0] for r in rows})} bestanden; {OUTPUT.name}')


if __name__ == '__main__':
    main()
