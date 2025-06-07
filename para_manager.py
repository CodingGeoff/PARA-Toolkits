import sys
import os
import json
import shutil
import subprocess
import traceback
from datetime import datetime
import send2trash

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QFrame, QPushButton, QDialog, QLineEdit,
    QFileDialog, QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QSplitter, QTreeView, QListWidget, QListWidgetItem, QStyle, QMessageBox,
    QMenu, QInputDialog, QStatusBar, QStackedWidget
)
from PyQt6.QtGui import (
    QFont, QIcon, QAction, QCursor, QFileSystemModel
)
# --- FIX: Imported QDir for the filter flags ---
from PyQt6.QtCore import (
    Qt, QUrl, QSize, QModelIndex, QDir
)

# --- Helper Function for Resource Path ---
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# --- Settings Dialog Window (Unchanged) ---
class SettingsDialog(QDialog):
    # This entire class is unchanged.
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
        except: self.path_edit.setText("")
        try:
            with open(resource_path("rules.json"), "r") as f:
                rules = json.load(f); self.rules_table.setRowCount(len(rules))
                for i, rule in enumerate(rules): self.add_rule_to_table(i, rule)
        except: self.rules_table.setRowCount(0)
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
        if (directory := QFileDialog.getExistingDirectory(self, "Select PARA Base Directory")): self.path_edit.setText(directory)
    def save_and_accept(self):
        with open(resource_path("config.json"), "w") as f: json.dump({"base_directory": self.path_edit.text()}, f, indent=4)
        rules_data = [{"category": self.rules_table.cellWidget(i, 0).currentText(), "condition_type": self.rules_table.cellWidget(i, 1).currentText(), "condition_value": self.rules_table.item(i, 2).text(), "action": self.rules_table.cellWidget(i, 3).currentText(), "action_value": self.rules_table.item(i, 4).text()} for i in range(self.rules_table.rowCount())]
        with open(resource_path("rules.json"), "w") as f: json.dump(rules_data, f, indent=4)
        self.accept()

# --- Drop Frame for the top panel (Unchanged) ---
class DropFrame(QFrame):
    def __init__(self, category_name, icon, main_window):
        super().__init__(); self.category_name = category_name; self.main_window = main_window; self.setAcceptDrops(True); self.setProperty("category", category_name)
        layout = QVBoxLayout(self); layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label = QLabel(); icon_label.setPixmap(icon.pixmap(QSize(48, 48))); layout.addWidget(icon_label, alignment=Qt.AlignmentFlag.AlignCenter)
        title_label = QLabel(category_name); title_label.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold)); layout.addWidget(title_label, alignment=Qt.AlignmentFlag.AlignCenter)
    def dropEvent(self, event):
        files = [url.toLocalFile() for url in event.mimeData().urls()]
        self.main_window.process_dropped_files(files, self.category_name); self.main_window.reset_drop_frame_styles(); event.acceptProposedAction()
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls(): event.acceptProposedAction()

# --- DropTreeView (Unchanged) ---
class DropTreeView(QTreeView):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window; self.setAcceptDrops(True); self.setDragDropMode(self.DragDropMode.DropOnly)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu); self.customContextMenuRequested.connect(self.main_window.show_context_menu)
        self.doubleClicked.connect(self.main_window.open_selected_item)
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls(): event.acceptProposedAction()
    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls(): event.acceptProposedAction()
    def dropEvent(self, event):
        index = self.indexAt(event.position().toPoint())
        if not index.isValid(): return
        target_dir_path = self.model().filePath(index) if self.model().isDir(index) else os.path.dirname(self.model().filePath(index))
        category_name = self.main_window.get_category_from_path(target_dir_path)
        if category_name:
            files = [url.toLocalFile() for url in event.mimeData().urls()]
            self.main_window.process_dropped_files(files, category_name)
        self.main_window.reset_drop_frame_styles(); event.acceptProposedAction()

# --- Main Application Window ---
class ParaFileManager(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PARA File Manager EVO"); self.setGeometry(100, 100, 1400, 900); self.base_dir = None
        self.para_folders = {"Projects": "1_Projects", "Areas": "2_Areas", "Resources": "3_Resources", "Archives": "4_Archives"}
        self.rules = []; self.file_index = []
        self.setAcceptDrops(True); self.setup_styles(); self.init_ui(); self.reload_configuration()
    def setup_styles(self):
        self.setStyleSheet("""
            QMainWindow, QDialog { background-color: #282c34; } QLabel { color: #abb2bf; }
            QPushButton { background-color: #61afef; color: #282c34; border: none; padding: 8px 16px; border-radius: 4px; font-weight: bold; }
            QPushButton:hover { background-color: #82c0ff; }
            QSplitter::handle { background-color: #21252b; }
            QTreeView { background-color: #21252b; border-radius: 5px; border: 1px solid #3e4451; color: #abb2bf; }
            QTreeView::item { padding: 5px; } QTreeView::item:selected { background-color: #61afef; color: #282c34; }
            QHeaderView::section { background-color: #3e4451; color: #abb2bf; padding: 5px; border: 1px solid #282c34;}
            QListWidget { background-color: #21252b; border-radius: 5px; border: 1px solid #3e4451; }
            QListWidget::item { color: #d8dee9; padding: 8px; } QStatusBar { color: #98c379; font-weight: bold; }
            QLineEdit { padding: 5px; border-radius: 4px; border: 1px solid #3e4451; background-color: #21252b; color: #d8dee9;}
            #DropFrame { background-color: #2c313a; border: 2px solid #3e4451; border-radius: 8px; }
            #DropFrame[dragging="true"] { border: 2px dashed #e5c07b; background-color: #4b5263; }
        """)
    def init_ui(self):
        central_widget = QWidget(); self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget); main_layout.setContentsMargins(10, 10, 10, 10); main_layout.setSpacing(10)
        self.setStatusBar(QStatusBar(self)); top_bar_layout = QHBoxLayout(); self.search_bar = QLineEdit(); self.search_bar.setPlaceholderText("Search all files and folders...")
        self.search_bar.textChanged.connect(self.handle_search); top_bar_layout.addWidget(self.search_bar)
        settings_button = QPushButton(); settings_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)); settings_button.setToolTip("Open Settings"); settings_button.clicked.connect(self.open_settings_dialog)
        top_bar_layout.addWidget(settings_button); main_layout.addLayout(top_bar_layout); v_splitter = QSplitter(Qt.Orientation.Vertical); main_layout.addWidget(v_splitter)
        top_pane_widget = QWidget(); top_pane_layout = QHBoxLayout(top_pane_widget); top_pane_layout.setSpacing(10)
        self.drop_frames = { "Projects": DropFrame("Projects", self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder), self), "Areas": DropFrame("Areas", self.style().standardIcon(QStyle.StandardPixmap.SP_DriveHDIcon), self), "Resources": DropFrame("Resources", self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView), self), "Archives": DropFrame("Archives", self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton), self) }
        for frame in self.drop_frames.values(): frame.setObjectName("DropFrame"); top_pane_layout.addWidget(frame)
        v_splitter.addWidget(top_pane_widget); self.bottom_pane = QStackedWidget(); v_splitter.addWidget(self.bottom_pane)
        self.file_system_model = QFileSystemModel()
        
        # --- FIX: Replaced QFileSystemModel.Filter with QDir.Filter ---
        self.file_system_model.setFilter(QDir.Filter.AllDirs | QDir.Filter.NoDotAndDotDot | QDir.Filter.AllEntries)
        
        self.tree_view = DropTreeView(self); self.tree_view.setModel(self.file_system_model); self.tree_view.setSortingEnabled(True); self.tree_view.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.search_results_list = QListWidget(); self.search_results_list.itemDoubleClicked.connect(self.open_selected_item)
        self.bottom_pane.addWidget(self.tree_view); self.bottom_pane.addWidget(self.search_results_list)
        v_splitter.setSizes([180, 720])
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls(): event.acceptProposedAction(); self.set_drop_frame_style(True)
    def dragLeaveEvent(self, event):
        self.reset_drop_frame_styles(); event.accept()
    def set_drop_frame_style(self, is_dragging):
        for frame in self.drop_frames.values(): frame.setProperty("dragging", is_dragging); frame.style().polish(frame)
    def reset_drop_frame_styles(self): self.set_drop_frame_style(False)
    def process_dropped_files(self, files, category_name):
        self.log(f"Processing {len(files)} file(s) for '{category_name}'..."); QApplication.processEvents()
        destination_folder = os.path.join(self.base_dir, self.para_folders[category_name])
        if not destination_folder or not os.path.exists(destination_folder): self.log(f"ERROR: Base directory for '{category_name}' is not set."); return
        for source_path in files:
            source_path = os.path.normpath(source_path); filename = os.path.basename(source_path); final_destination_path = destination_folder
            for rule in self.rules:
                if rule.get("category") == category_name and self.check_rule(rule, filename):
                    action, value = rule.get("action"), rule.get("action_value")
                    if action == "subfolder": final_destination_path = os.path.join(destination_folder, value); os.makedirs(final_destination_path, exist_ok=True)
                    elif action == "prefix": filename = f"{value}{filename}"
                    self.log(f"Rule Matched: '{action}' on '{os.path.basename(source_path)}'"); break
            try: shutil.move(source_path, os.path.join(final_destination_path, filename))
            except Exception as e: self.log(f"ERROR moving '{filename}': {e}")
        self.log(f"Processing complete for '{category_name}'."); self.rebuild_file_index()
    def reload_configuration(self):
        old_base_dir = self.base_dir; new_base_dir = None
        try:
            with open(resource_path("config.json"), "r") as f:
                config = json.load(f); path = config.get("base_directory")
                if path: new_base_dir = os.path.normpath(path)
                if not new_base_dir or not os.path.isdir(new_base_dir): raise ValueError(f"Path '{path}' invalid.")
        except Exception as e: self.log(f"Warning: {e}. Please set a valid base directory.")
        if old_base_dir and new_base_dir and old_base_dir != new_base_dir: self.move_para_structure(old_base_dir, new_base_dir)
        self.base_dir = new_base_dir
        try:
            with open(resource_path("rules.json"), "r") as f: self.rules = json.load(f)
        except: self.rules = []
        self.update_ui_from_config()
    def update_ui_from_config(self):
        if not self.base_dir or not os.path.isdir(self.base_dir): self.log("Configuration incomplete. Please set a valid base directory in settings."); return
        self.file_system_model.setRootPath(self.base_dir); self.tree_view.setRootIndex(self.file_system_model.index(self.base_dir))
        for i in range(1, self.file_system_model.columnCount()): self.tree_view.hideColumn(i)
        self.log(f"Configuration loaded. Root: {self.base_dir}"); self.rebuild_file_index()
    def rebuild_file_index(self):
        self.log("Indexing files for search..."); QApplication.processEvents(); self.file_index = []
        if not self.base_dir: return
        for root, dirs, files in os.walk(self.base_dir):
            for name in files: self.file_index.append((name.lower(), os.path.join(root, name)))
            for name in dirs: self.file_index.append((name.lower(), os.path.join(root, name)))
        self.log("Indexing complete."); self.handle_search(self.search_bar.text())
    def handle_search(self, text):
        term = text.lower()
        if not term: self.bottom_pane.setCurrentWidget(self.tree_view); return
        self.bottom_pane.setCurrentWidget(self.search_results_list); self.search_results_list.clear()
        results = [ (name, path) for name, path in self.file_index if term in name ]
        for name, path in results:
            item = QListWidgetItem(os.path.basename(path)); item.setToolTip(path); item.setData(Qt.ItemDataRole.UserRole, path); self.search_results_list.addItem(item)
    def get_category_from_path(self, path):
        if not self.base_dir: return None
        norm_path = os.path.normpath(path)
        for cat_name, folder_name in self.para_folders.items():
            if norm_path.startswith(os.path.join(self.base_dir, folder_name)): return cat_name
        return None
    def show_context_menu(self, pos):
        index = self.tree_view.indexAt(pos)
        if not index.isValid(): return
        path = self.file_system_model.filePath(index); menu = QMenu()
        open_action = menu.addAction("Open"); show_action = menu.addAction("Show in File Explorer"); menu.addSeparator()
        rename_action = menu.addAction("Rename..."); delete_action = menu.addAction("Delete...")
        action = menu.exec(self.tree_view.viewport().mapToGlobal(pos))
        if action == open_action: self.open_item(path)
        elif action == show_action: self.show_in_explorer(path)
        elif action == rename_action: self.rename_item(index)
        elif action == delete_action: self.delete_item(index)
    def open_selected_item(self, item_or_index):
        if isinstance(item_or_index, QListWidgetItem): path = item_or_index.data(Qt.ItemDataRole.UserRole)
        elif isinstance(item_or_index, QModelIndex): path = self.file_system_model.filePath(item_or_index)
        else: return
        self.open_item(path)
    def open_item(self, path):
        path = os.path.normpath(path)
        if sys.platform == "win32": os.startfile(path)
        else: subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", path])
    def show_in_explorer(self, path):
        path = os.path.normpath(path)
        if sys.platform == "win32": subprocess.run(["explorer", "/select,", path])
        else: subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", "-R", path])
    def rename_item(self, index):
        old_path = self.file_system_model.filePath(index); old_filename = os.path.basename(old_path)
        new_filename, ok = QInputDialog.getText(self, "Rename", "New name:", text=old_filename)
        if ok and new_filename and new_filename != old_filename:
            new_path = os.path.join(os.path.dirname(old_path), new_filename)
            try: os.rename(old_path, new_path); self.log(f"Renamed to '{new_filename}'"); self.rebuild_file_index()
            except Exception as e: self.log(f"ERROR: Could not rename. {e}")
    def delete_item(self, index):
        path = self.file_system_model.filePath(index); filename = os.path.basename(path)
        if not os.path.exists(path): self.log(f"ERROR: '{filename}' no longer exists."); return
        reply = QMessageBox.warning(self, "Confirm Delete", f"Move to Recycle Bin?\n\n'{filename}'", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            try: send2trash.send2trash(path); self.log(f"Moved '{filename}' to Recycle Bin"); self.rebuild_file_index()
            except Exception as e: self.log(f"ERROR: Could not move to Recycle Bin. {e}"); print(traceback.format_exc())
    def log(self, message):
        self.statusBar().showMessage(message, 5000); QApplication.processEvents()
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
    def check_rule(self, rule, filename):
        if rule.get("condition_type") == "extension" and any(filename.lower().endswith(ext.strip()) for ext in rule.get("condition_value", "").split(',')): return True
        elif rule.get("condition_type") == "keyword" and rule.get("condition_value", "").lower() in filename.lower(): return True
        return False

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ParaFileManager()
    window.show()
    sys.exit(app.exec())