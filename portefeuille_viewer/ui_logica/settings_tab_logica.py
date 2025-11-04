from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt
from portefeuille_viewer.ui.settting_ui import Ui_SettingsTab

from portefeuille_viewer.config.settings_manager import SettingsManager

class SettingsTab(QWidget, Ui_SettingsTab):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.settings_manager = SettingsManager()
        # Laad EUR/USD waarde uit settings.ini
        eurusd = self.settings_manager.get_eurusd()
        self.txtEURUSD.setText(str(eurusd))
        self.btnSaveEURUSD.clicked.connect(self.save_eurusd)

        # Database config table setup
        self.btnNewDatabase.clicked.connect(self.add_database)
        self.load_databases()

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