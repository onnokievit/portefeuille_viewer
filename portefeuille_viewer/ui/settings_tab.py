# portefeuille_viewer/ui/settings_tab.py
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLineEdit, QSpinBox, QPushButton, 
    QMessageBox, QGroupBox, QTableWidget, QTableWidgetItem, QHBoxLayout,
    QFileDialog, QHeaderView, QColorDialog
)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QColor
from portefeuille_viewer.config import (
    get_settings,
    get_databases, add_database, remove_database, 
    update_database, set_default_database, get_default_database
)

class SettingsTab(QWidget):
    def save_eurusd(self):
        try:
            value = float(self.eurusd_input.value())
            self.settings.set_eurusd(value)
            QMessageBox.information(self, "Succes", "✅ EUR/USD opgeslagen.")
        except Exception as e:
            QMessageBox.warning(self, "Fout", f"Kon EUR/USD niet opslaan: {e}")
    configChanged = Signal()  # Signal voor database wijzigingen
    
    def __init__(self):
        super().__init__()
        self.settings = get_settings()

        layout = QVBoxLayout()

        # === EURUSD SETTINGS ===
        from PySide6.QtWidgets import QDoubleSpinBox
        eurusd_group = QGroupBox("EUR/USD Instelling")
        eurusd_form = QFormLayout()
        self.eurusd_input = QDoubleSpinBox()
        self.eurusd_input.setDecimals(4)
        self.eurusd_input.setRange(0.0001, 100.0)
        self.eurusd_input.setSingleStep(0.0001)
        self.eurusd_input.setValue(self.settings.get_eurusd())
        eurusd_form.addRow("EUR/USD:", self.eurusd_input)
        save_eurusd_button = QPushButton("💾 EUR/USD Opslaan")
        save_eurusd_button.clicked.connect(self.save_eurusd)
        eurusd_form.addRow(save_eurusd_button)
        eurusd_group.setLayout(eurusd_form)
        layout.addWidget(eurusd_group)
        
        # === IB SETTINGS ===
        ib_group = QGroupBox("Interactive Brokers Instellingen")
        ib_form = QFormLayout()

        self.host_input = QLineEdit()
        self.port_input = QSpinBox()
        self.port_input.setRange(1, 65535)

        self.load_ib_config()

        ib_form.addRow("IB Host:", self.host_input)
        ib_form.addRow("IB Port:", self.port_input)

        save_ib_button = QPushButton("💾 IB Instellingen Opslaan")
        save_ib_button.clicked.connect(self.save_ib_config)

        ib_group.setLayout(ib_form)
        layout.addWidget(ib_group)
        layout.addWidget(save_ib_button)
        
        # === DATABASE SETTINGS ===
        db_group = self._build_database_group()
        layout.addWidget(db_group)
        
        layout.addStretch()
        self.setLayout(layout)

    # === IB FUNCTIES ===
    def load_ib_config(self):
        """Laad IB config uit settings.ini."""
        self.host_input.setText(self.settings.get_ib_host())
        self.port_input.setValue(self.settings.get_ib_port())

    def save_ib_config(self):
        """Sla IB config op naar settings.ini."""
        try:
            self.settings.set_ib_settings(
                self.host_input.text(),
                self.port_input.value(),
                self.settings.get_ib_client_id()
            )
            QMessageBox.information(self, "Succes", "✅ IB instellingen opgeslagen.")
        except Exception as e:
            QMessageBox.warning(self, "Fout", f"Kon instellingen niet opslaan: {e}")

    # === DATABASE FUNCTIES ===
    def _build_database_group(self):
        """Bouw database management sectie."""
        group = QGroupBox("Database Configuratie")
        layout = QVBoxLayout()
        
        # Tabel voor databases
        self.db_table = QTableWidget()
        self.db_table.setColumnCount(5)
        self.db_table.setHorizontalHeaderLabels([
            "Database", "Pad", "Tekst", "Achtergrond", "Acties"
        ])
        self.db_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.db_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.db_table.setMaximumHeight(300)
        layout.addWidget(self.db_table)
        
        # Buttons
        btn_layout = QHBoxLayout()
        btn_add = QPushButton("➕ Nieuwe Database")
        btn_add.clicked.connect(self._add_database)
        btn_layout.addWidget(btn_add)
        btn_layout.addStretch()
        
        layout.addLayout(btn_layout)
        group.setLayout(layout)
        
        self._load_databases()
        return group
    
    def _load_databases(self):
        """Laad databases in de tabel."""
        databases = get_databases()
        default_db = get_default_database()
        
        self.db_table.setRowCount(len(databases))
        
        for row, (name, config) in enumerate(databases.items()):
            # Naam (met ster voor default)
            name_text = f"⭐ {name}" if name == default_db else name
            name_item = QTableWidgetItem(name_text)
            name_item.setData(Qt.UserRole, name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            self.db_table.setItem(row, 0, name_item)
            
            # Pad
            path_item = QTableWidgetItem(config["path"])
            path_item.setFlags(path_item.flags() & ~Qt.ItemIsEditable)
            self.db_table.setItem(row, 1, path_item)
            
            # Tekstkleur knop
            fg_widget = QWidget()
            fg_layout = QHBoxLayout(fg_widget)
            fg_layout.setContentsMargins(4, 2, 4, 2)
            fg_btn = QPushButton()
            fg_btn.setStyleSheet(f"background-color: {config['fg_color']}; min-width: 50px;")
            fg_btn.clicked.connect(lambda checked, r=row, t='fg': self._change_color(r, t))
            fg_layout.addWidget(fg_btn)
            self.db_table.setCellWidget(row, 2, fg_widget)
            
            # Achtergrondkleur knop
            bg_widget = QWidget()
            bg_layout = QHBoxLayout(bg_widget)
            bg_layout.setContentsMargins(4, 2, 4, 2)
            bg_btn = QPushButton()
            bg_btn.setStyleSheet(f"background-color: {config['bg_color']}; min-width: 50px;")
            bg_btn.clicked.connect(lambda checked, r=row, t='bg': self._change_color(r, t))
            bg_layout.addWidget(bg_btn)
            self.db_table.setCellWidget(row, 3, bg_widget)
            
            # Actieknoppen
            action_widget = QWidget()
            action_layout = QHBoxLayout(action_widget)
            action_layout.setContentsMargins(2, 2, 2, 2)
            
            btn_default = QPushButton("⭐")
            btn_default.setToolTip("Stel in als standaard")
            btn_default.setMaximumWidth(35)
            btn_default.clicked.connect(lambda checked, n=name: self._set_default(n))
            action_layout.addWidget(btn_default)
            
            btn_edit = QPushButton("📁")
            btn_edit.setToolTip("Wijzig pad")
            btn_edit.setMaximumWidth(35)
            btn_edit.clicked.connect(lambda checked, r=row: self._edit_path(r))
            action_layout.addWidget(btn_edit)
            
            btn_delete = QPushButton("🗑️")
            btn_delete.setToolTip("Verwijder")
            btn_delete.setMaximumWidth(35)
            btn_delete.setStyleSheet("background-color: #ff6b6b; color: white;")
            btn_delete.clicked.connect(lambda checked, n=name: self._delete_database(n))
            action_layout.addWidget(btn_delete)
            
            self.db_table.setCellWidget(row, 4, action_widget)
    
    def _add_database(self):
        """Voeg nieuwe database toe via dialoog."""
        from PySide6.QtWidgets import QDialog, QDialogButtonBox
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Nieuwe Database Toevoegen")
        dialog.setMinimumWidth(500)
        layout = QFormLayout(dialog)
        
        name_edit = QLineEdit()
        layout.addRow("Naam:", name_edit)
        
        path_layout = QHBoxLayout()
        path_edit = QLineEdit()
        btn_browse = QPushButton("📁 Bladeren")
        btn_browse.clicked.connect(
            lambda: path_edit.setText(
                QFileDialog.getOpenFileName(
                    dialog, "Selecteer Database", "", 
                    "Access Database (*.accdb *.mdb);;Alle bestanden (*.*)"
                )[0]
            )
        )
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
                add_database(name, path)
                self._load_databases()
                self.configChanged.emit()
                QMessageBox.information(self, "Succes", f"✅ Database '{name}' toegevoegd!")
            except Exception as e:
                QMessageBox.critical(self, "Fout", f"Kon database niet toevoegen:\n{e}")
    
    def _edit_path(self, row):
        """Bewerk database pad."""
        name_item = self.db_table.item(row, 0)
        name = name_item.data(Qt.UserRole)
        current_path = self.db_table.item(row, 1).text()
        
        new_path, _ = QFileDialog.getOpenFileName(
            self, "Selecteer Database", current_path, 
            "Access Database (*.accdb *.mdb);;Alle bestanden (*.*)"
        )
        
        if new_path:
            try:
                update_database(name, path=new_path)
                self._load_databases()
                self.configChanged.emit()
            except Exception as e:
                QMessageBox.critical(self, "Fout", f"Kon pad niet updaten:\n{e}")
    
    def _change_color(self, row, color_type):
        """Verander kleur (fg of bg)."""
        name_item = self.db_table.item(row, 0)
        name = name_item.data(Qt.UserRole)
        
        databases = get_databases()
        current = databases[name][f"{color_type}_color"]
        
        color = QColorDialog.getColor(QColor(current), self, "Kies Kleur")
        if color.isValid():
            try:
                kwargs = {f"{color_type}_color": color.name()}
                update_database(name, **kwargs)
                self._load_databases()
                self.configChanged.emit()
            except Exception as e:
                QMessageBox.critical(self, "Fout", f"Kon kleur niet updaten:\n{e}")
    
    def _set_default(self, name):
        """Stel in als standaard database."""
        try:
            set_default_database(name)
            self._load_databases()
            self.configChanged.emit()
            QMessageBox.information(self, "Succes", f"✅ '{name}' is nu de standaard database")
        except Exception as e:
            QMessageBox.critical(self, "Fout", f"Kon default niet instellen:\n{e}")
    
    def _delete_database(self, name):
        """Verwijder database configuratie."""
        reply = QMessageBox.question(
            self, "Bevestigen", 
            f"Weet je zeker dat je database '{name}' uit de lijst wilt verwijderen?\n\n"
            f"(Het database bestand blijft bestaan op schijf)",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                remove_database(name)
                self._load_databases()
                self.configChanged.emit()
                QMessageBox.information(self, "Succes", f"✅ Database '{name}' verwijderd uit lijst")
            except Exception as e:
                QMessageBox.critical(self, "Fout", f"Kon database niet verwijderen:\n{e}")
