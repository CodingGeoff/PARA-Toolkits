# import sys
# import os
# import json
# import shutil
# from datetime import datetime

# from PyQt6.QtWidgets import (
#     QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
#     QLabel, QListWidget, QFrame, QTextEdit
# )
# from PyQt6.QtGui import QFont, QPalette, QColor, QIcon
# from PyQt6.QtCore import Qt, QUrl

# class DropZone(QFrame):
#     """ A custom QFrame that accepts file drops and emits a signal. """
#     def __init__(self, title, category_path, log_widget, parent=None):
#         super().__init__(parent)
#         self.setFrameShape(QFrame.Shape.StyledPanel)
#         self.setAcceptDrops(True)
#         self.category_path = category_path
#         self.log_widget = log_widget
#         self.title = title

#         layout = QVBoxLayout()
#         self.setLayout(layout)

#         label = QLabel(title)
#         label.setFont(QFont("Arial", 16, QFont.Weight.Bold))
#         label.setAlignment(Qt.AlignmentFlag.AlignCenter)
#         layout.addWidget(label)

#         # Load rules
#         try:
#             with open("rules.json", "r") as f:
#                 self.rules = json.load(f)
#         except (FileNotFoundError, json.JSONDecodeError):
#             self.rules = []
#             self.log("Warning: Could not load or parse rules.json.")


#     def dragEnterEvent(self, event):
#         if event.mimeData().hasUrls():
#             event.acceptProposedAction()
#         else:
#             event.ignore()

#     def dropEvent(self, event):
#         files = [url.toLocalFile() for url in event.mimeData().urls()]
#         for file_path in files:
#             self.process_file(file_path)

#     def log(self, message):
#         timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
#         self.log_widget.append(f"[{timestamp}] {message}")

#     def process_file(self, source_path):
#         """Processes a dropped file according to defined rules."""
#         filename = os.path.basename(source_path)
#         destination_path = self.category_path
        
#         # Apply rules
#         for rule in self.rules:
#             if rule.get("category") == self.title:
#                 condition_met = False
#                 if rule.get("condition_type") == "extension":
#                     extensions = [ext.strip() for ext in rule.get("condition_value", "").split(',')]
#                     if any(filename.lower().endswith(ext) for ext in extensions):
#                         condition_met = True
#                 elif rule.get("condition_type") == "keyword":
#                     if rule.get("condition_value", "").lower() in filename.lower():
#                         condition_met = True
                
#                 if condition_met:
#                     action = rule.get("action")
#                     action_value = rule.get("action_value")
#                     if action == "subfolder":
#                         destination_path = os.path.join(self.category_path, action_value)
#                         os.makedirs(destination_path, exist_ok=True)
#                         self.log(f"Rule matched: Moving to subfolder '{action_value}'.")
#                     elif action == "prefix":
#                         filename = f"{action_value}{filename}"
#                         self.log(f"Rule matched: Prefixing filename with '{action_value}'.")
#                     # Break after first matching rule for simplicity
#                     break

#         final_destination = os.path.join(destination_path, filename)

#         try:
#             shutil.move(source_path, final_destination)
#             self.log(f"SUCCESS: Moved '{os.path.basename(source_path)}' to '{os.path.relpath(final_destination)}'")
#         except Exception as e:
#             self.log(f"ERROR: Could not move file. {e}")


# class ParaFileManager(QMainWindow):
#     def __init__(self):
#         super().__init__()
#         self.setWindowTitle("Advanced PARA File Manager")
#         self.setGeometry(100, 100, 1200, 800)
#         self.setup_styles()
#         self.init_para_structure()
#         self.init_ui()

#     def setup_styles(self):
#         """Sets the visual style for the application."""
#         self.setStyleSheet("""
#             QMainWindow {
#                 background-color: #2E3440;
#             }
#             QLabel {
#                 color: #ECEFF4;
#             }
#             QFrame {
#                 background-color: #3B4252;
#                 border: 1px solid #4C566A;
#                 border-radius: 5px;
#             }
#             QTextEdit {
#                 background-color: #434C5E;
#                 color: #D8DEE9;
#                 border: 1px solid #4C566A;
#                 border-radius: 3px;
#                 font-family: Consolas, monaco, monospace;
#             }
#         """)

#     def init_para_structure(self):
#         """Loads config and creates PARA directories if they don't exist."""
#         try:
#             with open("config.json", "r") as f:
#                 config = json.load(f)
#                 base_dir = config.get("base_directory")
#                 if not base_dir:
#                     raise ValueError("'base_directory' not set in config.json")
#         except (FileNotFoundError, json.JSONDecodeError, ValueError) as e:
#             # Fallback for demonstration if config is missing/invalid
#             self.base_dir = os.path.join(os.path.expanduser("~"), "PARA_MANAGER_DEFAULT")
#             self.log_message = f"Warning: {e}. Using default directory: {self.base_dir}"
#         else:
#             self.base_dir = base_dir
#             self.log_message = f"Config loaded. Base directory: {self.base_dir}"

#         self.paths = {
#             "Projects": os.path.join(self.base_dir, "1_Projects"),
#             "Areas": os.path.join(self.base_dir, "2_Areas"),
#             "Resources": os.path.join(self.base_dir, "3_Resources"),
#             "Archives": os.path.join(self.base_dir, "4_Archives"),
#         }

#         for path in self.paths.values():
#             os.makedirs(path, exist_ok=True)

#     def init_ui(self):
#         """Initializes the main user interface."""
#         # Main layout
#         central_widget = QWidget()
#         main_layout = QVBoxLayout(central_widget)
#         self.setCentralWidget(central_widget)
        
#         # Log display
#         self.log_widget = QTextEdit()
#         self.log_widget.setReadOnly(True)
#         self.log_widget.setFixedHeight(150)
#         self.log_widget.append(self.log_message)

#         # Drop zones layout
#         drop_zones_layout = QHBoxLayout()

#         # Create the four PARA drop zones
#         self.projects_zone = DropZone("Projects", self.paths["Projects"], self.log_widget)
#         self.areas_zone = DropZone("Areas", self.paths["Areas"], self.log_widget)
#         self.resources_zone = DropZone("Resources", self.paths["Resources"], self.log_widget)
#         self.archives_zone = DropZone("Archives", self.paths["Archives"], self.log_widget)
        
#         drop_zones_layout.addWidget(self.projects_zone)
#         drop_zones_layout.addWidget(self.areas_zone)
#         drop_zones_layout.addWidget(self.resources_zone)
#         drop_zones_layout.addWidget(self.archives_zone)
        
#         # Add widgets to main layout
#         main_layout.addLayout(drop_zones_layout)
        
#         log_label = QLabel("Activity Log")
#         log_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))
#         main_layout.addWidget(log_label)
#         main_layout.addWidget(self.log_widget)


# if __name__ == "__main__":
#     app = QApplication(sys.argv)
#     window = ParaFileManager()
#     window.show()
#     sys.exit(app.exec())

import sys
import os
import json
import shutil
from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QTextEdit, QFrame, QPushButton, QDialog, QLineEdit,
    QFileDialog, QTableWidget, QTableWidgetItem, QHeaderView, QComboBox
)
from PyQt6.QtGui import QFont, QColor, QIcon
from PyQt6.QtCore import Qt, QUrl

# --- Helper Function for Resource Path (Crucial for PyInstaller) ---
def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# --- NEW: The Settings Dialog Window ---
class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings & Rules Editor")
        self.setMinimumSize(800, 600)
        self.setStyleSheet(parent.styleSheet()) # Inherit style from main window

        # Main Layout
        layout = QVBoxLayout(self)

        # --- Base Directory Configuration ---
        config_group = QFrame(self)
        config_group.setLayout(QVBoxLayout())
        layout.addWidget(config_group)
        
        config_label = QLabel("PARA Base Directory")
        config_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        self.path_edit = QLineEdit()
        browse_button = QPushButton("Browse...")
        browse_button.clicked.connect(self.browse_directory)
        
        path_layout = QHBoxLayout()
        path_layout.addWidget(self.path_edit)
        path_layout.addWidget(browse_button)
        config_group.layout().addWidget(config_label)
        config_group.layout().addLayout(path_layout)
        
        # --- Rules Configuration ---
        rules_group = QFrame(self)
        rules_group.setLayout(QVBoxLayout())
        layout.addWidget(rules_group)

        rules_label = QLabel("Custom Automation Rules")
        rules_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        self.rules_table = QTableWidget()
        self.setup_rules_table()
        
        rules_buttons_layout = QHBoxLayout()
        add_rule_button = QPushButton("Add Rule")
        add_rule_button.clicked.connect(self.add_rule)
        remove_rule_button = QPushButton("Remove Selected Rule")
        remove_rule_button.clicked.connect(self.remove_rule)
        rules_buttons_layout.addStretch()
        rules_buttons_layout.addWidget(add_rule_button)
        rules_buttons_layout.addWidget(remove_rule_button)
        
        rules_group.layout().addWidget(rules_label)
        rules_group.layout().addWidget(self.rules_table)
        rules_group.layout().addLayout(rules_buttons_layout)

        # --- Dialog Buttons (Save/Cancel) ---
        dialog_buttons_layout = QHBoxLayout()
        dialog_buttons_layout.addStretch()
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject) # Closes dialog without saving
        save_button = QPushButton("Save & Close")
        save_button.setDefault(True)
        save_button.clicked.connect(self.save_and_accept)
        
        dialog_buttons_layout.addWidget(cancel_button)
        dialog_buttons_layout.addWidget(save_button)
        layout.addLayout(dialog_buttons_layout)

        self.load_settings()

    def setup_rules_table(self):
        self.rules_table.setColumnCount(5)
        self.rules_table.setHorizontalHeaderLabels([
            "Category", "Condition Type", "Condition Value", "Action", "Action Value"
        ])
        self.rules_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

    def load_settings(self):
        # Load base directory from config.json
        try:
            with open(resource_path("config.json"), "r") as f:
                config = json.load(f)
                self.path_edit.setText(config.get("base_directory", ""))
        except (FileNotFoundError, json.JSONDecodeError):
            self.path_edit.setText("") # Or a default path

        # Load rules from rules.json
        try:
            with open(resource_path("rules.json"), "r") as f:
                rules = json.load(f)
                self.rules_table.setRowCount(len(rules))
                for i, rule in enumerate(rules):
                    self.add_rule_to_table(i, rule)
        except (FileNotFoundError, json.JSONDecodeError):
            self.rules_table.setRowCount(0)

    def add_rule_to_table(self, row, rule_data=None):
        # Helper lists for comboboxes
        categories = ["Projects", "Areas", "Resources", "Archives"]
        condition_types = ["extension", "keyword"]
        actions = ["subfolder", "prefix"]

        # Create and set combo boxes for controlled vocabulary fields
        # Category
        cat_combo = QComboBox()
        cat_combo.addItems(categories)
        if rule_data: cat_combo.setCurrentText(rule_data.get("category"))
        self.rules_table.setCellWidget(row, 0, cat_combo)
        
        # Condition Type
        cond_combo = QComboBox()
        cond_combo.addItems(condition_types)
        if rule_data: cond_combo.setCurrentText(rule_data.get("condition_type"))
        self.rules_table.setCellWidget(row, 1, cond_combo)

        # Action
        act_combo = QComboBox()
        act_combo.addItems(actions)
        if rule_data: act_combo.setCurrentText(rule_data.get("action"))
        self.rules_table.setCellWidget(row, 3, act_combo)

        # Set text for free-form fields
        cond_val_item = QTableWidgetItem(rule_data.get("condition_value", "") if rule_data else "")
        act_val_item = QTableWidgetItem(rule_data.get("action_value", "") if rule_data else "")
        self.rules_table.setItem(row, 2, cond_val_item)
        self.rules_table.setItem(row, 4, act_val_item)
    
    def add_rule(self):
        row_count = self.rules_table.rowCount()
        self.rules_table.insertRow(row_count)
        self.add_rule_to_table(row_count, None) # Add an empty rule

    def remove_rule(self):
        current_row = self.rules_table.currentRow()
        if current_row >= 0:
            self.rules_table.removeRow(current_row)

    def browse_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "Select PARA Base Directory")
        if directory:
            self.path_edit.setText(directory.replace("\\", "/")) # Use forward slashes

    def save_and_accept(self):
        # Save config.json
        config_data = {"base_directory": self.path_edit.text()}
        with open(resource_path("config.json"), "w") as f:
            json.dump(config_data, f, indent=4)

        # Save rules.json
        rules_data = []
        for i in range(self.rules_table.rowCount()):
            rule = {
                "category": self.rules_table.cellWidget(i, 0).currentText(),
                "condition_type": self.rules_table.cellWidget(i, 1).currentText(),
                "condition_value": self.rules_table.item(i, 2).text(),
                "action": self.rules_table.cellWidget(i, 3).currentText(),
                "action_value": self.rules_table.item(i, 4).text()
            }
            rules_data.append(rule)
        with open(resource_path("rules.json"), "w") as f:
            json.dump(rules_data, f, indent=4)
        
        self.accept() # Signals to the main window that we saved and closes.

class DropZone(QFrame):
    """ A custom QFrame that accepts file drops and emits a signal. """
    def __init__(self, title, log_widget, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setAcceptDrops(True)
        self.log_widget = log_widget
        self.title = title
        self.category_path = "" # Will be set by main window

        layout = QVBoxLayout()
        self.setLayout(layout)

        label = QLabel(title)
        label.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        self.load_rules()

    def load_rules(self):
        try:
            with open(resource_path("rules.json"), "r") as f:
                self.rules = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.rules = []
            self.log("Warning: Could not load or parse rules.json.")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        files = [url.toLocalFile() for url in event.mimeData().urls()]
        for file_path in files:
            self.process_file(file_path)

    def log(self, message):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_widget.append(f"[{timestamp}] {message}")

    def process_file(self, source_path):
        """Processes a dropped file according to defined rules."""
        if not self.category_path or not os.path.exists(self.category_path):
            self.log(f"ERROR: Base directory for '{self.title}' is not configured or does not exist.")
            return

        filename = os.path.basename(source_path)
        destination_path = self.category_path
        
        for rule in self.rules:
            if rule.get("category") == self.title:
                condition_met = False
                if rule.get("condition_type") == "extension":
                    extensions = [ext.strip() for ext in rule.get("condition_value", "").split(',')]
                    if any(filename.lower().endswith(ext) for ext in extensions):
                        condition_met = True
                elif rule.get("condition_type") == "keyword":
                    if rule.get("condition_value", "").lower() in filename.lower():
                        condition_met = True
                
                if condition_met:
                    action = rule.get("action")
                    action_value = rule.get("action_value")
                    if action == "subfolder":
                        destination_path = os.path.join(self.category_path, action_value)
                        os.makedirs(destination_path, exist_ok=True)
                        self.log(f"Rule matched: Moving to subfolder '{action_value}'.")
                    elif action == "prefix":
                        filename = f"{action_value}{filename}"
                        self.log(f"Rule matched: Prefixing filename with '{action_value}'.")
                    break

        final_destination = os.path.join(destination_path, filename)

        try:
            shutil.move(source_path, final_destination)
            self.log(f"SUCCESS: Moved '{os.path.basename(source_path)}' to '{os.path.relpath(final_destination, self.category_path)}'")
        except Exception as e:
            self.log(f"ERROR: Could not move file. {e}")


class ParaFileManager(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Advanced PARA File Manager")
        self.setGeometry(100, 100, 1200, 800)
        self.setup_styles()
        self.init_ui()
        self.reload_configuration() # Initial load of paths and rules

    def setup_styles(self):
        """Sets the visual style for the application."""
        self.setStyleSheet("""
            QMainWindow, QDialog {
                background-color: #2E3440;
                color: #ECEFF4;
            }
            QLabel {
                color: #ECEFF4;
            }
            QFrame {
                background-color: #3B4252;
                border: 1px solid #4C566A;
                border-radius: 5px;
            }
            QTextEdit, QLineEdit, QTableWidget {
                background-color: #434C5E;
                color: #D8DEE9;
                border: 1px solid #4C566A;
                border-radius: 3px;
                font-family: Consolas, monaco, monospace;
            }
            QPushButton {
                background-color: #5E81AC;
                color: #ECEFF4;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #81A1C1;
            }
            QPushButton:pressed {
                background-color: #4C566A;
            }
            QHeaderView::section {
                background-color: #4C566A;
                color: #ECEFF4;
                padding: 4px;
                border: 1px solid #2E3440;
            }
            QComboBox {
                background-color: #434C5E;
                border: 1px solid #4C566A;
                padding: 1px 18px 1px 3px;
            }
        """)

    def init_ui(self):
        """Initializes the main user interface."""
        central_widget = QWidget()
        main_layout = QVBoxLayout(central_widget)
        self.setCentralWidget(central_widget)
        
        # Top bar for buttons
        top_bar_layout = QHBoxLayout()
        top_bar_layout.addStretch()
        settings_button = QPushButton("Settings")
        settings_button.clicked.connect(self.open_settings_dialog)
        top_bar_layout.addWidget(settings_button)
        main_layout.addLayout(top_bar_layout)
        
        # Drop zones layout
        drop_zones_layout = QHBoxLayout()
        self.log_widget = QTextEdit()
        self.log_widget.setReadOnly(True)
        self.log_widget.setFixedHeight(150)

        self.drop_zones = {
            "Projects": DropZone("Projects", self.log_widget, self),
            "Areas": DropZone("Areas", self.log_widget, self),
            "Resources": DropZone("Resources", self.log_widget, self),
            "Archives": DropZone("Archives", self.log_widget, self),
        }
        
        for zone in self.drop_zones.values():
            drop_zones_layout.addWidget(zone)
        
        main_layout.addLayout(drop_zones_layout)
        
        log_label = QLabel("Activity Log")
        log_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        main_layout.addWidget(log_label)
        main_layout.addWidget(self.log_widget)

    def reload_configuration(self):
        """Loads config, creates directories, and updates drop zones."""
        log_message = ""
        try:
            with open(resource_path("config.json"), "r") as f:
                config = json.load(f)
                base_dir = config.get("base_directory")
                if not base_dir or not os.path.isdir(base_dir):
                    raise ValueError("'base_directory' in config.json is not a valid directory.")
        except (FileNotFoundError, json.JSONDecodeError, ValueError) as e:
            base_dir = None
            log_message = f"Warning: {e}. Please set a valid base directory in Settings."
        
        if base_dir:
            paths = {
                "Projects": os.path.join(base_dir, "1_Projects"),
                "Areas": os.path.join(base_dir, "2_Areas"),
                "Resources": os.path.join(base_dir, "3_Resources"),
                "Archives": os.path.join(base_dir, "4_Archives"),
            }
            for path in paths.values():
                os.makedirs(path, exist_ok=True)
            
            for name, zone in self.drop_zones.items():
                zone.category_path = paths[name]
            log_message = f"Config loaded. Base directory: {base_dir}"
        else:
            for name, zone in self.drop_zones.items():
                zone.category_path = "" # Invalidate paths if base_dir is not set

        self.log_widget.append(log_message)
        # Reload rules in all drop zones
        for zone in self.drop_zones.values():
            zone.load_rules()

    def open_settings_dialog(self):
        dialog = SettingsDialog(self)
        # .exec() opens a modal dialog, blocking interaction with the main window
        if dialog.exec(): # This is true if the dialog was accepted (Save clicked)
            self.log_widget.append("Settings saved. Reloading configuration...")
            self.reload_configuration()
        else:
            self.log_widget.append("Settings dialog was closed without saving.")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ParaFileManager()
    window.show()
    sys.exit(app.exec())