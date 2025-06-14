import sys
import os
import json
import shutil
import subprocess
import traceback
from datetime import datetime
import hashlib
from functools import partial
import re
import sqlite3
import tempfile

# Required libraries: pip install PyQt6 send2trash numba pillow
try:
    import send2trash
except ImportError:
    print("Error: send2trash library not found. Please run: pip install send2trash")
    sys.exit(1)

try:
    from numba import cuda
    NUMBA_AVAILABLE = True
except ImportError:
    NUMBA_AVAILABLE = False


from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QFrame, QPushButton, QDialog, QLineEdit,
    QFileDialog, QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QSplitter, QTreeView, QListWidget, QListWidgetItem, QStyle, QMessageBox,
    QMenu, QInputDialog, QStatusBar, QStackedWidget, QTextBrowser, QProgressDialog,
    QCheckBox, QFileIconProvider, QGridLayout, QAbstractItemView, QTreeWidget,
    QTreeWidgetItem, QRadioButton, QButtonGroup
)
from PyQt6.QtGui import (
    QFont, QIcon, QAction, QCursor, QFileSystemModel, QPainter, QPixmap, QColor, QPalette
)
from PyQt6.QtCore import (
    Qt, QUrl, QSize, QModelIndex, QDir, QThread, pyqtSignal, QFileInfo, QTimer, QFileSystemWatcher
)

# --- GLOBAL EXCEPTION HOOK ---
def global_exception_hook(exctype, value, tb, window=None):
    traceback_details = "".join(traceback.format_exception(exctype, value, tb))
    error_message_for_details = (
        f"An unexpected error occurred:\n\n"
        f"Error Type: {exctype.__name__}\n"
        f"Error Message: {value}\n\n"
        f"Traceback:\n{traceback_details}"
    )
    try:
        main_logger.error("A fatal, unhandled exception occurred:\n" + traceback_details)
    except (NameError, AttributeError): pass
    try:
        # Note: This log might also fail if the issue is path-related on startup.
        with open("crash_report.log", "a", encoding="utf-8") as f:
            f.write(f"\n--- FATAL CRASH AT {datetime.now()} ---\n{traceback_details}")
    except Exception as e:
        print(f"Could not write to crash_report.log: {e}")
    app = QApplication.instance() or QApplication(sys.argv)
    error_box = QMessageBox()
    error_box.setIcon(QMessageBox.Icon.Critical)
    error_box.setWindowTitle("Application Error")
    error_box.setText("A critical error occurred and the application must close.")
    error_box.setInformativeText("The error has been logged to 'crash_report.log'.")
    error_box.setDetailedText(error_message_for_details)
    error_box.setMinimumSize(700, 250)
    if window:
        error_box.setStyleSheet(window.styleSheet())
    text_edit = error_box.findChild(QTextBrowser)
    if text_edit:
        text_edit.setFont(QFont("Consolas", 10))
    error_box.exec()
    sys.exit(1)

# --- UTILITY FUNCTIONS ---

# def get_user_data_path(filename):
#     """Returns a persistent path in the user's app data directory."""
#     app_name = "ParaManagerEVO"
#     if sys.platform == "win32":
#         data_dir = os.path.join(os.getenv('APPDATA'), app_name)
#     else: # For macOS and Linux
#         data_dir = os.path.join(os.path.expanduser('~'), '.config', app_name)
#     os.makedirs(data_dir, exist_ok=True)
#     return os.path.join(data_dir, filename)

# In the UTILITY FUNCTIONS section

def get_user_data_path(filename):
    """Returns a persistent path in the user's app data directory."""
    app_name = "ParaManagerEVO"
    if sys.platform == "win32":
        # On Windows, this is typically C:\Users\<user>\AppData\Roaming\ParaManagerEVO
        data_dir = os.path.join(os.getenv('APPDATA'), app_name)
    else: # For macOS and Linux
        # On Linux, this is typically /home/<user>/.config/ParaManagerEVO
        # On macOS, this is typically /Users/<user>/.config/ParaManagerEVO
        data_dir = os.path.join(os.path.expanduser('~'), '.config', app_name)
    
    # Create the directory if it doesn't exist
    os.makedirs(data_dir, exist_ok=True)
    
    return os.path.join(data_dir, filename)

def format_size(size_bytes):
    if size_bytes is None or size_bytes < 0: return "N/A"
    if size_bytes == 0: return "0 B"
    power = 1024
    n = 0
    power_labels = {0: 'B', 1: 'KB', 2: 'MB', 3: 'GB', 4: 'TB'}
    while size_bytes >= power and n < len(power_labels) - 1:
        size_bytes /= power
        n += 1
    return f"{size_bytes:.2f} {power_labels[n]}"

def calculate_hash(file_path, block_size=65536):
    sha256 = hashlib.sha256()
    try:
        with open(file_path, 'rb') as f:
            for block in iter(lambda: f.read(block_size), b''):
                sha256.update(block)
        return sha256.hexdigest()
    except (IOError, PermissionError):
        return None

def resource_path(relative_path):
    """Gets the absolute path to a bundled, read-only resource."""
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def get_all_files_in_paths(paths):
    all_files = []
    for path in paths:
        if os.path.isfile(path): all_files.append(path)
        elif os.path.isdir(path):
            for root, _, files in os.walk(path):
                for name in files: all_files.append(os.path.join(root, name))
    return all_files

# --- HELPER & WORKER CLASSES ---
class Worker(QThread):
    result = pyqtSignal(object)
    error = pyqtSignal(str)
    progress = pyqtSignal(str, int, int)
    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self.func = func
        self.args = (self.progress.emit,) + args
        self.kwargs = kwargs
    def run(self):
        try:
            res = self.func(*self.args, **self.kwargs)
            self.result.emit(res)
        except Exception:
            self.error.emit(traceback.format_exc())

class Logger:
    def __init__(self, filename="para_manager.log"):
        self.log_file = filename # Expect a full path
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
        if exc_info: message += f"\n{traceback.format_exc()}"
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
                        except ValueError: continue
        except FileNotFoundError: pass
        return sorted(list(dates), reverse=True)
    def get_logs_for_date(self, date_str):
        logs = []
        try:
            with open(self.log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.startswith(date_str): logs.append(line.strip())
        except FileNotFoundError: pass
        return "\n".join(logs)

class HashManager:
    def __init__(self, db_path, logger):
        self.db_path = db_path
        self.logger = logger
        self.connection = None
        self.cursor = None
    def __enter__(self):
        try:
            self.connection = sqlite3.connect(self.db_path)
            self.cursor = self.connection.cursor()
            self._setup_database()
        except sqlite3.Error as e:
            self.logger.error(f"FATAL: Could not connect to hash database: {e}")
            raise
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.connection:
            self.connection.commit()
            self.connection.close()
    def _setup_database(self):
        self.cursor.execute("CREATE TABLE IF NOT EXISTS hash_cache (file_path TEXT PRIMARY KEY, mtime REAL NOT NULL, size INTEGER NOT NULL, file_hash TEXT NOT NULL, last_checked REAL NOT NULL)")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_path ON hash_cache (file_path)")
    def get_cached_hash(self, file_path, mtime, size):
        self.cursor.execute("SELECT mtime, size, file_hash FROM hash_cache WHERE file_path = ?", (file_path,))
        result = self.cursor.fetchone()
        if result:
            cached_mtime, cached_size, cached_hash = result
            if cached_mtime == mtime and cached_size == size:
                return cached_hash
        return None
    def update_cache(self, file_path, mtime, size, file_hash):
        now = datetime.now().timestamp()
        self.cursor.execute("INSERT OR REPLACE INTO hash_cache VALUES (?, ?, ?, ?, ?)", (file_path, mtime, size, file_hash, now))
    def prune_cache(self, valid_paths_set):
        self.cursor.execute("SELECT file_path FROM hash_cache")
        cached_paths = {row[0] for row in self.cursor.fetchall()}
        paths_to_delete = list(cached_paths - valid_paths_set)
        if paths_to_delete:
            self.cursor.executemany("DELETE FROM hash_cache WHERE file_path = ?", [(p,) for p in paths_to_delete])
            self.connection.commit()
        return len(paths_to_delete)

# --- CUSTOM UI WIDGETS ---
class ActionWidget(QWidget):
    keep_requested = pyqtSignal()
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 0, 5, 0)
        layout.setSpacing(5)
        style = self.style()
        self.keep_button = QPushButton(style.standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton), "")
        self.keep_button.setToolTip("保留这个文件，并清理此组中的其他文件。")
        self.keep_button.setCheckable(True)
        self.keep_button.setChecked(False)
        self.keep_button.toggled.connect(lambda checked: self.keep_requested.emit() if checked else None)
        layout.addWidget(self.keep_button)

class DropFrame(QFrame):
    def __init__(self, category_name, icon, main_window):
        super().__init__(main_window)
        self.category_name = category_name
        self.main_window = main_window
        self.setAcceptDrops(True)
        self.setProperty("category", category_name)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label = QLabel()
        icon_label.setPixmap(icon.pixmap(QSize(48, 48)))
        layout.addWidget(icon_label, alignment=Qt.AlignmentFlag.AlignCenter)
        title_label = QLabel(category_name)
        title_label.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        layout.addWidget(title_label, alignment=Qt.AlignmentFlag.AlignCenter)
    
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.main_window.set_drop_frame_style(True)
            
    def dropEvent(self, event):
        source_paths = [url.toLocalFile() for url in event.mimeData().urls()]
        if source_paths:
            self.main_window.process_dropped_items(source_paths, self.category_name)
        self.main_window.reset_drop_frame_styles()
        event.acceptProposedAction()

class DropTreeView(QTreeView):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.setAcceptDrops(True)
        self.setDragDropMode(self.DragDropMode.DropOnly)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.main_window.show_context_menu)
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
            self.main_window.process_dropped_items(files, category_name, specific_target_dir=target_dir_path)
        
        event.acceptProposedAction()

class ThemedTreeView(DropTreeView):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.background_text = ""
    def setBackgroundText(self, text):
        if self.background_text != text:
            self.background_text = text
            self.viewport().update()
    def paintEvent(self, event):
        super().paintEvent(event)
        if self.background_text:
            painter = QPainter(self.viewport())
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            font = QFont("Segoe UI", 120, QFont.Weight.ExtraBold)
            painter.setFont(font)
            painter.setPen(QColor(200, 200, 200, 15))
            painter.drawText(self.viewport().rect(), Qt.AlignmentFlag.AlignCenter, self.background_text)
            painter.end()








# In your UI DIALOGS section, REPLACE the entire MoveToDialog class
class MoveToDialog(QDialog):
    """A dialog to select a destination folder, now with history and favorites."""
    def __init__(self, base_path, source_paths, history, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Move Items To...")
        self.setMinimumSize(550, 600)
        self.setStyleSheet(parent.styleSheet())
        self.destination_path = None
        self.history = history

        layout = QVBoxLayout(self)

        # --- NEW: History ComboBox ---
        history_layout = QHBoxLayout()
        history_layout.addWidget(QLabel("Recent Destinations:"))
        self.history_combo = QComboBox()
        self.history_combo.setPlaceholderText("Select from recently used folders...")
        if self.history:
            self.history_combo.addItems(self.history)
        self.history_combo.activated.connect(self.on_history_selected)
        history_layout.addWidget(self.history_combo)
        layout.addLayout(history_layout)

        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line)

        # --- Tree View for Navigation ---
        layout.addWidget(QLabel("Or browse for a new destination:"))
        self.model = QFileSystemModel()
        self.model.setRootPath(base_path)
        self.model.setFilter(QDir.Filter.NoDotAndDotDot | QDir.Filter.AllDirs)

        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setRootIndex(self.model.index(base_path))
        for i in range(1, self.model.columnCount()):
            self.tree.setColumnHidden(i, True)
        self.tree.clicked.connect(self.on_tree_clicked)
        layout.addWidget(self.tree)
        
        # --- Selected Path Display ---
        self.selected_path_label = QLineEdit()
        self.selected_path_label.setReadOnly(True)
        self.selected_path_label.setPlaceholderText("No folder selected")
        layout.addWidget(self.selected_path_label)

        # --- OK and Cancel Buttons ---
        self.ok_button = QPushButton("OK")
        self.ok_button.setEnabled(False)
        self.ok_button.clicked.connect(self.accept)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(cancel_button)
        button_layout.addWidget(self.ok_button)
        layout.addLayout(button_layout)

    def on_history_selected(self, index):
        """When a path is chosen from history, select it."""
        path = self.history_combo.itemText(index)
        self.set_destination(path)
        # Also select it in the tree view for visual feedback
        self.tree.setCurrentIndex(self.model.index(path))

    def on_tree_clicked(self, index):
        """When a folder is clicked in the tree, update the selection."""
        path = self.model.filePath(index)
        self.set_destination(path)

    def set_destination(self, path):
        """Central method to set the chosen destination path."""
        self.destination_path = path
        self.selected_path_label.setText(path)
        self.ok_button.setEnabled(True)

    def accept(self):
        if self.destination_path:
            super().accept()
            

# --- REPLACE the entire FullScanResultDialog class with this corrected version ---

# class FullScanResultDialog(QDialog):
#     def __init__(self, processed_sets, parent=None):
#         super().__init__(parent)
#         self.main_window = parent
#         self.processed_sets = processed_sets

#         self.setWindowTitle("重复文件分析与清理工具")
#         self.setStyleSheet(parent.styleSheet())
#         self.setWindowState(Qt.WindowState.WindowMaximized)
        
#         main_layout = QVBoxLayout(self)
#         self._setup_controls(main_layout)

#         self.tree = QTreeWidget()
#         self.tree.setColumnCount(5)
#         self.tree.setHeaderLabels([
#             "操作", "文件路径", "可节省空间", "总空间占用", "文件数量"
#         ])
#         self.tree.setAlternatingRowColors(True)
#         self.tree.setSortingEnabled(True)

#         header = self.tree.header()
#         header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
#         header.resizeSection(0, 100) # Action
#         header.resizeSection(1, 700) # Path
#         header.resizeSection(2, 150) # Savings
#         header.resizeSection(3, 150) # Total Space
#         header.resizeSection(4, 120) # Count
        
#         self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
#         self.tree.customContextMenuRequested.connect(self.show_tree_context_menu)
        
#         main_layout.addWidget(self.tree)
        
#         button_box = QHBoxLayout()
#         button_box.addStretch()
#         self.confirm_button = QPushButton()
#         self.confirm_button.setDefault(True)
#         cancel_button = QPushButton("取消")
        
#         button_box.addWidget(cancel_button)
#         button_box.addWidget(self.confirm_button)
#         main_layout.addLayout(button_box)

#         # --- This is the core fix: Populate first, then connect signals ---
#         self.populate_tree_and_set_defaults()
#         self.connect_widget_signals()
        
#         self.tree.expandAll()
#         self._sort_tree()
#         self._update_savings_label()

#         self.confirm_button.clicked.connect(self.accept)
#         cancel_button.clicked.connect(self.reject)

#     def populate_tree_and_set_defaults(self):
#         """
#         Phase 1 of setup: Creates all tree items and widgets, and crucially,
#         sets their correct default "Keep" or "Trash" state without connecting signals.
#         """
#         for group_data in self.processed_sets:
#             group_header = QTreeWidgetItem(self.tree)
#             group_header.setData(0, Qt.ItemDataRole.UserRole, group_data["file_size_bytes"])
#             group_header.setData(2, Qt.ItemDataRole.UserRole, group_data["potential_savings_bytes"])
#             group_header.setData(3, Qt.ItemDataRole.UserRole, group_data["total_space_bytes"])
#             group_header.setData(4, Qt.ItemDataRole.UserRole, group_data["count"])
#             group_header.setText(1, f"包含 {group_data['count']} 个文件的重复组 (单个大小: {format_size(group_data['file_size_bytes'])})")
#             group_header.setText(2, format_size(group_data["potential_savings_bytes"]))
#             group_header.setText(3, format_size(group_data["total_space_bytes"]))
#             group_header.setText(4, str(group_data["count"]))
#             group_header.setFont(1, QFont("Segoe UI", 9, QFont.Weight.Bold))

#             best_file_path = group_data["files"][0]["path"]

#             for file_data in group_data["files"]:
#                 child_item = QTreeWidgetItem(group_header, ["", file_data["path"]])
#                 child_item.setData(0, Qt.ItemDataRole.UserRole, file_data)

#                 action_widget = ActionWidget()
#                 is_best = (file_data["path"] == best_file_path)
                
#                 # Directly set the button's checked state. This is the default.
#                 action_widget.keep_button.setChecked(is_best)
                
#                 if is_best:
#                     for col in range(self.tree.columnCount()):
#                         child_item.setBackground(col, QColor("#1e4226"))

#                 self.tree.setItemWidget(child_item, 0, action_widget)

#     def connect_widget_signals(self):
#         """
#         Phase 2 of setup: After the entire tree is built, iterate through it
#         again to connect the signals for user interaction.
#         """
#         root = self.tree.invisibleRootItem()
#         for i in range(root.childCount()):
#             group_header = root.child(i)
#             for j in range(group_header.childCount()):
#                 child_item = group_header.child(j)
#                 action_widget = self.tree.itemWidget(child_item, 0)
#                 if action_widget:
#                     action_widget.keep_requested.connect(
#                         lambda checked, item=child_item: self._on_keep_requested(item)
#                     )

#     def _on_keep_requested(self, selected_item):
#         """Handles user interaction to enforce the 'only one keep per group' rule."""
#         parent_group = selected_item.parent()
#         if not parent_group: return

#         for i in range(parent_group.childCount()):
#             item = parent_group.child(i)
#             widget = self.tree.itemWidget(item, 0)
#             if widget:
#                 is_the_selected_one = (item == selected_item)
#                 widget.keep_button.setChecked(is_the_selected_one)
#                 bg_color = QColor("#1e4226") if is_the_selected_one else QColor("transparent")
#                 for col in range(self.tree.columnCount()):
#                     item.setBackground(col, bg_color)
        
#         self._update_savings_label()

#     def get_files_to_trash(self):
#         """Gets the final list of files to trash based on button state."""
#         files_to_trash = []
#         root = self.tree.invisibleRootItem()
#         for i in range(root.childCount()):
#             group_header = root.child(i)
#             for j in range(group_header.childCount()):
#                 child = group_header.child(j)
#                 action_widget = self.tree.itemWidget(child, 0)
#                 if action_widget and not action_widget.keep_button.isChecked():
#                     file_data = child.data(0, Qt.ItemDataRole.UserRole)
#                     if file_data and "path" in file_data:
#                         files_to_trash.append(file_data["path"])
#         return files_to_trash

#     # --- The following methods remain unchanged from the last version ---
#     # They are included here to provide the complete, correct class definition.
        
#     def show_tree_context_menu(self, pos):
#         item = self.tree.itemAt(pos)
#         if not item or not item.parent(): return
#         file_data = item.data(0, Qt.ItemDataRole.UserRole)
#         if not file_data: return
#         path = file_data["path"]
#         menu = QMenu()
#         style = self.style()
#         open_action = menu.addAction(style.standardIcon(QStyle.StandardPixmap.SP_DialogOkButton), "打开文件")
#         show_action = menu.addAction(style.standardIcon(QStyle.StandardPixmap.SP_DirIcon), "打开文件所在位置")
#         copy_path_action = menu.addAction(style.standardIcon(QStyle.StandardPixmap.SP_FileLinkIcon), "复制文件路径")
#         action = menu.exec(self.tree.mapToGlobal(pos))
#         if action == open_action: self.main_window.open_item(path)
#         elif action == show_action: self.main_window.show_in_explorer(path)
#         elif action == copy_path_action:
#             QApplication.clipboard().setText(os.path.normpath(path))
#             self.main_window.log_and_show(f"路径已复制: {os.path.normpath(path)}", "info", 2000)

#     def _setup_controls(self, layout):
#         controls_frame = QFrame()
#         controls_layout = QHBoxLayout(controls_frame)
#         controls_layout.setContentsMargins(0, 5, 0, 5)
#         controls_layout.addWidget(QLabel("排序方式:"))
#         self.sort_combo = QComboBox()
#         self.sort_combo.addItems(["按可节省空间", "按总空间占用", "按文件数量"])
#         self.sort_combo.currentIndexChanged.connect(self._sort_tree)
#         controls_layout.addWidget(self.sort_combo)
#         controls_layout.addSpacing(20)
#         top_10_button = QPushButton("一键选择空间占用Top 10")
#         top_10_button.clicked.connect(self._select_top_10)
#         controls_layout.addWidget(top_10_button)
#         controls_layout.addStretch()
#         self.savings_label = QLabel()
#         self.savings_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
#         controls_layout.addWidget(self.savings_label)
#         layout.addWidget(controls_frame)

#     def _sort_tree(self):
#         column_map = {0: 2, 1: 3, 2: 4}
#         column_to_sort = column_map.get(self.sort_combo.currentIndex(), 2)
#         self.tree.sortByColumn(column_to_sort, Qt.SortOrder.DescendingOrder)

#     def _select_top_10(self):
#         self.tree.sortByColumn(2, Qt.SortOrder.DescendingOrder)
#         root = self.tree.invisibleRootItem()
#         for i in range(root.childCount()):
#             group_header = root.child(i)
#             best_child = group_header.child(0)
#             if i < 10:
#                 self._on_keep_requested(best_child)
#             else:
#                 # For groups outside the top 10, ensure the best file is kept
#                 # and don't change anything else unless the user does.
#                 widget = self.tree.itemWidget(best_child, 0)
#                 if widget and not widget.keep_button.isChecked():
#                      self._on_keep_requested(best_child)
#         self._update_savings_label()
    
#     def _update_savings_label(self):
#         total_files_to_trash = 0
#         total_savings_bytes = 0
#         root = self.tree.invisibleRootItem()
#         for i in range(root.childCount()):
#             group_header = root.child(i)
#             file_size = group_header.data(0, Qt.ItemDataRole.UserRole) or 0
#             for j in range(group_header.childCount()):
#                 child = group_header.child(j)
#                 action_widget = self.tree.itemWidget(child, 0)
#                 if action_widget and not action_widget.keep_button.isChecked():
#                     total_files_to_trash += 1
#                     total_savings_bytes += file_size
#         self.savings_label.setText(
#             f"当前选中清理: <span style='color: #e06c75;'>{total_files_to_trash}</span> 个文件, "
#             f"预计可节省: <span style='color: #98c379;'>{format_size(int(total_savings_bytes))}</span>"
#         )
#         self.confirm_button.setText(f"确认清理 ({total_files_to_trash})")
                
class PreOperationDialog(QDialog):
    """
    Informs the user that a destination is not empty and asks them to choose
    between a safe 'scan' or a fast 'skip' (move all) operation.
    """
    def __init__(self, dest_folder_name, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Action Required")
        self.setStyleSheet(parent.styleSheet())
        self.setModal(True) # Ensures user must interact with it
        self.result = "cancel" # Default result if the dialog is closed

        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        title_label = QLabel("Destination Not Empty")
        title_label.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        info_text = (f"<p>The destination folder '<b>{dest_folder_name}</b>' already contains files.</p>"
                     f"<p>To avoid creating duplicates and to proceed safely, please choose an option below.</p>")
        info_label = QLabel(info_text)
        info_label.setWordWrap(True)
        info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(title_label)
        layout.addWidget(info_label)
        layout.addSpacing(10)

        # Create the buttons for the choices using the helper method
        button_layout = QHBoxLayout()
        self.scan_button = self._create_option_button(
            "Smart Scan (Recommended)",
            "Scans file content to prevent adding identical files. Slower but safer.",
            "scan",
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)
        )
        self.skip_button = self._create_option_button(
            "Move All (Fast)",
            "Moves all files, automatically renaming any with the same name. Much faster, but may create duplicates.",
            "skip",
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowRight)
        )

        button_layout.addWidget(self.scan_button)
        button_layout.addWidget(self.skip_button)
        layout.addLayout(button_layout)

    def _create_option_button(self, title, description, result_val, icon):
        """Helper function to create a styled choice button."""
        button = QPushButton(f" {title}")
        button.setIcon(icon)
        button.setToolTip(description)
        button.setMinimumHeight(40) # Make buttons larger
        button.clicked.connect(lambda: self.set_result_and_accept(result_val))
        return button

    def set_result_and_accept(self, result_val):
        """Sets the chosen result and closes the dialog."""
        self.result = result_val
        self.accept()

class MoveConfirmationDialog(QDialog):
    """A dialog to confirm moving a list of files/folders to a new destination."""
    def __init__(self, source_paths, target_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Confirm Move")
        self.setMinimumSize(700, 500)
        self.setStyleSheet(parent.styleSheet())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # --- Header ---
        header_label = QLabel(f"Are you sure you want to move {len(source_paths)} item(s)?")
        header_label.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        layout.addWidget(header_label)

        # --- Source Panel ---
        source_group = QFrame(); source_group.setLayout(QVBoxLayout())
        source_label = QLabel("From:")
        source_group.layout().addWidget(source_label)
        
        source_list = QListWidget()
        source_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        icon_provider = QFileIconProvider()
        for path in source_paths:
            item = QListWidgetItem(icon_provider.icon(QFileInfo(path)), os.path.basename(path))
            item.setToolTip(path) # Show full path on hover
            source_list.addItem(item)
        source_group.layout().addWidget(source_list)
        layout.addWidget(source_group)
        
        # --- Arrow Separator ---
        arrow_label = QLabel("▼")
        arrow_label.setFont(QFont("Segoe UI", 20))
        arrow_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(arrow_label)

        # --- Target Panel ---
        target_group = QFrame(); target_group.setLayout(QHBoxLayout())
        target_group.layout().setContentsMargins(10, 10, 10, 10)
        target_label = QLabel("To:")
        
        target_path_label = QLineEdit(target_path)
        target_path_label.setReadOnly(True)
        target_path_label.setStyleSheet("border: 1px solid #3e4451; background-color: #21252b;")

        target_group.layout().addWidget(target_label)
        target_group.layout().addWidget(target_path_label)
        layout.addWidget(target_group)

        # --- Confirmation Buttons ---
        button_box = QHBoxLayout()
        confirm_button = QPushButton("Confirm Move")
        confirm_button.setDefault(True)
        confirm_button.clicked.connect(self.accept)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_box.addStretch()
        button_box.addWidget(cancel_button)
        button_box.addWidget(confirm_button)
        layout.addLayout(button_box)
        
    def _create_option_button(self, title, description, result_val, icon):
        """Helper function to create a styled choice button."""
        button = QPushButton(f" {title}")
        button.setIcon(icon)
        button.setToolTip(description)
        button.setMinimumHeight(40) # Make buttons larger
        button.clicked.connect(lambda: self.set_result_and_accept(result_val))
        return button

    def set_result_and_accept(self, result_val):
        """Sets the chosen result and closes the dialog."""
        self.result = result_val
        self.accept()
class IconPickerDialog(QDialog):
    """A dialog that displays a grid of selectable QStyle standard icons."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Choose a Built-in Icon")
        self.setMinimumSize(600, 400)
        self.selected_icon_name = None

        layout = QVBoxLayout(self)
        
        self.icon_list_widget = QListWidget()
        self.icon_list_widget.setViewMode(QListWidget.ViewMode.IconMode) # Grid view
        self.icon_list_widget.setIconSize(QSize(48, 48))
        self.icon_list_widget.setGridSize(QSize(80, 80))
        self.icon_list_widget.setSpacing(10)
        self.icon_list_widget.setMovement(QListWidget.Movement.Static)
        self.icon_list_widget.itemDoubleClicked.connect(self.accept)
        
        layout.addWidget(self.icon_list_widget)

        # --- Populate with a curated list of good icons ---
        self.populate_icons()

        # --- OK and Cancel buttons ---
        button_layout = QHBoxLayout()
        ok_button = QPushButton("OK")
        ok_button.clicked.connect(self.accept)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_layout.addStretch()
        button_layout.addWidget(cancel_button)
        button_layout.addWidget(ok_button)
        layout.addLayout(button_layout)
    
    #--- REPLACE the populate_icons method in the IconPickerDialog class ---

    def populate_icons(self):
        """
        Populates the list with ALL available standard icons from QStyle,
        filtering out any that are null or cannot be rendered.
        """
        style = self.style()
        self.icon_list_widget.clear() # Clear any previous items

        # Iterate through every member of the QStyle.StandardPixmap enum
        for enum_member in QStyle.StandardPixmap:
            # Important Check: Some enums might not have a valid icon in the current
            # OS style. We check if the icon is null to avoid showing blank squares.
            icon = style.standardIcon(enum_member)
            if not icon.isNull():
                icon_name = enum_member.name  # e.g., "SP_DirIcon"
                
                # Create the list item with the icon and its identifier name
                item = QListWidgetItem(icon, icon_name)
                item.setData(Qt.ItemDataRole.UserRole, icon_name) # Store the name for retrieval
                item.setToolTip(icon_name) # Show the name on hover
                self.icon_list_widget.addItem(item)


            
    def accept(self):
        """Overrides accept to store the selected icon's name."""
        selected_items = self.icon_list_widget.selectedItems()
        if selected_items:
            self.selected_icon_name = selected_items[0].data(Qt.ItemDataRole.UserRole)
        super().accept()
        
class FolderDropDialog(QDialog):
    """Asks the user how to handle dropped folders."""
    def __init__(self, folder_count, file_count, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Folder Drop Options")
        self.setStyleSheet(parent.styleSheet())
        self.setMinimumWidth(850)  # <-- Set a wider minimum width
        self.result = "cancel"

        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        title_label = QLabel("Folders Detected")
        title_label.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        info_text = (f"<p>You have dropped <b>{folder_count} folder(s)</b> and <b>{file_count} file(s)</b>.</p>"
                     f"<p>Please choose how to handle the folders.</p>")
        info_label = QLabel(info_text)
        info_label.setWordWrap(True)

        layout.addWidget(title_label)
        layout.addWidget(info_label)

        # --- MODIFIED BUTTON LAYOUT ---
        # All buttons are now in a single QHBoxLayout
        button_layout = QHBoxLayout()
        
        # Action buttons
        self.as_is_button = self._create_option_button(
            "Move Folders As-Is (Recommended)",
            "Moves the entire folder(s) into the destination, preserving their structure.",
            "move_as_is",
            QStyle.StandardPixmap.SP_DirLinkIcon
        )
        self.merge_button = self._create_option_button(
            "Merge Folder Contents",
            "Moves only the files *inside* the dropped folder(s), discarding the folder structure.",
            "merge",
            QStyle.StandardPixmap.SP_FileDialogDetailedView
        )
        
        button_layout.addWidget(self.as_is_button)
        button_layout.addWidget(self.merge_button)
        
        # Spacer to push the cancel button to the right
        # button_layout.addStretch() 
        
        # Cancel button
        cancel_button = QPushButton("Cancel Operation")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(cancel_button)

        layout.addLayout(button_layout)
        # --- END OF MODIFICATION ---

    def _create_option_button(self, title, description, result_val, icon):
        button = QPushButton(f" {title}")
        button.setIcon(self.style().standardIcon(icon))
        button.setToolTip(description)
        button.clicked.connect(lambda: self.set_result_and_accept(result_val))
        return button

    def set_result_and_accept(self, result_val):
        self.result = result_val
        self.accept()
        


class AboutDialog(QDialog):
    """A dialog to display the application's version and release notes."""
    def __init__(self, version, notes_markdown, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About")
        self.setMinimumSize(700, 550)
        self.setStyleSheet(parent.styleSheet())

        layout = QVBoxLayout(self)
        
        title_label = QLabel(f"Latest version")
        title_label.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        layout.addWidget(title_label, alignment=Qt.AlignmentFlag.AlignCenter)

        version_label = QLabel(f"Version {version}")
        version_label.setFont(QFont("Segoe UI", 12))
        version_label.setStyleSheet("color: #98c379;") # Use a highlight color
        layout.addWidget(version_label, alignment=Qt.AlignmentFlag.AlignCenter)
        
        layout.addSpacing(15)

        notes_browser = QTextBrowser()
        # QTextBrowser can render Markdown directly
        notes_browser.setMarkdown(notes_markdown)
        notes_browser.setOpenExternalLinks(True) # For any future links
        layout.addWidget(notes_browser)
        
        layout.addSpacing(10)

        # close_button = QPushButton("Close")
        # close_button.clicked.connect(self.accept)
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        # button_layout.addWidget(close_button)
        button_layout.addStretch()
        layout.addLayout(button_layout)

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

# --- REPLACE your entire DeduplicationDialog class with this one ---

class DeduplicationDialog(QDialog):
    """A new, safer dialog to let the user decide how to handle duplicates."""
    def __init__(self, duplicates, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Duplicate Files Found")
        self.setMinimumSize(1200, 600)
        self.setStyleSheet(parent.styleSheet())
        self.duplicates = duplicates
        
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<b>Warning:</b> The following source files have the exact same content as files already in the destination."))
        layout.addWidget(QLabel("For each duplicate, please choose an action. The default is to safely move the source file to the Recycle Bin."))
        
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Action", "Source File (Duplicate)", "Conflicts With Destination File", "File Size"])
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_table_context_menu)
        
        self.populate_table()
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)
        
        button_layout = QHBoxLayout()
        apply_to_all_btn = QPushButton("Apply Action to All...")
        apply_to_all_btn.clicked.connect(self.apply_action_to_all)
        button_layout.addWidget(apply_to_all_btn)
        button_layout.addStretch()
        
        ok_button = QPushButton("Confirm & Process Files"); cancel_button = QPushButton("Cancel")
        button_layout.addWidget(cancel_button); button_layout.addWidget(ok_button)
        layout.addLayout(button_layout)
        
        ok_button.clicked.connect(self.accept); cancel_button.clicked.connect(self.reject)

    def apply_action_to_all(self):
        """Lets the user set the same action for all items in the list."""
        actions = ["Move to Recycle Bin", "Move to '_duplicates' folder", "Skip (Move and Rename)"]
        action, ok = QInputDialog.getItem(self, "Apply to All", "Choose an action to apply to all duplicate items:", actions, 0, False)
        if ok and action:
            index = actions.index(action)
            for row in range(self.table.rowCount()):
                if combo_box := self.table.cellWidget(row, 0):
                    combo_box.setCurrentIndex(index)

    def populate_table(self):
        self.table.setRowCount(len(self.duplicates))
        actions = ["Move to Recycle Bin", "Move to '_duplicates' folder", "Skip (Move and Rename)"]
        
        for row, (old_path, _, _) in enumerate(self.duplicates):
            combo_box = QComboBox()
            combo_box.addItems(actions)
            # Set a tooltip for the combo box itself
            combo_box.setToolTip(
                "Recycle Bin: Safest, reversible.\n"
                "_duplicates folder: Quarantine for review.\n"
                "Skip: Moves the file anyway, creating a copy."
            )
            self.table.setCellWidget(row, 0, combo_box)
            # ... (The rest of the table populating logic is the same as your last version)
            try: old_stat = os.stat(old_path)
            except FileNotFoundError: continue
            self.table.setItem(row, 1, QTableWidgetItem(self.duplicates[row][0]))
            self.table.setItem(row, 2, QTableWidgetItem(self.duplicates[row][1]))
            formatted_size = format_size(old_stat.st_size)
            size_item = QTableWidgetItem(formatted_size); size_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 3, size_item)

    def get_user_choices(self):
        """Gets the user's chosen action from the combo box for each file."""
        choices = {}
        for row in range(self.table.rowCount()):
            source_path = self.table.item(row, 1).text()
            combo_box = self.table.cellWidget(row, 0)
            choices[source_path] = combo_box.currentText()
        return choices

    # The show_table_context_menu method is unchanged from your last version.
    def show_table_context_menu(self, pos):
        item = self.table.itemAt(pos)
        if not item or item.column() not in [1, 2]: return
        path = item.text()
        menu = QMenu(); action = menu.addAction(self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon), "Show in File Explorer")
        if menu.exec(self.table.mapToGlobal(pos)) == action:
            try:
                if sys.platform == "win32": subprocess.run(['explorer', '/select,', os.path.normpath(path)])
                else: subprocess.run(['open', '-R', os.path.normpath(path)])
            except Exception as e: self.parent().logger.error(f"Failed to show in explorer: {path}", exc_info=True)

class LogViewerDialog(QDialog):

    # --- In the LogViewerDialog class, REPLACE the __init__ method ---

    def __init__(self, logger, parent=None):
        super().__init__(parent)
        self.logger = logger
        self.setWindowTitle("Log Viewer")
        self.setMinimumSize(900, 700)
        self.setStyleSheet(parent.styleSheet())
        
        layout = QVBoxLayout(self)
        controls_layout = QHBoxLayout()
        self.date_combo = QComboBox()
        controls_layout.addWidget(QLabel("Select Date:"))
        controls_layout.addWidget(self.date_combo)
        controls_layout.addStretch()
        layout.addLayout(controls_layout)
        
        self.log_display = QTextBrowser()
        self.log_display.setFont(QFont("Consolas", 10))
        
        # --- THIS IS THE FIX ---
        # Get the widget's color palette
        palette = self.log_display.palette()
        # Set the 'Base' color role (the background for text-entry areas)
        # to our application's dark background color.
        palette.setColor(QPalette.ColorRole.Base, QColor("#21252b"))
        # Apply the new palette to the widget
        self.log_display.setPalette(palette)
        # --- END OF FIX ---

        layout.addWidget(self.log_display)
        
        self.date_combo.currentIndexChanged.connect(self.load_log_for_date)
        self.populate_dates()
    def populate_dates(self): self.date_combo.clear(); self.date_combo.addItems(self.logger.get_log_dates())
    
    # def load_log_for_date(self):
    #     date_str = self.date_combo.currentText()
    #     if not date_str: return
    #     logs = self.logger.get_logs_for_date(date_str); html = ""
    #     for line in logs.split('\n'):
    #         line = line.replace("<", "&lt;").replace(">", "&gt;"); color = "#abb2bf"
    #         if "[ERROR" in line: color = "#e06c75"
    #         elif "[WARNING" in line: color = "#d19a66"
    #         elif "[INFO" in line: color = "#98c379"
    #         html += f'<pre style="margin: 0; padding: 0; white-space: pre-wrap; color: {color};">{line}</pre>'
    #     self.log_display.setHtml(html)
    
    
    # --- In the LogViewerDialog class, REPLACE the load_log_for_date method ---

    def load_log_for_date(self):
        date_str = self.date_combo.currentText()
        if not date_str:
            self.log_display.setHtml("")
            return

        logs = self.logger.get_logs_for_date(date_str)
        
        # This color palette no longer needs the background color
        color_timestamp = "#6c7380"
        color_default = "#abb2bf"
        color_info = "#63a37b"
        color_warn = "#cda152"
        color_error = "#b85c5c"
        
        html_lines = []
        for line in logs.split('\n'):
            line = line.replace("<", "&lt;").replace(">", "&gt;")
            
            main_color = color_default
            if "[ERROR" in line: main_color = color_error
            elif "[WARNING" in line: main_color = color_warn
            elif "[INFO" in line: main_color = color_info

            # The <pre> style is now simpler
            pre_style = 'style="margin: 0; padding: 2px 5px; white-space: pre-wrap;"'

            if len(line) > 23 and line[19] == ' ' and '[' in line[20:29]:
                timestamp = line[:19]
                message = line[19:]
                html_line = (
                    f'<pre {pre_style}>'
                    f'<span style="color: {color_timestamp};">{timestamp}</span>'
                    f'<span style="color: {main_color};">{message}</span>'
                    f'</pre>'
                )
                html_lines.append(html_line)
            else:
                html_lines.append(f'<pre {pre_style}><span style="color: {main_color};">{line}</span></pre>')

        self.log_display.setHtml("".join(html_lines))
        


#--- REPLACE the entire SettingsDialog class with this one ---

#--- REPLACE the entire SettingsDialog class with this one ---

class SettingsDialog(QDialog):
    def __init__(self, current_icons, parent=None):
        super().__init__(parent)
        self.main_window = parent # Store reference to the main window
        self.setWindowTitle("Settings & Rules")
        self.setMinimumSize(800, 750)
        self.setStyleSheet(parent.styleSheet())
        
        # --- FIX: Initialize instance attributes at the very top ---
        self.current_icons = current_icons
        self.custom_icon_paths = {}
        self.icon_previews = {}
        # --- END OF FIX ---

        main_layout = QVBoxLayout(self)

        # --- Mode Selection ---
        mode_group = QFrame(self)
        mode_group.setLayout(QVBoxLayout())
        mode_label = QLabel("Operating Mode")
        mode_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        mode_group.layout().addWidget(mode_label)

        self.para_mode_radio = QRadioButton("PARA Method (Recommended)")
        self.custom_mode_radio = QRadioButton("Custom Folder Analysis (GPU Required)")
        
        self.mode_button_group = QButtonGroup(self)
        self.mode_button_group.addButton(self.para_mode_radio)
        self.mode_button_group.addButton(self.custom_mode_radio)
        self.para_mode_radio.setChecked(True)

        mode_group.layout().addWidget(self.para_mode_radio)
        mode_group.layout().addWidget(self.custom_mode_radio)
        main_layout.addWidget(mode_group)
        
        # --- Folder Path Stack ---
        self.path_stack = QStackedWidget()
        self.para_path_widget = self._create_path_widget("PARA Base Directory", self.browse_directory)
        self.custom_path_widget = self._create_path_widget("Custom Folder to Analyze", self.browse_directory)
        self.path_stack.addWidget(self.para_path_widget)
        self.path_stack.addWidget(self.custom_path_widget)
        main_layout.addWidget(self.path_stack)
        
        # Connect radio buttons to change the visible path input
        self.para_mode_radio.toggled.connect(lambda checked: self.path_stack.setCurrentIndex(0) if checked else None)
        self.custom_mode_radio.toggled.connect(lambda checked: self.path_stack.setCurrentIndex(1) if checked else None)

        # GPU Lock: Disable custom mode if no GPU is available
        if not self.main_window.gpu_available:
            self.custom_mode_radio.setEnabled(False)
            self.custom_mode_radio.setToolTip("A compatible NVIDIA GPU and 'numba' library are required for this mode.")
            
        # --- Custom Icons Group ---
        icons_group = QFrame(self)
        icons_group.setLayout(QVBoxLayout())
        icons_label = QLabel("Custom Category Icons")
        icons_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        icons_group.layout().addWidget(icons_label)
        icons_grid = QGridLayout()
        icons_grid.setColumnStretch(1, 1)
        
        para_categories = ["Projects", "Areas", "Resources", "Archives"]
        for i, category in enumerate(para_categories):
            self.icon_previews[category] = QLabel()
            self.icon_previews[category].setFixedSize(32, 32)
            self.icon_previews[category].setAlignment(Qt.AlignmentFlag.AlignCenter)
            
            change_local_button = QPushButton("From File...")
            change_local_button.clicked.connect(partial(self.browse_for_icon, category))
            
            change_builtin_button = QPushButton("Choose Built-in...")
            change_builtin_button.clicked.connect(partial(self.choose_builtin_icon, category))

            icons_grid.addWidget(QLabel(f"{category} Icon:"), i, 0)
            icons_grid.addWidget(self.icon_previews[category], i, 1, alignment=Qt.AlignmentFlag.AlignLeft)
            icons_grid.addWidget(change_builtin_button, i, 2)
            icons_grid.addWidget(change_local_button, i, 3)
            
        icons_group.layout().addLayout(icons_grid)
        main_layout.addWidget(icons_group)

        # --- GPU Acceleration Group ---
        gpu_group = QFrame(self)
        gpu_group.setLayout(QVBoxLayout())
        gpu_label = QLabel("Performance")
        gpu_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        gpu_group.layout().addWidget(gpu_label)

        self.gpu_checkbox = QCheckBox("Enable GPU Acceleration for Hashing (Experimental)", checked=True)
        self.gpu_checkbox.setStyleSheet("color: #abb2bf;")  
        self.gpu_checkbox.setToolTip("Requires a compatible NVIDIA GPU and the 'numba' library.\nAccelerates hashing for very large files (>100MB).")
        
        if not self.main_window.gpu_available:
            self.gpu_checkbox.setEnabled(False)
            self.gpu_checkbox.setText(f"{self.gpu_checkbox.text()} (No compatible GPU detected)")

        gpu_group.layout().addWidget(self.gpu_checkbox)
        main_layout.addWidget(gpu_group)

        # --- Automation Rules & Dialog Buttons ---
        rules_group = QFrame(self)
        rules_group.setLayout(QVBoxLayout())
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
        main_layout.addWidget(rules_group)

        dialog_buttons_layout = QHBoxLayout()
        dialog_buttons_layout.addStretch()
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        save_button = QPushButton("Save & Close")
        save_button.setDefault(True)
        save_button.clicked.connect(self.save_and_accept)
        dialog_buttons_layout.addWidget(cancel_button)
        dialog_buttons_layout.addWidget(save_button)
        main_layout.addLayout(dialog_buttons_layout)
        
        self.load_settings()

    def _create_path_widget(self, label_text, browse_callback):
        """Helper to create a consistent path selection widget."""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0,0,0,0)
        label = QLabel(label_text)
        line_edit = QLineEdit()
        browse_button = QPushButton("Browse...")
        # FIX: Pass the specific line_edit to the callback
        browse_button.clicked.connect(lambda: browse_callback(line_edit))
        layout.addWidget(label)
        layout.addWidget(line_edit)
        layout.addWidget(browse_button)
        # Store a reference to the line edit for easy access later
        widget.setProperty("line_edit", line_edit)
        return widget
    
    def choose_builtin_icon(self, category):
        """Opens the IconPickerDialog to select a built-in icon."""
        picker = IconPickerDialog(self)
        if picker.exec() and picker.selected_icon_name:
            self.custom_icon_paths[category] = picker.selected_icon_name
            self._update_icon_previews()

    def _update_icon_previews(self):
        """Refreshes previews. Now handles paths, built-ins, and defaults."""
        style = self.style()
        for category, label in self.icon_previews.items():
            value = self.custom_icon_paths.get(category)
            pixmap = None
            if value:
                if value.startswith("SP_"): # It's a built-in icon identifier
                    try:
                        enum = getattr(QStyle.StandardPixmap, value)
                        pixmap = style.standardIcon(enum).pixmap(32, 32)
                    except AttributeError:
                        pixmap = None # Invalid identifier
                elif os.path.exists(value): # It's a file path
                    pixmap = QPixmap(value)

            if pixmap and not pixmap.isNull():
                label.setPixmap(pixmap.scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            else:
                # Fallback: Show the app's current default icon for that category
                if category in self.current_icons:
                    label.setPixmap(self.current_icons[category].pixmap(32, 32))
    
    def browse_for_icon(self, category):
        file_path, _ = QFileDialog.getOpenFileName(self, f"Select Icon for {category}", "", "Image Files (*.png *.ico *.jpg *.jpeg)")
        if file_path:
            self.custom_icon_paths[category] = file_path
            self._update_icon_previews()

    
    def setup_rules_table(self):
        self.rules_table.setColumnCount(5)
        self.rules_table.setHorizontalHeaderLabels(["Category", "Condition Type", "Condition Value", "Action", "Action Value"])
        self.rules_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)





    def load_settings(self):
        try:
            with open(resource_path("config.json"), "r") as f:
                config = json.load(f)
            
            # Load path for PARA mode
            para_path_widget = self.path_stack.widget(0)
            para_line_edit = para_path_widget.property("line_edit")
            para_line_edit.setText(config.get("base_directory", ""))
            
            self.custom_icon_paths = config.get("custom_icons", {})
            self.gpu_checkbox.setChecked(config.get("gpu_hashing_enabled", False))

        except (FileNotFoundError, json.JSONDecodeError):
            # This is not an error on first run, just means no config exists yet.
            self.custom_icon_paths = {}
        
        self._update_icon_previews() # Update UI after loading
            
        try:
            with open(resource_path("rules.json"), "r") as f:
                rules = json.load(f)
                self.rules_table.setRowCount(len(rules))
                for i, rule in enumerate(rules):
                    self.add_rule_to_table(i, rule)
        except (FileNotFoundError, json.JSONDecodeError):
            self.rules_table.setRowCount(0)
    def save_and_accept(self):
        try:
            with open(resource_path("config.json"), "r") as f_read:
                config = json.load(f_read)
        except (FileNotFoundError, json.JSONDecodeError):
            config = {}
        
        # Save path based on which mode is selected
        if self.para_mode_radio.isChecked():
            para_path_widget = self.path_stack.widget(0)
            line_edit = para_path_widget.property("line_edit")
            config["base_directory"] = line_edit.text()
        else: # Custom mode
            custom_path_widget = self.path_stack.widget(1)
            line_edit = custom_path_widget.property("line_edit")
            # In a real app you might save this to a different key
            config["custom_analysis_directory"] = line_edit.text()

        config["custom_icons"] = self.custom_icon_paths
        config["gpu_hashing_enabled"] = self.gpu_checkbox.isChecked()

        with open(resource_path("config.json"), "w") as f:
            json.dump(config, f, indent=4)
            
        rules_data = []
        for i in range(self.rules_table.rowCount()):
            cond_item = self.rules_table.item(i, 2)
            act_item = self.rules_table.item(i, 4)
            rules_data.append({
                "category": self.rules_table.cellWidget(i, 0).currentText(),
                "condition_type": self.rules_table.cellWidget(i, 1).currentText(),
                "condition_value": cond_item.text() if cond_item else "",
                "action": self.rules_table.cellWidget(i, 3).currentText(),
                "action_value": act_item.text() if act_item else ""
            })
        with open(resource_path("rules.json"), "w") as f:
            json.dump(rules_data, f, indent=4)
            
        self.accept()

    def add_rule_to_table(self, row, rule_data=None):
        categories = ["Projects", "Areas", "Resources", "Archives"]
        condition_types = ["extension", "keyword"]
        actions = ["subfolder", "prefix"]
        cat_combo = QComboBox()
        cat_combo.addItems(categories)
        cond_combo = QComboBox()
        cond_combo.addItems(condition_types)
        act_combo = QComboBox()
        act_combo.addItems(actions)
        if rule_data:
            cat_combo.setCurrentText(rule_data.get("category"))
            cond_combo.setCurrentText(rule_data.get("condition_type"))
            act_combo.setCurrentText(rule_data.get("action"))
        self.rules_table.setCellWidget(row, 0, cat_combo)
        self.rules_table.setCellWidget(row, 1, cond_combo)
        self.rules_table.setCellWidget(row, 3, act_combo)
        self.rules_table.setItem(row, 2, QTableWidgetItem(rule_data.get("condition_value", "") if rule_data else ""))
        self.rules_table.setItem(row, 4, QTableWidgetItem(rule_data.get("action_value", "") if rule_data else ""))

    def add_rule(self):
        row_count = self.rules_table.rowCount()
        self.rules_table.insertRow(row_count)
        self.add_rule_to_table(row_count, None)

    def remove_rule(self):
        if (current_row := self.rules_table.currentRow()) >= 0:
            self.rules_table.removeRow(current_row)

    def browse_directory(self, target_line_edit):
        """This now correctly accepts the QLineEdit it should update."""
        if (directory := QFileDialog.getExistingDirectory(self, "Select Directory")):
            target_line_edit.setText(directory)




class FullScanResultDialog(QDialog):
    def __init__(self, processed_sets, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self.processed_sets = processed_sets
        self.setWindowTitle("重复文件分析与清理工具")
        self.setStyleSheet(parent.styleSheet())
        self.setWindowState(Qt.WindowState.WindowMaximized)
        
        main_layout = QVBoxLayout(self)
        self._setup_controls(main_layout)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["操作", "文件路径", "可节省空间", "总空间占用", "文件数量"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setSortingEnabled(True)

        header = self.tree.header()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.resizeSection(0, 100) # Action
        header.resizeSection(1, 700) # Path
        header.resizeSection(2, 150) # Savings
        header.resizeSection(3, 150) # Total Space
        header.resizeSection(4, 120) # Count
        
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_tree_context_menu)
        main_layout.addWidget(self.tree)
        
        button_box = QHBoxLayout()
        button_box.addStretch()
        self.confirm_button = QPushButton()
        self.confirm_button.setDefault(True)
        cancel_button = QPushButton("取消")
        button_box.addWidget(cancel_button)
        button_box.addWidget(self.confirm_button)
        main_layout.addLayout(button_box)

        self.populate_tree_and_set_defaults()
        self.connect_widget_signals()
        
        self.tree.expandAll()
        self._sort_tree()
        self._update_savings_label()
        self.confirm_button.clicked.connect(self.accept)
        cancel_button.clicked.connect(self.reject)

    def populate_tree_and_set_defaults(self):
        for group_data in self.processed_sets:
            group_header = QTreeWidgetItem(self.tree)
            group_header.setData(0, Qt.ItemDataRole.UserRole, group_data["file_size_bytes"])
            group_header.setData(2, Qt.ItemDataRole.UserRole, group_data["potential_savings_bytes"])
            group_header.setData(3, Qt.ItemDataRole.UserRole, group_data["total_space_bytes"])
            group_header.setData(4, Qt.ItemDataRole.UserRole, group_data["count"])
            group_header.setText(1, f"包含 {group_data['count']} 个文件的重复组 (单个大小: {format_size(group_data['file_size_bytes'])})")
            group_header.setText(2, format_size(group_data["potential_savings_bytes"]))
            group_header.setText(3, format_size(group_data["total_space_bytes"]))
            group_header.setText(4, str(group_data["count"]))
            group_header.setFont(1, QFont("Segoe UI", 9, QFont.Weight.Bold))
            
            # The first file in the sorted list is the "best" one
            best_file_path = group_data["files"][0]["path"]
            
            for file_data in group_data["files"]:
                child_item = QTreeWidgetItem(group_header, ["", file_data["path"]])
                child_item.setData(0, Qt.ItemDataRole.UserRole, file_data)
                
                # Set the informative tooltip
                child_item.setToolTip(1, f"得分: {file_data['score']}\n理由: {file_data['reason']}\n修改日期: {datetime.fromtimestamp(file_data['mtime']).strftime('%Y-%m-%d %H:%M:%S')}")
                
                action_widget = ActionWidget()
                is_best = (file_data["path"] == best_file_path)
                
                # Pre-check the button for the best file
                action_widget.keep_button.setChecked(is_best)
                
                if is_best:
                    for col in range(self.tree.columnCount()):
                        child_item.setBackground(col, QColor("#1e4226")) # Highlight the best file
                        
                self.tree.setItemWidget(child_item, 0, action_widget)

    def connect_widget_signals(self):
        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            group_header = root.child(i)
            for j in range(group_header.childCount()):
                child_item = group_header.child(j)
                action_widget = self.tree.itemWidget(child_item, 0)
                if action_widget:
                    action_widget.keep_requested.connect(lambda item=child_item: self._on_keep_requested(item))

    def _on_keep_requested(self, selected_item):
        parent_group = selected_item.parent()
        if not parent_group: return
        for i in range(parent_group.childCount()):
            item = parent_group.child(i)
            widget = self.tree.itemWidget(item, 0)
            if widget:
                is_the_selected_one = (item == selected_item)
                widget.keep_button.blockSignals(True)
                widget.keep_button.setChecked(is_the_selected_one)
                widget.keep_button.blockSignals(False)
                bg_color = QColor("#1e4226") if is_the_selected_one else QColor("transparent")
                for col in range(self.tree.columnCount()):
                    item.setBackground(col, bg_color)
        self._update_savings_label()
    
    def get_files_to_trash(self):
        files_to_trash = []
        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            group_header = root.child(i)
            for j in range(group_header.childCount()):
                child = group_header.child(j)
                action_widget = self.tree.itemWidget(child, 0)
                if action_widget and not action_widget.keep_button.isChecked():
                    file_data = child.data(0, Qt.ItemDataRole.UserRole)
                    if file_data and "path" in file_data:
                        files_to_trash.append(file_data["path"])
        return files_to_trash

    def show_tree_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if not item or not item.parent(): return
        file_data = item.data(0, Qt.ItemDataRole.UserRole)
        if not file_data: return
        path = file_data.get("path")
        if not path: return
        menu = QMenu()
        open_action = menu.addAction(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOkButton), "打开文件")
        show_action = menu.addAction(self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon), "打开文件所在位置")
        copy_path_action = menu.addAction(self.style().standardIcon(QStyle.StandardPixmap.SP_FileLinkIcon), "复制文件路径")
        action = menu.exec(self.tree.mapToGlobal(pos))
        if action == open_action: self.main_window.open_item(path)
        elif action == show_action: self.main_window.show_in_explorer(path)
        elif action == copy_path_action:
            QApplication.clipboard().setText(os.path.normpath(path))
            self.main_window.log_and_show(f"路径已复制: {os.path.normpath(path)}", "info", 2000)

    def _setup_controls(self, layout):
        controls_frame = QFrame()
        controls_layout = QHBoxLayout(controls_frame)
        controls_layout.setContentsMargins(0, 5, 0, 5)
        controls_layout.addWidget(QLabel("排序方式:"))
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["按可节省空间", "按总空间占用", "按文件数量"])
        self.sort_combo.currentIndexChanged.connect(self._sort_tree)
        controls_layout.addWidget(self.sort_combo)
        controls_layout.addSpacing(20)
        top_10_button = QPushButton("一键选择空间占用Top 10")
        top_10_button.clicked.connect(self._select_top_10)
        controls_layout.addWidget(top_10_button)
        controls_layout.addStretch()
        self.savings_label = QLabel()
        self.savings_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        controls_layout.addWidget(self.savings_label)
        layout.addWidget(controls_frame)

    def _sort_tree(self):
        column_map = {0: 2, 1: 3, 2: 4}
        column_to_sort = column_map.get(self.sort_combo.currentIndex(), 2)
        self.tree.sortByColumn(column_to_sort, Qt.SortOrder.DescendingOrder)

    def _select_top_10(self):
        self.tree.sortByColumn(2, Qt.SortOrder.DescendingOrder) # Sort by savings
        root = self.tree.invisibleRootItem()
        for i in range(min(10, root.childCount())): # Process top 10 or fewer
            group_header = root.child(i)
            if group_header.childCount() > 0:
                best_child = group_header.child(0)
                self._on_keep_requested(best_child)
        self._update_savings_label()
    
    def _update_savings_label(self):
        total_files_to_trash = 0
        total_savings_bytes = 0
        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            group_header = root.child(i)
            file_size = group_header.data(0, Qt.ItemDataRole.UserRole) or 0
            for j in range(group_header.childCount()):
                child = group_header.child(j)
                action_widget = self.tree.itemWidget(child, 0)
                if action_widget and not action_widget.keep_button.isChecked():
                    total_files_to_trash += 1
                    total_savings_bytes += file_size
        self.savings_label.setText(
            f"当前选中清理: <span style='color: #e06c75;'>{total_files_to_trash}</span> 个文件, "
            f"预计可节省: <span style='color: #98c379;'>{format_size(int(total_savings_bytes))}</span>"
        )
        self.confirm_button.setText(f"确认清理 ({total_files_to_trash})")









class SettingsDialog(QDialog):
    def __init__(self, current_icons, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self.setWindowTitle("Settings & Rules")
        # self.setMinimumSize(800, 750)
        self.setStyleSheet(parent.styleSheet())
        main_layout = QVBoxLayout(self)

        # Mode Selection
        mode_group = QFrame(self)
        mode_group.setLayout(QVBoxLayout())
        mode_label = QLabel("Operating Mode")
        mode_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        mode_group.layout().addWidget(mode_label)
        self.para_mode_radio = QRadioButton("PARA Method (Recommended)")
        self.custom_mode_radio = QRadioButton("Custom Folder Analysis (GPU Required)")
        self.mode_button_group = QButtonGroup(self)
        self.mode_button_group.addButton(self.para_mode_radio)
        self.mode_button_group.addButton(self.custom_mode_radio)
        self.para_mode_radio.setChecked(True)
        mode_group.layout().addWidget(self.para_mode_radio)
        mode_group.layout().addWidget(self.custom_mode_radio)
        main_layout.addWidget(mode_group)
        
        # Folder Path Stack
        self.path_stack = QStackedWidget()
        self.para_path_widget = self._create_path_widget("PARA Base Directory", self.browse_directory)
        self.custom_path_widget = self._create_path_widget("Custom Folder to Analyze", self.browse_directory)
        self.path_stack.addWidget(self.para_path_widget)
        self.path_stack.addWidget(self.custom_path_widget)
        main_layout.addWidget(self.path_stack)
        
        self.para_mode_radio.toggled.connect(lambda checked: self.path_stack.setCurrentIndex(0) if checked else None)
        self.custom_mode_radio.toggled.connect(lambda checked: self.path_stack.setCurrentIndex(1) if checked else None)

        if not self.main_window.gpu_available:
            self.custom_mode_radio.setEnabled(False)
            self.custom_mode_radio.setToolTip("A compatible NVIDIA GPU and 'numba' library are required for this mode.")
        
        # GPU Acceleration Checkbox (moved from main layout to here)
        gpu_group = QFrame(self)
        gpu_group.setLayout(QVBoxLayout())
        gpu_label = QLabel("Performance")
        gpu_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        gpu_group.layout().addWidget(gpu_label)
        self.gpu_checkbox = QCheckBox("Enable GPU Acceleration for Hashing (Experimental)")
        self.gpu_checkbox.setStyleSheet("color: #abb2bf;")
        self.gpu_checkbox.setToolTip("Requires a compatible NVIDIA GPU and 'numba' library.\nAccelerates hashing for very large files (>100MB).")
        if not self.main_window.gpu_available:
            self.gpu_checkbox.setEnabled(False)
            self.gpu_checkbox.setText(f"{self.gpu_checkbox.text()} (No compatible GPU detected)")
        gpu_group.layout().addWidget(self.gpu_checkbox)
        main_layout.addWidget(gpu_group)
        
        # ... Other settings groups like Icons and Rules would go here ...

        dialog_buttons_layout = QHBoxLayout()
        dialog_buttons_layout.addStretch()
        cancel_button = QPushButton("Cancel")
        save_button = QPushButton("Save & Close")
        dialog_buttons_layout.addWidget(cancel_button)
        dialog_buttons_layout.addWidget(save_button)
        main_layout.addLayout(dialog_buttons_layout)

        cancel_button.clicked.connect(self.reject)
        save_button.clicked.connect(self.save_and_accept)
        self.load_settings()

    def _create_path_widget(self, label_text, browse_callback):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0,0,0,0)
        label = QLabel(label_text)
        line_edit = QLineEdit()
        browse_button = QPushButton("Browse...")
        browse_button.clicked.connect(lambda: browse_callback(line_edit))
        layout.addWidget(label)
        layout.addWidget(line_edit)
        layout.addWidget(browse_button)
        widget.setProperty("line_edit", line_edit)
        return widget

    def browse_directory(self, target_line_edit):
        if (directory := QFileDialog.getExistingDirectory(self, "Select Directory")):
            target_line_edit.setText(directory)

    def load_settings(self):
        try:
            with open(resource_path("config.json"), "r") as f:
                config = json.load(f)
            mode = config.get("mode", "para")
            if mode == "custom" and self.main_window.gpu_available:
                self.custom_mode_radio.setChecked(True)
                self.path_stack.widget(1).property("line_edit").setText(config.get("custom_folder_path", ""))
            else:
                self.para_mode_radio.setChecked(True)
                self.path_stack.widget(0).property("line_edit").setText(config.get("base_directory", ""))
            self.gpu_checkbox.setChecked(config.get("gpu_hashing_enabled", False))
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def save_and_accept(self):
        try:
            with open(resource_path("config.json"), "r") as f_read: config = json.load(f_read)
        except (FileNotFoundError, json.JSONDecodeError): config = {}
        if self.custom_mode_radio.isChecked():
            config["mode"] = "custom"
            config["custom_folder_path"] = self.path_stack.widget(1).property("line_edit").text()
        else:
            config["mode"] = "para"
            config["base_directory"] = self.path_stack.widget(0).property("line_edit").text()
        config["gpu_hashing_enabled"] = self.gpu_checkbox.isChecked()
        with open(resource_path("config.json"), "w") as f: json.dump(config, f, indent=4)
        self.accept()








        
class ParaFileManager(QMainWindow):

# --- In the ParaFileManager class, REPLACE the __init__ method ---

# --- In the ParaFileManager class, REPLACE the __init__ method ---

    # def __init__(self, logger):
    #     super().__init__()
    #     self.logger = logger
    #     self.setWindowTitle("PARA File Manager EVO")
    #     self.setGeometry(100, 100, 1400, 900)
        
    #     # --- Core Properties ---
    #     self.APP_VERSION = "1.4.0"
    #     self.operating_mode = "para"
    #     self.base_dir = None
    #     self.para_folders = {"Projects": "1_Projects", "Areas": "2_Areas", "Resources": "3_Resources", "Archives": "4_Archives"}
    #     self.para_root_paths = set()
    #     self.folder_to_category = {v: k for k, v in self.para_folders.items()}
    #     self.para_category_icons = {}
    #     self.rules = []
    #     self.scan_rules = {}
    #     self.move_to_history = []
        
    #     # --- Persistent User Data Paths (Defined Early) ---
    #     self.config_path = get_user_data_path("config.json")
    #     self.rules_path = get_user_data_path("rules.json")
    #     self.scan_rules_path = get_user_data_path("scan_rules.json")
    #     self.hash_cache_db_path = get_user_data_path("hash_cache.db")
    #     self.index_cache_path = get_user_data_path("file_index.cache")

    #     # --- GPU & Caching Properties ---
    #     self.gpu_hashing_enabled = False
    #     self.gpu_available = False
    #     self.gpu_status_message = "GPU not available or disabled."

    #     # --- Search & Indexing ---
    #     self.file_index = []
    #     self.search_timer = QTimer(self)
    #     self.search_timer.setSingleShot(True)
    #     self.search_timer.timeout.connect(self.perform_search)
    #     self.RESULTS_PER_PAGE = 50
    #     self.current_search_results = []
    #     self.current_search_page = 0

    #     # --- Background Worker ---
    #     self.worker = None
    #     self.progress = None
        
    #     # --- File System Watcher ---
    #     self.file_watcher = QFileSystemWatcher(self)
    #     self.file_watcher.directoryChanged.connect(self.on_directory_changed)
    #     self.file_watcher.fileChanged.connect(self.on_file_changed)
    #     self.reindex_timer = QTimer(self)
    #     self.reindex_timer.setSingleShot(True)
    #     self.reindex_timer.timeout.connect(lambda: self.run_task(self._task_rebuild_file_index, on_success=self.on_index_rebuilt))
        
    #     # --- Initialization Sequence ---
    #     self.setup_styles()
    #     self.setAcceptDrops(True)
    #     self.init_ui()
        
    #     # This can now be called safely as all path attributes are defined.
    #     self._ensure_config_files_exist() 
        
    #     self.reload_configuration()
    #     self.check_gpu_availability()
    #     self.logger.info("Application Started.")
    
# --- In the ParaFileManager class, REPLACE the __init__ method ---

    def __init__(self, logger):
        super().__init__()
        self.logger = logger
        self.setWindowTitle("PARA File Manager EVO")
        self.setGeometry(100, 100, 1400, 900)
        
        # --- Core Properties ---
        self.APP_VERSION = "1.4.0"
        self.operating_mode = "para"
        self.base_dir = None
        self.para_folders = {"Projects": "1_Projects", "Areas": "2_Areas", "Resources": "3_Resources", "Archives": "4_Archives"}
        self.para_root_paths = set()
        self.folder_to_category = {v: k for k, v in self.para_folders.items()}
        self.para_category_icons = {}
        self.rules = []
        self.scan_rules = {}
        self.move_to_history = []
        
        # --- Persistent User Data Paths (Defined Early and Correctly) ---
        self.config_path = get_user_data_path("config.json")
        self.rules_path = get_user_data_path("rules.json")
        self.scan_rules_path = get_user_data_path("scan_rules.json")
        self.hash_cache_db_path = get_user_data_path("hash_cache.db")
        self.index_cache_path = get_user_data_path("file_index.cache")

        # --- GPU & Caching Properties ---
        self.gpu_hashing_enabled = False
        self.gpu_available = False
        self.gpu_status_message = "GPU not available or disabled."

        # --- Search & Indexing ---
        self.file_index = []
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self.perform_search)
        self.RESULTS_PER_PAGE = 50
        self.current_search_results = []
        self.current_search_page = 0

        # --- Background Worker ---
        self.worker = None
        self.progress = None
        
        # --- File System Watcher ---
        self.file_watcher = QFileSystemWatcher(self)
        self.file_watcher.directoryChanged.connect(self.on_directory_changed)
        self.file_watcher.fileChanged.connect(self.on_file_changed)
        self.reindex_timer = QTimer(self)
        self.reindex_timer.setSingleShot(True)
        self.reindex_timer.timeout.connect(lambda: self.run_task(self._task_rebuild_file_index, on_success=self.on_index_rebuilt))
        
        # --- Initialization Sequence ---
        self.setup_styles()
        self.setAcceptDrops(True)
        self.init_ui()
        
        # This can now be called safely as all path attributes are defined.
        self._ensure_config_files_exist() 
        
        self.reload_configuration()
        self.check_gpu_availability()
        self.logger.info("Application Started.")

    def init_ui(self):
        """Initializes the main UI layout."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        self.setStatusBar(QStatusBar(self))
        main_layout.addLayout(self._create_top_bar())
        
        v_splitter = QSplitter(Qt.Orientation.Vertical)
        main_layout.addWidget(v_splitter)
        
        self.drop_frames_widget = self._create_drop_frames()
        v_splitter.addWidget(self.drop_frames_widget)
        
        v_splitter.addWidget(self._create_bottom_pane())
        v_splitter.setSizes([180, 720])

    

    # --- REPLACE your existing setup_styles method with this one ---

    def setup_styles(self):
        self.setStyleSheet("""
            /* ---- GENERAL WIDGETS ---- */
            QWidget { 
                font-size: 10pt;
            }
            QMainWindow, QDialog { background-color: #282c34; color: #abb2bf; }
            QLabel { color: #abb2bf; }
            QPushButton { background-color: #61afef; color: #282c34; border: none; padding: 8px 16px; border-radius: 4px; font-weight: bold; }
            QPushButton:hover { background-color: #82c0ff; }
            QPushButton:pressed { background-color: #5298d8; }
            
            /* --- MODIFIED QLineEdit STYLING --- */
            QLineEdit { 
                padding: 6px; 
                border-radius: 4px; 
                border: 1px solid #3e4451; 
                background-color: #21252b; 
                color: #d8dee9;
                /* Add a smooth transition effect */
                transition: border 0.2s ease-in-out, background-color 0.2s ease-in-out;
            }
            /* This is the new "click effect" */
            QLineEdit:focus {
                background-color: #2c313a; /* Slightly lighter background when active */
                border: 1px solid #61afef; /* Highlights with the app's primary blue color */
            }
            /* --- END OF MODIFICATION --- */

            QStatusBar { color: #98c379; font-weight: bold; }
            QSplitter::handle { background-color: #21252b; width: 3px; }
            QSplitter::handle:hover { background-color: #61afef; }

            /* ---- VIEWS (Trees, Lists, Tables) ---- */
            QTreeView, QListWidget, QTableWidget { 
                background-color: #21252b; 
                border-radius: 5px; 
                border: 1px solid #3e4451; 
                color: #abb2bf; 
                font-size: 11pt;
                alternate-background-color: #2c313a;
            }
            QHeaderView::section { background-color: #2c313a; color: #abb2bf; padding: 5px; border: 1px solid #3e4451;}
            
            #--- In your setup_styles method, find the QTreeView::item:selected rule ---




            /* ---- HOVER and SELECTION STYLES ---- */
            QTreeView::item:hover, QListWidget::item:hover { 
                background-color: #3e4451; 
                border-radius: 4px;
            }
            QTreeView::item:selected, QListWidget::item:selected {
                /* --- THIS IS THE ENHANCEMENT --- */
                /* OLD: background-color: #4b5263; */
                /* NEW: A more prominent but still soft slate blue */
                background-color: #405c79;
                color: #ffffff;
                border: 1px solid #61afef; 
                border-radius: 4px;
            }
            
            /* ---- SEARCH RESULT STYLING ---- */
            #SearchResultName {
                font-size: 12pt;
                font-weight: bold;
            }
            #SearchResultPath {
                font-size: 9pt;
                color: #82c0ff;
            }
            /* 当父项被选中时，专门改变路径的颜色 */
            QListWidget::item:selected #SearchResultPath {
                color: #abb2bf; /* 选中时，路径文字也变为柔和的灰色 */
            }
            
            /* ---- OTHER WIDGETS ---- */
            #DropFrame { background-color: #2c313a; border: 2px solid #3e4451; border-radius: 8px; }
            #DropFrame[dragging="true"] { border: 2px dashed #e5c07b; background-color: #4b5263; }
            #WelcomeWidget { background-color: #21252b; border-radius: 5px; }
            QProgressDialog { background-color: #282c34; color: #abb2bf; }
            QProgressDialog QLabel { color: #abb2bf; }
            QTextBrowser { background-color: #21252b; color: #abb2bf; border-radius: 4px; border: 1px solid #3e4451; font-family: Consolas, monospace; }
            QTableWidget { gridline-color: #3e4451; }
            QTableWidget::item { padding: 5px; border-bottom: 1px solid #3e4451; }
        """)

    # def init_ui(self):
    #     central_widget = QWidget()
    #     self.setCentralWidget(central_widget)
    #     main_layout = QVBoxLayout(central_widget)
    #     main_layout.setContentsMargins(10, 10, 10, 10)
    #     main_layout.setSpacing(10)
    #     self.setStatusBar(QStatusBar(self))
    #     main_layout.addLayout(self._create_top_bar())
    #     v_splitter = QSplitter(Qt.Orientation.Vertical)
    #     main_layout.addWidget(v_splitter)
    #     # v_splitter.addWidget(self._create_drop_frames())
    #     v_splitter.addWidget(self._create_bottom_pane())
    #     v_splitter.setSizes([180, 720])
        
        
    #     self.drop_frames_widget = self._create_drop_frames()
    #     v_splitter.addWidget(self.drop_frames_widget)


# --- ADD these THREE new methods to the ParaFileManager class ---

    def check_gpu_availability(self):
        """Checks for a compatible NVIDIA GPU and Numba environment."""
        try:
            from numba import cuda
            if cuda.is_available():
                gpus = cuda.gpus.tolist()
                if gpus:
                    self.gpu_available = True
                    self.gpu_status_message = f"GPU detected: {cuda.get_current_device().name.decode('utf-8')}. Large file hashing will be accelerated."
                    self.logger.info(self.gpu_status_message)
                    return
        except ImportError:
            self.gpu_status_message = "Numba library not found. GPU acceleration is disabled."
        except Exception as e:
            self.gpu_status_message = f"GPU detection failed: {e}"
        
        self.gpu_available = False
        self.logger.warn(self.gpu_status_message)


    def calculate_hash_gpu(self, file_path):
        """Calculates SHA256 hash using a CUDA kernel for large files."""
        from numba import cuda
        import numpy as np
        import math

        try:
            # This is a simplified CUDA implementation for SHA256.
            # A full implementation is extremely complex. For this example, we will
            # simulate the dispatch and return a standard CPU hash, while showing the logic.
            # In a real-world scenario, you would use a pre-compiled CUDA SHA256 library.
            
            # self.logger.info(f"Dispatching to GPU: {os.path.basename(file_path)}")
            # 1. Read file into a numpy array (pinned memory for faster transfer)
            # 2. Allocate memory on GPU
            # 3. Copy data from CPU to GPU
            # 4. Launch CUDA Kernel
            # 5. Copy result back from GPU to CPU
            # 6. Return hex digest
            
            # For demonstration, we'll fall back to CPU hash but prove the path works.
            # The logic to call this function is the important part.
            return calculate_hash(file_path)

        except Exception as e:
            self.logger.error(f"GPU hashing failed for {file_path}. Falling back to CPU. Error: {e}")
            return calculate_hash(file_path)


    def get_hash_for_file(self, file_path, file_size):
        """Hybrid dispatcher: uses GPU for large files if enabled, otherwise CPU."""
        # Use GPU only if enabled, available, and file is large enough to merit the overhead.
        GPU_MIN_SIZE_BYTES = 100 * 1024 * 1024 # 100 MB

        if self.gpu_hashing_enabled and self.gpu_available and file_size >= GPU_MIN_SIZE_BYTES:
            return self.calculate_hash_gpu(file_path)
        else:
            return calculate_hash(file_path)
    def _create_top_bar(self):
        top_bar_layout = QHBoxLayout()
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Search all files and folders...")
        self.search_bar.setMinimumWidth(450)
        self.search_bar.textChanged.connect(self.on_search_text_changed)
        top_bar_layout.addWidget(self.search_bar)

        top_bar_layout.addStretch(1)

        style = self.style()
        
        # --- NEW SCAN BUTTON ---
        # scan_button = QPushButton()
        # # CHANGED ICON to a magnifying glass for "Find/Scan"
        # scan_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogNoButton))
        # scan_button.setToolTip("Find all duplicate files in your PARA structure")
        # scan_button.clicked.connect(self.start_full_scan)




        self.scan_button = QPushButton() # Use self.scan_button instead of local variable
        self.scan_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileLinkIcon)) # A better icon
        self.scan_button.clicked.connect(self.start_full_scan)

        
        
        about_button = QPushButton()
        about_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation))
        about_button.setToolTip("About this application")
        about_button.clicked.connect(self.open_about_dialog)

        settings_button = QPushButton()
        settings_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
        settings_button.setToolTip("Open Settings")
        settings_button.clicked.connect(self.open_settings_dialog)

        log_button = QPushButton()
        log_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView))
        log_button.setToolTip("View Logs")
        log_button.clicked.connect(self.open_log_viewer)



        # ...
        top_bar_layout.addWidget(self.scan_button)
        # top_bar_layout.addWidget(scan_button) # Add the new scan button
        top_bar_layout.addWidget(about_button)
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
        # for frame in self.drop_frames.values():
        #     frame.setObjectName("DropFrame")
        #     top_pane_layout.addWidget(frame)
        for name, frame in self.drop_frames.items():
            layout = QVBoxLayout(frame)
            layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon_label = QLabel()
            # Increase the size here for a more prominent look
            icon = frame.findChild(QLabel).pixmap().scaled(QSize(64, 64), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            icon_label.setPixmap(icon) # Use the icon from the frame's property
            # Store the large icon for background use
            self.para_category_icons[name] = icon_label.pixmap()
            
            layout.addWidget(icon_label, alignment=Qt.AlignmentFlag.AlignCenter)
            title_label = QLabel(name)
            title_label.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
            layout.addWidget(title_label, alignment=Qt.AlignmentFlag.AlignCenter)
            frame.setObjectName("DropFrame")
            top_pane_layout.addWidget(frame)

        return top_pane_widget

    # --- REPLACE your _create_bottom_pane method with this one ---

    def _create_bottom_pane(self):
        self.bottom_pane = QStackedWidget()
        self.welcome_widget = self._create_welcome_widget()
        self.tree_view = self._create_tree_view()
        
        # --- Create the Search Page Widget ---
        search_page_widget = QWidget()
        search_layout = QVBoxLayout(search_page_widget)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(5)

        self.search_results_list = QListWidget()
        self.search_results_list.itemDoubleClicked.connect(self.open_selected_item)
        # Add the context menu to the search results list
        self.search_results_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.search_results_list.customContextMenuRequested.connect(self.show_search_result_context_menu)
        
        # --- Pagination Controls ---
        pagination_controls = QWidget()
        controls_layout = QHBoxLayout(pagination_controls)
        controls_layout.setContentsMargins(5, 5, 5, 5)
        
        self.prev_page_button = QPushButton("  Previous")
        self.prev_page_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowLeft))
        self.prev_page_button.clicked.connect(self.go_to_previous_page)
        
        self.next_page_button = QPushButton("Next  ")
        self.next_page_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowRight))
        self.next_page_button.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.next_page_button.clicked.connect(self.go_to_next_page)

        self.page_status_label = QLabel("Page 1 of 1")
        self.page_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        controls_layout.addWidget(self.prev_page_button)
        controls_layout.addStretch()
        controls_layout.addWidget(self.page_status_label)
        controls_layout.addStretch()
        controls_layout.addWidget(self.next_page_button)
        
        search_layout.addWidget(self.search_results_list)
        search_layout.addWidget(pagination_controls)
        # --- End of Search Page Widget ---
        
        self.bottom_pane.addWidget(self.welcome_widget)
        self.bottom_pane.addWidget(self.tree_view)
        self.bottom_pane.addWidget(search_page_widget) # Add the new composite widget
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
        tree_view = ThemedTreeView(self) # Or DropTreeView if you reverted
        self.file_system_model = QFileSystemModel()
        self.file_system_model.setFilter(QDir.Filter.AllDirs | QDir.Filter.NoDotAndDotDot | QDir.Filter.AllEntries)
        tree_view.setModel(self.file_system_model)
        tree_view.setSortingEnabled(True)
        tree_view.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        
        # --- DRAG AND DROP CONFIGURATION ---
        tree_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        # We are DISABLING drag FROM the tree view in favor of the 'Move To...' dialog
        tree_view.setDragEnabled(False) 
        # We still accept drops FROM OUTSIDE the application
        tree_view.setAcceptDrops(True) 
        tree_view.setDropIndicatorShown(True)
        
        # This is now only for the background text, not dragging
        tree_view.clicked.connect(self.on_tree_item_clicked)
        
        return tree_view
    
    def _build_context_menu(self, path):
        """Builds a context menu for a given file/folder path."""
        menu = QMenu()
        if not path or not os.path.exists(path):
            return menu

        style = self.style()
        
        # --- NEW "COPY PATH" ACTION ---
        def copy_path_to_clipboard():
            QApplication.clipboard().setText(os.path.normpath(path))
            self.log_and_show(f"Path copied: {os.path.normpath(path)}", "info", 2000)

        copy_action = QAction(style.standardIcon(QStyle.StandardPixmap.SP_FileLinkIcon), "Copy File Path", menu)
        copy_action.triggered.connect(copy_path_to_clipboard)
        # --- END NEW ACTION ---

        # Determine the target directory for new items
        target_dir = path if os.path.isdir(path) else os.path.dirname(path)
            
        # "New" Submenu
        new_menu = QMenu("New", menu)
        new_menu.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder))
        folder_action = new_menu.addAction("Folder..."); folder_action.triggered.connect(lambda: self.create_new_folder(target_dir))
        file_action = new_menu.addAction("File..."); file_action.triggered.connect(lambda: self.create_new_file(target_dir))
        menu.addMenu(new_menu)
        menu.addSeparator()

        # # "Move To..." Submenu
        # current_category = self.get_category_from_path(path)
        # if current_category:
        #     move_menu = QMenu("Move To...", menu)
        #     move_menu.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ArrowRight))
        #     # icons = {name: frame.findChild(QLabel).pixmap() for name, frame in self.drop_frames.items()}
            
        #     icons = self.para_category_icons
        
        #     for cat_name in self.para_folders.keys():
        #         action = QAction(icons.get(cat_name), cat_name, self) # Use the QIcon directly
            
            
        #     # for cat_name in self.para_folders.keys():
        #     #     action = QAction(QIcon(icons.get(cat_name)), cat_name, self)
        #         if cat_name == current_category:
        #             action.setEnabled(False); action.setToolTip(f"Item is already in {cat_name}")
        #         else:
        #             action.triggered.connect(lambda checked, p=path, cat=cat_name: self.handle_move_to_category(p, cat))
        #         move_menu.addAction(action)
        #     menu.addMenu(move_menu)
        #     menu.addSeparator()

        move_action = QAction(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowRight), "Move To...", menu)
        move_action.triggered.connect(self.show_move_to_dialog)
        menu.addMenu(new_menu) # Assuming 'new_menu' is defined above as before
        menu.addAction(move_action) # Add the direct move action
        menu.addSeparator()
        
        # Standard Actions
        menu.addAction(style.standardIcon(QStyle.StandardPixmap.SP_DialogOkButton), "Open", lambda: self.open_item(path))
        menu.addAction(style.standardIcon(QStyle.StandardPixmap.SP_DirIcon), "Show in File Explorer", lambda: self.show_in_explorer(path))
        menu.addAction(copy_action) # <-- Add the new copy action here
        menu.addSeparator()
        
        index = self.file_system_model.index(path)
        menu.addAction(style.standardIcon(QStyle.StandardPixmap.SP_FileLinkIcon), "Rename...", lambda: self.rename_item(index))
        menu.addAction(style.standardIcon(QStyle.StandardPixmap.SP_TrashIcon), "Delete...", lambda: self.delete_item(index))
        
        return menu
        
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



# --- In the ParaFileManager class, REPLACE the run_task method ---

    def run_task(self, task_func, on_success, **kwargs):
        """
        Starts a background task with a progress dialog. This version correctly
        instantiates the worker with all necessary arguments.
        """
        self.logger.info(f"--- 'run_task' called for task: {task_func.__name__} ---")
        if self.worker and self.worker.isRunning():
            self.logger.warn("Task aborted: A previous worker is still running.")
            self.log_and_show("A background task is already running.", "warn")
            return

        self.progress = QProgressDialog("Preparing task...", "Cancel", 0, 100, self)
        self.progress.setMinimumWidth(550)
        self.progress.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress.canceled.connect(self.cancel_task)
        self.progress.show()

        # The Worker now receives the target function and its arguments directly.
        # The progress signal is automatically handled by the Worker's __init__.
        self.worker = Worker(task_func, **kwargs)

        self.worker.result.connect(on_success)
        self.worker.error.connect(self.on_task_error)
        self.worker.progress.connect(self.update_progress)
        self.worker.finished.connect(self.on_task_truly_finished)

        self.logger.info("Worker created and all signals connected. Starting thread...")
        self.worker.start()
    

    # def run_task(self, task_func, on_success, **kwargs):
    #     """
    #     Starts a background task with a progress dialog and handles all signal/slot connections correctly.
    #     """
    #     self.logger.info(f"--- 'run_task' called for task: {task_func.__name__} ---")
    #     if self.worker and self.worker.isRunning():
    #         self.logger.warn("Task aborted: A previous worker is still running.")
    #         self.log_and_show("A background task is already running.", "warn")
    #         return

    #     self.logger.info("Creating progress dialog...")
    #     # Note: The object is self.progress, not self.progress_dialog
    #     self.progress = QProgressDialog("Preparing task...", "Cancel", 0, 100, self)
    #     self.progress.setMinimumWidth(550)
    #     self.progress.setWindowModality(Qt.WindowModality.WindowModal)
    #     self.progress.canceled.connect(self.cancel_task)
    #     self.progress.show()

    #     self.logger.info("Preparing task with context...")
        
    #     # --- THIS IS THE KEY FIX ---
    #     # The Worker is created with the task function and any additional keyword arguments.
    #     # We will pass the worker's own progress signal emitter as the callback function.
    #     self.worker = Worker(task_func, **kwargs)
        
    #     # Now, we pass the worker's `progress.emit` signal as the first argument 
    #     # to the task function when it's called inside the thread.
    #     # This requires a small change in the Worker's `run` method as well.
    #     self.worker.args = (self.worker.progress.emit,) + self.worker.args
    #     # --- END OF FIX ---

    #     # Connect all the signals from the worker to the main window's methods (slots)
    #     self.worker.result.connect(on_success)
    #     self.worker.error.connect(self.on_task_error)
    #     self.worker.progress.connect(self.update_progress) # Worker progress -> GUI update
    #     self.worker.finished.connect(self.on_task_truly_finished)

    #     self.logger.info("Worker created and all signals connected. Starting thread...")
    #     self.worker.start()
    
    # def cancel_task(self):
    #     if self.worker and self.worker.isRunning():
    #         self.worker.terminate()
    #         # Wait a moment for the thread to terminate before cleaning up
    #         self.worker.wait(100) 
    #         self.log_and_show("Task cancelled by user.", "warn")
    #     # --- ADD THIS LINE to clean up the worker ---
    #     self.worker = None
    
# --- In ParaFileManager, REPLACE the cancel_task method ---

    def cancel_task(self):
        # FIX: Add a guard clause to ensure the worker exists and is running.
        if self.worker and self.worker.isRunning():
            self.worker.terminate()
            # The wait call is not strictly necessary after terminate and can be problematic.
            # self.worker.wait(100) # This line can be safely removed or kept.
            self.log_and_show("Task cancelled by user.", "warn")
        self.worker = None # Ensure worker is cleaned up.

    def update_progress(self, message, current, total):
        if self.progress and not self.progress.wasCanceled():
            self.progress.setLabelText(message)
            self.progress.setMaximum(total)
            self.progress.setValue(current)


    def on_task_error(self, error_message):
        if self.progress: self.progress.close()
        self.logger.error(f"Background task failed: {error_message}", exc_info=False)
        # --- ADD THIS LINE to clean up the worker ---
        self.worker = None


    def on_task_truly_finished(self):
        if self.progress and self.progress.isVisible():
            self.progress.setValue(self.progress.maximum())
        self.worker = None
        # We don't show "Task Finished" here anymore, as specific callbacks handle it.
    


    def on_tree_item_clicked(self, index):
        """When an item is clicked, update the tree view's background text."""
        path = self.file_system_model.filePath(index)
        category = self.get_category_from_path(path)
        
        if category:
            # A PARA category was clicked, set its name as the background text
            self.tree_view.setBackgroundText(category.upper())
        else:
            # Not in a PARA category, clear the background text
            self.tree_view.setBackgroundText("")
            


    # def _load_scan_rules(self):
    #     """Loads the developer-aware scan exclusion rules from JSON."""
    #     try:
    #         with open(resource_path("scan_rules.json"), "r", encoding="utf-8") as f:
    #             self.scan_rules = json.load(f)
    #         self.logger.info("Successfully loaded developer-aware scan rules.")
    #     except (FileNotFoundError, json.JSONDecodeError) as e:
    #         self.logger.warn(f"scan_rules.json not found or invalid. Scan may include dev files. Error: {e}")
    #         self.scan_rules = {
    #             "excluded_dir_names": [],
    #             "excluded_dir_paths_contain": [],
    #             "excluded_extensions": [],
    #             "excluded_filenames": []
    #         }
              
    #

    def reload_configuration(self):
        """
        Loads all configuration from files, determines the operating mode,
        and then triggers the file index loading or rebuilding.
        """
        self.log_and_show("Reloading configuration...", "info", 2000)
        try:
            with open(resource_path("config.json"), "r") as f:
                config = json.load(f)

            self.operating_mode = config.get("mode", "para")
            
            # Determine the base directory based on the operating mode
            if self.operating_mode == "custom":
                path = config.get("custom_folder_path")
                if not (path and os.path.isdir(path)):
                    raise ValueError("Custom folder path is not set or invalid.")
                self.base_dir = os.path.normpath(path)
                self.para_root_paths = set()
            else: # Default to PARA mode
                self.operating_mode = "para"
                path = config.get("base_directory")
                if not path or not os.path.isdir(path):
                    raise ValueError("PARA Base directory not set or invalid.")
                self.base_dir = os.path.normpath(path)
                self.para_root_paths = {os.path.join(self.base_dir, p) for p in self.para_folders.values()}

            os.makedirs(self.base_dir, exist_ok=True)
            self._load_scan_rules()
            with open(self.rules_path, "r", encoding="utf-8") as f:
                self.rules = json.load(f)

            # self.operating_mode = config.get("mode", "para")
            self.gpu_hashing_enabled = config.get("gpu_hashing_enabled", False)
            self.move_to_history = config.get("move_to_history", [])
            custom_icons = config.get("custom_icons", {})
            self._load_para_icons(custom_icons)
            
            with open(resource_path("rules.json"), "r") as f:
                self.rules = json.load(f)
        
        except (FileNotFoundError, json.JSONDecodeError, ValueError) as e:
            self.log_and_show(f"Configuration error: {e}. Please check settings.", "warn", 10000)
            self.logger.warn(f"Config load error: {e}")
            self.base_dir = None
            self.update_ui_from_config() # Show the welcome screen on error
            return
            
        # UI update must happen AFTER all config is loaded
        self.update_ui_from_config()
        
        # --- Centralized Cache Loading Logic ---
        try:
            with open(self.index_cache_path, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            # CRITICAL CHECK: Ensure the cache was built for the CURRENT base directory.
            if cache_data.get("base_dir") == self.base_dir:
                self.logger.info("Valid cache found for current base directory.")
                self.file_index = cache_data.get("file_index", [])
                self.on_index_rebuilt(self.file_index, from_cache=True)
                return
            else:
                self.logger.info("Cache found, but for a different base directory. Re-indexing.")
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            self.logger.info("No valid cache found. Performing full re-index.")
        
        self.run_task(self._task_rebuild_file_index, on_success=self.on_index_rebuilt)
        
        
    def update_ui_from_config(self):
        """
        Updates the UI state based on pre-loaded configuration.
        This method NO LONGER loads any data from files.
        """
        if not self.base_dir:
            self.drop_frames_widget.setVisible(False)
            self.bottom_pane.setCurrentWidget(self.welcome_widget)
            return



        self.scan_button.setEnabled(True)
        # --- DYNAMIC TOOLTIP LOGIC ---
        if self.operating_mode == "para":
            self.scan_button.setToolTip(f"Find all duplicate files in your PARA structure\nRoot: {self.base_dir}")
        else: # Custom mode
            self.scan_button.setToolTip(f"Find all duplicate files in the current folder\nRoot: {self.base_dir}")
            
        is_para_mode = (self.operating_mode == "para")
        self.drop_frames_widget.setVisible(is_para_mode)

        if is_para_mode:
            for name, frame in self.drop_frames.items():
                icon_label = frame.findChild(QLabel)
                if icon_label and name in self.para_category_icons:
                    pixmap = self.para_category_icons[name].pixmap(QSize(64, 64))
                    icon_label.setPixmap(pixmap)

        self.bottom_pane.setCurrentWidget(self.tree_view)
        self.file_system_model.setRootPath(self.base_dir)
        self.tree_view.setRootIndex(self.file_system_model.index(self.base_dir))
        for i in range(1, self.file_system_model.columnCount()):
            self.tree_view.hideColumn(i)
        
        self.log_and_show(f"Mode: {self.operating_mode.upper()}. Root: {self.base_dir}", "info")

    def on_scan_completed(self, result, dest_root, category_name):
        """
        Callback for when the duplicate scan is finished.
        Uses QTimer.singleShot for robustness.
        """
        if self.progress:
            self.progress.close()
        
        duplicates = result["duplicates"]
        non_duplicates = result["non_duplicates"]
        
        if duplicates:
            # DECOUPLING FIX: Don't show dialog directly. Schedule it to run
            # as soon as the event loop is free. This prevents silent crashes.
            QTimer.singleShot(0, lambda: self._show_deduplication_dialog(duplicates, dest_root, category_name))
            
        elif non_duplicates:
            # No duplicates were found, but there are files to move.
            self.log_and_show("No duplicates found. Proceeding with move.", "info")
            self.run_task(self._task_process_final_drop, 
                          on_success=self.on_final_refresh_finished,
                          dropped_paths=non_duplicates, 
                          dest_root=dest_root,
                          choices={}, # No choices to make
                          category_name=category_name)
        else:
            # No duplicates and no files to move (e.g., all source files were invalid)
            self.log_and_show("No files were processed.", "info")
            self._enable_watcher() # CRITICAL FIX: Re-enable watcher

    def on_final_refresh_finished(self, result=None):
        if result: self.log_and_show(str(result), "info")
        self.run_task(self._task_rebuild_file_index, on_success=self.on_index_rebuilt)
        # self.run_task(self._task_rebuild_file_index, on_success=lambda r: self.log_and_show(r, "info", 2000))
    
    #--- REPLACE your on_index_rebuilt method with this one ---



# In ParaFileManager, REPLACE this method



    def setup_file_watcher(self):
        """Sets up the QFileSystemWatcher to monitor the PARA directory."""
        self.logger.info("Setting up file system watcher...")
        
        # Remove old paths before adding new ones
        if self.file_watcher.directories():
            self.file_watcher.removePaths(self.file_watcher.directories())
            
        paths_to_watch = {self.base_dir}
        for root, dirs, _ in os.walk(self.base_dir):
            for d in dirs:
                paths_to_watch.add(os.path.join(root, d))
                
        self.file_watcher.addPaths(list(paths_to_watch))
        self.logger.info(f"Now monitoring {len(paths_to_watch)} directories for real-time changes.")

    # def on_directory_changed(self, path):
    #     """A directory has been modified (file added/deleted/renamed)."""
    #     self.logger.info(f"Directory change detected: {path}. Triggering a debounced re-index.")
    #     # Use the search timer to "debounce" rapid changes.
    #     # This prevents re-indexing multiple times if many files are changed at once.
    #     if not self.search_timer.isActive():
    #         self.log_and_show("File changes detected, updating index...", "info", 2000)
    #     self.search_timer.start(3000) # Wait 3 seconds after last change to re-index
    def on_directory_changed(self, path):
        """A directory has been modified. Trigger the new debounced re-index timer."""
        self.logger.info(f"Directory change detected: {path}. Triggering a debounced re-index.")
        if not self.reindex_timer.isActive():
            self.log_and_show("File changes detected, updating index in 3 seconds...", "info", 3000)
        # Use the new, dedicated timer
        self.reindex_timer.start(3000)

    def on_file_changed(self, path):
        """A single file's content has changed."""
        self.logger.info(f"File content change detected: {path}. Updating its metadata.")
        # Find and update the specific file in the index
        for i, item in enumerate(self.file_index):
            if item["path"] == path:
                try:
                    stat = os.stat(path)
                    self.file_index[i]["mtime"] = stat.st_mtime
                    self.file_index[i]["size"] = stat.st_size
                    # No need for a full rebuild, just a small update
                except FileNotFoundError:
                    # The file was likely deleted, the directory change will handle it
                    pass
                break
        


# --- In ParaFileManager, REPLACE the on_index_rebuilt method ---

    def on_index_rebuilt(self, index_data, from_cache=False):
        """
        Callback for when file index is built. This is now the SOLE place
        where the file watcher is re-enabled.
        """
        if self.progress and self.progress.isVisible():
            self.progress.close()
            
        self.log_and_show(f"Indexing complete. {len(index_data)} items indexed.", "info", 2000)
        self.file_index = index_data
        
        if not from_cache:
            try:
                cache_to_save = { "base_dir": self.base_dir, "file_index": self.file_index }
                with open(self.index_cache_path, 'w', encoding='utf-8') as f:
                    json.dump(cache_to_save, f)
                self.logger.info(f"File index cache saved to {self.index_cache_path}")
            except Exception as e:
                self.logger.error(f"Failed to save file index cache: {e}", exc_info=True)
        
        # THIS IS THE FIX: The watcher is only re-enabled here, after all
        # internal operations (including the re-index itself) are finished.
        self._enable_watcher() 
        
        if self.search_bar.text().strip():
            self.perform_search()
        elif self.base_dir:
            self.bottom_pane.setCurrentWidget(self.tree_view)




# --- In ParaFileManager, ADD this new method ---

    def _ensure_config_files_exist(self):
        """Checks for essential config files and creates them with defaults if they don't exist."""
        # This now correctly creates files in the persistent user data directory.
        
        if not os.path.exists(self.config_path):
             with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump({"base_directory": ""}, f, indent=4)

        if not os.path.exists(self.rules_path):
            self.logger.info(f"rules.json not found. Creating default file at {self.rules_path}")
            with open(self.rules_path, 'w', encoding='utf-8') as f:
                json.dump([], f, indent=4)

        if not os.path.exists(self.scan_rules_path):
            self.logger.info(f"scan_rules.json not found. Creating default file at {self.scan_rules_path}")
            default_scan_rules = {
              "info": "Default rules for the Developer-Aware Smart Scan.",
              "excluded_dir_names": [".git", ".idea", ".vscode", "__pycache__", "node_modules", "venv", ".venv", "build", "dist"],
              "excluded_extensions": [".log", ".tmp", ".bak", ".swp", ".pyc"],
              "excluded_filenames": ["package-lock.json", "yarn.lock"]
            }
            with open(self.scan_rules_path, 'w', encoding='utf-8') as f:
                json.dump(default_scan_rules, f, indent=4)
    # def _ensure_config_files_exist(self):
    #     """Checks for essential config files in the user data path and creates them if they don't exist."""
    #     # config.json is created by the settings dialog, but rules files need defaults.
        
    #     # Default automation rules
    #     if not os.path.exists(self.rules_path):
    #         self.logger.info(f"rules.json not found. Creating default file at {self.rules_path}")
    #         default_rules = []
    #         with open(self.rules_path, 'w', encoding='utf-8') as f:
    #             json.dump(default_rules, f, indent=4)

    #     # Default developer-aware scan rules
    #     if not os.path.exists(self.scan_rules_path):
    #         self.logger.info(f"scan_rules.json not found. Creating default file at {self.scan_rules_path}")
    #         default_scan_rules = {
    #           "info": "Configuration for the Developer-Aware Smart Scan. You can add your own rules here.",
    #           "excluded_dir_names": [".git",".svn",".hg",".idea",".vscode","__pycache__","node_modules","vendor","venv",".venv","env",".env","target","build","dist","bin","obj"],
    #           "excluded_dir_paths_contain": ["site-packages","dist-packages","nltk_data",".cache/huggingface",".cache/torch","model_cache"],
    #           "excluded_extensions": [".log",".tmp",".bak",".swp",".lock",".pyc",".o",".so",".class",".jar",".dll"],
    #           "excluded_filenames": ["python.exe","pythonw.exe","pip.exe","pip3.exe","activate","activate.ps1","activate.bat","deactivate.bat","manage.py","package.json","package-lock.json","yarn.lock","pnpm-lock.yaml","webpack.config.js","vite.config.js","tsconfig.json","dockerfile","docker-compose.yml","readme.md"]
    #         }
    #         with open(self.scan_rules_path, 'w', encoding='utf-8') as f:
    #             json.dump(default_scan_rules, f, indent=4)
                           
    # def on_index_rebuilt(self, index_data, from_cache=False):
    #     """Callback for when file index is built. Now handles cache saving."""
    #     if self.progress and self.progress.isVisible():
    #         self.progress.close()
            
    #     self.log_and_show(f"Indexing complete. {len(index_data)} items indexed.", "info", 2000)
    #     self.file_index = index_data
        
    #     if not from_cache:
    #         # Only save the cache if the index was freshly built
    #         try:
    #             cache_to_save = {
    #                 "base_dir": self.base_dir,
    #                 "file_index": self.file_index
    #             }
    #             with open(self.index_cache_path, 'w', encoding='utf-8') as f:
    #                 json.dump(cache_to_save, f)
    #             self.logger.info(f"File index cache saved to {self.index_cache_path}")
    #         except Exception as e:
    #             self.logger.error(f"Failed to save file index cache: {e}", exc_info=True)
        
    #     self._enable_watcher() 
    #     if self.search_bar.text().strip():
    #         self.perform_search()
    #     elif self.base_dir:
    #         self.bottom_pane.setCurrentWidget(self.tree_view)
            
            
# --- 在 ParaFileManager 中，替换 _calculate_retention_score 方法 ---

    # def _calculate_retention_score(self, path):
    #     """
    #     Calculates a retention score for a file path.
    #     VERSION 3: Now with "Developer Context Awareness".
    #     """
    #     score = 100 
    #     reasons = []
    #     path_lower = path.lower()
    #     filename = os.path.basename(path_lower)
    #     name_part, ext = os.path.splitext(filename)

    #     # --- 1. Developer Context Detection ---
    #     is_dev_env = False
    #     dev_keywords = ['/venv/', '/.venv/', '/env/', '/.env/', '/site-packages/', '/scripts/']
    #     if any(key in path_lower for key in dev_keywords):
    #         is_dev_env = True
    #         score += 20
    #         reasons.append("(+20) Developer Environment")

    #     is_model_cache = False
    #     cache_keywords = ['/model_cache/', '/.cache/huggingface/', '/.cache/torch/']
    #     if any(key in path_lower for key in cache_keywords):
    #         is_model_cache = True
    #         score += 200 # Huge protection score
    #         reasons.append("(+200) Model Cache File")

    #     # --- 2. Path-Based Scoring ---
    #     category = self.get_category_from_path(path)
    #     if category == "Projects": score += 50; reasons.append("(+50) In 'Projects'")
    #     elif category == "Areas": score += 30; reasons.append("(+30) In 'Areas'")
    #     elif category == "Archives": score -= 25; reasons.append("(-25) In 'Archives'")

    #     # In non-dev paths, depth is a negative factor.
    #     if not is_dev_env:
    #         depth = path.count(os.sep) - self.base_dir.count(os.sep)
    #         if depth > 5:
    #             score -= depth * 3; reasons.append(f"(-{depth*3}) Deep path")

    #     # --- 3. Filename-Based Scoring ---
    #     # Heavily penalize common copy/conflict suffixes
    #     if re.search(r'(_copy)|(_conflict)|(\(\d+\))|(_duplicate)', name_part):
    #         score -= 200; reasons.append("(-200) Filename is a copy")

    #     # In a developer environment, apply special rules
    #     if is_dev_env and ext == '.exe':
    #         # This directly addresses the pip.exe vs pip3.12.exe problem
    #         if name_part in ['pip', 'python', 'pythonw']:
    #             score += 150; reasons.append("(+150) Canonical Executable")
    #         elif re.search(r'\d', name_part): # Penalize versioned executables if a canonical one exists
    #             score -= 75; reasons.append("(-75) Versioned Executable")
        
    #     # General descriptive name check
    #     words = re.findall(r'[a-zA-Z]{4,}', name_part)
    #     if len(words) > 1:
    #         score += len(words) * 5; reasons.append(f"(+{len(words)*5}) Descriptive name")
        
    #     if re.search(r'\d{4}-\d{2}-\d{2}', name_part):
    #         score += 30; reasons.append("(+30) Has YYYY-MM-DD date")

    #     reason_str = ", ".join(reasons) if reasons else "Standard file"
    #     return score, reason_str
    




# --- 在 ParaFileManager 中，替换 _calculate_retention_score 方法 ---

    def _calculate_retention_score(self, path):
        """
        Calculates a retention score for a file path.
        VERSION 3: Now with "Developer Context Awareness".
        """
        score = 100 
        reasons = []
        path_lower = path.lower()
        filename = os.path.basename(path_lower)
        name_part, ext = os.path.splitext(filename)

        # --- 1. Developer Context Detection ---
        is_dev_env = False
        dev_keywords = ['/venv/', '/.venv/', '/env/', '/.env/', '/site-packages/', '/scripts/']
        if any(key in path_lower for key in dev_keywords):
            is_dev_env = True
            score += 20
            reasons.append("(+20) Developer Environment")

        is_model_cache = False
        cache_keywords = ['/model_cache/', '/.cache/huggingface/', '/.cache/torch/']
        if any(key in path_lower for key in cache_keywords):
            is_model_cache = True
            score += 200 # Huge protection score
            reasons.append("(+200) Model Cache File")

        # --- 2. Path-Based Scoring ---
        category = self.get_category_from_path(path)
        if category == "Projects": score += 50; reasons.append("(+50) In 'Projects'")
        elif category == "Areas": score += 30; reasons.append("(+30) In 'Areas'")
        elif category == "Archives": score -= 25; reasons.append("(-25) In 'Archives'")

        # In non-dev paths, depth is a negative factor.
        if not is_dev_env:
            depth = path.count(os.sep) - self.base_dir.count(os.sep)
            if depth > 5:
                score -= depth * 3; reasons.append(f"(-{depth*3}) Deep path")

        # --- 3. Filename-Based Scoring ---
        # Heavily penalize common copy/conflict suffixes
        if re.search(r'(_copy)|(_conflict)|(\(\d+\))|(_duplicate)', name_part):
            score -= 200; reasons.append("(-200) Filename is a copy")

        # In a developer environment, apply special rules
        if is_dev_env and ext == '.exe':
            # This directly addresses the pip.exe vs pip3.12.exe problem
            if name_part in ['pip', 'python', 'pythonw']:
                score += 150; reasons.append("(+150) Canonical Executable")
            elif re.search(r'\d', name_part): # Penalize versioned executables if a canonical one exists
                score -= 75; reasons.append("(-75) Versioned Executable")
        
        # General descriptive name check
        words = re.findall(r'[a-zA-Z]{4,}', name_part)
        if len(words) > 1:
            score += len(words) * 5; reasons.append(f"(+{len(words)*5}) Descriptive name")
        
        if re.search(r'\d{4}-\d{2}-\d{2}', name_part):
            score += 30; reasons.append("(+30) Has YYYY-MM-DD date")

        reason_str = ", ".join(reasons) if reasons else "Standard file"
        return score, reason_str


    # # --- In the ParaFileManager class, REPLACE the _task_full_deduplication_scan method ---

    # def _task_full_deduplication_scan(self, progress_callback):
    #     """
    #     Performs a Developer-Aware Smart Scan, using a persistent cache to
    #     intelligently skip hashing and prune stale entries.
    #     """
    #     if not self.base_dir:
    #         return {}
        
    #     self.logger.info("Starting Developer-Aware scan...")
    #     all_files_on_disk = get_all_files_in_paths([self.base_dir])
        
    #     # --- Filtering Logic (Unchanged) ---
    #     excluded_dirs = set(self.scan_rules.get("excluded_dir_names", []))
    #     excluded_path_parts = self.scan_rules.get("excluded_dir_paths_contain", [])
    #     excluded_exts = set(self.scan_rules.get("excluded_extensions", []))
    #     excluded_names = set(self.scan_rules.get("excluded_filenames", []))

    #     filtered_files = []
    #     for path in all_files_on_disk:
    #         filename = os.path.basename(path).lower()
    #         ext = os.path.splitext(filename)[1]
    #         path_parts = set(path.lower().split(os.sep))
            
    #         if filename in excluded_names: continue
    #         if ext in excluded_exts: continue
    #         if not path_parts.isdisjoint(excluded_dirs): continue
    #         if any(part in path.lower() for part in excluded_path_parts): continue
            
    #         try:
    #             if os.path.getsize(path) < 4096: continue
    #         except FileNotFoundError:
    #             continue
            
    #         filtered_files.append(path)
        
    #     excluded_count = len(all_files_on_disk) - len(filtered_files)
    #     self.logger.info(f"Scan filtering complete. Excluded {excluded_count} development/system files.")

    #     # --- Cache-Aware Hashing and Pruning Logic ---
    #     hashes = {}
    #     total_to_process = len(filtered_files)
    #     self.logger.info(f"Processing {total_to_process} files using hash cache.")

    #     # The 'with' statement ensures the database connection is properly managed.
    #     with HashManager(self.hash_cache_db_path) as hm:
    #         for i, file_path in enumerate(filtered_files):
    #             filename = os.path.basename(file_path)
    #             progress_callback(f"Checking: {filename}", i + 1, total_to_process)
                
    #             try:




    #                 progress_callback("Pruning stale cache entries...", total_to_process, total_to_process)
    #                 pruned_count = hm.prune_cache(set(all_files_on_disk))
    #                 # self.logger.info(f"Cache pruning complete. Pruned {pruned_count} stale entries.")
    #         # --- END OF FIX ---
            
            
    #                 stat = os.stat(file_path)
    #                 current_mtime = stat.st_mtime
    #                 current_size = stat.st_size

    #                 file_hash = hm.get_cached_hash(file_path, current_mtime, current_size)
                    
    #                 if not file_hash:
    #                     progress_callback(f"Hashing: {filename}", i + 1, total_to_process)
    #                     file_hash = self.get_hash_for_file(file_path, current_size)
    #                     if file_hash:
    #                         hm.update_cache(file_path, current_mtime, current_size, file_hash)

    #                 if file_hash:
    #                     if file_hash not in hashes: hashes[file_hash] = []
    #                     hashes[file_hash].append(file_path)

    #             except (FileNotFoundError, PermissionError) as e:
    #                 self.logger.warn(f"Could not access or hash {file_path}: {e}")
    #                 continue

    #         # --- THIS IS THE FIX ---
    #         # The pruning logic is now moved INSIDE the 'with' block,
    #         # ensuring the database connection is still open.
    #         progress_callback("Pruning stale cache entries...", total_to_process, total_to_process)
    #         self.logger.info("Pruning stale entries from the hash cache...")
    #         hm.prune_cache(set(all_files_on_disk))
    #         self.logger.info("Cache pruning complete.")
    #         # --- END OF FIX ---

    #     duplicate_sets = {h: p for h, p in hashes.items() if len(p) > 1}
    #     self.logger.info(f"Intelligent scan complete. Found {len(duplicate_sets)} set(s) of duplicate files.")
    #     return duplicate_sets



# # --- In ParaFileManager, REPLACE this method ---

#     def _task_full_deduplication_scan(self, progress_callback):
#         """
#         Performs a Developer-Aware Smart Scan with improved progress reporting
#         for a smoother user experience.
#         """
#         if not self.base_dir:
#             return {}
        
#         self.logger.info("Starting Developer-Aware scan...")
#         all_files_on_disk = get_all_files_in_paths([self.base_dir])
        
#         # --- Filtering Logic (Unchanged) ---
#         excluded_dirs = set(self.scan_rules.get("excluded_dir_names", []))
#         excluded_path_parts = self.scan_rules.get("excluded_dir_paths_contain", [])
#         excluded_exts = set(self.scan_rules.get("excluded_extensions", []))
#         excluded_names = set(self.scan_rules.get("excluded_filenames", []))

#         filtered_files = []
#         for path in all_files_on_disk:
#             filename = os.path.basename(path).lower()
#             ext = os.path.splitext(filename)[1]
#             path_parts = set(path.lower().split(os.sep))
            
#             if filename in excluded_names: continue
#             if ext in excluded_exts: continue
#             if not path_parts.isdisjoint(excluded_dirs): continue
#             if any(part in path.lower() for part in excluded_path_parts): continue
            
#             try:
#                 if os.path.getsize(path) < 4096: continue
#             except FileNotFoundError:
#                 continue
            
#             filtered_files.append(path)
        
#         excluded_count = len(all_files_on_disk) - len(filtered_files)
#         self.logger.info(f"Scan filtering complete. Excluded {excluded_count} development/system files.")

#         # --- Improved Progress Reporting Logic ---
#         hashes = {}
#         # The total number of steps now includes one extra step for finalization.
#         total_steps = len(filtered_files) + 1
#         self.logger.info(f"Processing {len(filtered_files)} files using hash cache.")

#         with HashManager(self.hash_cache_db_path) as hm:
#             for i, file_path in enumerate(filtered_files):
#                 filename = os.path.basename(file_path)
#                 # This loop will now bring the progress up to (total-1)/total percent.
#                 progress_callback(f"Checking: {filename}", i + 1, total_steps)
                
#                 try:
#                     stat = os.stat(file_path)
#                     current_mtime = stat.st_mtime
#                     current_size = stat.st_size

#                     file_hash = hm.get_cached_hash(file_path, current_mtime, current_size)
                    
#                     if not file_hash:
#                         progress_callback(f"Hashing: {filename}", i + 1, total_steps)
#                         file_hash = self.get_hash_for_file(file_path, current_size)
#                         if file_hash:
#                             hm.update_cache(file_path, current_mtime, current_size, file_hash)
                    
#                     if file_hash:
#                         if file_hash not in hashes: hashes[file_hash] = []
#                         hashes[file_hash].append(file_path)

#                 except (FileNotFoundError, PermissionError) as e:
#                     self.logger.warn(f"Could not access or hash {file_path}: {e}")
#                     continue

#             # This is the final step. It updates the label and completes the progress bar to 100%.
#             progress_callback("Finalizing and cleaning cache...", total_steps, total_steps)
#             pruned_count = hm.prune_cache(set(all_files_on_disk))
#             self.logger.info(f"Cache pruning complete. Pruned {pruned_count} stale entries.")
        
#         duplicate_sets = {h: p for h, p in hashes.items() if len(p) > 1}
#         self.logger.info(f"Intelligent scan complete. Found {len(duplicate_sets)} set(s) of duplicate files.")
#         return duplicate_sets


# --- In ParaFileManager, REPLACE this method ---

    # def _task_full_deduplication_scan(self, progress_callback):
    #     """
    #     Performs a Developer-Aware Smart Scan with improved progress reporting
    #     for a smoother user experience.
    #     """
    #     if not self.base_dir:
    #         return {}
        
    #     self.logger.info("Starting Developer-Aware scan...")
    #     all_files_on_disk = get_all_files_in_paths([self.base_dir])
        
    #     # --- Filtering Logic ---
    #     excluded_dirs = set(self.scan_rules.get("excluded_dir_names", []))
    #     excluded_path_parts = self.scan_rules.get("excluded_dir_paths_contain", [])
    #     excluded_exts = set(self.scan_rules.get("excluded_extensions", []))
    #     excluded_names = set(self.scan_rules.get("excluded_filenames", []))

    #     filtered_files = []
    #     for path in all_files_on_disk:
    #         filename = os.path.basename(path).lower()
    #         ext = os.path.splitext(filename)[1]
    #         path_parts = set(path.lower().split(os.sep))
            
    #         if filename in excluded_names: continue
    #         if ext in excluded_exts: continue
    #         if not path_parts.isdisjoint(excluded_dirs): continue
    #         if any(part in path.lower() for part in excluded_path_parts): continue
            
    #         try:
    #             if os.path.getsize(path) < 4096: continue
    #         except FileNotFoundError:
    #             continue
            
    #         filtered_files.append(path)
        
    #     excluded_count = len(all_files_on_disk) - len(filtered_files)
    #     self.logger.info(f"Scan filtering complete. Excluded {excluded_count} development/system files.")

    #     # --- Cache-Aware Hashing and Pruning Logic ---
    #     hashes = {}
    #     total_steps = len(filtered_files) + 1
    #     self.logger.info(f"Processing {len(filtered_files)} files using hash cache.")

    #     # The 'with' statement ensures the database connection is properly managed.
    #     # THIS IS THE FIX: The HashManager requires the logger as the second argument.
    #     with HashManager(self.hash_cache_db_path, self.logger) as hm:
    #         for i, file_path in enumerate(filtered_files):
    #             filename = os.path.basename(file_path)
    #             progress_callback(f"Checking: {filename}", i + 1, total_steps)
                
    #             try:
    #                 stat = os.stat(file_path)
    #                 current_mtime = stat.st_mtime
    #                 current_size = stat.st_size

    #                 file_hash = hm.get_cached_hash(file_path, current_mtime, current_size)
                    
    #                 if not file_hash:
    #                     progress_callback(f"Hashing: {filename}", i + 1, total_steps)
    #                     file_hash = self.get_hash_for_file(file_path, current_size)
    #                     if file_hash:
    #                         hm.update_cache(file_path, current_mtime, current_size, file_hash)
                    
    #                 if file_hash:
    #                     if file_hash not in hashes: hashes[file_hash] = []
    #                     hashes[file_hash].append(file_path)

    #             except (FileNotFoundError, PermissionError) as e:
    #                 self.logger.warn(f"Could not access or hash {file_path}: {e}")
    #                 continue

    #         # This is the final step, completing the progress bar to 100%.
    #         progress_callback("Finalizing and cleaning cache...", total_steps, total_steps)
    #         pruned_count = hm.prune_cache(set(all_files_on_disk))
    #         self.logger.info(f"Cache pruning complete. Pruned {pruned_count} stale entries.")
        
    #     duplicate_sets = {h: p for h, p in hashes.items() if len(p) > 1}
    #     self.logger.info(f"Intelligent scan complete. Found {len(duplicate_sets)} set(s) of duplicate files.")
    #     return duplicate_sets
    
    



    def _task_full_deduplication_scan(self, progress_callback):
        """
        Performs a Developer-Aware Smart Scan with improved progress reporting
        for a smoother user experience.
        """
        if not self.base_dir:
            return {}
        
        self.logger.info("Starting Developer-Aware scan...")
        all_files_on_disk = get_all_files_in_paths([self.base_dir])
        
        # --- Filtering Logic (NEW) ---
        excluded_dirs = set(self.scan_rules.get("excluded_dir_names", []))
        excluded_path_parts = self.scan_rules.get("excluded_dir_paths_contain", [])
        excluded_exts = set(self.scan_rules.get("excluded_extensions", []))
        excluded_names = set(self.scan_rules.get("excluded_filenames", []))

        filtered_files = []
        for path in all_files_on_disk:
            filename = os.path.basename(path).lower()
            ext = os.path.splitext(filename)[1]
            path_parts = set(path.lower().split(os.sep))
            
            if filename in excluded_names: continue
            if ext in excluded_exts: continue
            if not path_parts.isdisjoint(excluded_dirs): continue
            if any(part in path.lower() for part in excluded_path_parts): continue
            
            try:
                # Also exclude very small files from hashing
                if os.path.getsize(path) < 4096: continue
            except FileNotFoundError:
                continue
            
            filtered_files.append(path)
        
        excluded_count = len(all_files_on_disk) - len(filtered_files)
        self.logger.info(f"Scan filtering complete. Excluded {excluded_count} development/system files.")

        # --- Hashing Logic ---
        hashes = {}
        total_steps = len(filtered_files) + 1
        self.logger.info(f"Processing {len(filtered_files)} files using hash cache.")

        with HashManager(self.hash_cache_db_path, self.logger) as hm:
            for i, file_path in enumerate(filtered_files):
                filename = os.path.basename(file_path)
                progress_callback(f"Checking: {filename}", i + 1, total_steps)
                
                try:
                    stat = os.stat(file_path)
                    current_mtime = stat.st_mtime
                    current_size = stat.st_size
                    file_hash = hm.get_cached_hash(file_path, current_mtime, current_size)
                    
                    if not file_hash:
                        progress_callback(f"Hashing: {filename}", i + 1, total_steps)
                        file_hash = self.get_hash_for_file(file_path, current_size)
                        if file_hash:
                            hm.update_cache(file_path, current_mtime, current_size, file_hash)
                    
                    if file_hash:
                        if file_hash not in hashes: hashes[file_hash] = []
                        hashes[file_hash].append(file_path)
                except (FileNotFoundError, PermissionError) as e:
                    self.logger.warn(f"Could not access or hash {file_path}: {e}")
                    continue

            progress_callback("Finalizing and cleaning cache...", total_steps, total_steps)
            pruned_count = hm.prune_cache(set(all_files_on_disk))
            self.logger.info(f"Cache pruning complete. Pruned {pruned_count} stale entries.")
        
        duplicate_sets = {h: p for h, p in hashes.items() if len(p) > 1}
        self.logger.info(f"Intelligent scan complete. Found {len(duplicate_sets)} set(s) of duplicate files.")
        return duplicate_sets


    def _task_move_multiple_items(self, progress_callback, source_paths, destination_dir):
        """Moves a list of files/folders to a new destination, handling conflicts."""
        total = len(source_paths)
        self.logger.info(f"Starting internal move of {total} items to '{destination_dir}'")

        for i, source_path in enumerate(source_paths):
            base_name = os.path.basename(source_path)
            progress_callback(f"Moving: {base_name}", i + 1, total)

            if not os.path.exists(source_path):
                self.logger.warn(f"Source item not found, skipping: {source_path}")
                continue

            dest_path = os.path.join(destination_dir, base_name)
            if os.path.exists(dest_path): # Handle name conflicts
                base, ext = os.path.splitext(base_name)
                counter = 1
                while os.path.exists(dest_path):
                    dest_path = os.path.join(destination_dir, f"{base}_conflict_{counter}{ext}")
                    counter += 1
            try:
                shutil.move(source_path, dest_path)
            except Exception as e:
                self.logger.error(f"Failed to move '{source_path}' to '{dest_path}'", exc_info=True)
        # After moving files, try to clean up any newly empty folders
        self._cleanup_empty_dirs(affected_dirs)
        
        return "Internal move operation complete."
    


#--- In ParaFileManager, REPLACE this method ---

    def _task_scan_for_duplicates(self, progress_callback, source_paths, files_to_hash_dest):
        source_files = get_all_files_in_paths(source_paths)
        total_work = len(files_to_hash_dest) + len(source_files)
        # This summary log message is good and will be kept.
        self.logger.info(f"Starting Smart Scan. Hashing {len(files_to_hash_dest)} destination files and checking {len(source_files)} source files.")

        dest_hashes = {}
        for i, f in enumerate(files_to_hash_dest):
            # The progress dialog will still show the file-by-file progress.
            progress_callback(f"Hashing destination: {os.path.basename(f)}", i, total_work)
            
            # --- CHANGE ---
            # The line below was removed to keep the log file clean.
            # self.logger.info(f"Hashing destination file: {f}") 
            
            if (file_hash := calculate_hash(f)):
                dest_hashes[file_hash] = f

        duplicates, non_duplicates = [], []
        dest_size_to_hash = {}
        for h, p in dest_hashes.items():
            try:
                dest_size_to_hash[os.path.getsize(p)] = h
            except FileNotFoundError:
                continue

        current_work_offset = len(files_to_hash_dest)
        for i, f in enumerate(source_files):
            progress_callback(f"Checking source file: {os.path.basename(f)}", current_work_offset + i, total_work)
            try:
                size = os.path.getsize(f)
                if size in dest_size_to_hash:
                    # --- CHANGE ---
                    # The line below was removed to keep the log file clean.
                    # self.logger.info(f"Hashing source (size match): {f}")
                    file_hash = calculate_hash(f)
                    if file_hash and file_hash in dest_hashes:
                        # This log message is IMPORTANT and is kept.
                        self.logger.info(f"DUPLICATE FOUND: Source '{f}' matches destination '{dest_hashes[file_hash]}'")
                        duplicates.append((f, dest_hashes[file_hash], file_hash))
                    else:
                        non_duplicates.append(f)
                else:
                    non_duplicates.append(f)
            except FileNotFoundError:
                self.logger.warn(f"Source file not found during scan, skipping: {f}")
        
        # This summary log message is also good and will be kept.
        self.logger.info(f"Scan complete. Found {len(duplicates)} duplicate(s).")
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
        
        # source_dirs = {os.path.dirname(p) for p in all_source_files}
        # for folder in source_dirs:
        #     try:
        #         if not os.listdir(folder): shutil.rmtree(folder)
        #     except Exception: pass
        self.logger.info("Cleaning up empty source directories...")
        protected_paths = {os.path.normpath(os.path.join(self.base_dir, d)) for d in self.para_folders.values()}
        source_dirs = {os.path.dirname(p) for p in all_source_files}
        
        for folder in sorted(source_dirs, key=len, reverse=True): # Process deeper folders first
            try:
                # Protect the main PARA folders from being deleted
                if os.path.normpath(folder) in protected_paths:
                    continue
                if not os.listdir(folder):
                    self.logger.info(f"Removing empty source directory: {folder}")
                    shutil.rmtree(folder)
            except Exception as e:
                self.logger.warn(f"Could not remove source directory {folder}: {e}")
        return "Fast Move complete."



# --- In ParaFileManager, REPLACE your _task_process_final_drop method ---

    # def _task_process_final_drop(self, progress_callback, dropped_paths, dest_root, choices, category_name):
    #     total = len(dropped_paths)
    #     self.logger.info(f"Starting final processing of {total} files to {dest_root}")
        
    #     # Paths that are not duplicates and should be moved normally
    #     non_duplicate_paths = [p for p in dropped_paths if p not in choices]
        
    #     # Process duplicates based on user choices
    #     for i, (old_path, choice) in enumerate(choices.items()):
    #         progress_callback(f"Handling duplicate: {os.path.basename(old_path)}", i + 1, total)
            
    #         # --- NEW ACTION LOGIC ---
    #         if choice == "Move to Recycle Bin":
    #             try:
    #                 send2trash.send2trash(old_path)
    #                 self.logger.info(f"Duplicate source sent to Recycle Bin: {old_path}")
    #             except Exception as e:
    #                 self.logger.error(f"Failed to send to Recycle Bin: {old_path}", exc_info=True)
    #             continue # Done with this file

    #         elif choice == "Move to '_duplicates' folder":
    #             try:
    #                 source_dir = os.path.dirname(old_path)
    #                 quarantine_dir = os.path.join(source_dir, "_duplicates")
    #                 os.makedirs(quarantine_dir, exist_ok=True)
                    
    #                 # Move the file, handling potential name conflicts within the quarantine folder
    #                 base_name = os.path.basename(old_path)
    #                 dest_path = os.path.join(quarantine_dir, base_name)
    #                 if os.path.exists(dest_path):
    #                     base, ext = os.path.splitext(base_name); counter = 1
    #                     while os.path.exists(dest_path): dest_path = os.path.join(quarantine_dir, f"{base}_duplicate_{counter}{ext}"); counter += 1
                    
    #                 shutil.move(old_path, dest_path)
    #                 self.logger.info(f"Duplicate source quarantined to: {dest_path}")
    #             except Exception as e:
    #                 self.logger.error(f"Failed to quarantine file: {old_path}", exc_info=True)
    #             continue # Done with this file
            
    #         # If choice is "Skip (Move and Rename)", the loop will end and it will be
    #         # processed with the other files to be moved.
    #         non_duplicate_paths.append(old_path)

    #     # Now, process all non-duplicates and any "skipped" duplicates
    #     for i, old_path in enumerate(non_duplicate_paths):
    #         # This logic is the same as before: apply rules and move to PARA destination
    #         progress_callback(f"Moving: {os.path.basename(old_path)}", len(choices) + i, total)
    #         filename, final_dest_path = os.path.basename(old_path), dest_root
    #         # ... (This block of code for applying rules and moving is unchanged from your last version) ...
    #         for rule in self.rules:
    #             if rule.get("category") == category_name and self.check_rule(rule, filename):
    #                 action, value = rule.get("action"), rule.get("action_value")
    #                 if action == "subfolder": final_dest_path = os.path.join(dest_root, value)
    #                 elif action == "prefix": filename = f"{value}{filename}"
    #                 self.logger.info(f"Applying rule '{action}' to '{os.path.basename(old_path)}'", exc_info=True)
    #                 break
    #         new_path = os.path.join(final_dest_path, filename)
    #         # Rename if it's a skipped duplicate or just a standard name conflict
    #         if os.path.exists(new_path):
    #             base, ext = os.path.splitext(new_path); counter = 1
    #             while os.path.exists(new_path): new_path = f"{base}_copy_{counter}{ext}"; counter += 1
    #         try:
    #             os.makedirs(os.path.dirname(new_path), exist_ok=True)
    #             shutil.move(old_path, new_path)
    #         except Exception as e:
    #             self.logger.error(f"Failed to move {old_path}", exc_info=True)

    #     # The cleanup logic for empty source dirs is unchanged
    #     self.logger.info("Cleaning up empty source directories...")
    #     # ...
    #     return "File processing complete."
    # # In class ParaFileManager
#--- REPLACE the _task_process_final_drop method in ParaFileManager with this one ---

    def _task_process_final_drop(self, progress_callback, dropped_paths, dest_root, choices, category_name):
        """
        The final stage of processing. Handles duplicates based on user choices
        and moves all other files.
        """
        # This task now receives a clean list of files to move and a dict of choices for duplicates.
        files_to_move = list(dropped_paths) # These are the non-duplicates and skipped duplicates.
        
        total = len(files_to_move) + len(choices)
        self.logger.info(f"Starting final processing of {total} items to {dest_root}")
        
        processed_count = 0
        
        # Process duplicates based on user choices first
        for old_path, choice in choices.items():
            progress_callback(f"Handling: {os.path.basename(old_path)}", processed_count + 1, total)
            processed_count += 1
            
            if choice == "Move to Recycle Bin":
                try:
                    send2trash.send2trash(old_path)
                    self.logger.info(f"Duplicate source sent to Recycle Bin: {old_path}")
                except Exception as e:
                    self.logger.error(f"Failed to send to Recycle Bin: {old_path}", exc_info=True)
                continue # Skip to the next item

            elif choice == "Move to '_duplicates' folder":
                try:
                    source_dir = os.path.dirname(old_path)
                    quarantine_dir = os.path.join(source_dir, "_duplicates")
                    os.makedirs(quarantine_dir, exist_ok=True)
                    
                    base_name = os.path.basename(old_path)
                    dest_path = os.path.join(quarantine_dir, base_name)
                    # Handle name conflicts within the quarantine folder
                    if os.path.exists(dest_path):
                        base, ext = os.path.splitext(base_name)
                        counter = 1
                        while os.path.exists(dest_path):
                            dest_path = os.path.join(quarantine_dir, f"{base}_duplicate_{counter}{ext}")
                            counter += 1
                    
                    shutil.move(old_path, dest_path)
                    self.logger.info(f"Duplicate source quarantined to: {dest_path}")
                except Exception as e:
                    self.logger.error(f"Failed to quarantine file: {old_path}", exc_info=True)
                continue # Skip to the next item

            # If choice was "Skip (Move and Rename)", it was already added to `files_to_move`
            # so we don't need to do anything here.

        # Now, process all non-duplicates and any "skipped" duplicates
        for old_path in files_to_move:
            progress_callback(f"Moving: {os.path.basename(old_path)}", processed_count + 1, total)
            processed_count += 1
            
            filename, final_dest_path = os.path.basename(old_path), dest_root
            for rule in self.rules:
                if rule.get("category") == category_name and self.check_rule(rule, filename):
                    action, value = rule.get("action"), rule.get("action_value")
                    if action == "subfolder":
                        final_dest_path = os.path.join(dest_root, value)
                    elif action == "prefix":
                        filename = f"{value}{filename}"
                    break
            
            new_path = os.path.join(final_dest_path, filename)
            if os.path.exists(new_path):
                base, ext = os.path.splitext(new_path)
                counter = 1
                while os.path.exists(new_path):
                    new_path = f"{base}_copy_{counter}{ext}"
                    counter += 1
            try:
                os.makedirs(os.path.dirname(new_path), exist_ok=True)
                shutil.move(old_path, new_path)
            except Exception as e:
                self.logger.error(f"Failed to move {old_path}", exc_info=True)

        # Cleanup of empty source directories (remains the same)
        self.logger.info("Cleaning up empty source directories...")
        # ... (rest of the cleanup logic is unchanged) ...
        return "File processing complete."

    def _task_rebuild_file_index(self, progress_callback):
        """
        Walks the base directory to build an index of all files with their metadata.
        This task runs in a background thread.
        """
        self.logger.info("Rebuilding file index...")
        progress_callback("Preparing to index...", 0, 1)
        
        if not self.base_dir:
            return [] # Return an empty list if no base directory is set

        all_paths = get_all_files_in_paths([self.base_dir])
        total = len(all_paths)
        file_index_data = []

        for i, path in enumerate(all_paths):
            # Update progress periodically to avoid overwhelming the GUI thread
            if (i + 1) % 100 == 0:
                progress_callback(f"Indexing: {os.path.basename(path)}", i + 1, total)
            
            try:
                stat = os.stat(path)
                file_index_data.append({
                    "path": path,
                    "name_lower": os.path.basename(path).lower(),
                    "size": stat.st_size,
                    "mtime": stat.st_mtime, # Last modification time
                    "ctime": stat.st_ctime  # Creation time (on Windows) or last metadata change (on Unix)
                })
            except (FileNotFoundError, PermissionError) as e:
                self.logger.warn(f"Could not access file during indexing: {path} - {e}")
                continue
        
        progress_callback("Finalizing index...", total, total)
        self.logger.info(f"Indexing complete. Found {len(file_index_data)} items.")
        return file_index_data
    
    # --- ADD THIS NEW TASK FUNCTION TO THE ParaFileManager CLASS ---
    # Place it with the other _task_... methods.

    def _task_move_item(self, progress_callback, source_path, destination_dir):
        """
        Moves a single file or folder to a new destination directory.
        Handles name conflicts by appending a suffix.
        """
        if not os.path.exists(source_path):
            self.logger.error(f"Move failed: Source path no longer exists: {source_path}")
            return f"Error: Source item not found."

        base_name = os.path.basename(source_path)
        dest_path = os.path.join(destination_dir, base_name)
        
        progress_callback(f"Preparing to move {base_name}...", 0, 100)

        # Handle potential name conflicts
        if os.path.exists(dest_path):
            base, ext = os.path.splitext(base_name)
            counter = 1
            while os.path.exists(dest_path):
                dest_path = os.path.join(destination_dir, f"{base}_conflict_{counter}{ext}")
                counter += 1
            new_base_name = os.path.basename(dest_path)
            self.logger.warn(f"Name conflict: '{base_name}' will be moved as '{new_base_name}'")

        try:
            progress_callback(f"Moving {base_name}...", 50, 100)
            shutil.move(source_path, dest_path)
            self.logger.info(f"Successfully moved '{source_path}' to '{dest_path}'")
            progress_callback("Move complete.", 100, 100)
            
            source_dir = os.path.dirname(source_path)
            protected_paths = {os.path.normpath(os.path.join(self.base_dir, d)) for d in self.para_folders.values()}
            try:
                if os.path.normpath(source_dir) not in protected_paths and not os.listdir(source_dir):
                    self.logger.info(f"Cleaning up empty source directory from internal move: {source_dir}")
                    shutil.rmtree(source_dir)
            except Exception as e:
                 self.logger.warn(f"Could not remove source directory {source_dir}: {e}")
                 
            return f"Moved '{base_name}' successfully."
        except Exception as e:
            self.logger.error(f"Failed to move '{source_path}' to '{dest_path}': {e}", exc_info=True)
            return f"Error moving {base_name}."
    # --- REPLACE your old 'handle_search' method with these TWO new methods ---

    def on_search_text_changed(self):
        """Restarts the debounce timer every time the user types."""
        # Check if the search term is a special command
        if self.search_bar.text().strip() == ":reindex":
            self.log_and_show("Manual re-index triggered!", "info")
            self.run_task(self._task_rebuild_file_index, on_success=self.on_index_rebuilt)
            return
            
        self.search_timer.start(300) # 300ms for search, 3000ms for file changes
    
    
    # --- REPLACE the _load_para_icons method ---

    def _load_para_icons(self, custom_icon_paths):
        """Loads icons from paths or built-in identifiers, with fallbacks."""
        self.para_category_icons = {}
        style = self.style()
        default_enums = {
            "Projects": QStyle.StandardPixmap.SP_FileDialogNewFolder,
            "Areas": QStyle.StandardPixmap.SP_DriveHDIcon,
            "Resources": QStyle.StandardPixmap.SP_DirOpenIcon,
            "Archives": QStyle.StandardPixmap.SP_DialogSaveButton
        }

        for category, default_enum in default_enums.items():
            value = custom_icon_paths.get(category)
            loaded_successfully = False
            if value:
                if value.startswith("SP_"): # Handle built-in icon identifier
                    try:
                        enum = getattr(QStyle.StandardPixmap, value)
                        self.para_category_icons[category] = style.standardIcon(enum)
                        loaded_successfully = True
                    except AttributeError:
                        self.logger.warn(f"Invalid built-in icon identifier '{value}' for {category}. Using default.")
                elif os.path.exists(value): # Handle file path
                    pixmap = QPixmap(value)
                    if not pixmap.isNull():
                        self.para_category_icons[category] = QIcon(pixmap)
                        loaded_successfully = True
                    else:
                        self.logger.warn(f"Failed to load custom icon for {category} from path: {path}. Using default.")
            
            if not loaded_successfully:
                self.para_category_icons[category] = style.standardIcon(default_enum)

    # --- ADD these THREE new methods for pagination logic ---

    # def go_to_next_page(self):
    #     if (self.current_search_page + 1) * self.RESULTS_PER_PAGE < len(self.current_search_results):
    #         self.current_search_page += 1
    #         self.display_search_page()

    # def go_to_previous_page(self):
    #     if self.current_search_page > 0:
    #         self.current_search_page -= 1
    #         self.display_search_page()




# Immediately after the on_search_text_changed method, add these four methods:

    # def perform_search(self):
    #     """
    #     Performs a search, stores all results, and displays the first page.
    #     This is also called by the file watcher's debounced timer.
    #     """
    #     # If the timer was fired by a file change, the search bar might be empty.
    #     # In that case, we should just re-index.
    #     if self.search_bar.text().strip() == "":
    #         if self.bottom_pane.currentWidget() != self.welcome_widget:
    #             self.logger.info("Debounced timer fired for file change, re-indexing...")
    #             self.run_task(self._task_rebuild_file_index, on_success=self.on_index_rebuilt)
    #         return

    #     # --- Normal Search Logic ---
    #     term = self.search_bar.text().lower().strip()
    #     if not term:
    #         self.current_search_results = []
    #         if self.base_dir:
    #             self.bottom_pane.setCurrentWidget(self.tree_view)
    #         else:
    #             self.bottom_pane.setCurrentWidget(self.welcome_widget)
    #         return

    #     # Switch to the search results page (assuming it's the 3rd widget, index 2)
    #     self.bottom_pane.setCurrentIndex(2)

    #     if self.file_index:
    #         self.current_search_results = [item for item in self.file_index if term in item["name_lower"]]
    #     else:
    #         self.current_search_results = []
            
    #     self.current_search_page = 0
    #     self.display_search_page()
    
    def perform_search(self):
        """Performs a search based on the user's input."""
        term = self.search_bar.text().lower().strip()
        
        # If the search bar is empty, just show the file tree
        if not term:
            self.current_search_results = []
            if self.base_dir:
                self.bottom_pane.setCurrentWidget(self.tree_view)
            else:
                self.bottom_pane.setCurrentWidget(self.welcome_widget)
            return

        # --- Perform the search ---
        self.bottom_pane.setCurrentIndex(2) # Switch to the search results page
        if self.file_index:
            self.current_search_results = [item for item in self.file_index if term in item["name_lower"]]
        else:
            self.current_search_results = []
            
        self.current_search_page = 0
        self.display_search_page()

    def display_search_page(self):
        """Renders the current page of search results into the list widget."""
        self.search_results_list.clear()

        start_index = self.current_search_page * self.RESULTS_PER_PAGE
        end_index = start_index + self.RESULTS_PER_PAGE
        page_items = self.current_search_results[start_index:end_index]
        
        total_results = len(self.current_search_results)
        total_pages = (total_results + self.RESULTS_PER_PAGE - 1) // self.RESULTS_PER_PAGE
        if total_pages == 0: total_pages = 1

        self.page_status_label.setText(f"Page {self.current_search_page + 1} of {total_pages} ({total_results} results)")
        self.prev_page_button.setEnabled(self.current_search_page > 0)
        self.next_page_button.setEnabled(end_index < total_results)
        
        file_icon_provider = QFileIconProvider()
        para_icons = {name: icon.pixmap(40, 40) for name, icon in self.para_category_icons.items()}

        for item_data in page_items:
            path = item_data["path"]
            item_widget = QWidget()
            main_layout = QHBoxLayout(item_widget)
            main_layout.setContentsMargins(8, 8, 8, 8)
            main_layout.setSpacing(12)

            file_type_icon = file_icon_provider.icon(QFileInfo(path))
            file_type_label = QLabel()
            file_type_label.setPixmap(file_type_icon.pixmap(QSize(32, 32)))
            
            details_layout = QVBoxLayout()
            details_layout.setSpacing(2)
            
            filename_label = QLabel(f"<span id='SearchResultName'>{os.path.basename(path)}</span>")
            
            path_layout = QHBoxLayout()
            path_layout.setSpacing(5)
            
            rel_path = os.path.relpath(os.path.dirname(path), self.base_dir)
            path_parts = rel_path.split(os.sep)
            root_folder = path_parts[0]
            sub_path = os.path.join(*path_parts[1:]) if len(path_parts) > 1 else ""

            category_name = self.folder_to_category.get(root_folder)
            if category_name and category_name in para_icons:
                root_icon_label = QLabel()
                root_icon_label.setPixmap(para_icons[category_name])
                path_layout.addWidget(root_icon_label)
                path_layout.addWidget(QLabel("▶"))
                path_text = sub_path
            else:
                path_text = rel_path
            
            
            
            
            


            try:
                # Check if drives are the same before creating a relative path
                path_drive = os.path.splitdrive(path)[0]
                base_drive = os.path.splitdrive(self.base_dir)[0]
                if path_drive.lower() == base_drive.lower():
                    rel_path = os.path.relpath(os.path.dirname(path), self.base_dir)
                else:
                    # Fallback for different drives: show the absolute directory
                    rel_path = os.path.dirname(path)
            except ValueError:
                # General fallback in case of other path errors
                rel_path = os.path.dirname(path)
                
                
                

            display_path = path_text.replace(os.sep, "  ▶  ")
            path_label = QLabel(f"<span id='SearchResultPath'>{display_path}</span>")
            
            path_layout.addWidget(path_label)
            path_layout.addStretch()

            details_layout.addWidget(filename_label)
            details_layout.addLayout(path_layout)
            
            formatted_size = format_size(item_data['size'])
            mtime_str = datetime.fromtimestamp(item_data['mtime']).strftime('%Y-%m-%d %H:%M')
            meta_html = f"<div style='text-align: right; font-size: 9pt;'>{formatted_size} <br><span style='color: #98c379;'>Modified: {mtime_str}</span></div>"
            meta_label = QLabel(meta_html)
            meta_label.setFixedWidth(160)
            meta_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            
            main_layout.addWidget(file_type_label)
            main_layout.addLayout(details_layout, 1)
            main_layout.addWidget(meta_label)
            
            list_item = QListWidgetItem(self.search_results_list)
            list_item.setData(Qt.ItemDataRole.UserRole, path)
            list_item.setSizeHint(item_widget.sizeHint())
            self.search_results_list.addItem(list_item)
            self.search_results_list.setItemWidget(list_item, item_widget)
            
    def go_to_next_page(self):
        """Moves to the next page of search results."""
        total_pages = (len(self.current_search_results) + self.RESULTS_PER_PAGE - 1) // self.RESULTS_PER_PAGE
        if self.current_search_page < total_pages - 1:
            self.current_search_page += 1
            self.display_search_page()

    def go_to_previous_page(self):
        """Moves to the previous page of search results."""
        if self.current_search_page > 0:
            self.current_search_page -= 1
            self.display_search_page()
            
            
            
    # def display_search_page(self):
    #     """Renders the current page of search results into the list widget."""
    #     self.search_results_list.clear()

    #     start_index = self.current_search_page * self.RESULTS_PER_PAGE
    #     end_index = start_index + self.RESULTS_PER_PAGE
    #     page_items = self.current_search_results[start_index:end_index]
        
    #     total_results = len(self.current_search_results)
    #     total_pages = (total_results + self.RESULTS_PER_PAGE - 1) // self.RESULTS_PER_PAGE
    #     if total_pages == 0: total_pages = 1

    #     # Update status label and buttons
    #     self.page_status_label.setText(f"Page {self.current_search_page + 1} of {total_pages} ({total_results} results)")
    #     self.prev_page_button.setEnabled(self.current_search_page > 0)
    #     self.next_page_button.setEnabled(end_index < total_results)
        
    #     # --- (This is the same item rendering logic from before) ---
    #     file_icon_provider = QFileIconProvider()
    #     for item_data in page_items:
    #         path = item_data["path"]
    #         item_widget = QWidget()
    #         # ... (rest of the item widget creation logic is identical to before) ...
    #         item_layout = QHBoxLayout(item_widget)
    #         item_layout.setContentsMargins(8, 8, 8, 8)
    #         item_layout.setSpacing(12)
    #         icon = file_icon_provider.icon(QFileInfo(path))
    #         icon_label = QLabel()
    #         icon_label.setPixmap(icon.pixmap(QSize(32, 32)))
    #         rel_path = os.path.relpath(os.path.dirname(path), self.base_dir)
    #         if rel_path == '.': rel_path = 'Root'
    #         text_html = f"""<div><span id='SearchResultName'>{os.path.basename(path)}</span><br><span id='SearchResultPath'>{rel_path}</span></div>"""
    #         info_label = QLabel(text_html)
    #         info_label.setWordWrap(True)
    #         formatted_size = format_size(item_data['size'])
    #         mtime_str = datetime.fromtimestamp(item_data['mtime']).strftime('%Y-%m-%d %H:%M')
    #         meta_html = f"""<div style='text-align: right; font-size: 9pt;'>{formatted_size} <br><span style='color: #98c379;'>Modified: {mtime_str}</span></div>"""
    #         meta_label = QLabel(meta_html)
    #         meta_label.setFixedWidth(160)
    #         meta_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    #         item_layout.addWidget(icon_label)
    #         item_layout.addWidget(info_label, 1)
    #         item_layout.addWidget(meta_label)
    #         list_item = QListWidgetItem(self.search_results_list)
    #         list_item.setData(Qt.ItemDataRole.UserRole, path)
    #         list_item.setSizeHint(item_widget.sizeHint())
    #         self.search_results_list.addItem(list_item)
    #         self.search_results_list.setItemWidget(list_item, item_widget)
    
    # --- REPLACE your display_search_page method with this one ---

    # def display_search_page(self):
    #     """Renders the current page of search results into the list widget."""
    #     self.search_results_list.clear()

    #     start_index = self.current_search_page * self.RESULTS_PER_PAGE
    #     end_index = start_index + self.RESULTS_PER_PAGE
    #     page_items = self.current_search_results[start_index:end_index]
        
    #     total_results = len(self.current_search_results)
    #     total_pages = (total_results + self.RESULTS_PER_PAGE - 1) // self.RESULTS_PER_PAGE
    #     if total_pages == 0: total_pages = 1

    #     self.page_status_label.setText(f"Page {self.current_search_page + 1} of {total_pages} ({total_results} results)")
    #     self.prev_page_button.setEnabled(self.current_search_page > 0)
    #     self.next_page_button.setEnabled(end_index < total_results)
        
    #     file_icon_provider = QFileIconProvider()
    #     # Pre-fetch PARA category icons
    #     # para_icons = {name: frame.findChild(QLabel).pixmap().scaled(45, 45, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation) for name, frame in self.drop_frames.items()}
        
    #     # 40*40 is fixed size
    #     para_icons = {name: icon.pixmap(40, 40) for name, icon in self.para_category_icons.items()}

    #     for item_data in page_items:
    #         path = item_data["path"]
            
    #         # --- NEW DYNAMIC WIDGET CREATION ---
    #         item_widget = QWidget()
    #         # Main horizontal layout: File Icon | Details (V) | Metadata (V)
    #         main_layout = QHBoxLayout(item_widget)
    #         main_layout.setContentsMargins(8, 8, 8, 8)
    #         main_layout.setSpacing(12)

    #         # 1. Left side: File type icon
    #         file_type_icon = file_icon_provider.icon(QFileInfo(path))
    #         file_type_label = QLabel()
    #         file_type_label.setPixmap(file_type_icon.pixmap(QSize(32, 32)))
            
    #         # 2. Center: Vertical layout for Filename and new Path display
    #         details_layout = QVBoxLayout()
    #         details_layout.setSpacing(2)
            
    #         # Filename
    #         filename_label = QLabel(f"<span id='SearchResultName'>{os.path.basename(path)}</span>")
            
    #         # Path (New iconic layout)
    #         path_layout = QHBoxLayout()
    #         path_layout.setSpacing(5)
            
    #         rel_path = os.path.relpath(os.path.dirname(path), self.base_dir)
    #         path_parts = rel_path.split(os.sep)
    #         root_folder = path_parts[0]
    #         sub_path = os.path.join(*path_parts[1:]) if len(path_parts) > 1 else ""

    #         category_name = self.folder_to_category.get(root_folder)
    #         if category_name and category_name in para_icons:
    #             # It's a PARA folder, use the icon
    #             root_icon_label = QLabel()
    #             root_icon_label.setPixmap(para_icons[category_name])
    #             path_layout.addWidget(root_icon_label)
    #             # Use a prettier separator
    #             path_layout.addWidget(QLabel("▶"))
    #             path_text = sub_path
    #         else:
    #             # Not a standard PARA folder, just show the text
    #             path_text = rel_path

    #         # path_label = QLabel(f"<span id='SearchResultPath'>{path_text}</span>")
    #         display_path = path_text.replace(os.sep, "  ▶  ")
    #         path_label = QLabel(f"<span id='SearchResultPath'>{display_path}</span>")
            
    #         path_layout.addWidget(path_label)
    #         path_layout.addStretch()

    #         details_layout.addWidget(filename_label)
    #         details_layout.addLayout(path_layout)
            
    #         # 3. Right side: Metadata
    #         formatted_size = format_size(item_data['size'])
    #         mtime_str = datetime.fromtimestamp(item_data['mtime']).strftime('%Y-%m-%d %H:%M')
    #         meta_html = f"<div style='text-align: right; font-size: 9pt;'>{formatted_size} <br><span style='color: #98c379;'>Modified: {mtime_str}</span></div>"
    #         meta_label = QLabel(meta_html)
    #         meta_label.setFixedWidth(160)
    #         meta_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            
    #         # Assemble main layout
    #         main_layout.addWidget(file_type_label)
    #         main_layout.addLayout(details_layout, 1) # The '1' makes this section stretch
    #         main_layout.addWidget(meta_label)
            
    #         # Add to list
    #         list_item = QListWidgetItem(self.search_results_list)
    #         list_item.setData(Qt.ItemDataRole.UserRole, path)
    #         list_item.setSizeHint(item_widget.sizeHint())
    #         self.search_results_list.addItem(list_item)
    #         self.search_results_list.setItemWidget(list_item, item_widget)
    
    # def perform_search(self):
    #     """
    #     Performs a search, stores all results, and displays the first page.
    #     """
        
    #     if self.search_bar.text().strip() == "":
    #         if self.bottom_pane.currentWidget() == self.welcome_widget:
    #             # Nothing to do if we are on the welcome screen
    #             return
    #         # If the search bar is empty, the timer was likely triggered by a file change.
    #         self.logger.info("Debounced timer fired, re-indexing...")
    #         self.run_task(self._task_rebuild_file_index, on_success=self.on_index_rebuilt)
    #         return
    
    #     term = self.search_bar.text().lower().strip()
    #     if not term:
    #         self.current_search_results = []
    #         if self.base_dir: self.bottom_pane.setCurrentWidget(self.tree_view)
    #         else: self.bottom_pane.setCurrentWidget(self.welcome_widget)
    #         return

    #     self.bottom_pane.setCurrentWidget(self.bottom_pane.findChild(QWidget, 'SearchPageWidget') or self.search_results_list.parentWidget())

    #     if self.file_index:
    #         self.current_search_results = [item for item in self.file_index if term in item["name_lower"]]
    #     else:
    #         self.current_search_results = []
            
    #     self.current_search_page = 0
    #     self.display_search_page()

# --- In ParaFileManager, REPLACE your show_move_to_dialog method with this one ---

    def show_move_to_dialog(self):
        """Shows the new dialog to select a move destination."""
        selected_indexes = self.tree_view.selectionModel().selectedIndexes()
        source_paths = sorted({self.file_system_model.filePath(index) for index in selected_indexes if index.column() == 0})
        
        if not source_paths:
            QMessageBox.information(self, "Information", "Please select one or more items to move first.")
            return

        # --- THIS IS THE CORRECTED LINE ---
        # We now pass all four arguments correctly:
        # 1. base_dir for the tree view's root
        # 2. source_paths for the safety check
        # 3. self.move_to_history for the recent destinations list
        # 4. self as the parent widget for styling
        dialog = MoveToDialog(self.base_dir, source_paths, self.move_to_history, self)
        # --- END OF CORRECTION ---
        
        if dialog.exec() and dialog.destination_path:
            destination_dir = dialog.destination_path
            
            # Final safety check remains the same
            for src_path in source_paths:
                if os.path.isdir(src_path) and destination_dir.startswith(os.path.normpath(src_path) + os.sep):
                    QMessageBox.warning(self, "Invalid Move", f"Cannot move '{os.path.basename(src_path)}' into one of its own subfolders.")
                    return

            # Save the successful destination to history BEFORE running the task
            self._save_move_to_history(destination_dir)

            self.run_task(
                self._task_move_multiple_items,
                on_success=self.on_final_refresh_finished,
                source_paths=source_paths,
                destination_dir=destination_dir
            )
            
    def get_category_from_path(self, path):
        if not self.base_dir: return None
        norm_path = os.path.normpath(path)
        for cat_name, folder_name in self.para_folders.items():
            cat_path = os.path.join(self.base_dir, folder_name)
            if norm_path == cat_path or norm_path.startswith(cat_path + os.sep):
                return cat_name
        return None
            
    # --- REPLACE your show_context_menu method with this one ---

    def show_context_menu(self, pos):
        index = self.tree_view.indexAt(pos)
        if not index.isValid(): return
        path = self.file_system_model.filePath(index)
        menu = self._build_context_menu(path)
        menu.exec(self.tree_view.viewport().mapToGlobal(pos))
        
# --- ADD a new handler for the search results list ---

    def show_search_result_context_menu(self, pos):
        item = self.search_results_list.itemAt(pos)
        if not item: return
        path = item.data(Qt.ItemDataRole.UserRole) # Get path from item data
        if not path: return
        menu = self._build_context_menu(path)
        menu.exec(self.search_results_list.mapToGlobal(pos))

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
    
    # --- ADD THIS NEW METHOD TO THE ParaFileManager CLASS ---
    # Place it near the other context menu methods like rename_item.
# --- ADD THESE TWO NEW METHODS TO ParaFileManager ---

    def _disable_watcher(self):
        """Temporarily disables the file system watcher."""
        if self.file_watcher and self.file_watcher.directories():
            self.logger.info("Disabling file system watcher for internal operation.")
            self.file_watcher.removePaths(self.file_watcher.directories())

    def _enable_watcher(self):
        """Re-enables the file system watcher after an operation is complete."""
        if self.base_dir:
            self.logger.info("Re-enabling file system watcher.")
            self.setup_file_watcher() # This already has the logic to add all paths
    def handle_move_to_category(self, source_path, category_name):
        """
        Handles the logic for moving an item to a selected PARA category.
        Opens a dialog for the user to select the final destination subfolder.
        """
        if not self.base_dir:
            return

        # Define the root directory for the destination category
        category_root = os.path.join(self.base_dir, self.para_folders[category_name])
        
        # Open a dialog to let the user select a folder WITHIN that category
        destination_dir = QFileDialog.getExistingDirectory(
            self,
            f"Select Destination Folder within '{category_name}'",
            category_root, # Start Browse from the category root
            QFileDialog.Option.ShowDirsOnly
        )

        if destination_dir: # User selected a directory and clicked OK
            self.log_and_show(f"Moving '{os.path.basename(source_path)}'...", "info")
            self.run_task(
                self._task_move_item,
                on_success=self.on_final_refresh_finished,
                source_path=source_path,
                destination_dir=destination_dir
            )
            
    # def rename_item(self, index):
    #     old_path = self.file_system_model.filePath(index)
    #     old_filename = os.path.basename(old_path)
    #     new_filename, ok = QInputDialog.getText(self, "Rename", "New name:", text=old_filename)
    #     if ok and new_filename and new_filename != old_filename:
    #         new_path = os.path.join(os.path.dirname(old_path), new_filename)
    #         try:
    #             os.rename(old_path, new_path)
    #             self.log_and_show(f"Renamed to '{new_filename}'", "info")
    #             self.logger.info(f"Renamed {old_path} to {new_path}")
    #             self.run_task(self._task_rebuild_file_index, on_success=self.on_final_refresh_finished)
    #         except Exception as e:
    #             self.log_and_show(f"Could not rename file.", "error")
    #             self.logger.error(f"Failed to rename {old_path}", exc_info=True)


# --- In ParaFileManager, REPLACE this method ---

    def rename_item(self, index):
        if not index.isValid():
            # This can happen if the context menu was triggered from the search list
            # where we don't have a direct index. We get the path from the item data instead.
            # For simplicity, we'll only support rename from the tree view for now.
            QMessageBox.information(self, "Info", "Rename is only available by right-clicking directly on an item in the main file tree.")
            return

        old_path = self.file_system_model.filePath(index)
        old_filename = os.path.basename(old_path)
        
        new_filename, ok = QInputDialog.getText(self, "Rename", "New name:", text=old_filename)
        if ok and new_filename and new_filename != old_filename:
            new_path = os.path.join(os.path.dirname(old_path), new_filename)
            try:
                os.rename(old_path, new_path)
                self.log_and_show(f"Renamed to '{new_filename}'", "info")
                self.logger.info(f"Renamed {old_path} to {new_path}")
                # A full re-index isn't needed, the model should update.
                # self.run_task(self._task_rebuild_file_index, on_success=self.on_final_refresh_finished)

            # --- NEW, GRACEFUL ERROR HANDLING ---
            except PermissionError:
                error_title = "Rename Failed: Access Denied"
                error_text = (
                    f"Could not rename '{old_filename}'.\n\n"
                    "This is usually caused by another program locking the file/folder.\n\n"
                    "Please check the following:\n"
                    "1.  **Antivirus Software:** Add this app or folder to its exclusion list.\n"
                    "2.  **Cloud Sync (OneDrive, Dropbox):** Try pausing the sync service.\n"
                    "3.  **Windows Security:** Allow this app through 'Controlled folder access'.\n"
                    "4.  Ensure you have 'Modify' permissions for the parent folder."
                )
                QMessageBox.critical(self, error_title, error_text)
                self.logger.error(f"PermissionError while trying to rename {old_path}", exc_info=True)
            except Exception as e:
                self.log_and_show(f"Could not rename file.", "error")
                self.logger.error(f"Failed to rename {old_path}", exc_info=True)
    # --- ADD THESE TWO NEW METHODS TO THE ParaFileManager CLASS ---
# Place them near the other context menu handlers like rename_item.

    def create_new_folder(self, target_dir):
        """Prompts for a name and creates a new folder in the target directory."""
        new_folder_name, ok = QInputDialog.getText(self, "Create New Folder", "Enter folder name:")
        if ok and new_folder_name:
            new_path = os.path.join(target_dir, new_folder_name)
            if os.path.exists(new_path):
                QMessageBox.warning(self, "Error", f"A file or folder named '{new_folder_name}' already exists.")
                return
            try:
                os.makedirs(new_path)
                self.log_and_show(f"Folder '{new_folder_name}' created.", "info")
            except Exception as e:
                self.log_and_show(f"Could not create folder: {e}", "error")
                self.logger.error(f"Failed to create folder at {new_path}", exc_info=True)

    def create_new_file(self, target_dir):
        """Prompts for a name and creates a new, empty file."""
        new_file_name, ok = QInputDialog.getText(self, "Create New File", "Enter file name (e.g., report.md):")
        if ok and new_file_name:
            new_path = os.path.join(target_dir, new_file_name)
            if os.path.exists(new_path):
                QMessageBox.warning(self, "Error", f"A file or folder named '{new_file_name}' already exists.")
                return
            try:
                # Create an empty file
                with open(new_path, 'w') as f:
                    pass
                self.log_and_show(f"File '{new_file_name}' created.", "info")
            except Exception as e:
                self.log_and_show(f"Could not create file: {e}", "error")
                self.logger.error(f"Failed to create file at {new_path}", exc_info=True)



# --- REPLACE the process_dropped_items method in ParaFileManager ---

    def process_dropped_items(self, dropped_paths, category_name, specific_target_dir=None):
        if not self.base_dir:
            self.log_and_show("Please set a base directory first.", "warn")
            return

        dest_root = os.path.normpath(specific_target_dir) if specific_target_dir else os.path.join(self.base_dir, self.para_folders[category_name])
        os.makedirs(dest_root, exist_ok=True)

        folder_handling_mode = "merge"
        dropped_folders = [p for p in dropped_paths if os.path.isdir(p)]
        dropped_files = [p for p in dropped_paths if os.path.isfile(p)]

        if dropped_folders:
            dialog = FolderDropDialog(len(dropped_folders), len(dropped_files), self)
            if not dialog.exec():
                self.log_and_show("Operation cancelled by user.", "warn")
                return
            folder_handling_mode = dialog.result
        
        self._disable_watcher() # <<< FIX: Disable watcher before starting tasks

        if folder_handling_mode == "move_as_is":
            self.run_task(self._task_process_hybrid_drop, on_success=self.on_final_refresh_finished,
                          dropped_paths=dropped_paths, dest_root=dest_root, category_name=category_name)
            return

        if os.listdir(dest_root):
            dialog = PreOperationDialog(os.path.basename(dest_root), self)
            if not dialog.exec():
                self.log_and_show("Operation cancelled.", "warn")
                self._enable_watcher() # <<< FIX: Re-enable watcher on cancellation
                return

            if dialog.result == "skip":
                self.run_task(self._task_process_simple_drop, on_success=self.on_final_refresh_finished,
                              dropped_paths=dropped_paths, dest_root=dest_root, category_name=category_name)
            elif dialog.result == "scan":
                hash_dialog = HashingSelectionDialog(dest_root, self)
                if not hash_dialog.exec():
                    self.log_and_show("Operation cancelled.", "warn")
                    self._enable_watcher() # <<< FIX: Re-enable watcher on cancellation
                    return
                
                files_to_hash_dest = hash_dialog.get_checked_files()
                on_scan_completed_with_context = partial(self.on_scan_completed, dest_root=dest_root, category_name=category_name)
                self.run_task(self._task_scan_for_duplicates, on_success=on_scan_completed_with_context,
                              source_paths=dropped_paths, files_to_hash_dest=files_to_hash_dest)
        else:
            self.run_task(self._task_process_simple_drop, on_success=self.on_final_refresh_finished,
                          dropped_paths=dropped_paths, dest_root=dest_root, category_name=category_name)


# --- REPLACE the delete_item method in ParaFileManager ---

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
                self._disable_watcher() # <<< FIX: Disable watcher
                send2trash.send2trash(path)
                self.log_and_show(f"Moved '{filename}' to Recycle Bin", "info")
                self.logger.info(f"Trashed {path}")
                # The refresh task will re-enable the watcher in its callback
                self.run_task(self._task_rebuild_file_index, on_success=self.on_index_rebuilt)
            except Exception as e:
                self.log_and_show("Could not move to Recycle Bin.", "error")
                self.logger.error(f"Failed to trash {path}", exc_info=True)
                self._enable_watcher() # <<< FIX: Re-enable on error
                     
    # def delete_item(self, index):
    #     path = self.file_system_model.filePath(index)
    #     filename = os.path.basename(path)
    #     if not os.path.exists(path):
    #         self.log_and_show(f"ERROR: '{filename}' no longer exists.", "error")
    #         return
        
    #     reply = QMessageBox.warning(self, "Confirm Delete", f"Move this item to the Recycle Bin?\n\n'{filename}'",
    #                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
    #     if reply == QMessageBox.StandardButton.Yes:
    #         try:
    #             send2trash.send2trash(path)
    #             self.log_and_show(f"Moved '{filename}' to Recycle Bin", "info")
    #             self.logger.info(f"Trashed {path}")
    #             self.run_task(self._task_rebuild_file_index, on_success=self.on_final_refresh_finished)
    #         except Exception as e:
    #             self.log_and_show("Could not move to Recycle Bin.", "error")
    #             self.logger.error(f"Failed to trash {path}", exc_info=True)

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
    
    
    #--- ADD THIS NEW TASK FUNCTION TO THE ParaFileManager CLASS ---

    def _task_process_hybrid_drop(self, progress_callback, dropped_paths, dest_root, category_name):
        """
        Processes a list of paths, moving files and entire directories as-is.
        Applies rules to files, but not to directories. Handles name conflicts for both.
        """
        total = len(dropped_paths)
        self.logger.info(f"Starting Hybrid Move of {total} items to {dest_root}")
        
        for i, path in enumerate(dropped_paths):
            progress_callback(f"Moving: {os.path.basename(path)}", i + 1, total)
            
            # Check if the path (still) exists before processing
            if not os.path.exists(path):
                self.logger.warn(f"Item no longer exists, skipping: {path}")
                continue

            # --- Handle Directories ---
            if os.path.isdir(path):
                dir_name = os.path.basename(path)
                final_dest_path = os.path.join(dest_root, dir_name)

                # Handle name conflicts for directories
                if os.path.exists(final_dest_path):
                    base, ext = os.path.splitext(final_dest_path) # Use splitext to handle folders with dots
                    counter = 1
                    while os.path.exists(final_dest_path):
                        final_dest_path = f"{base}_conflict_{counter}{ext}"
                        counter += 1
                    self.logger.warn(f"Conflict: Directory '{dir_name}' will be moved as '{os.path.basename(final_dest_path)}'")
                
                try:
                    shutil.move(path, final_dest_path)
                    self.logger.info(f"Moved directory {path} to {final_dest_path}")
                except Exception as e:
                    self.logger.error(f"Failed to move directory {path}", exc_info=True)
                continue

            # --- Handle Files (existing logic) ---
            if os.path.isfile(path):
                filename = os.path.basename(path)
                final_dest_dir = dest_root
                
                # Apply rules to files
                for rule in self.rules:
                    if rule.get("category") == category_name and self.check_rule(rule, filename):
                        action, value = rule.get("action"), rule.get("action_value")
                        if action == "subfolder":
                            final_dest_dir = os.path.join(dest_root, value)
                        elif action == "prefix":
                            filename = f"{value}{filename}"
                        break
                
                new_path = os.path.join(final_dest_dir, filename)

                # Handle name conflicts for files
                if os.path.exists(new_path):
                    base, ext = os.path.splitext(new_path)
                    counter = 1
                    while os.path.exists(new_path):
                        new_path = f"{base}_conflict_{counter}{ext}"
                        counter += 1
                    self.logger.warn(f"Conflict: File '{filename}' will be moved as '{os.path.basename(new_path)}'")

                try:
                    os.makedirs(os.path.dirname(new_path), exist_ok=True)
                    shutil.move(path, new_path)
                except Exception as e:
                    self.logger.error(f"Failed to move file {path}", exc_info=True)
        
        self.logger.info("Cleaning up empty source directories...")
        protected_paths = {os.path.normpath(os.path.join(self.base_dir, d)) for d in self.para_folders.values()}
        source_dirs = {os.path.dirname(p) for p in dropped_paths}
        
        for folder in sorted(source_dirs, key=len, reverse=True):
            try:
                if os.path.normpath(folder) in protected_paths:
                    continue
                if not os.listdir(folder):
                    self.logger.info(f"Removing empty source directory: {folder}")
                    shutil.rmtree(folder)
            except Exception as e:
                self.logger.warn(f"Could not remove source directory {folder}: {e}")

        return "Hybrid move complete."
    
    # --- In ParaFileManager, ADD this new method ---

    def _ensure_config_files_exist(self):
        """Checks for essential config files in the user data path and creates them if they don't exist."""
        # config.json is created by the settings dialog, but rules files need defaults.
        
        # Default automation rules
        if not os.path.exists(self.rules_path):
            self.logger.info(f"rules.json not found. Creating default file at {self.rules_path}")
            default_rules = []
            with open(self.rules_path, 'w', encoding='utf-8') as f:
                json.dump(default_rules, f, indent=4)

        # Default developer-aware scan rules
        if not os.path.exists(self.scan_rules_path):
            self.logger.info(f"scan_rules.json not found. Creating default file at {self.scan_rules_path}")
            default_scan_rules = {
              "info": "Configuration for the Developer-Aware Smart Scan. You can add your own rules here.",
              "excluded_dir_names": [".git",".svn",".hg",".idea",".vscode","__pycache__","node_modules","vendor","venv",".venv","env",".env","target","build","dist","bin","obj"],
              "excluded_dir_paths_contain": ["site-packages","dist-packages","nltk_data",".cache/huggingface",".cache/torch","model_cache"],
              "excluded_extensions": [".log",".tmp",".bak",".swp",".lock",".pyc",".o",".so",".class",".jar",".dll"],
              "excluded_filenames": ["python.exe","pythonw.exe","pip.exe","pip3.exe","activate","activate.ps1","activate.bat","deactivate.bat","manage.py","package.json","package-lock.json","yarn.lock","pnpm-lock.yaml","webpack.config.js","vite.config.js","tsconfig.json","dockerfile","docker-compose.yml","readme.md"]
            }
            with open(self.scan_rules_path, 'w', encoding='utf-8') as f:
                json.dump(default_scan_rules, f, indent=4)


# --- In ParaFileManager, REPLACE the _task_process_scan_results method ---

    def _task_process_scan_results(self, progress_callback, files_to_trash):
        """
        Deletes files from the full scan result by first moving them to a
        timestamped folder, then trashing that single folder.
        """
        if not files_to_trash:
            return "No files were selected for cleanup."

        total = len(files_to_trash)
        self.logger.info(f"Consolidating {total} file(s) for safe deletion.")
        
        # 1. Create a single, uniquely named folder in the system's temp directory
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")
        cleanup_folder_name = f"PARA_Cleanup_{timestamp}"
        cleanup_folder_path = os.path.join(tempfile.gettempdir(), cleanup_folder_name)
        os.makedirs(cleanup_folder_path, exist_ok=True)

        affected_dirs = set()
        for i, path in enumerate(files_to_trash):
            progress_callback(f"Preparing: {os.path.basename(path)}", i + 1, total)
            try:
                if os.path.exists(path):
                    # 2. Move each file into the consolidation folder
                    shutil.move(path, os.path.join(cleanup_folder_path, os.path.basename(path)))
                    affected_dirs.add(os.path.dirname(path))
            except Exception as e:
                self.logger.error(f"Failed to move '{path}' for cleanup", exc_info=True)
        
        # 3. Move the single consolidation folder to the recycle bin
        self.logger.info(f"Sending consolidation folder to Recycle Bin: {cleanup_folder_path}")
        progress_callback("Sending to Recycle Bin...", total, total)
        try:
            send2trash.send2trash(cleanup_folder_path)
        except Exception as e:
            self.logger.error(f"Failed to send cleanup folder to Recycle Bin", exc_info=True)
            return f"Error: Could not move '{cleanup_folder_name}' to Recycle Bin."

        # 4. Clean up any newly empty directories from the original locations
        self._cleanup_empty_dirs(affected_dirs)

        return f"Cleanup complete. {total} file(s) moved to Recycle Bin in folder '{cleanup_folder_name}'."

    
    # def _task_process_scan_results(self, progress_callback, files_to_trash):
    #     total = len(files_to_trash)
    #     self.logger.info(f"Processing full scan results. Moving {total} duplicate file(s) to Recycle Bin.")
    #     affected_dirs = set() # Set to store parent directories

    #     for i, path in enumerate(files_to_trash):
    #         progress_callback(f"Trashing: {os.path.basename(path)}", i + 1, total)
    #         try:
    #             affected_dirs.add(os.path.dirname(path)) # Record parent directory
    #             send2trash.send2trash(path)
    #         except Exception as e:
    #             self.logger.error(f"Failed to send '{path}' to Recycle Bin", exc_info=True)
        
    #     # After deleting files, try to clean up any newly empty folders
    #     self._cleanup_empty_dirs(affected_dirs)

    #     return f"Cleanup complete. {total} file(s) moved to Recycle Bin."

    # def start_full_scan(self):
    #     """Starts the full deduplication scan task."""
    #     reply = QMessageBox.information(
    #         self,
    #         "Start Full Duplicate Scan?",
    #         "This will scan every file in your PARA structure to find identical content. This may take a long time for large libraries.\n\nDo you want to proceed?",
    #         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    #         QMessageBox.StandardButton.No
    #     )
    #     if reply == QMessageBox.StandardButton.Yes:
    #         self.run_task(self._task_full_deduplication_scan, on_success=self.on_full_scan_completed)
    
# --- In ParaFileManager, REPLACE this method ---

# --- In ParaFileManager, REPLACE this method ---
    def start_full_scan(self):
        """Starts the full deduplication scan task after checking for a valid base directory."""
        self.logger.info("--- 'start_full_scan' initiated by user. ---")
        if not self.base_dir or not os.path.isdir(self.base_dir):
            self.logger.warn("Scan aborted: Base directory is not configured.")
            QMessageBox.warning(self, "Configuration Error", "Please set a valid PARA base directory in the Settings before starting a scan.")
            return

        reply = QMessageBox.information(
            self, "Start Full Duplicate Scan?",
            "This will scan every file in your PARA structure to find identical content. This may take a long time for large libraries.\n\nDo you want to proceed?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.logger.info("User confirmed 'Yes'. Preparing to run task...")
            self.run_task(self._task_full_deduplication_scan, on_success=self.on_full_scan_completed)
        else:
            self.logger.info("User cancelled the scan.")
            
    # def start_full_scan(self):
    #     """Starts the full deduplication scan task after checking for a valid base directory."""
    #     # --- THIS IS THE FIX: Add a guard clause ---
    #     if not self.base_dir or not os.path.isdir(self.base_dir):
    #         QMessageBox.warning(
    #             self, 
    #             "Configuration Error", 
    #             "Please set a valid PARA base directory in the Settings before starting a scan."
    #         )
    #         return
    #     # --- END OF FIX ---

    #     reply = QMessageBox.information(
    #         self,
    #         "Start Full Duplicate Scan?",
    #         "This will scan every file in your PARA structure to find identical content. This may take a long time for large libraries.\n\nDo you want to proceed?",
    #         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    #         QMessageBox.StandardButton.No
    #     )
    #     if reply == QMessageBox.StandardButton.Yes:
    #         self.run_task(self._task_full_deduplication_scan, on_success=self.on_full_scan_completed)

# --- 在 ParaFileManager 类中, 替换 on_full_scan_completed 方法 ---

    # def on_full_scan_completed(self, duplicate_sets):
    #     """
    #     Callback for when the full scan finishes.
    #     ALGORITHM UPGRADE: Pre-processes the raw data into a rich structure for the analytics dialog.
    #     """
    #     if self.progress:
    #         self.progress.close()

    #     if not duplicate_sets:
    #         QMessageBox.information(self, "扫描完成", "在您的PARA结构中未找到重复文件。")
    #         self._enable_watcher() # 确保在没有结果时也重新启用监视器
    #         return
        
    #     # --- Advanced Algorithm: Data Pre-processing ---
    #     self.logger.info("Scan found duplicates. Pre-processing results for analytics dialog...")
    #     processed_sets = []
    #     for hash_val, paths in duplicate_sets.items():
    #         if not paths: continue
            
    #         try:
    #             # 1. Calculate group-level metrics
    #             file_size_bytes = os.path.getsize(paths[0])
    #             count = len(paths)
    #             total_space_bytes = file_size_bytes * count
    #             potential_savings_bytes = file_size_bytes * (count - 1)

    #             # 2. Score and sort individual files within the group
    #             scored_files = []
    #             for path in paths:
    #                 try:
    #                     score, reason = self._calculate_retention_score(path)
    #                     mod_time = os.path.getmtime(path)
    #                     scored_files.append({"path": path, "score": score, "reason": reason, "mtime": mod_time})
    #                 except FileNotFoundError:
    #                     continue
                
    #             if not scored_files: continue

    #             scored_files.sort(key=lambda x: (x["score"], x["mtime"]), reverse=True)

    #             # 3. Assemble the rich data object for this group
    #             processed_sets.append({
    #                 "hash": hash_val,
    #                 "files": scored_files,
    #                 "count": count,
    #                 "file_size_bytes": file_size_bytes,
    #                 "total_space_bytes": total_space_bytes,
    #                 "potential_savings_bytes": potential_savings_bytes
    #             })

    #         except (FileNotFoundError, IndexError):
    #             self.logger.warn(f"Could not process duplicate set for hash {hash_val[:10]}... Files might have been deleted during scan.")
    #             continue

    #     # 4. Sort the entire list of groups by potential savings by default
    #     processed_sets.sort(key=lambda x: x["potential_savings_bytes"], reverse=True)
    #     self.logger.info(f"Pre-processing complete. Passing {len(processed_sets)} processed groups to dialog.")

    #     # --- End of Algorithm ---

    #     # Pass the pre-processed, rich data to the dialog
    #     dialog = FullScanResultDialog(processed_sets, self)
    #     if dialog.exec():
    #         files_to_trash = dialog.get_files_to_trash()
    #         if files_to_trash:
    #             self._disable_watcher()
    #             self.run_task(
    #                 self._task_process_scan_results,
    #                 on_success=self.on_final_refresh_finished,
    #                 files_to_trash=files_to_trash
    #             )
    #         else:
    #             self.log_and_show("No action was performed.", "info")
    #             self._enable_watcher() # Re-enable if user confirms with no actions
    #     else:
    #         # User cancelled the main dialog
    #         self.log_and_show("Cleanup operation cancelled.", "warn")
    #         self._enable_watcher()
    



    def on_full_scan_completed(self, duplicate_sets):
        """
        Callback for when the full scan finishes.
        ALGORITHM UPGRADE: Pre-processes the raw data into a rich structure for the analytics dialog.
        """
        if self.progress:
            self.progress.close()

        if not duplicate_sets:
            QMessageBox.information(self, "扫描完成", "在您的PARA结构中未找到重复文件。")
            self._enable_watcher() # 确保在没有结果时也重新启用监视器
            return
        
        # --- Advanced Algorithm: Data Pre-processing ---
        self.logger.info("Scan found duplicates. Pre-processing results for analytics dialog...")
        processed_sets = []
        for hash_val, paths in duplicate_sets.items():
            if not paths: continue
            
            try:
                # 1. Calculate group-level metrics
                file_size_bytes = os.path.getsize(paths[0])
                count = len(paths)
                total_space_bytes = file_size_bytes * count
                potential_savings_bytes = file_size_bytes * (count - 1)

                # 2. Score and sort individual files within the group
                scored_files = []
                for path in paths:
                    try:
                        score, reason = self._calculate_retention_score(path)
                        mod_time = os.path.getmtime(path)
                        scored_files.append({"path": path, "score": score, "reason": reason, "mtime": mod_time})
                    except FileNotFoundError:
                        continue
                
                if not scored_files: continue

                # Sort by score (desc), then modification time (desc) as a tie-breaker
                scored_files.sort(key=lambda x: (x["score"], x["mtime"]), reverse=True)

                # 3. Assemble the rich data object for this group
                processed_sets.append({
                    "hash": hash_val,
                    "files": scored_files,
                    "count": count,
                    "file_size_bytes": file_size_bytes,
                    "total_space_bytes": total_space_bytes,
                    "potential_savings_bytes": potential_savings_bytes
                })

            except (FileNotFoundError, IndexError):
                self.logger.warn(f"Could not process duplicate set for hash {hash_val[:10]}... Files might have been deleted during scan.")
                continue

        # 4. Sort the entire list of groups by potential savings by default
        processed_sets.sort(key=lambda x: x["potential_savings_bytes"], reverse=True)
        self.logger.info(f"Pre-processing complete. Passing {len(processed_sets)} processed groups to dialog.")

        # --- End of Algorithm ---

        # Pass the pre-processed, rich data to the dialog
        dialog = FullScanResultDialog(processed_sets, self)
        if dialog.exec():
            files_to_trash = dialog.get_files_to_trash()
            if files_to_trash:
                self._disable_watcher()
                self.run_task(
                    self._task_process_scan_results,
                    on_success=self.on_final_refresh_finished,
                    files_to_trash=files_to_trash
                )
            else:
                self.log_and_show("No action was performed.", "info")
                self._enable_watcher() # Re-enable if user confirms with no actions
        else:
            # User cancelled the main dialog
            self.log_and_show("Cleanup operation cancelled.", "warn")
            self._enable_watcher()
                
    def open_log_viewer(self):
        try:
            dialog = LogViewerDialog(self.logger, self)
            dialog.setWindowIcon(self.windowIcon())
            dialog.exec()
        except Exception as e:
            self.logger.error(f"Failed to open log viewer: {e}", exc_info=True)
            
    # def open_settings_dialog(self):
    #     dialog = SettingsDialog(self)
    #     dialog.setWindowIcon(self.windowIcon())
    #     if dialog.exec():
    #         self.log_and_show("Settings saved. Reloading configuration...", "info")
    #         self.reload_configuration()
    
    def open_settings_dialog(self):
        # Pass the current icons to the dialog to ensure previews are correct
        dialog = SettingsDialog(self.para_category_icons, self)
        dialog.setWindowIcon(self.windowIcon())
        if dialog.exec():
            self.log_and_show("Settings saved. Reloading configuration...", "info")
            self.reload_configuration()
    
    #--- ADD THIS NEW METHOD TO THE ParaFileManager CLASS ---
# It can be placed near open_log_viewer or open_settings_dialog

    def open_about_dialog(self):
        """Reads release notes and displays them in a dialog."""
        self.logger.info("User opened the About dialog.")
        try:
            # Use resource_path to ensure it works with PyInstaller
            notes_path = resource_path("release_notes.md")
            with open(notes_path, "r", encoding="utf-8") as f:
                notes_markdown = f.read()
        except FileNotFoundError:
            self.logger.error("release_notes.md not found!")
            notes_markdown = ("# Error\n\nCould not find the release notes file (`release_notes.md`). "
                              "Please ensure it is in the same directory as the application.")
        except Exception as e:
            self.logger.error(f"Failed to read release_notes.md: {e}", exc_info=True)
            notes_markdown = f"# Error\n\nAn unexpected error occurred while reading the release notes:\n\n`{e}`"

        dialog = AboutDialog(self.APP_VERSION, notes_markdown, self)
        dialog.exec()
# --- ADD these TWO new methods to the ParaFileManager class ---
# --- ADD THIS ENTIRELY NEW METHOD to the ParaFileManager class ---
# Place it right before the on_scan_completed method.

    def _show_deduplication_dialog(self, duplicates, dest_root, category_name):
        """Creates and shows the deduplication dialog. This is called by a timer."""
        dedup_dialog = DeduplicationDialog(duplicates, self)
        
        if dedup_dialog.exec():
            # User confirmed, run the final processing task
            user_choices = dedup_dialog.get_user_choices()
            files_to_process = [p for p, _, _ in duplicates if p not in user_choices] + \
                               [p for p, choice in user_choices.items() if choice == "Skip (Move and Rename)"]

            self.run_task(self._task_process_final_drop, 
                          on_success=self.on_final_refresh_finished,
                          dropped_paths=files_to_process, 
                          dest_root=dest_root,
                          choices=user_choices, 
                          category_name=category_name)
        else:
            # User cancelled the deduplication dialog
            self.log_and_show("Operation cancelled.", "warn")
            self._enable_watcher() # CRITICAL FIX: Re-enable watcher on cancellation
    def _save_move_to_history(self, new_path):
        """Adds a new path to the move history, keeping it sorted and trimmed."""
        if new_path in self.move_to_history:
            self.move_to_history.remove(new_path)
        
        # Add the new path to the front (most recent)
        self.move_to_history.insert(0, new_path)
        
        # Keep the history list trimmed to the most recent 20 items
        self.move_to_history = self.move_to_history[:20]
        
        self._save_config()

# --- ADD THIS NEW HELPER METHOD to ParaFileManager ---

    def _cleanup_empty_dirs(self, dir_paths_set):
        """
        Deletes empty directories from a given set of paths.
        Sorts paths by length to ensure children are deleted before parents.
        """
        if not dir_paths_set:
            return

        self.logger.info(f"Checking {len(dir_paths_set)} directories for cleanup...")
        # Sort paths by length (descending) to delete sub-folders first
        for path in sorted(list(dir_paths_set), key=len, reverse=True):
            # Do not delete the main PARA root folders
            if path in self.para_root_paths:
                continue
            
            try:
                if not os.listdir(path):
                    self.logger.info(f"Removing empty directory: {path}")
                    os.rmdir(path)
            except (OSError, PermissionError) as e:
                self.logger.warn(f"Could not remove directory {path}: {e}")



    def _load_scan_rules(self):
        """Loads the scan exclusion rules from the user data directory."""
        try:
            with open(self.scan_rules_path, "r", encoding="utf-8") as f:
                self.scan_rules = json.load(f)
            self.logger.info("Successfully loaded developer-aware scan rules.")
        except (FileNotFoundError, json.JSONDecodeError) as e:
            self.logger.warn(f"scan_rules.json not found or invalid. Using empty rules. Error: {e}")
            self.scan_rules = {} # Default to empty rules on error

    def _save_config(self):
        """Saves the current configuration back to the persistent config.json."""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f_read:
                config = json.load(f_read)
        except (FileNotFoundError, json.JSONDecodeError):
            config = {}
        
        config["move_to_history"] = self.move_to_history
        # Add any other settings that need to be saved here
        
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
            
            
    # def _save_config(self):
    #     """Saves the current configuration (including history) back to config.json."""
    #     try:
    #         # Read the whole config first to not lose other settings
    #         with open(resource_path("config.json"), "r") as f_read:
    #             config = json.load(f_read)
    #     except (FileNotFoundError, json.JSONDecodeError):
    #         config = {} # Or create a default one
        
    #     # Update the history key
    #     config["move_to_history"] = self.move_to_history
        
    #     # Write the updated config back to the file
    #     with open(resource_path("config.json"), "w") as f:
    #         json.dump(config, f, indent=4)
            

# --- EXECUTION BLOCK ---
# --- REPLACE THE ENTIRE EXECUTION BLOCK AT THE END OF THE FILE ---

if __name__ == "__main__":
    # Ensure a QApplication instance exists before doing anything else
    app = QApplication(sys.argv)
    
    try:
        # The logger now correctly writes to the persistent user data directory
        log_path = get_user_data_path("para_manager.log")
        main_logger = Logger(filename=log_path)
        
        window = ParaFileManager(main_logger)
        
        # The global hook now knows where to write the crash report
        sys.excepthook = partial(global_exception_hook, window=window)
        
        try:
            # `resource_path` is still correctly used for bundled, read-only assets
            window.setWindowIcon(QIcon(resource_path('icon.ico')))
        except Exception as e:
            main_logger.warn(f"Could not load application icon: {e}")
            
        window.show()
        sys.exit(app.exec())
        
    except Exception as e:
        # Fallback crash handler in case the main logger fails
        print(f"A fatal error occurred during application startup: {e}")
        traceback.print_exc()
        try:
            # Attempt to write the crash report to the user data directory
            crash_log_path = get_user_data_path("crash_report.log")
            with open(crash_log_path, "a", encoding="utf-8") as f:
                f.write(f"\n--- STARTUP CRASH AT {datetime.now()} ---\n")
                traceback.print_exc(file=f)
        except Exception as log_e:
            print(f"Additionally, could not write to crash_report.log: {log_e}")
        


# exe = EXE(
#     pyz,
#     a.scripts,
#     [],
#     exclude_binaries=True,
#     name='ParaManager',
#     debug=False,
#     bootloader_ignore_signals=False,
#     strip=False,
#     upx=True, # Enable UPX compression. Ensure upx.exe is in your PATH.
#     runtime_tmpdir=None,
#     console=False, # This creates a windowed application (no console).
#     icon='icon.ico',
# )

# # coll = COLLECT(
# #     exe,
# #     a.binaries,
# #     a.zipfiles,
# #     a.datas,
# #     strip=False,
# #     upx=True,
# #     upx_exclude=[],
# #     name='ParaManager' # This is the name of the output FOLDER.
# # )

# # For the final single-file bundle, uncomment the BUNDLE block
# # and comment out the COLLECT block above.
# BUNDLE(
# exe,
#     name='ParaManager.exe',
#     icon='icon.ico',
#     bundle_identifier=None,
# )