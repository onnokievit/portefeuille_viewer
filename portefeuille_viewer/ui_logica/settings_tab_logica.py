from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from portefeuille_viewer.ui.settting_ui import Ui_SettingsTab

from portefeuille_viewer.config import get_settings
from portefeuille_viewer.signals import signals

class SettingsTab(QWidget, Ui_SettingsTab):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.settings_manager = get_settings()
        # Laad EUR/USD waarde uit settings.ini
        eurusd = self.settings_manager.get_eurusd()
        self.txtEURUSD.setText(str(eurusd))
        self.btnSaveEURUSD.clicked.connect(self.save_eurusd)

        # Database config table setup
        self.btnNewDatabase.clicked.connect(self.add_database)
        self.load_databases()

        # Comment kleur-config (open opties)
        self._loading_comment_colors = False
        if hasattr(self, "tableColorOptiesConfig"):
            self.tableColorOptiesConfig.setColumnCount(3)
            self.tableColorOptiesConfig.setHorizontalHeaderLabels(["Naam", "Achtergrond", "Tekst"])
            self.tableColorOptiesConfig.cellClicked.connect(self._on_comment_color_cell_clicked)
            self.tableColorOptiesConfig.cellChanged.connect(self._on_comment_color_cell_changed)
            self.load_comment_colors()

        self._init_ui_color_settings()

    def _init_ui_color_settings(self):
        if not hasattr(self, "groupBox_2"):
            return
        self.groupBox_2.setTitle("UI kleuren")
        layout = QHBoxLayout(self.groupBox_2)
        label = QLabel("Header rij kleur")
        layout.addWidget(label)
        self._header_color_btn = QPushButton()
        self._header_color_btn.setFixedWidth(80)
        self._header_color_btn.clicked.connect(self._on_header_color_clicked)
        layout.addWidget(self._header_color_btn)

        label_total = QLabel("Totalen rij kleur")
        layout.addWidget(label_total)
        self._total_color_btn = QPushButton()
        self._total_color_btn.setFixedWidth(80)
        self._total_color_btn.clicked.connect(self._on_total_color_clicked)
        layout.addWidget(self._total_color_btn)

        label_tab_inactive = QLabel("Tab inactief")
        layout.addWidget(label_tab_inactive)
        self._tab_inactive_btn = QPushButton()
        self._tab_inactive_btn.setFixedWidth(80)
        self._tab_inactive_btn.clicked.connect(self._on_tab_inactive_clicked)
        layout.addWidget(self._tab_inactive_btn)

        label_tab_active = QLabel("Tab actief")
        layout.addWidget(label_tab_active)
        self._tab_active_btn = QPushButton()
        self._tab_active_btn.setFixedWidth(80)
        self._tab_active_btn.clicked.connect(self._on_tab_active_clicked)
        layout.addWidget(self._tab_active_btn)

        label_tab_hover = QLabel("Tab hover")
        layout.addWidget(label_tab_hover)
        self._tab_hover_btn = QPushButton()
        self._tab_hover_btn.setFixedWidth(80)
        self._tab_hover_btn.clicked.connect(self._on_tab_hover_clicked)
        layout.addWidget(self._tab_hover_btn)

        layout.addStretch(1)
        self._refresh_header_color_button()
        self._refresh_total_color_button()
        self._refresh_tab_inactive_button()
        self._refresh_tab_active_button()
        self._refresh_tab_hover_button()

    def _refresh_header_color_button(self):
        color = self.settings_manager.get_table_header_bg()
        self._header_color_btn.setStyleSheet(f"background-color: {color};")
        self._header_color_btn.setToolTip(color)

    def _refresh_total_color_button(self):
        color = self.settings_manager.get_table_total_bg()
        self._total_color_btn.setStyleSheet(f"background-color: {color};")
        self._total_color_btn.setToolTip(color)

    def _refresh_tab_inactive_button(self):
        color = self.settings_manager.get_tab_inactive_bg()
        self._tab_inactive_btn.setStyleSheet(f"background-color: {color};")
        self._tab_inactive_btn.setToolTip(color)

    def _refresh_tab_active_button(self):
        color = self.settings_manager.get_tab_active_bg()
        self._tab_active_btn.setStyleSheet(f"background-color: {color};")
        self._tab_active_btn.setToolTip(color)

    def _refresh_tab_hover_button(self):
        color = self.settings_manager.get_tab_hover_bg()
        self._tab_hover_btn.setStyleSheet(f"background-color: {color};")
        self._tab_hover_btn.setToolTip(color)

    def _on_header_color_clicked(self):
        from PySide6.QtWidgets import QColorDialog
        current = self.settings_manager.get_table_header_bg()
        color = QColorDialog.getColor(QColor(current), self, "Kies header kleur")
        if not color.isValid():
            return
        self.settings_manager.set_table_header_bg(color.name())
        self._refresh_header_color_button()
        signals.uiStyleChanged.emit("table_header_bg")

    def _on_total_color_clicked(self):
        from PySide6.QtWidgets import QColorDialog
        current = self.settings_manager.get_table_total_bg()
        color = QColorDialog.getColor(QColor(current), self, "Kies totalen kleur")
        if not color.isValid():
            return
        self.settings_manager.set_table_total_bg(color.name())
        self._refresh_total_color_button()
        signals.uiStyleChanged.emit("table_total_bg")

    def _on_tab_inactive_clicked(self):
        from PySide6.QtWidgets import QColorDialog
        current = self.settings_manager.get_tab_inactive_bg()
        color = QColorDialog.getColor(QColor(current), self, "Kies tab inactief kleur")
        if not color.isValid():
            return
        self.settings_manager.set_tab_inactive_bg(color.name())
        self._refresh_tab_inactive_button()
        signals.uiStyleChanged.emit("tab_inactive_bg")

    def _on_tab_active_clicked(self):
        from PySide6.QtWidgets import QColorDialog
        current = self.settings_manager.get_tab_active_bg()
        color = QColorDialog.getColor(QColor(current), self, "Kies tab actief kleur")
        if not color.isValid():
            return
        self.settings_manager.set_tab_active_bg(color.name())
        self._refresh_tab_active_button()
        signals.uiStyleChanged.emit("tab_active_bg")

    def _on_tab_hover_clicked(self):
        from PySide6.QtWidgets import QColorDialog
        current = self.settings_manager.get_tab_hover_bg()
        color = QColorDialog.getColor(QColor(current), self, "Kies tab hover kleur")
        if not color.isValid():
            return
        self.settings_manager.set_tab_hover_bg(color.name())
        self._refresh_tab_hover_button()
        signals.uiStyleChanged.emit("tab_hover_bg")


    def load_comment_colors(self):
        if not hasattr(self, "tableColorOptiesConfig"):
            return
        self._loading_comment_colors = True
        try:
            colors = self.settings_manager.get_comment_colors()  # (prio,label,bg,fg)
            self.tableColorOptiesConfig.setRowCount(len(colors))
            for row, (_prio, label, bg_hex, fg_hex) in enumerate(colors):
                name_item = self._make_editable_item(label)
                self.tableColorOptiesConfig.setItem(row, 0, name_item)

                bg_item = self._make_color_item(bg_hex, use_foreground=False)
                self.tableColorOptiesConfig.setItem(row, 1, bg_item)

                fg_item = self._make_color_item(fg_hex, use_foreground=True)
                self.tableColorOptiesConfig.setItem(row, 2, fg_item)
        finally:
            self._loading_comment_colors = False

    def _make_editable_item(self, text):
        from PySide6.QtWidgets import QTableWidgetItem
        item = QTableWidgetItem(text or "")
        item.setFlags(item.flags() | Qt.ItemIsEditable)
        return item

    def _make_color_item(self, hexval, *, use_foreground: bool):
        from PySide6.QtWidgets import QTableWidgetItem
        item = QTableWidgetItem("A" if (use_foreground and hexval) else "")
        item.setData(Qt.UserRole, hexval or "")
        if hexval:
            item.setToolTip(hexval)
        item.setFlags((item.flags() & ~Qt.ItemIsEditable) | Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        if hexval:
            if use_foreground:
                item.setForeground(QColor(hexval))
                item.setBackground(QColor("#ffffff"))
            else:
                item.setBackground(QColor(hexval))
        return item

    def _save_comment_colors_from_table(self):
        if not hasattr(self, "tableColorOptiesConfig"):
            return
        table = self.tableColorOptiesConfig
        rows = table.rowCount()
        colors = []
        for r in range(rows):
            name_item = table.item(r, 0)
            bg_item = table.item(r, 1)
            fg_item = table.item(r, 2)
            label = (name_item.text() if name_item else "").strip()
            bg_hex = ""
            fg_hex = ""
            if bg_item:
                bg_hex = (bg_item.data(Qt.UserRole) or bg_item.text() or "").strip()
            if fg_item:
                fg_hex = (fg_item.data(Qt.UserRole) or fg_item.text() or "").strip()
            if not label:
                continue
            colors.append((label, bg_hex, fg_hex))
        if colors:
            self.settings_manager.set_comment_colors(colors)

    def _on_comment_color_cell_clicked(self, row, col):
        if not hasattr(self, "tableColorOptiesConfig"):
            return
        if col not in (1, 2):
            return
        from PySide6.QtWidgets import QColorDialog
        item = self.tableColorOptiesConfig.item(row, col)
        current = (item.data(Qt.UserRole) if item else "") or ""
        color = QColorDialog.getColor(QColor(current) if current else QColor("#ffffff"), self, "Kies kleur")
        if not color.isValid():
            return
        hexval = color.name()
        if item is None:
            item = self._make_color_item(hexval, use_foreground=(col == 2))
            self.tableColorOptiesConfig.setItem(row, col, item)
        else:
            item.setData(Qt.UserRole, hexval)
            if col == 2:
                item.setForeground(QColor(hexval))
                item.setBackground(QColor("#ffffff"))
                item.setText("A")
            else:
                item.setBackground(QColor(hexval))
                item.setText("")
            item.setToolTip(hexval)
        self._save_comment_colors_from_table()

    def _on_comment_color_cell_changed(self, row, col):
        if self._loading_comment_colors:
            return
        # Alleen naamkolom edits wegschrijven
        if col != 0:
            return
        self._save_comment_colors_from_table()

    def load_databases(self):
        databases = self.settings_manager.get_databases()
        default_db = self.settings_manager.get_default_database()
        self.tblDatabaseConfig.setRowCount(len(databases))
        for row, (name, config) in enumerate(databases.items()):
            # Name (with star for default)
            name_text = f"⭐ {name}" if name == default_db else name
            name_item = self._make_item(name_text, name)
            self.tblDatabaseConfig.setItem(row, 0, name_item)

            # Path
            path_item = self._make_item(config["path"])
            self.tblDatabaseConfig.setItem(row, 1, path_item)

            # Text color button
            fg_btn = self._make_color_button(config["fg_color"], lambda _, r=row: self.change_color(r, 'fg'))
            self.tblDatabaseConfig.setCellWidget(row, 2, fg_btn)

            # Background color button
            bg_btn = self._make_color_button(config["bg_color"], lambda _, r=row: self.change_color(r, 'bg'))
            self.tblDatabaseConfig.setCellWidget(row, 3, bg_btn)

            # Action buttons (default, edit, delete)
            self.tblDatabaseConfig.setCellWidget(row, 4, self._make_action_buttons(name, row))

    def _make_item(self, text, user_data=None):
        from PySide6.QtWidgets import QTableWidgetItem
        item = QTableWidgetItem(text)
        if user_data is not None:
            item.setData(256, user_data)  # Qt.UserRole = 256
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)  # Not editable
        return item

    def _make_color_button(self, color, slot):
        from PySide6.QtWidgets import QPushButton, QWidget, QHBoxLayout
        btn = QPushButton()
        btn.setStyleSheet(f"background-color: {color}; min-width: 50px;")
        btn.clicked.connect(slot)
        w = QWidget()
        layout = QHBoxLayout(w)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.addWidget(btn)
        return w

    def _make_action_buttons(self, name, row):
        from PySide6.QtWidgets import QPushButton, QWidget, QHBoxLayout
        w = QWidget()
        layout = QHBoxLayout(w)
        layout.setContentsMargins(2, 2, 2, 2)
        btn_default = self._extracted_from__make_action_buttons_7(
            QPushButton, "⭐", "Stel in als standaard"
        )
        btn_default.clicked.connect(lambda _, n=name: self.set_default_database(n))
        layout.addWidget(btn_default)
        btn_edit = self._extracted_from__make_action_buttons_7(
            QPushButton, "📁", "Wijzig pad"
        )
        btn_edit.clicked.connect(lambda _, r=row: self.edit_path(r))
        layout.addWidget(btn_edit)
        btn_delete = self._extracted_from__make_action_buttons_7(
            QPushButton, "🗑️", "Verwijder"
        )
        btn_delete.setStyleSheet("background-color: #ff6b6b; color: white;")
        btn_delete.clicked.connect(lambda _, n=name: self.delete_database(n))
        layout.addWidget(btn_delete)
        return w

    # TODO Rename this here and in `_make_action_buttons`
    def _extracted_from__make_action_buttons_7(self, QPushButton, arg1, arg2):
        # Default
        result = QPushButton(arg1)
        result.setToolTip(arg2)
        result.setMaximumWidth(35)
        return result

    def add_database(self):
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QHBoxLayout, QPushButton, QFileDialog, QMessageBox
        dialog = QDialog(self)
        dialog.setWindowTitle("Nieuwe Database Toevoegen")
        dialog.setMinimumWidth(500)
        layout = QFormLayout(dialog)
        name_edit = QLineEdit()
        layout.addRow("Naam:", name_edit)
        path_layout = QHBoxLayout()
        path_edit = QLineEdit()
        btn_browse = QPushButton("📁 Bladeren")
        btn_browse.clicked.connect(lambda: path_edit.setText(QFileDialog.getOpenFileName(dialog, "Selecteer Database", "", "Access Database (*.accdb *.mdb);;Alle bestanden (*.*)")[0]))
        path_layout.addWidget(path_edit)
        path_layout.addWidget(btn_browse)
        layout.addRow("Pad:", path_layout)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        if dialog.exec() == QDialog.Accepted:
            name = name_edit.text().strip()
            path = path_edit.text().strip()
            if not name or not path:
                QMessageBox.warning(self, "Fout", "Naam en pad zijn verplicht!")
                return
            try:
                self.settings_manager.add_database(name, path)
                self.load_databases()
            except Exception as e:
                QMessageBox.critical(self, "Fout", f"Kon database niet toevoegen:\n{e}")

    def edit_path(self, row):
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        name_item = self.tblDatabaseConfig.item(row, 0)
        name = name_item.data(256)  # Qt.UserRole
        current_path = self.tblDatabaseConfig.item(row, 1).text()
        new_path, _ = QFileDialog.getOpenFileName(self, "Selecteer Database", current_path, "Access Database (*.accdb *.mdb);;Alle bestanden (*.*)")
        if new_path:
            try:
                self.settings_manager.update_database(name, path=new_path)
                self.load_databases()
            except Exception as e:
                QMessageBox.critical(self, "Fout", f"Kon pad niet updaten:\n{e}")

    def change_color(self, row, color_type):
        from PySide6.QtWidgets import QColorDialog, QMessageBox
        from PySide6.QtGui import QColor
        name_item = self.tblDatabaseConfig.item(row, 0)
        name = name_item.data(256)
        databases = self.settings_manager.get_databases()
        current = databases[name][f"{color_type}_color"]
        color = QColorDialog.getColor(QColor(current), self, "Kies Kleur")
        if color.isValid():
            try:
                kwargs = {f"{color_type}_color": color.name()}
                self.settings_manager.update_database(name, **kwargs)
                self.load_databases()
            except Exception as e:
                QMessageBox.critical(self, "Fout", f"Kon kleur niet updaten:\n{e}")

    def set_default_database(self, name):
        from PySide6.QtWidgets import QMessageBox
        try:
            self.settings_manager.set_default_database(name)
            self.load_databases()
            QMessageBox.information(self, "Succes", f"✅ '{name}' is nu de standaard database")
        except Exception as e:
            QMessageBox.critical(self, "Fout", f"Kon default niet instellen:\n{e}")

    def delete_database(self, name):
        from PySide6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self, "Bevestigen",
            f"Weet je zeker dat je database '{name}' uit de lijst wilt verwijderen?\n\n"
            f"(Het database bestand blijft bestaan op schijf)",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                self.settings_manager.remove_database(name)
                self.load_databases()
                QMessageBox.information(self, "Succes", f"✅ Database '{name}' verwijderd uit lijst")
            except Exception as e:
                QMessageBox.critical(self, "Fout", f"Kon database niet verwijderen:\n{e}")

    def save_eurusd(self):
        value = self.txtEURUSD.text()
        self.settings_manager.set_eurusd(value)
