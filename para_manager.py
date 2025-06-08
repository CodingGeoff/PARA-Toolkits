import sys
import os
import json
import shutil
import subprocess
import traceback
from datetime import datetime
import hashlib
from functools import partial

# Required libraries: pip install PyQt6 send2trash tqdm
import send2trash
from tqdm import tqdm

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QFrame, QPushButton, QDialog, QLineEdit,
    QFileDialog, QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QSplitter, QTreeView, QListWidget, QListWidgetItem, QStyle, QMessageBox,
    QMenu, QInputDialog, QStatusBar, QStackedWidget, QTextBrowser, QProgressDialog,
    QCheckBox
)
from PyQt6.QtGui import (
    QFont, QIcon, QAction, QCursor, QFileSystemModel
)
from PyQt6.QtCore import (
    Qt, QUrl, QSize, QModelIndex, QDir, QThread, pyqtSignal
)


# --- UTILITY FUNCTIONS ---
def calculate_hash(file_path, block_size=65536):
    """Calculates the SHA256 hash of a file."""
    sha256 = hashlib.sha256()
    try:
        with open(file_path, 'rb') as f:
            for block in iter(lambda: f.read(block_size), b''):
                sha256.update(block)
        return sha256.hexdigest()
    except (IOError, PermissionError):
        return None

def resource_path(relative_path):
    """Gets the absolute path to a resource, for PyInstaller compatibility."""
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def get_all_files_in_paths(paths):
    """Recursively gets all file paths from a list of starting paths."""
    all_files = []
    for path in paths:
        if os.path.isfile(path):
            all_files.append(path)
        elif os.path.isdir(path):
            for root, _, files in os.walk(path):
                for name in files:
                    all_files.append(os.path.join(root, name))
    return all_files


# --- BACKGROUND WORKER THREAD ---
class Worker(QThread):
    """A generic worker thread for running background tasks."""
    result = pyqtSignal(object)
    error = pyqtSignal(str)
    progress = pyqtSignal(str, int, int)

    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            res = self.func(self.progress.emit, *self.args, **self.kwargs)
            self.result.emit(res)
        except Exception:
            self.error.emit(traceback.format_exc())


# --- DEDICATED LOGGER ---
class Logger:
    """A simple file-based logger."""
    def __init__(self, filename="para_manager.log"):
        self.log_file = resource_path(filename)
        self.log_format = "{timestamp} [{level:<8}] {message}"
        self.info("Logger initialized.")

    def _write(self, level, message):
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(self.log_format.format(timestamp=timestamp, level=level, message=message) + "\n")
        except Exception as e:
            print(f"FATAL: Could not write to log file {self.log_file}: {e}")

    def info(self, message): self._write("INFO", message)
    def warn(self, message): self._write("WARNING", message)
    def error(self, message, exc_info=False):
        if exc_info:
            message += f"\n{traceback.format_exc()}"
        self._write("ERROR", message)

    def get_log_dates(self):
        dates = set()
        try:
            with open(self.log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if len(line) >= 10:
                        try:
                            datetime.strptime(line[:10], '%Y-%m-%d')
                            dates.add(line[:10])
                        except ValueError:
                            continue
        except FileNotFoundError:
            pass
        return sorted(list(dates), reverse=True)

    def get_logs_for_date(self, date_str):
        logs = []
        try:
            with open(self.log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.startswith(date_str):
                        logs.append(line.strip())
        except FileNotFoundError:
            pass
        return "\n".join(logs)


# --- UI DIALOGS ---
class PreOperationDialog(QDialog):
    """Informs the user why a complex operation is needed and offers choices."""
    def __init__(self, dest_folder_name, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Action Required")
        self.setStyleSheet(parent.styleSheet())
        self.result = "cancel"

        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        title_label = QLabel("Destination Not Empty")
        title_label.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        info_text = f"""<p>The destination folder '<b>{dest_folder_name}</b>' already contains files.</p><p>To avoid creating duplicates, please choose how you'd like to proceed.</p>"""
        info_label = QLabel(info_text)
        info_label.setWordWrap(True)

        layout.addWidget(title_label)
        layout.addWidget(info_label)

        button_layout = QHBoxLayout()
        self.scan_button = self._create_option_button(
            "Smart Scan (Recommended)",
            "Scans file content to prevent adding identical files. Slower but safer.",
            "scan",
            QStyle.StandardPixmap.SP_FileDialogDetailedView
        )
        self.skip_button = self._create_option_button(
            "Move All (Fast)",
            "Moves all files, automatically renaming any with the same name. Much faster.",
            "skip",
            QStyle.StandardPixmap.SP_ArrowRight
        )
        
        button_layout.addWidget(self.scan_button)
        button_layout.addWidget(self.skip_button)
        layout.addLayout(button_layout)

    def _create_option_button(self, title, description, result_val, icon):
        button = QPushButton(f" {title}")
        button.setIcon(self.style().standardIcon(icon))
        button.setToolTip(description)
        button.clicked.connect(lambda: self.set_result_and_accept(result_val))
        return button

    def set_result_and_accept(self, result_val):
        self.result = result_val
        self.accept()

class HashingSelectionDialog(QDialog):
    """Dialog for users to select files/folders for deduplication, with robust checkbox logic."""
    def __init__(self, root_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Scope for Duplicate Check")
        self.setMinimumSize(800, 600)
        self.setStyleSheet(parent.styleSheet())
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<b>Select items in the destination to include in the content check.</b>"))
        layout.addWidget(QLabel("Uncheck items to exclude them. Parent/child selections are linked."))

        self.model = QFileSystemModel()
        self.model.setFilter(QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot)
        self.model.setRootPath(root_path)
        self.model.setReadOnly(False)

        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setRootIndex(self.model.index(root_path))
        self.tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tree.setColumnHidden(1, True); self.tree.setColumnHidden(2, True); self.tree.setColumnHidden(3, True)
        
        self._block_signals = False
        self.set_check_state_recursive(self.model.index(0, 0, self.tree.rootIndex()), Qt.CheckState.Checked)
        self.tree.expand(self.tree.rootIndex())
        self.model.dataChanged.connect(self.on_data_changed)
        layout.addWidget(self.tree)

        button_layout = QHBoxLayout()
        check_all_btn = QPushButton("Check All")
        uncheck_all_btn = QPushButton("Uncheck All")
        ok_button = QPushButton("Confirm & Start Scan")
        cancel_button = QPushButton("Cancel")
        button_layout.addWidget(check_all_btn); button_layout.addWidget(uncheck_all_btn)
        button_layout.addStretch(); button_layout.addWidget(cancel_button); button_layout.addWidget(ok_button)
        layout.addLayout(button_layout)

        ok_button.clicked.connect(self.accept); cancel_button.clicked.connect(self.reject)
        
        # --- FIX: Connect to new wrapper methods that block signals for performance ---
        check_all_btn.clicked.connect(self.check_all_items)
        uncheck_all_btn.clicked.connect(self.uncheck_all_items)

    def check_all_items(self):
        """Checks all items, blocking signals for performance."""
        self.model.blockSignals(True)
        self.set_check_state_recursive(self.tree.rootIndex(), Qt.CheckState.Checked)
        self.model.blockSignals(False)
        # Emit a single dataChanged signal for the root to notify the view of a major change
        root_index = self.tree.rootIndex()
        self.model.dataChanged.emit(root_index, root_index, [])
        self.tree.viewport().update()

    def uncheck_all_items(self):
        """Unchecks all items, blocking signals for performance."""
        self.model.blockSignals(True)
        self.set_check_state_recursive(self.tree.rootIndex(), Qt.CheckState.Unchecked)
        self.model.blockSignals(False)
        # Emit a single dataChanged signal for the root to notify the view of a major change
        root_index = self.tree.rootIndex()
        self.model.dataChanged.emit(root_index, root_index, [])
        self.tree.viewport().update()
    
    # in class ParaFileManager
# ... (把它放在其他 on_... 函数附近)

    # def on_index_rebuilt(self, index_data):
    #     """这个槽函数在主线程中运行，用于接收索引结果并更新UI。"""
    #     self.log_and_show(f"Indexing complete. {len(index_data)} items indexed.", "info", 2000)
    #     self.file_index = index_data
    #     # 现在可以安全地调用 handle_search 来刷新UI了
    #     self.handle_search(self.search_bar.text())
    
    def on_data_changed(self, topLeft, bottomRight, roles):
        if Qt.ItemDataRole.CheckStateRole in roles and not self._block_signals:
            self._block_signals = True
            state = self.model.data(topLeft, Qt.ItemDataRole.CheckStateRole)
            if self.model.hasChildren(topLeft):
                self.set_check_state_recursive(topLeft, state, set_parent=False)
            self.update_parent_states(topLeft.parent())
            self._block_signals = False
            
    def set_check_state_recursive(self, parent_index, state, set_parent=True):
        if not parent_index.isValid(): return
        if set_parent:
             self.model.setData(parent_index, state, Qt.ItemDataRole.CheckStateRole)
        for i in range(self.model.rowCount(parent_index)):
            child_index = self.model.index(i, 0, parent_index)
            self.set_check_state_recursive(child_index, state)

    def update_parent_states(self, parent_index):
        if not parent_index.isValid(): return
        checked_count, partially_checked_count, total_count = 0, 0, self.model.rowCount(parent_index)
        for i in range(total_count):
            state = self.model.data(self.model.index(i, 0, parent_index), Qt.ItemDataRole.CheckStateRole)
            if state == Qt.CheckState.Checked: checked_count += 1
            elif state == Qt.CheckState.PartiallyChecked: partially_checked_count += 1
        new_state = Qt.CheckState.Unchecked
        if checked_count == total_count: new_state = Qt.CheckState.Checked
        elif checked_count > 0 or partially_checked_count > 0: new_state = Qt.CheckState.PartiallyChecked
        self.model.setData(parent_index, new_state, Qt.ItemDataRole.CheckStateRole)
        self.update_parent_states(parent_index.parent())

    def get_checked_files(self):
        checked_files = []
        self._get_checked_recursive(self.tree.rootIndex(), checked_files)
        return checked_files

    def _get_checked_recursive(self, index, checked_list):
        if not index.isValid(): return
        if self.model.data(index, Qt.ItemDataRole.CheckStateRole) != Qt.CheckState.Unchecked:
            path = self.model.filePath(index)
            if os.path.isfile(path):
                checked_list.append(path)
            elif os.path.isdir(path) and self.model.hasChildren(index):
                 for i in range(self.model.rowCount(index)):
                    self._get_checked_recursive(self.model.index(i, 0, index), checked_list)

class DeduplicationDialog(QDialog):
    """Dialog to show found duplicates and let the user decide how to handle them, with a context menu."""
    def __init__(self, duplicates, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Duplicate Files Found")
        self.setMinimumSize(1200, 600)
        self.setStyleSheet(parent.styleSheet())
        self.duplicates = duplicates
        
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<b>Warning:</b> The following source files have the <b>exact same content</b> as files already in the destination."))
        layout.addWidget(QLabel("By default, duplicate source files will be <b>deleted</b>. Uncheck to <b>keep</b> them (they will be moved and renamed). <b>Right-click</b> a path to open its location."))
        
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Action (Check to Delete)", "Source File", "Conflicts With Destination File", "File Size (KB)"])
        self.table.setAlternatingRowColors(True)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        
        self.populate_table()
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)
        
        button_layout = QHBoxLayout()
        deselect_all_btn = QPushButton("Select All (Mark All for Deletion)")
        select_all_btn = QPushButton("Deselect All (Mark All to Keep)")
        button_layout.addWidget(select_all_btn); button_layout.addWidget(deselect_all_btn); button_layout.addStretch()
        ok_button = QPushButton("Confirm & Process Files"); cancel_button = QPushButton("Cancel")
        button_layout.addWidget(cancel_button); button_layout.addWidget(ok_button); layout.addLayout(button_layout)
        
        ok_button.clicked.connect(self.accept); cancel_button.clicked.connect(self.reject)
        select_all_btn.clicked.connect(lambda: self.set_all_checkboxes(False))
        deselect_all_btn.clicked.connect(lambda: self.set_all_checkboxes(True))

    def populate_table(self):
        self.table.setRowCount(len(self.duplicates))
        for row, (old_path, conflict_path, _) in enumerate(self.duplicates):
            checkbox = QCheckBox(); checkbox.setChecked(True); checkbox.setToolTip("Check this box to delete the source file after processing.")
            cell_widget = QWidget(); cell_layout = QHBoxLayout(cell_widget); cell_layout.addWidget(checkbox); cell_layout.setAlignment(Qt.AlignmentFlag.AlignCenter); cell_layout.setContentsMargins(0,0,0,0); self.table.setCellWidget(row, 0, cell_widget)
            try: old_stat = os.stat(old_path)
            except FileNotFoundError: continue
            self.table.setItem(row, 1, QTableWidgetItem(old_path))
            self.table.setItem(row, 2, QTableWidgetItem(conflict_path))
            self.table.setItem(row, 3, QTableWidgetItem(f"{old_stat.st_size / 1024:.2f}"))

    def set_all_checkboxes(self, checked):
        for row in range(self.table.rowCount()):
            if (cell_widget := self.table.cellWidget(row, 0)) and (checkbox := cell_widget.findChild(QCheckBox)): checkbox.setChecked(checked)

    def get_user_choices(self):
        choices = {}
        for row in range(self.table.rowCount()):
            old_path = self.table.item(row, 1).text()
            checkbox = self.table.cellWidget(row, 0).findChild(QCheckBox)
            choices[old_path] = "delete" if checkbox.isChecked() else "keep"
        return choices

    def show_context_menu(self, pos):
        item = self.table.itemAt(pos)
        if not item or item.column() not in [1, 2]: return
        path = self.table.item(item.row(), item.column()).text()
        menu = QMenu()
        action = menu.addAction(self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon), "Show in File Explorer")
        if menu.exec(self.table.mapToGlobal(pos)) == action:
            try:
                if sys.platform == "win32": subprocess.run(['explorer', '/select,', os.path.normpath(path)])
                else: subprocess.run(['open', '-R', os.path.normpath(path)])
            except Exception as e: self.parent().logger.error(f"Failed to show in explorer: {path}", exc_info=True)

class LogViewerDialog(QDialog):
    def __init__(self, logger, parent=None):
        super().__init__(parent); self.logger = logger; self.setWindowTitle("Log Viewer"); self.setMinimumSize(900, 700); self.setStyleSheet(parent.styleSheet())
        layout = QVBoxLayout(self); controls_layout = QHBoxLayout(); self.date_combo = QComboBox(); controls_layout.addWidget(QLabel("Select Date:")); controls_layout.addWidget(self.date_combo); controls_layout.addStretch(); layout.addLayout(controls_layout)
        self.log_display = QTextBrowser(); self.log_display.setFont(QFont("Consolas", 10)); layout.addWidget(self.log_display)
        self.date_combo.currentIndexChanged.connect(self.load_log_for_date); self.populate_dates()
    def populate_dates(self): self.date_combo.clear(); self.date_combo.addItems(self.logger.get_log_dates())
    def load_log_for_date(self):
        date_str = self.date_combo.currentText()
        if not date_str: return
        logs = self.logger.get_logs_for_date(date_str); html = ""
        for line in logs.split('\n'):
            line = line.replace("<", "&lt;").replace(">", "&gt;"); color = "#abb2bf"
            if "[ERROR" in line: color = "#e06c75"
            elif "[WARNING" in line: color = "#d19a66"
            elif "[INFO" in line: color = "#98c379"
            html += f'<pre style="margin: 0; padding: 0; white-space: pre-wrap; color: {color};">{line}</pre>'
        self.log_display.setHtml(html)

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent); self.setWindowTitle("Settings & Rules"); self.setMinimumSize(800, 600); self.setStyleSheet(parent.styleSheet())
        layout = QVBoxLayout(self); config_group = QFrame(self); config_group.setLayout(QVBoxLayout()); config_label = QLabel("PARA Base Directory"); config_label.setFont(QFont("Arial", 12, QFont.Weight.Bold)); self.path_edit = QLineEdit(); browse_button = QPushButton("Browse..."); browse_button.clicked.connect(self.browse_directory); path_layout = QHBoxLayout(); path_layout.addWidget(self.path_edit); path_layout.addWidget(browse_button); config_group.layout().addWidget(config_label); config_group.layout().addLayout(path_layout); layout.addWidget(config_group)
        rules_group = QFrame(self); rules_group.setLayout(QVBoxLayout()); rules_label = QLabel("Custom Automation Rules"); rules_label.setFont(QFont("Arial", 12, QFont.Weight.Bold)); self.rules_table = QTableWidget(); self.setup_rules_table(); rules_buttons_layout = QHBoxLayout(); add_rule_button = QPushButton("Add Rule"); add_rule_button.clicked.connect(self.add_rule); remove_rule_button = QPushButton("Remove Selected Rule"); remove_rule_button.clicked.connect(self.remove_rule); rules_buttons_layout.addStretch(); rules_buttons_layout.addWidget(add_rule_button); rules_buttons_layout.addWidget(remove_rule_button); rules_group.layout().addWidget(rules_label); rules_group.layout().addWidget(self.rules_table); rules_group.layout().addLayout(rules_buttons_layout); layout.addWidget(rules_group)
        dialog_buttons_layout = QHBoxLayout(); dialog_buttons_layout.addStretch(); cancel_button = QPushButton("Cancel"); cancel_button.clicked.connect(self.reject); save_button = QPushButton("Save & Close"); save_button.setDefault(True); save_button.clicked.connect(self.save_and_accept); dialog_buttons_layout.addWidget(cancel_button); dialog_buttons_layout.addWidget(save_button); layout.addLayout(dialog_buttons_layout)
        self.load_settings()
    def setup_rules_table(self): self.rules_table.setColumnCount(5); self.rules_table.setHorizontalHeaderLabels(["Category", "Condition Type", "Condition Value", "Action", "Action Value"]); self.rules_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    def load_settings(self):
        try:
            with open(resource_path("config.json"), "r") as f: self.path_edit.setText(json.load(f).get("base_directory", ""))
        except (FileNotFoundError, json.JSONDecodeError): self.path_edit.setText("")
        try:
            with open(resource_path("rules.json"), "r") as f: rules = json.load(f); self.rules_table.setRowCount(len(rules));
            for i, rule in enumerate(rules): self.add_rule_to_table(i, rule)
        except (FileNotFoundError, json.JSONDecodeError): self.rules_table.setRowCount(0)
    def add_rule_to_table(self, row, rule_data=None):
        categories = ["Projects", "Areas", "Resources", "Archives"]; condition_types = ["extension", "keyword"]; actions = ["subfolder", "prefix"]; cat_combo = QComboBox(); cat_combo.addItems(categories); cond_combo = QComboBox(); cond_combo.addItems(condition_types); act_combo = QComboBox(); act_combo.addItems(actions)
        if rule_data: cat_combo.setCurrentText(rule_data.get("category")); cond_combo.setCurrentText(rule_data.get("condition_type")); act_combo.setCurrentText(rule_data.get("action"))
        self.rules_table.setCellWidget(row, 0, cat_combo); self.rules_table.setCellWidget(row, 1, cond_combo); self.rules_table.setCellWidget(row, 3, act_combo); self.rules_table.setItem(row, 2, QTableWidgetItem(rule_data.get("condition_value", "") if rule_data else "")); self.rules_table.setItem(row, 4, QTableWidgetItem(rule_data.get("action_value", "") if rule_data else ""))
    def add_rule(self): row_count = self.rules_table.rowCount(); self.rules_table.insertRow(row_count); self.add_rule_to_table(row_count, None)
    def remove_rule(self):
        if (current_row := self.rules_table.currentRow()) >= 0: self.rules_table.removeRow(current_row)
    def browse_directory(self):
        if (directory := QFileDialog.getExistingDirectory(self, "Select PARA Base Directory")): self.path_edit.setText(directory)
    def save_and_accept(self):
        try:
            with open(resource_path("config.json"), "r") as f_read: config = json.load(f_read)
        except (FileNotFoundError, json.JSONDecodeError): config = {}
        config["base_directory"] = self.path_edit.text()
        with open(resource_path("config.json"), "w") as f: json.dump(config, f, indent=4)
        rules_data = []
        for i in range(self.rules_table.rowCount()):
            cond_item = self.rules_table.item(i, 2); act_item = self.rules_table.item(i, 4)
            rules_data.append({"category": self.rules_table.cellWidget(i, 0).currentText(), "condition_type": self.rules_table.cellWidget(i, 1).currentText(), "condition_value": cond_item.text() if cond_item else "", "action": self.rules_table.cellWidget(i, 3).currentText(), "action_value": act_item.text() if act_item else ""})
        with open(resource_path("rules.json"), "w") as f: json.dump(rules_data, f, indent=4)
        self.accept()

class DropFrame(QFrame):
    def __init__(self, category_name, icon, main_window):
        super().__init__(); self.category_name = category_name; self.main_window = main_window; self.setAcceptDrops(True); self.setProperty("category", category_name)
        layout = QVBoxLayout(self); layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label = QLabel(); icon_label.setPixmap(icon.pixmap(QSize(48, 48))); layout.addWidget(icon_label, alignment=Qt.AlignmentFlag.AlignCenter)
        title_label = QLabel(category_name); title_label.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold)); layout.addWidget(title_label, alignment=Qt.AlignmentFlag.AlignCenter)
    def dropEvent(self, event):
        files = [url.toLocalFile() for url in event.mimeData().urls()]; self.main_window.process_dropped_items(files, self.category_name); self.main_window.reset_drop_frame_styles(); event.acceptProposedAction()
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls(): event.acceptProposedAction()

class DropTreeView(QTreeView):
    def __init__(self, main_window):
        super().__init__(); self.main_window = main_window; self.setAcceptDrops(True); self.setDragDropMode(self.DragDropMode.DropOnly)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu); self.customContextMenuRequested.connect(self.main_window.show_context_menu); self.doubleClicked.connect(self.main_window.open_selected_item)
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
            self.main_window.process_dropped_items(files, category_name)
        self.main_window.reset_drop_frame_styles(); event.acceptProposedAction()


# --- MAIN APPLICATION WINDOW ---
class ParaFileManager(QMainWindow):
    def __init__(self, logger):
        super().__init__()
        self.logger = logger
        self.setWindowTitle("PARA File Manager EVO")
        self.setGeometry(100, 100, 1400, 900)
        self.base_dir = None
        self.para_folders = {"Projects": "1_Projects", "Areas": "2_Areas", "Resources": "3_Resources", "Archives": "4_Archives"}
        self.rules = []
        self.file_index = []
        self.worker = None
        self.progress = None
        self.setup_styles()
        self.setAcceptDrops(True)
        self.init_ui()
        self.reload_configuration()
        self.logger.info("Application Started.")

    def setup_styles(self):
        self.setStyleSheet("""
            QMainWindow, QDialog { background-color: #282c34; color: #abb2bf; } QWidget { font-size: 9pt; } QLabel { color: #abb2bf; }
            QPushButton { background-color: #61afef; color: #282c34; border: none; padding: 8px 16px; border-radius: 4px; font-weight: bold; }
            QPushButton:hover { background-color: #82c0ff; } QPushButton:pressed { background-color: #5298d8; }
            QSplitter::handle { background-color: #21252b; width: 3px; } QSplitter::handle:hover { background-color: #61afef; }
            QTreeView, QListWidget { background-color: #21252b; border-radius: 5px; border: 1px solid #3e4451; color: #abb2bf; font-size: 10pt; }
            QTreeView::item { padding: 5px; } QTreeView::item:hover { background-color: #3e4451; } QTreeView::item:selected { background-color: #61afef; color: #282c34; }
            QHeaderView::section { background-color: #2c313a; color: #abb2bf; padding: 5px; border: 1px solid #3e4451;}
            QListWidget::item { color: #d8dee9; padding: 8px; border-radius: 3px; } QListWidget::item:hover { background-color: #3e4451; } QListWidget::item:selected { background-color: #61afef; color: #282c34; }
            QStatusBar { color: #98c379; font-weight: bold; }
            QLineEdit { padding: 6px; border-radius: 4px; border: 1px solid #3e4451; background-color: #21252b; color: #d8dee9;}
            #DropFrame { background-color: #2c313a; border: 2px solid #3e4451; border-radius: 8px; } #DropFrame[dragging="true"] { border: 2px dashed #e5c07b; background-color: #4b5263; }
            #WelcomeWidget { background-color: #21252b; border-radius: 5px; }
            QProgressDialog { background-color: #282c34; color: #abb2bf; } QProgressDialog QLabel { color: #abb2bf; }
            QTextBrowser { background-color: #21252b; color: #abb2bf; border-radius: 4px; border: 1px solid #3e4451; }
            QTableWidget { background-color: #21252b; color: #abb2bf; border: 1px solid #3e4451; gridline-color: #3e4451; font-size: 9pt; alternate-background-color: #2c313a; }
            QTableWidget::item { padding: 5px; border-bottom: 1px solid #3e4451; }
        """)

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        self.setStatusBar(QStatusBar(self))
        main_layout.addLayout(self._create_top_bar())
        v_splitter = QSplitter(Qt.Orientation.Vertical)
        main_layout.addWidget(v_splitter)
        v_splitter.addWidget(self._create_drop_frames())
        v_splitter.addWidget(self._create_bottom_pane())
        v_splitter.setSizes([180, 720])

    def _create_top_bar(self):
        top_bar_layout = QHBoxLayout()
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Search all files and folders...")
        self.search_bar.textChanged.connect(self.handle_search)
        top_bar_layout.addWidget(self.search_bar)
        
        style = self.style()
        settings_button = QPushButton()
        settings_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
        settings_button.setToolTip("Open Settings")
        settings_button.clicked.connect(self.open_settings_dialog)

        log_button = QPushButton()
        log_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView))
        log_button.setToolTip("View Logs")
        log_button.clicked.connect(self.open_log_viewer)

        top_bar_layout.addWidget(settings_button)
        top_bar_layout.addWidget(log_button)
        return top_bar_layout

    def _create_drop_frames(self):
        top_pane_widget = QWidget()
        top_pane_layout = QHBoxLayout(top_pane_widget)
        top_pane_layout.setSpacing(10)
        style = self.style()
        self.drop_frames = {
            "Projects": DropFrame("Projects", style.standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder), self),
            "Areas": DropFrame("Areas", style.standardIcon(QStyle.StandardPixmap.SP_DriveHDIcon), self),
            "Resources": DropFrame("Resources", style.standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon), self),
            "Archives": DropFrame("Archives", style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton), self)
        }
        for frame in self.drop_frames.values():
            frame.setObjectName("DropFrame")
            top_pane_layout.addWidget(frame)
        return top_pane_widget

    def _create_bottom_pane(self):
        self.bottom_pane = QStackedWidget()
        self.welcome_widget = self._create_welcome_widget()
        self.tree_view = self._create_tree_view()
        self.search_results_list = QListWidget()
        self.search_results_list.itemDoubleClicked.connect(self.open_selected_item)
        self.bottom_pane.addWidget(self.welcome_widget)
        self.bottom_pane.addWidget(self.tree_view)
        self.bottom_pane.addWidget(self.search_results_list)
        return self.bottom_pane
    
    def _create_welcome_widget(self):
        widget = QWidget()
        widget.setObjectName("WelcomeWidget")
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        welcome_label = QLabel("Welcome to PARA File Manager")
        welcome_label.setFont(QFont("Segoe UI", 24, QFont.Weight.Bold))
        info_label = QLabel("To get started, please set your main PARA folder in the settings.")
        info_label.setFont(QFont("Segoe UI", 12))
        open_settings_button = QPushButton("Open Settings")
        open_settings_button.clicked.connect(self.open_settings_dialog)
        open_settings_button.setFixedWidth(200)
        layout.addWidget(welcome_label, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(info_label, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(20)
        layout.addWidget(open_settings_button, alignment=Qt.AlignmentFlag.AlignCenter)
        return widget

    def _create_tree_view(self):
        self.file_system_model = QFileSystemModel()
        self.file_system_model.setFilter(QDir.Filter.AllDirs | QDir.Filter.NoDotAndDotDot | QDir.Filter.AllEntries)
        tree_view = DropTreeView(self)
        tree_view.setModel(self.file_system_model)
        tree_view.setSortingEnabled(True)
        tree_view.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        return tree_view

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.set_drop_frame_style(True)

    def dragLeaveEvent(self, event):
        self.reset_drop_frame_styles()
        event.accept()

    def set_drop_frame_style(self, is_dragging):
        for frame in self.drop_frames.values():
            frame.setProperty("dragging", is_dragging)
            frame.style().polish(frame)

    def reset_drop_frame_styles(self):
        self.set_drop_frame_style(False)

    def log_and_show(self, message, level="info", duration=5000):
        self.statusBar().showMessage(message, duration)
        if level == "info": self.logger.info(message)
        elif level == "warn": self.logger.warn(message)
        elif level == "error": self.logger.error(message)
        QApplication.processEvents()

    def run_task(self, task_func, on_success, **kwargs):
        if self.worker and self.worker.isRunning():
            self.log_and_show("A background task is already running.", "warn")
            return
        self.progress = QProgressDialog("Preparing task...", "Cancel", 0, 100, self)
        self.progress.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress.canceled.connect(self.cancel_task)
        self.progress.show()
        
        self.worker = Worker(task_func, **kwargs)
        self.worker.result.connect(on_success)
        self.worker.error.connect(self.on_task_error)
        self.worker.progress.connect(self.update_progress)
        self.worker.finished.connect(self.on_task_truly_finished)
        self.worker.start()

    def cancel_task(self):
        if self.worker and self.worker.isRunning():
            self.worker.terminate()
            self.log_and_show("Task cancelled by user.", "warn")

    def update_progress(self, message, current, total):
        if self.progress and not self.progress.wasCanceled():
            self.progress.setLabelText(message)
            self.progress.setMaximum(total)
            self.progress.setValue(current)

    def on_task_error(self, error_message):
        if self.progress: self.progress.close()
        # 生产环境不显示
        # self.log_and_show("ERROR: A background task failed. Check logs for details.", "error")
        # self.logger.error(f"Background task failed: {error_message}", exc_info=False)

    def on_task_truly_finished(self):
        if self.progress and self.progress.isVisible():
            self.progress.setValue(self.progress.maximum())
        # We don't show "Task Finished" here anymore, as specific callbacks handle it.

    # --- Core Logic with New Transparent Workflow ---
    def reload_configuration(self):
        self.log_and_show("Reloading configuration...", "info", 2000)
        try:
            with open(resource_path("config.json"), "r") as f:
                config = json.load(f)
                path = config.get("base_directory")
            if not path:
                raise ValueError("Base directory not set in config.")
            self.base_dir = os.path.normpath(path)
            os.makedirs(self.base_dir, exist_ok=True)
            with open(resource_path("rules.json"), "r") as f:
                self.rules = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, ValueError) as e:
            self.log_and_show(f"Configuration incomplete. Please set a valid base directory.", "warn")
            self.logger.warn(f"Config load error: {e}")
            self.bottom_pane.setCurrentWidget(self.welcome_widget)
            return
        self.update_ui_from_config()

    def update_ui_from_config(self):
        if not self.base_dir or not os.path.isdir(self.base_dir):
            self.bottom_pane.setCurrentWidget(self.welcome_widget)
            return
        
        self.bottom_pane.setCurrentWidget(self.tree_view)
        self.file_system_model.setRootPath(self.base_dir)
        self.tree_view.setRootIndex(self.file_system_model.index(self.base_dir))
        for i in range(1, self.file_system_model.columnCount()):
            self.tree_view.hideColumn(i)
        
        self.log_and_show(f"Configuration loaded. Root: {self.base_dir}", "info")
        # self.run_task(self._task_rebuild_file_index, on_success=lambda r: self.log_and_show(r, "info", 2000))
        self.run_task(self._task_rebuild_file_index, on_success=self.on_index_rebuilt)
        
    
    def process_dropped_items(self, dropped_paths, category_name):
        if not self.base_dir:
            self.log_and_show("Please set a base directory first.", "warn")
            return
        
        dest_root = os.path.join(self.base_dir, self.para_folders[category_name])
        os.makedirs(dest_root, exist_ok=True)
        
        if os.listdir(dest_root):
            dialog = PreOperationDialog(self.para_folders[category_name], self)
            if not dialog.exec():
                self.log_and_show("Operation cancelled.", "warn")
                return

            if dialog.result == "skip":
                self.run_task(self._task_process_simple_drop, on_success=self.on_final_refresh_finished,
                              dropped_paths=dropped_paths, dest_root=dest_root, category_name=category_name)
            elif dialog.result == "scan":
                hash_dialog = HashingSelectionDialog(dest_root, self)
                if not hash_dialog.exec():
                    self.log_and_show("Operation cancelled.", "warn")
                    return
                
                files_to_hash_dest = hash_dialog.get_checked_files()
                on_scan_completed_with_context = partial(self.on_scan_completed, dest_root=dest_root, category_name=category_name)
                self.run_task(self._task_scan_for_duplicates, on_success=on_scan_completed_with_context,
                              source_paths=dropped_paths, files_to_hash_dest=files_to_hash_dest)
        else:
            self.log_and_show("Destination is empty, performing fast move.", "info")
            self.run_task(self._task_process_simple_drop, on_success=self.on_final_refresh_finished,
                          dropped_paths=dropped_paths, dest_root=dest_root, category_name=category_name)
    
    # --- Task Callbacks (Slots) ---
    def on_scan_completed(self, result, dest_root, category_name):
        if self.progress: self.progress.close()
        
        duplicates = result["duplicates"]
        non_duplicates = result["non_duplicates"]
        
        user_choices = {}
        if duplicates:
            dedup_dialog = DeduplicationDialog(duplicates, self)
            if dedup_dialog.exec():
                user_choices = dedup_dialog.get_user_choices()
            else:
                self.log_and_show("Operation cancelled.", "warn")
                return
        
        files_to_process = non_duplicates + [p for p, _, _ in duplicates]
        
        self.run_task(self._task_process_final_drop, on_success=self.on_final_refresh_finished,
                      dropped_paths=files_to_process, dest_root=dest_root,
                      choices=user_choices, category_name=category_name)

    def on_final_refresh_finished(self, result=None):
        if result: self.log_and_show(str(result), "info")
        self.run_task(self._task_rebuild_file_index, on_success=self.on_index_rebuilt)
        # self.run_task(self._task_rebuild_file_index, on_success=lambda r: self.log_and_show(r, "info", 2000))
    
    def on_index_rebuilt(self, index_data):
        """This slot runs in the main thread to receive index results and update the UI."""
        self.log_and_show(f"Indexing complete. {len(index_data)} items indexed.", "info", 2000)
        self.file_index = index_data
        # Now it's safe to call handle_search to refresh the UI
        self.handle_search(self.search_bar.text())
    # --- Background Tasks (Workers) ---
    def _task_scan_for_duplicates(self, progress_callback, source_paths, files_to_hash_dest):
        source_files = get_all_files_in_paths(source_paths)
        total_work = len(files_to_hash_dest) + len(source_files)
        current_work = 0
        self.logger.info(f"Starting Smart Scan. Total work units: {total_work}.")

        self.logger.info(f"Phase 1: Hashing {len(files_to_hash_dest)} destination files.")
        dest_hashes = {}
        for f in files_to_hash_dest:
            progress_callback(f"Hashing destination: {os.path.basename(f)}", current_work, total_work)
            self.logger.info(f"Hashing destination file: {f}")
            if (file_hash := calculate_hash(f)):
                dest_hashes[file_hash] = f
            current_work += 1

        self.logger.info(f"Phase 2: Checking {len(source_files)} source files for duplicates.")
        duplicates, non_duplicates = [], []
        # Pre-calculating sizes of destination files for a small speed boost
        dest_size_to_hash = {}
        for h, p in dest_hashes.items():
            try: dest_size_to_hash[os.path.getsize(p)] = h
            except FileNotFoundError: continue

        for f in source_files:
            progress_callback(f"Checking source file: {os.path.basename(f)}", current_work, total_work)
            try:
                size = os.path.getsize(f)
                if size in dest_size_to_hash:
                    self.logger.info(f"Hashing source (size match): {f}")
                    file_hash = calculate_hash(f)
                    if file_hash and file_hash in dest_hashes:
                        self.logger.info(f"DUPLICATE FOUND: Source '{f}' matches destination '{dest_hashes[file_hash]}'")
                        duplicates.append((f, dest_hashes[file_hash], file_hash))
                    else: non_duplicates.append(f)
                else: non_duplicates.append(f)
            except FileNotFoundError: self.logger.warn(f"Source file not found, skipping: {f}")
            current_work += 1
        
        self.logger.info(f"Scan complete. Found {len(duplicates)} duplicates.")
        return {"duplicates": duplicates, "non_duplicates": non_duplicates}

    def _task_process_simple_drop(self, progress_callback, dropped_paths, dest_root, category_name):
        all_source_files = get_all_files_in_paths(dropped_paths)
        total = len(all_source_files)
        self.logger.info(f"Starting Fast Move of {total} files to {dest_root}")
        for i, old_path in enumerate(all_source_files):
        # for i, old_path in enumerate(tqdm(all_source_files, desc="Fast Moving Files", unit="f", leave=False, ncols=80)):
            progress_callback(f"Moving: {os.path.basename(old_path)}", i + 1, total)
            filename, final_dest_path = os.path.basename(old_path), dest_root
            for rule in self.rules:
                if rule.get("category") == category_name and self.check_rule(rule, filename):
                    action, value = rule.get("action"), rule.get("action_value")
                    if action == "subfolder": final_dest_path = os.path.join(dest_root, value)
                    elif action == "prefix": filename = f"{value}{filename}"
                    break
            new_path = os.path.join(final_dest_path, filename)
            if os.path.exists(new_path):
                base, ext = os.path.splitext(new_path); counter = 1
                while os.path.exists(new_path): new_path = f"{base}_conflict_{counter}{ext}"; counter += 1
                self.logger.warn(f"Name conflict for '{filename}', renaming to '{os.path.basename(new_path)}'")
            try: os.makedirs(os.path.dirname(new_path), exist_ok=True); shutil.move(old_path, new_path)
            except Exception as e: self.logger.error(f"Failed to move {old_path}", exc_info=True)
        
        source_dirs = {os.path.dirname(p) for p in all_source_files}
        for folder in source_dirs:
            try:
                if not os.listdir(folder): shutil.rmtree(folder)
            except Exception: pass
        return "Fast Move complete."

    def _task_process_final_drop(self, progress_callback, dropped_paths, dest_root, choices, category_name):
        total = len(dropped_paths)
        self.logger.info(f"Starting final processing of {total} files to {dest_root}")
        # for i, old_path in enumerate(tqdm(dropped_paths, desc="Finalizing Move", unit="f", leave=False, ncols=80)):
        for i, old_path in enumerate(dropped_paths):
            progress_callback(f"Processing: {os.path.basename(old_path)}", i + 1, total)
            choice = choices.get(old_path)
            if choice == "delete":
                try:
                    os.remove(old_path)
                    self.logger.info(f"User choice: Deleting duplicate source file: {old_path}")
                except Exception as e: self.logger.error(f"Failed to delete {old_path}", exc_info=True)
                continue
            
            filename, final_dest_path = os.path.basename(old_path), dest_root
            for rule in self.rules:
                if rule.get("category") == category_name and self.check_rule(rule, filename):
                    action, value = rule.get("action"), rule.get("action_value")
                    if action == "subfolder": final_dest_path = os.path.join(dest_root, value)
                    elif action == "prefix": filename = f"{value}{filename}"
                    self.logger.info(f"Applying rule '{action}' to '{os.path.basename(old_path)}'")
                    break
            
            new_path = os.path.join(final_dest_path, filename)
            if choice == "keep": # Only rename if user chose to keep a known duplicate
                base, ext = os.path.splitext(new_path); counter = 1
                while os.path.exists(new_path): new_path = f"{base}_duplicate_{counter}{ext}"; counter += 1
                self.logger.info(f"User choice: Keeping duplicate '{filename}', renaming to '{os.path.basename(new_path)}'")
            
            try: os.makedirs(os.path.dirname(new_path), exist_ok=True); shutil.move(old_path, new_path)
            except Exception as e: self.logger.error(f"Failed to move {old_path}", exc_info=True)
        
        source_dirs = {p for p in get_all_files_in_paths(dropped_paths) if os.path.isdir(p)} # Needs re-evaluation
        for folder in source_dirs:
            try:
                if not os.listdir(folder): shutil.rmtree(folder)
            except Exception: pass
        return "File processing complete."

    def _task_rebuild_file_index(self, progress_callback):
        self.logger.info("Rebuilding file index...")
        progress_callback("Indexing files...", 0, 1)
        self.file_index.clear()
        if not self.base_dir: return "Index empty: No base directory."
        
        all_items = get_all_files_in_paths([self.base_dir])
        total = len(all_items)
        # for i, path in enumerate(tqdm(all_items, desc="Indexing", unit="items", leave=False, ncols=80)):
        # for i, path in enumerate(all_items):
        #     progress_callback(f"Indexing ({i+1}/{total})", i + 1, total)
        #     self.file_index.append((os.path.basename(path).lower(), path))
        
        # # self.handle_search(self.search_bar.text())
        # return f"Indexing complete. {len(self.file_index)} items indexed."
        for i, path in enumerate(all_items):
        # Only send a progress update every 100 files to avoid flooding the UI thread
            if (i + 1) % 100 == 0:
                progress_callback(f"Indexing ({i+1}/{total})", i + 1, total)
            file_index_data.append((os.path.basename(path).lower(), path))

        # Ensure the progress bar always finishes at 100%
        progress_callback("Finalizing index...", total, total)
        return file_index_data

    def handle_search(self, text):
        term = text.lower().strip()
        if not term:
            if self.base_dir: self.bottom_pane.setCurrentWidget(self.tree_view)
            return
        
        self.bottom_pane.setCurrentWidget(self.search_results_list)
        self.search_results_list.clear()
        if not self.file_index: return
        
        results = [(name, path) for name, path in self.file_index if term in name]
        for name, path in results:
            rel_path = os.path.relpath(os.path.dirname(path), self.base_dir)
            if rel_path == '.': rel_path = 'Root'
            html = f"""<div><span style='font-size: 11pt;'>{os.path.basename(path)}</span><br><span style='font-size: 8pt; color: #82c0ff;'>In: {rel_path}</span></div>"""
            item = QListWidgetItem()
            label = QLabel(html)
            label.setToolTip(path)
            item.setSizeHint(label.sizeHint())
            item.setData(Qt.ItemDataRole.UserRole, path)
            self.search_results_list.addItem(item)
            self.search_results_list.setItemWidget(item, label)
    
    def get_category_from_path(self, path):
        if not self.base_dir: return None
        norm_path = os.path.normpath(path)
        for cat_name, folder_name in self.para_folders.items():
            cat_path = os.path.join(self.base_dir, folder_name)
            if norm_path == cat_path or norm_path.startswith(cat_path + os.sep):
                return cat_name
        return None
            
    def show_context_menu(self, pos):
        index = self.tree_view.indexAt(pos)
        if not index.isValid(): return
        path = self.file_system_model.filePath(index)
        menu = QMenu()
        style = self.style()
        menu.addAction(style.standardIcon(QStyle.StandardPixmap.SP_DialogOkButton), "Open", lambda: self.open_item(path))
        menu.addAction(style.standardIcon(QStyle.StandardPixmap.SP_DirIcon), "Show in File Explorer", lambda: self.show_in_explorer(path))
        menu.addSeparator()
        menu.addAction(style.standardIcon(QStyle.StandardPixmap.SP_FileLinkIcon), "Rename...", lambda: self.rename_item(index))
        menu.addAction(style.standardIcon(QStyle.StandardPixmap.SP_TrashIcon), "Delete...", lambda: self.delete_item(index))
        menu.exec(self.tree_view.viewport().mapToGlobal(pos))

    def open_selected_item(self, item_or_index):
        path = ""
        if isinstance(item_or_index, QListWidgetItem): path = item_or_index.data(Qt.ItemDataRole.UserRole)
        elif isinstance(item_or_index, QModelIndex): path = self.file_system_model.filePath(item_or_index)
        if path: self.open_item(path)

    def open_item(self, path):
        try:
            path = os.path.normpath(path)
            self.logger.info(f"Opening: {path}")
            if sys.platform == "win32": os.startfile(path)
            else: subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", path])
        except Exception as e:
            self.log_and_show(f"Could not open {os.path.basename(path)}", "error")
            self.logger.error(f"Failed to open {path}", exc_info=True)

    def show_in_explorer(self, path):
        try:
            path = os.path.normpath(path)
            self.logger.info(f"Showing in explorer: {path}")
            if sys.platform == "win32": subprocess.run(["explorer", "/select,", path])
            else: subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", "-R", path])
        except Exception as e:
            self.log_and_show("Could not show item in explorer.", "error")
            self.logger.error(f"Failed to show {path}", exc_info=True)

    def rename_item(self, index):
        old_path = self.file_system_model.filePath(index)
        old_filename = os.path.basename(old_path)
        new_filename, ok = QInputDialog.getText(self, "Rename", "New name:", text=old_filename)
        if ok and new_filename and new_filename != old_filename:
            new_path = os.path.join(os.path.dirname(old_path), new_filename)
            try:
                os.rename(old_path, new_path)
                self.log_and_show(f"Renamed to '{new_filename}'", "info")
                self.logger.info(f"Renamed {old_path} to {new_path}")
                self.run_task(self._task_rebuild_file_index, on_success=self.on_final_refresh_finished)
            except Exception as e:
                self.log_and_show(f"Could not rename file.", "error")
                self.logger.error(f"Failed to rename {old_path}", exc_info=True)

    def delete_item(self, index):
        path = self.file_system_model.filePath(index)
        filename = os.path.basename(path)
        if not os.path.exists(path):
            self.log_and_show(f"ERROR: '{filename}' no longer exists.", "error")
            return
        
        reply = QMessageBox.warning(self, "Confirm Delete", f"Move this item to the Recycle Bin?\n\n'{filename}'",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            try:
                send2trash.send2trash(path)
                self.log_and_show(f"Moved '{filename}' to Recycle Bin", "info")
                self.logger.info(f"Trashed {path}")
                self.run_task(self._task_rebuild_file_index, on_success=self.on_final_refresh_finished)
            except Exception as e:
                self.log_and_show("Could not move to Recycle Bin.", "error")
                self.logger.error(f"Failed to trash {path}", exc_info=True)

    def check_rule(self, rule, filename):
        cond_type = rule.get("condition_type")
        cond_val = rule.get("condition_value", "").lower()
        if not cond_val: return False
        
        filename_lower = filename.lower()
        if cond_type == "extension":
            return any(filename_lower.endswith(ext.strip()) for ext in cond_val.split(',') if ext.strip())
        elif cond_type == "keyword":
            return cond_val in filename_lower
        return False

    def open_log_viewer(self):
        try:
            dialog = LogViewerDialog(self.logger, self)
            dialog.setWindowIcon(self.windowIcon())
            dialog.exec()
        except Exception as e:
            self.logger.error(f"Failed to open log viewer: {e}", exc_info=True)
            
    def open_settings_dialog(self):
        dialog = SettingsDialog(self)
        dialog.setWindowIcon(self.windowIcon())
        if dialog.exec():
            self.log_and_show("Settings saved. Reloading configuration...", "info")
            self.reload_configuration()
    
# --- EXECUTION BLOCK ---
if __name__ == "__main__":
    app = QApplication(sys.argv)
    try:
        main_logger = Logger()
        window = ParaFileManager(main_logger)
        try:
            window.setWindowIcon(QIcon(resource_path('icon.ico')))
        except Exception as e:
            main_logger.warn(f"Could not load application icon: {e}")
        window.show()
        sys.exit(app.exec())
    except Exception as e:
        print(f"A fatal error occurred during application startup: {e}")
        traceback.print_exc()
        try:
            with open("crash_report.log", "a", encoding="utf-8") as f:
                f.write(f"\n--- CRASH AT {datetime.now()} ---\n")
                traceback.print_exc(file=f)
        except:
            pass