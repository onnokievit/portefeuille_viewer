from PySide6.QtWidgets import QWidget, QVBoxLayout, QFormLayout, QLineEdit, QSpinBox, QPushButton, QMessageBox
import os

class SettingsTab(QWidget):
    def __init__(self):
        super().__init__()
        self.config_path = os.path.join(os.path.dirname(__file__), '..', 'config.py')

        layout = QVBoxLayout()
        form = QFormLayout()

        # Velden voor host en port
        self.host_input = QLineEdit()
        self.port_input = QSpinBox()
        self.port_input.setRange(1, 65535)

        # Huidige waarden laden
        self.load_config()

        form.addRow("IB Host:", self.host_input)
        form.addRow("IB Port:", self.port_input)

        save_button = QPushButton("Save settings")
        save_button.clicked.connect(self.save_config)

        layout.addLayout(form)
        layout.addWidget(save_button)
        self.setLayout(layout)

    def load_config(self):
        try:
            with open(self.config_path, 'r') as f:
                content = f.read()
            lines = [l.strip() for l in content.splitlines() if l.strip().startswith(('IB_HOST', 'IB_PORT'))]
            for line in lines:
                if line.startswith('IB_HOST'):
                    self.host_input.setText(line.split('=')[1].strip().strip('"\''))
                elif line.startswith('IB_PORT'):
                    self.port_input.setValue(int(line.split('=')[1].strip()))
        except Exception as e:
            print(f"Kon config niet laden: {e}")

    def save_config(self):
        try:
            with open(self.config_path, 'r') as f:
                lines = f.readlines()

            new_lines = []
            for line in lines:
                if line.strip().startswith('IB_HOST'):
                    new_lines.append(f'IB_HOST = "{self.host_input.text()}"\n')
                elif line.strip().startswith('IB_PORT'):
                    new_lines.append(f'IB_PORT = {self.port_input.value()}\n')
                else:
                    new_lines.append(line)

            with open(self.config_path, 'w') as f:
                f.writelines(new_lines)

            QMessageBox.information(self, "Settings", "Instellingen opgeslagen.")
        except Exception as e:
            QMessageBox.warning(self, "Fout", f"Kon instellingen niet opslaan: {e}")