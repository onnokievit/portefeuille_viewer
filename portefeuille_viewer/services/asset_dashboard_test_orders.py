"""Reuse the original test-order editor and scenario handlers without a second write path."""
from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtGui import QValidator, QCursor
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QWidget, QDialogButtonBox, QStyleOptionViewItem, QComboBox, QLineEdit
from portefeuille_viewer.data.test_order_repository import get_effective_test_orders_for_asset
from portefeuille_viewer.data.repository import build_uniek_id, fetch_open_optie_comments


class DashboardTestOrders:
    def __init__(self, target, dashboard):
        self.target = target
        self.dashboard = dashboard
        self.dialog = None
        self.asset = None
        target.testOrdersTable.cellChanged.connect(self.changed)
        target.checkBoxEnableTestOrders.toggled.connect(self.changed)
        target.checkBoxAssetOrdersOnly.toggled.connect(self.changed)
        target.comboboxScenarioSelector.currentIndexChanged.connect(self.changed)
        if hasattr(target, "asset_selector"):
            target.asset_selector.currentTextChanged.connect(self.editor_asset_changed)

    def editor_asset_changed(self, asset):
        if self.dialog is not None and asset and asset != self.dashboard.selected_asset:
            self.asset = asset
            self.dashboard._asset_status = 'all'
            self.dashboard._publish(force=True, asset=asset)
            self.dialog.setWindowTitle('Testorders en scenario’s — ' + asset)

    def changed(self, *_args):
        if not self.dashboard._timer.isActive():
            self.dashboard._timer.start()

    def sync_asset(self, asset):
        if self.asset == asset and self.target.asset_selector.currentText() == asset:
            return
        self.asset = asset
        if self.target.asset_selector.currentText() != asset:
            self.target.asset_selector.setCurrentText(asset)
        self.target._refresh_test_orders_view_for_active_asset(asset)

    def state(self, asset):
        self.sync_asset(asset)
        target = self.target
        table = target.testOrdersTable
        columns = [i for i in range(table.columnCount()) if not table.isColumnHidden(i)]
        rows = []
        row_keys = []
        identities = []
        for row in range(table.rowCount()):
            values = target.row_to_dict_db(row)
            kind = str(values.get('asset_type') or '').strip().lower()
            complete = bool(values.get('broker') and values.get('asset_rollup')) and kind in {'optie','aandeel'}
            if kind == 'optie':
                complete = complete and all(values.get(key) not in (None,'') for key in ('optie_exp_date','optie_strike','optie_call_put'))
            identities.append(build_uniek_id(values) if complete else None)
            row_keys.append(str(values.get('scenario_order_uid') or values.get('Id') or ('row-'+str(row))))
        ids = [identity for identity in identities if identity]
        frame = fetch_open_optie_comments(ids) if ids else None
        latest = {r['uniek_id']:r for r in frame.to_dicts()} if frame is not None and not frame.is_empty() else {}
        for row in range(table.rowCount()):
            cells = []
            for col in columns:
                item = table.item(row, col)
                if item is None:
                    cells.append(dict(text='',editable=False))
                    continue
                cells.append(dict(editable=bool(item.flags() & Qt.ItemIsEditable),checked=item.checkState()==Qt.Checked,text=('✓' if item.checkState() == Qt.Checked else '—')
                    if target.test_order_columns[col] == 'include' else item.text(),
                    background=item.background().color().name() if item.background().style() != Qt.NoBrush else '',
                    foreground=item.foreground().color().name() if item.foreground().style() != Qt.NoBrush else ''))
            identity = identities[row]
            if identity and 'optie_comment' in target.test_order_columns:
                source_col = target.test_order_columns.index('optie_comment')
                if source_col in columns:
                    cell = cells[columns.index(source_col)]
                    comment = latest.get(identity, {})
                    if comment:
                        cell.update(text=comment.get('optie_comment') or '',
                            background=comment.get('optie_comment_color') or '',
                            foreground=comment.get('optie_comment_textcolor') or '')
                    cell['comment'] = dict(id=identity, background=cell.get('background') or '', foreground=cell.get('foreground') or '')
            rows.append(cells)
        choices={}
        for col in columns:
            delegate=table.itemDelegateForColumn(col)
            if hasattr(delegate,'options'):
                choices[target.test_order_columns[col]]=list(delegate.options)
        combo = target.comboboxScenarioSelector
        return dict(enabled=target.checkBoxEnableTestOrders.isChecked(),
                    asset_only=target.checkBoxAssetOrdersOnly.isChecked(),
                    scenario=combo.currentData(),
                    scenarios=[dict(id=combo.itemData(i), name=combo.itemText(i)) for i in range(combo.count())],
                    columns=[table.horizontalHeaderItem(i).text() for i in columns], fields=[target.test_order_columns[i] for i in columns], choices=choices, rows=rows, row_keys=row_keys)

    def _row_key(self, row):
        values=self.target.row_to_dict_db(row)
        return str(values.get('scenario_order_uid') or values.get('Id') or ('row-'+str(row)))

    def _find_row(self, key):
        for row in range(self.target.testOrdersTable.rowCount()):
            if self._row_key(row)==str(key):return row
        raise ValueError('Deze testorder bestaat niet meer; vernieuw de tabel')

    def edit(self, key, field, value):
        target=self.target;table=target.testOrdersTable;row=self._find_row(key)
        if field not in target.test_order_columns_db or field in {'Id','scenario_order_uid'}:
            raise ValueError('Dit veld is niet bewerkbaar')
        col=target.test_order_columns.index(field);item=table.item(row,col)
        if item is None:raise ValueError('Testorderveld ontbreekt')
        if field=='include':
            if type(value) is not bool:raise ValueError('Ongeldige inclusiekeuze')
            item.setCheckState(Qt.Checked if value else Qt.Unchecked)
        else:
            if not item.flags() & Qt.ItemIsEditable:raise ValueError('Dit veld is niet bewerkbaar')
            text=str(value or '')
            if len(text)>1000:raise ValueError('De invoer is te lang')
            delegate=table.itemDelegateForColumn(col)
            editor=delegate.createEditor(table.viewport(),QStyleOptionViewItem(),table.model().index(row,col)) if delegate else None
            try:
                if isinstance(editor,QComboBox):editor.setCurrentText(text)
                elif isinstance(editor,QLineEdit):
                    validator=editor.validator()
                    if validator is not None and validator.validate(text,0)[0]==QValidator.State.Invalid:
                        raise ValueError('Ongeldige numerieke invoer')
                    editor.setText(text)
                else:
                    item.setText(text);editor=None
                if editor is not None:delegate.setModelData(editor,table.model(),table.model().index(row,col))
            finally:
                if editor is not None:editor.deleteLater()
        self.changed()
        updated=table.item(self._find_row(key),col)
        return dict(value=updated.checkState()==Qt.Checked if field=='include' else updated.text())

    def capture(self, asset):
        frame = get_effective_test_orders_for_asset(asset, scenario_id=self.target._current_scenario_id)
        return frame.clone() if frame is not None else None

    def action(self, action, value=None):
        target = self.target
        if action == 'enabled':
            target.checkBoxEnableTestOrders.setChecked(bool(value))
        elif action == 'asset_only':
            # This is a view filter, not a change to orders or payoff.
            # Avoid the native toggled handler rebuilding the table a second time.
            with QSignalBlocker(target.checkBoxAssetOrdersOnly):
                target.checkBoxAssetOrdersOnly.setChecked(bool(value))
            target.show_all_test_orders = not bool(value)
            target._refresh_test_orders_view_for_active_asset(self.asset)
        elif action == 'scenario':
            index = target.comboboxScenarioSelector.findData(int(value))
            if index < 0:
                raise ValueError('Onbekend scenario')
            target.comboboxScenarioSelector.setCurrentIndex(index)
        elif action == 'sort':
            field=value.get('field')
            if field not in target.test_order_columns:raise ValueError('Onbekende kolom')
            target.testOrdersTable.sortItems(target.test_order_columns.index(field),
                Qt.DescendingOrder if value.get('descending') else Qt.AscendingOrder)
        elif action == 'color_filter':
            target._open_test_orders_comment_color_popup(QCursor.pos())
            for popup in target.findChildren(QWidget):
                if type(popup).__name__=='ColumnFilterPopup':
                    popup.acceptedSelection.connect(self.changed)
                    popup.cleared.connect(self.changed)
        elif action == 'clear_filter':
            target._clear_test_order_comment_color_filter()
        elif action == 'builder':
            target._open_scenario_builder()
        elif action == 'manager':
            target._open_scenario_manager()
        elif action == 'add':
            before={self._row_key(row) for row in range(target.testOrdersTable.rowCount())}
            target.add_empty_row()
            new=next((self._row_key(row) for row in range(target.testOrdersTable.rowCount()) if self._row_key(row) not in before),None)
            self.changed()
            return new
        elif action == 'delete':
            row=self._find_row(value)
            target.testOrdersTable.setCurrentCell(row,0)
            target._handle_delete_test_order_clicked()
        elif action == 'editor':
            self.open_editor()
        else:
            raise ValueError('Onbekende testorderactie')
        self.changed()

    def open_editor(self):
        if self.dialog is not None:
            self.dialog.raise_()
            return
        self.target._refresh_test_orders_view_for_active_asset(self.asset)
        dialog = QDialog(self.dashboard)
        self.dialog = dialog
        dialog.setWindowTitle('Testorders en scenario’s — ' + (self.asset or ''))
        dialog.resize(1300, 560)
        layout = QVBoxLayout(dialog)
        toolbar = QHBoxLayout()
        layout.addLayout(toolbar)
        borrowed = []
        try:
            for name in ('checkBoxEnableTestOrders', 'checkBoxAssetOrdersOnly',
                         'comboboxScenarioSelector', 'buttonEditScenarios',
                         'buttonAddTestOrder', 'buttonDeleteTestOrder', 'testOrdersTable'):
                widget = getattr(self.target, name)
                parent = widget.parentWidget()
                original_layout = parent.layout()
                placeholder = QWidget(parent)
                # The placeholder keeps the old layout position and stretch intact.
                geometry = widget.geometry()
                hidden = widget.isHidden()
                if original_layout is not None:
                    original_layout.replaceWidget(widget, placeholder, Qt.FindChildrenRecursively)
                borrowed.append((widget, parent, original_layout, placeholder, hidden, geometry))
                (layout if name == 'testOrdersTable' else toolbar).addWidget(widget)
                widget.show()
            buttons = QDialogButtonBox(QDialogButtonBox.Close)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)
            dialog.exec()
        finally:
            for widget, parent, original_layout, placeholder, hidden, geometry in reversed(borrowed):
                widget.setParent(parent)
                if original_layout is not None:
                    original_layout.replaceWidget(placeholder, widget, Qt.FindChildrenRecursively)
                else:
                    widget.setGeometry(geometry)
                widget.setVisible(not hidden)
                placeholder.deleteLater()
            self.dialog = None
            dialog.deleteLater()
            self.changed()
