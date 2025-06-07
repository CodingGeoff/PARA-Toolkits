import sys
import os
import json
import shutil
import subprocess
import traceback # <-- 1. 导入 traceback 模块用于详细错误输出
from datetime import datetime
import send2trash

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QTextEdit, QFrame, QPushButton, QDialog, QLineEdit,
    QFileDialog, QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QSplitter, QToolBox, QListWidget, QListWidgetItem, QStyle, QMessageBox,
    QMenu, QInputDialog, QStatusBar
)
from PyQt6.QtGui import QFont, QIcon, QAction, QCursor
from PyQt6.QtCore import Qt, QUrl, QSize

# --- Helper Function for Resource Path ---
def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# --- Settings Dialog Window (Unchanged) ---
class SettingsDialog(QDialog):
    # This entire class is unchanged.
    # It is included here so the code block is complete.
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings & Rules Editor"); self.setMinimumSize(800, 600); self.setStyleSheet(parent.styleSheet())
        layout = QVBoxLayout(self)
        config_group = QFrame(self); config_group.setLayout(QVBoxLayout()); layout.addWidget(config_group)
        config_label = QLabel("PARA Base Directory"); config_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        self.path_edit = QLineEdit()
        browse_button = QPushButton("Browse..."); browse_button.clicked.connect(self.browse_directory)
        path_layout = QHBoxLayout(); path_layout.addWidget(self.path_edit); path_layout.addWidget(browse_button)
        config_group.layout().addWidget(config_label); config_group.layout().addLayout(path_layout)
        rules_group = QFrame(self); rules_group.setLayout(QVBoxLayout()); layout.addWidget(rules_group)
        rules_label = QLabel("Custom Automation Rules"); rules_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        self.rules_table = QTableWidget(); self.setup_rules_table()
        rules_buttons_layout = QHBoxLayout()
        add_rule_button = QPushButton("Add Rule"); add_rule_button.clicked.connect(self.add_rule)
        remove_rule_button = QPushButton("Remove Selected Rule"); remove_rule_button.clicked.connect(self.remove_rule)
        rules_buttons_layout.addStretch(); rules_buttons_layout.addWidget(add_rule_button); rules_buttons_layout.addWidget(remove_rule_button)
        rules_group.layout().addWidget(rules_label); rules_group.layout().addWidget(self.rules_table); rules_group.layout().addLayout(rules_buttons_layout)
        dialog_buttons_layout = QHBoxLayout(); dialog_buttons_layout.addStretch()
        cancel_button = QPushButton("Cancel"); cancel_button.clicked.connect(self.reject)
        save_button = QPushButton("Save & Close"); save_button.setDefault(True); save_button.clicked.connect(self.save_and_accept)
        dialog_buttons_layout.addWidget(cancel_button); dialog_buttons_layout.addWidget(save_button)
        layout.addLayout(dialog_buttons_layout)
        self.load_settings()
    def setup_rules_table(self):
        self.rules_table.setColumnCount(5); self.rules_table.setHorizontalHeaderLabels(["Category", "Condition Type", "Condition Value", "Action", "Action Value"])
        self.rules_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    def load_settings(self):
        try:
            with open(resource_path("config.json"), "r") as f: self.path_edit.setText(json.load(f).get("base_directory", ""))
        except (FileNotFoundError, json.JSONDecodeError): self.path_edit.setText("")
        try:
            with open(resource_path("rules.json"), "r") as f:
                rules = json.load(f); self.rules_table.setRowCount(len(rules))
                for i, rule in enumerate(rules): self.add_rule_to_table(i, rule)
        except (FileNotFoundError, json.JSONDecodeError): self.rules_table.setRowCount(0)
    def add_rule_to_table(self, row, rule_data=None):
        categories = ["Projects", "Areas", "Resources", "Archives"]; condition_types = ["extension", "keyword"]; actions = ["subfolder", "prefix"]
        cat_combo = QComboBox(); cat_combo.addItems(categories); cond_combo = QComboBox(); cond_combo.addItems(condition_types); act_combo = QComboBox(); act_combo.addItems(actions)
        if rule_data: cat_combo.setCurrentText(rule_data.get("category")); cond_combo.setCurrentText(rule_data.get("condition_type")); act_combo.setCurrentText(rule_data.get("action"))
        self.rules_table.setCellWidget(row, 0, cat_combo); self.rules_table.setCellWidget(row, 1, cond_combo); self.rules_table.setCellWidget(row, 3, act_combo)
        self.rules_table.setItem(row, 2, QTableWidgetItem(rule_data.get("condition_value", "") if rule_data else "")); self.rules_table.setItem(row, 4, QTableWidgetItem(rule_data.get("action_value", "") if rule_data else ""))
    def add_rule(self):
        row_count = self.rules_table.rowCount(); self.rules_table.insertRow(row_count); self.add_rule_to_table(row_count, None)
    def remove_rule(self):
        if (current_row := self.rules_table.currentRow()) >= 0: self.rules_table.removeRow(current_row)
    def browse_directory(self):
        if (directory := QFileDialog.getExistingDirectory(self, "Select PARA Base Directory")): self.path_edit.setText(directory.replace("\\", "/"))
    def save_and_accept(self):
        with open(resource_path("config.json"), "w") as f: json.dump({"base_directory": self.path_edit.text()}, f, indent=4)
        rules_data = [{"category": self.rules_table.cellWidget(i, 0).currentText(), "condition_type": self.rules_table.cellWidget(i, 1).currentText(), "condition_value": self.rules_table.item(i, 2).text(), "action": self.rules_table.cellWidget(i, 3).currentText(), "action_value": self.rules_table.item(i, 4).text()} for i in range(self.rules_table.rowCount())]
        with open(resource_path("rules.json"), "w") as f: json.dump(rules_data, f, indent=4)
        self.accept()

# --- DropListWidget Class (Unchanged) ---
class DropListWidget(QListWidget):
    def __init__(self, category_name, main_window):
        super().__init__(); self.category_name = category_name; self.main_window = main_window; self.category_path = ""; self.rules = []
        self.setAcceptDrops(True); self.setSpacing(2); self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.main_window.show_context_menu); self.itemDoubleClicked.connect(self.main_window.open_selected_file)
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls(): event.acceptProposedAction()
    def dropEvent(self, event):
        for file_path in [url.toLocalFile() for url in event.mimeData().urls()]: self.process_file(file_path)
    def process_file(self, source_path):
        if not self.category_path or not os.path.exists(self.category_path):
            self.main_window.log(f"ERROR: Base directory for '{self.category_name}' is not set."); return
        filename = os.path.basename(source_path); destination_path = self.category_path
        for rule in self.rules:
            if rule.get("category") == self.category_name and self.main_window.check_rule(rule, filename):
                action, value = rule.get("action"), rule.get("action_value")
                if action == "subfolder": destination_path = os.path.join(self.category_path, value); os.makedirs(destination_path, exist_ok=True)
                elif action == "prefix": filename = f"{value}{filename}"
                self.main_window.log(f"Rule Matched: '{action}' with value '{value}'"); break
        try:
            final_destination = os.path.join(destination_path, filename); shutil.move(source_path, final_destination)
            self.main_window.log(f"SUCCESS: Moved '{os.path.basename(source_path)}' to '{self.category_name}'"); self.main_window.refresh_file_list(self.category_name)
        except Exception as e: self.main_window.log(f"ERROR: Could not move file. {e}")

# --- Main Application Window ---
class ParaFileManager(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PARA File Manager Pro"); self.setGeometry(100, 100, 1400, 900); self.base_dir = None
        self.para_folders = {"Projects": "1_Projects", "Areas": "2_Areas", "Resources": "3_Resources", "Archives": "4_Archives"}
        self.setup_styles(); self.init_ui(); self.reload_configuration()
    def setup_styles(self):
        self.setStyleSheet("""
            QMainWindow,QDialog{background-color:#2E3440}QLabel{color:#ECEFF4}QPushButton{background-color:#5E81AC;color:#ECEFF4;border:none;padding:8px 16px;border-radius:4px}
            QPushButton:hover{background-color:#81A1C1}QPushButton:pressed{background-color:#4C566A}QToolBox::tab{background-color:#434C5E;color:#ECEFF4;border-radius:4px;padding:8px}
            QToolBox::tab:selected{background-color:#5E81AC;font-weight:bold}QSplitter::handle{background-color:#4C566A}QListWidget{background-color:#3B4252;border-radius:5px;border:1px solid #4C566A}
            QListWidget::item{color:#D8DEE9;padding:6px}QListWidget::item:hover{background-color:#434C5E}QListWidget::item:selected{background-color:#5E81AC;color:#ECEFF4}
            QStatusBar{color:#ECEFF4}QLineEdit{padding:5px;border-radius:4px;border:1px solid #4C566A;background-color:#434C5E;color:#D8DEE9}
            QHeaderView::section{background-color:#4C566A;color:#ECEFF4;padding:4px;border:1px solid #2E3440}QComboBox{background-color:#434C5E;border:1px solid #4C566A;padding:1px 18px 1px 3px}
        """)
    def init_ui(self):
        central_widget = QWidget(); main_layout = QVBoxLayout(central_widget); self.setCentralWidget(central_widget); self.setStatusBar(QStatusBar(self))
        top_bar_layout = QHBoxLayout(); self.search_bar = QLineEdit(); self.search_bar.setPlaceholderText("Search all files..."); self.search_bar.textChanged.connect(self.filter_all_lists)
        top_bar_layout.addWidget(self.search_bar)
        settings_button = QPushButton(); settings_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)); settings_button.setToolTip("Open Settings"); settings_button.clicked.connect(self.open_settings_dialog)
        top_bar_layout.addWidget(settings_button); main_layout.addLayout(top_bar_layout)
        splitter = QSplitter(Qt.Orientation.Horizontal); main_layout.addWidget(splitter)
        self.category_toolbox = QToolBox(); self.category_toolbox.setMinimumWidth(300); splitter.addWidget(self.category_toolbox)
        self.file_display_widget = QWidget(); self.file_display_layout = QVBoxLayout(self.file_display_widget); splitter.addWidget(self.file_display_widget)
        self.file_lists = {}
        for category_name in self.para_folders.keys():
            list_widget = DropListWidget(category_name, self); self.file_lists[category_name] = list_widget; self.file_display_layout.addWidget(list_widget); list_widget.hide()
        self.category_toolbox.currentChanged.connect(self.on_category_changed); splitter.setSizes([300, 1100])
    def reload_configuration(self):
        old_base_dir = self.base_dir; new_base_dir = None
        try:
            with open(resource_path("config.json"), "r") as f:
                config = json.load(f); path = config.get("base_directory")
                if path and os.path.isdir(os.path.dirname(path)): new_base_dir = path
                else: raise ValueError(f"Path '{path}' is invalid or parent doesn't exist.")
        except Exception as e: self.log(f"Warning: {e}. Please set a valid base directory.")
        if old_base_dir and new_base_dir and old_base_dir != new_base_dir: self.move_para_structure(old_base_dir, new_base_dir)
        self.base_dir = new_base_dir; rules = []
        try:
            with open(resource_path("rules.json"), "r") as f: rules = json.load(f)
        except Exception: pass
        for list_widget in self.file_lists.values(): list_widget.rules = rules
        self.update_ui_from_config()
    def update_ui_from_config(self):
        while self.category_toolbox.count() > 0: self.category_toolbox.removeItem(0)
        if not self.base_dir: self.log("Configuration incomplete. Please set base directory in settings."); return
        for category_name, folder_name in self.para_folders.items():
            category_path = os.path.join(self.base_dir, folder_name); os.makedirs(category_path, exist_ok=True)
            self.file_lists[category_name].category_path = category_path
            self.category_toolbox.addItem(self.file_lists[category_name], category_name); self.refresh_file_list(category_name)
        if self.category_toolbox.count() > 0: self.category_toolbox.setCurrentIndex(0); self.on_category_changed(0)
        self.log(f"Config loaded. Base directory: {self.base_dir}")
    def on_category_changed(self, index):
        if index == -1: return
        current_widget = self.category_toolbox.widget(index)
        for list_widget in self.file_lists.values(): list_widget.setVisible(list_widget == current_widget)
    def refresh_file_list(self, category_name):
        list_widget = self.file_lists[category_name]; list_widget.clear(); path = list_widget.category_path
        if not path or not os.path.exists(path): return
        try:
            for filename in sorted(os.listdir(path)):
                full_path = os.path.join(path, filename); item = QListWidgetItem(filename); item.setData(Qt.ItemDataRole.UserRole, full_path); item.setToolTip(full_path); list_widget.addItem(item)
        except Exception as e: self.log(f"Error reading directory {path}: {e}")
    def filter_all_lists(self, text):
        term = text.lower()
        for list_widget in self.file_lists.values():
            for i in range(list_widget.count()): list_widget.item(i).setHidden(term not in list_widget.item(i).text().lower())
    def get_current_list_and_item(self):
        if (index := self.category_toolbox.currentIndex()) == -1: return None, None
        list_widget = self.category_toolbox.widget(index); item = list_widget.currentItem(); return list_widget, item
    def show_context_menu(self, pos):
        list_widget, item = self.get_current_list_and_item()
        if not item or not list_widget: return
        global_pos = list_widget.mapToGlobal(pos); menu = QMenu()
        open_action = menu.addAction(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOkButton), "Open")
        show_action = menu.addAction(self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon), "Show in File Explorer")
        menu.addSeparator()
        rename_action = menu.addAction(self.style().standardIcon(QStyle.StandardPixmap.SP_FileLinkIcon), "Rename...")
        delete_action = menu.addAction(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon), "Delete...")
        action = menu.exec(global_pos)
        if action == open_action: self.open_selected_file()
        elif action == show_action: self.show_in_explorer()
        elif action == rename_action: self.rename_file()
        elif action == delete_action: self.delete_file()
    def open_selected_file(self, item=None):
        if not item: _, item = self.get_current_list_and_item()
        if not item: return
        path = item.data(Qt.ItemDataRole.UserRole)
        if sys.platform == "win32": os.startfile(path)
        elif sys.platform == "darwin": subprocess.run(["open", path])
        else: subprocess.run(["xdg-open", path])
    def show_in_explorer(self):
        _, item = self.get_current_list_and_item()
        if not item: return
        path = item.data(Qt.ItemDataRole.UserRole)
        if sys.platform == "win32": subprocess.run(["explorer", "/select,", os.path.normpath(path)])
        elif sys.platform == "darwin": subprocess.run(["open", "-R", path])
        else: subprocess.run(["xdg-open", os.path.dirname(path)])
    def rename_file(self):
        list_widget, item = self.get_current_list_and_item()
        if not item: return
        old_path = item.data(Qt.ItemDataRole.UserRole); old_filename = os.path.basename(old_path)
        new_filename, ok = QInputDialog.getText(self, "Rename File", "New name:", text=old_filename)
        if ok and new_filename and new_filename != old_filename:
            new_path = os.path.join(os.path.dirname(old_path), new_filename)
            try:
                os.rename(old_path, new_path)
                self.log(f"Renamed '{old_filename}' to '{new_filename}'"); self.refresh_file_list(list_widget.category_name)
            except Exception as e: self.log(f"ERROR: Could not rename file. {e}")
            
    def delete_file(self):
        # --- METHOD HAS BEEN UPDATED FOR ROBUSTNESS ---
        list_widget, item = self.get_current_list_and_item()
        if not item: return
        path = item.data(Qt.ItemDataRole.UserRole); filename = os.path.basename(path)
        
        # 2. Add a pre-check to ensure file exists before attempting to delete
        if not os.path.exists(path):
            self.log(f"ERROR: File '{filename}' no longer exists at the specified path.")
            self.refresh_file_list(list_widget.category_name)
            return

        reply = QMessageBox.warning(self, "Confirm Action",
            f"Are you sure you want to move this file to the Recycle Bin?\n\n'{filename}'",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                send2trash.send2trash(path)
                self.log(f"Moved '{filename}' to Recycle Bin")
                self.refresh_file_list(list_widget.category_name)
            except Exception as e:
                # 3. Add detailed error logging
                self.log(f"ERROR: Could not move to Recycle Bin. See console for details.")
                print("--- SEND2TRASH ERROR ---")
                print(f"Failed to trash file: {path}")
                traceback.print_exc()
                print("------------------------")

    def log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S"); self.statusBar().showMessage(f"[{timestamp}] {message}", 6000); QApplication.processEvents()
    def check_rule(self, rule, filename):
        if rule.get("condition_type") == "extension" and any(filename.lower().endswith(ext.strip()) for ext in rule.get("condition_value", "").split(',')): return True
        elif rule.get("condition_type") == "keyword" and rule.get("condition_value", "").lower() in filename.lower(): return True
        return False
    def move_para_structure(self, old_root, new_root):
        os.makedirs(new_root, exist_ok=True); self.log(f"Migrating PARA structure from '{old_root}'...")
        for cat, folder in self.para_folders.items():
            old_path = os.path.join(old_root, folder); new_path = os.path.join(new_root, folder)
            if os.path.exists(old_path):
                try: shutil.move(old_path, new_path); self.log(f"Moved '{cat}' folder successfully.")
                except Exception as e: self.log(f"ERROR moving '{cat}': {e}")
        QApplication.processEvents()
    def open_settings_dialog(self):
        dialog = SettingsDialog(self)
        if dialog.exec(): self.log("Settings saved. Reloading configuration..."); self.reload_configuration()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ParaFileManager()
    window.show()
    sys.exit(app.exec())