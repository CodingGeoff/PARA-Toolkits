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
    QCheckBox, QFileIconProvider, QGridLayout
)
from PyQt6.QtGui import (
    QFont, QIcon, QAction, QCursor, QFileSystemModel, QPainter, QPixmap, QColor, QPalette
)
from PyQt6.QtCore import (
    Qt, QUrl, QSize, QModelIndex, QDir, QThread, pyqtSignal, QFileInfo, QTimer
)



# --- ADD THIS NEW FUNCTION NEAR THE TOP OF YOUR SCRIPT ---

#--- REPLACE your existing global_exception_hook function with this one ---

def global_exception_hook(exctype, value, tb, window=None):
    """
    A global hook to catch ALL unhandled exceptions.
    This version creates a wider, styled error dialog.
    """
    # Format the traceback
    traceback_details = "".join(traceback.format_exception(exctype, value, tb))
    error_message_for_details = (
        "An unexpected error has occurred, and the application needs to close.\n\n"
        "Please provide the following details to the developer.\n\n"
        f"Error Type: {exctype.__name__}\n"
        f"Error Message: {value}\n\n"
        f"Traceback:\n{traceback_details}"
    )
    
    # Log the fatal error
    try:
        main_logger.error("A fatal, unhandled exception occurred:\n" + traceback_details)
    except (NameError, AttributeError):
        pass

    try:
        with open("crash_report.log", "a", encoding="utf-8") as f:
            f.write(f"\n--- FATAL CRASH AT {datetime.now()} ---\n{traceback_details}")
    except Exception as e:
        print(f"Could not write to crash_report.log: {e}")

    # Ensure a QApplication instance exists
    app = QApplication.instance() or QApplication(sys.argv)
    
    # Create and style the message box
    error_box = QMessageBox()
    error_box.setIcon(QMessageBox.Icon.Critical)
    error_box.setWindowTitle("Application Error")
    error_box.setText("A critical error occurred and the application must close.")
    error_box.setInformativeText(
        "The error has been logged to 'crash_report.log'.\n"
        "Please click 'Show Details' to copy the error information."
    )
    error_box.setDetailedText(error_message_for_details)
    
    # --- UI ENHANCEMENTS ---
    error_box.setMinimumSize(700, 250) # Set a wider and taller minimum size
    if window:
        error_box.setStyleSheet(window.styleSheet()) # Apply the main window's theme

    # Improve the detailed text area font
    text_edit = error_box.findChild(QTextBrowser)
    if text_edit:
        text_edit.setFont(QFont("Consolas", 10))

    error_box.exec()
    
    sys.exit(1)
    

# --- UTILITY FUNCTIONS ---

def format_size(size_bytes):
    """Converts a size in bytes to a human-readable string (B, KB, MB, GB, TB)."""
    if size_bytes is None or size_bytes < 0:
        return "N/A"
    if size_bytes < 1024:
        return f"{size_bytes} B"
    size_kb = size_bytes / 1024
    if size_kb < 1024:
        return f"{size_kb:.2f} KB"
    size_mb = size_kb / 1024
    if size_mb < 1024:
        return f"{size_mb:.2f} MB"
    size_gb = size_mb / 1024
    if size_gb < 1024:
        return f"{size_gb:.2f} GB"
    size_tb = size_gb / 1024
    return f"{size_tb:.2f} TB"

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


# --- UI DIALOGS ----

# --- REPLACE THE EXISTING FolderDropDialog CLASS WITH THIS ONE ---
# --- ADD THIS ENTIRE NEW CLASS to your script ---
# You can place it with your other dialog classes.

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

    # def populate_icons(self):
    #     style = self.style()
    #     # A curated list of useful and distinct standard icons
    #     icon_enums = [
    #         QStyle.StandardPixmap.SP_DirIcon, QStyle.StandardPixmap.SP_FileIcon,
    #         QStyle.StandardPixmap.SP_FileDialogNewFolder, QStyle.StandardPixmap.SP_DirOpenIcon,
    #         QStyle.StandardPixmap.SP_DriveHDIcon, QStyle.StandardPixmap.SP_DriveNetIcon,
    #         QStyle.StandardPixmap.SP_ComputerIcon, QStyle.StandardPixmap.SP_DesktopIcon,
    #         QStyle.StandardPixmap.SP_DirHomeIcon, QStyle.StandardPixmap.SP_TrashIcon,
    #         QStyle.StandardPixmap.SP_DialogSaveButton, QStyle.StandardPixmap.SP_ToolBarHorizontalExtensionButton,
    #         QStyle.StandardPixmap.SP_MessageBoxInformation, QStyle.StandardPixmap.SP_MessageBoxWarning,
    #         QStyle.StandardPixmap.SP_MessageBoxCritical, QStyle.StandardPixmap.SP_DialogHelpButton,
    #         QStyle.StandardPixmap.SP_ArrowUp, QStyle.StandardPixmap.SP_ArrowDown,
    #         QStyle.StandardPixmap.SP_ArrowLeft, QStyle.StandardPixmap.SP_ArrowRight,
    #         QStyle.StandardPixmap.SP_CommandLink, QStyle.StandardPixmap.SP_MediaPlay,
    #     ]
        
    #     for enum in icon_enums:
    #         icon_name = enum.name # e.g., "SP_DirIcon"
    #         item = QListWidgetItem(style.standardIcon(enum), icon_name)
    #         item.setData(Qt.ItemDataRole.UserRole, icon_name) # Store the name
    #         self.icon_list_widget.addItem(item)
            
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
        self.table.setHorizontalHeaderLabels(["Action (Check to Delete)", "Source File", "Conflicts With Destination File", "File Size"])
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
            try:
                old_stat = os.stat(old_path)
            except FileNotFoundError:
                continue
            
            self.table.setItem(row, 1, QTableWidgetItem(old_path))
            self.table.setItem(row, 2, QTableWidgetItem(conflict_path))
            
            # Use the new format_size function here
            formatted_size = format_size(old_stat.st_size)
            size_item = QTableWidgetItem(formatted_size)
            # Align text to the right for better readability
            size_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 3, size_item)

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
        index = self.tree_view.indexAt(pos)
        if not index.isValid(): return
        
        path = self.file_system_model.filePath(index)
        menu = QMenu()
        style = self.style()

        # Determine the target directory for new items
        if os.path.isdir(path):
            target_dir = path
        else:
            target_dir = os.path.dirname(path)
            
        # --- NEW "CREATE" ACTIONS ---
        new_menu = QMenu("New", menu)
        new_menu.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder))
        
        folder_action = new_menu.addAction("Folder...")
        folder_action.triggered.connect(lambda: self.create_new_folder(target_dir))
        
        file_action = new_menu.addAction("File...")
        file_action.triggered.connect(lambda: self.create_new_file(target_dir))
        
        menu.addMenu(new_menu)
        menu.addSeparator()
        # --- END OF NEW "CREATE" ACTIONS ---

        current_category = self.get_category_from_path(path)
        if current_category:
            move_menu = QMenu("Move To...", menu)
            move_menu.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ArrowRight))
            
            icons = {
                "Projects": self.drop_frames["Projects"].findChild(QLabel).pixmap(),
                "Areas": self.drop_frames["Areas"].findChild(QLabel).pixmap(),
                "Resources": self.drop_frames["Resources"].findChild(QLabel).pixmap(),
                "Archives": self.drop_frames["Archives"].findChild(QLabel).pixmap(),
            }

            for cat_name in self.para_folders.keys():
                action = QAction(QIcon(icons.get(cat_name)), cat_name, self)
                if cat_name == current_category:
                    action.setEnabled(False)
                    action.setToolTip(f"Item is already in {cat_name}")
                else:
                    action.triggered.connect(lambda checked, p=path, cat=cat_name: self.handle_move_to_category(p, cat))
                move_menu.addAction(action)

            menu.addMenu(move_menu)
            menu.addSeparator()

        menu.addAction(style.standardIcon(QStyle.StandardPixmap.SP_DialogOkButton), "Open", lambda: self.open_item(path))
        menu.addAction(style.standardIcon(QStyle.StandardPixmap.SP_DirIcon), "Show in File Explorer", lambda: self.show_in_explorer(path))
        menu.addSeparator()
        menu.addAction(style.standardIcon(QStyle.StandardPixmap.SP_FileLinkIcon), "Rename...", lambda: self.rename_item(index))
        menu.addAction(style.standardIcon(QStyle.StandardPixmap.SP_TrashIcon), "Delete...", lambda: self.delete_item(index))
        
        menu.exec(self.tree_view.viewport().mapToGlobal(pos))

class LogViewerDialog(QDialog):
    # def __init__(self, logger, parent=None):
    #     super().__init__(parent); self.logger = logger; self.setWindowTitle("Log Viewer"); self.setMinimumSize(900, 700); self.setStyleSheet(parent.styleSheet())
    #     layout = QVBoxLayout(self); controls_layout = QHBoxLayout(); self.date_combo = QComboBox(); controls_layout.addWidget(QLabel("Select Date:")); controls_layout.addWidget(self.date_combo); controls_layout.addStretch(); layout.addLayout(controls_layout)
    #     self.log_display = QTextBrowser(); self.log_display.setFont(QFont("Consolas", 10)); layout.addWidget(self.log_display)
    #     self.date_combo.currentIndexChanged.connect(self.load_log_for_date); self.populate_dates()
    
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
        
# class SettingsDialog(QDialog):
#     def __init__(self, parent=None):
#         super().__init__(parent); self.setWindowTitle("Settings & Rules"); self.setMinimumSize(800, 600); self.setStyleSheet(parent.styleSheet())
#         layout = QVBoxLayout(self); config_group = QFrame(self); config_group.setLayout(QVBoxLayout()); config_label = QLabel("PARA Base Directory"); config_label.setFont(QFont("Arial", 12, QFont.Weight.Bold)); self.path_edit = QLineEdit(); browse_button = QPushButton("Browse..."); browse_button.clicked.connect(self.browse_directory); path_layout = QHBoxLayout(); path_layout.addWidget(self.path_edit); path_layout.addWidget(browse_button); config_group.layout().addWidget(config_label); config_group.layout().addLayout(path_layout); layout.addWidget(config_group)
#         rules_group = QFrame(self); rules_group.setLayout(QVBoxLayout()); rules_label = QLabel("Custom Automation Rules"); rules_label.setFont(QFont("Arial", 12, QFont.Weight.Bold)); self.rules_table = QTableWidget(); self.setup_rules_table(); rules_buttons_layout = QHBoxLayout(); add_rule_button = QPushButton("Add Rule"); add_rule_button.clicked.connect(self.add_rule); remove_rule_button = QPushButton("Remove Selected Rule"); remove_rule_button.clicked.connect(self.remove_rule); rules_buttons_layout.addStretch(); rules_buttons_layout.addWidget(add_rule_button); rules_buttons_layout.addWidget(remove_rule_button); rules_group.layout().addWidget(rules_label); rules_group.layout().addWidget(self.rules_table); rules_group.layout().addLayout(rules_buttons_layout); layout.addWidget(rules_group)
#         dialog_buttons_layout = QHBoxLayout(); dialog_buttons_layout.addStretch(); cancel_button = QPushButton("Cancel"); cancel_button.clicked.connect(self.reject); save_button = QPushButton("Save & Close"); save_button.setDefault(True); save_button.clicked.connect(self.save_and_accept); dialog_buttons_layout.addWidget(cancel_button); dialog_buttons_layout.addWidget(save_button); layout.addLayout(dialog_buttons_layout)
#         self.load_settings()
#     def setup_rules_table(self): self.rules_table.setColumnCount(5); self.rules_table.setHorizontalHeaderLabels(["Category", "Condition Type", "Condition Value", "Action", "Action Value"]); self.rules_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
#     def load_settings(self):
#         try:
#             with open(resource_path("config.json"), "r") as f: self.path_edit.setText(json.load(f).get("base_directory", ""))
#         except (FileNotFoundError, json.JSONDecodeError): self.path_edit.setText("")
#         try:
#             with open(resource_path("rules.json"), "r") as f: rules = json.load(f); self.rules_table.setRowCount(len(rules));
#             for i, rule in enumerate(rules): self.add_rule_to_table(i, rule)
#         except (FileNotFoundError, json.JSONDecodeError): self.rules_table.setRowCount(0)
#     def add_rule_to_table(self, row, rule_data=None):
#         categories = ["Projects", "Areas", "Resources", "Archives"]; condition_types = ["extension", "keyword"]; actions = ["subfolder", "prefix"]; cat_combo = QComboBox(); cat_combo.addItems(categories); cond_combo = QComboBox(); cond_combo.addItems(condition_types); act_combo = QComboBox(); act_combo.addItems(actions)
#         if rule_data: cat_combo.setCurrentText(rule_data.get("category")); cond_combo.setCurrentText(rule_data.get("condition_type")); act_combo.setCurrentText(rule_data.get("action"))
#         self.rules_table.setCellWidget(row, 0, cat_combo); self.rules_table.setCellWidget(row, 1, cond_combo); self.rules_table.setCellWidget(row, 3, act_combo); self.rules_table.setItem(row, 2, QTableWidgetItem(rule_data.get("condition_value", "") if rule_data else "")); self.rules_table.setItem(row, 4, QTableWidgetItem(rule_data.get("action_value", "") if rule_data else ""))
#     def add_rule(self): row_count = self.rules_table.rowCount(); self.rules_table.insertRow(row_count); self.add_rule_to_table(row_count, None)
#     def remove_rule(self):
#         if (current_row := self.rules_table.currentRow()) >= 0: self.rules_table.removeRow(current_row)
#     def browse_directory(self):
#         if (directory := QFileDialog.getExistingDirectory(self, "Select PARA Base Directory")): self.path_edit.setText(directory)
#     def save_and_accept(self):
#         try:
#             with open(resource_path("config.json"), "r") as f_read: config = json.load(f_read)
#         except (FileNotFoundError, json.JSONDecodeError): config = {}
#         config["base_directory"] = self.path_edit.text()
#         with open(resource_path("config.json"), "w") as f: json.dump(config, f, indent=4)
#         rules_data = []
#         for i in range(self.rules_table.rowCount()):
#             cond_item = self.rules_table.item(i, 2); act_item = self.rules_table.item(i, 4)
#             rules_data.append({"category": self.rules_table.cellWidget(i, 0).currentText(), "condition_type": self.rules_table.cellWidget(i, 1).currentText(), "condition_value": cond_item.text() if cond_item else "", "action": self.rules_table.cellWidget(i, 3).currentText(), "action_value": act_item.text() if act_item else ""})
#         with open(resource_path("rules.json"), "w") as f: json.dump(rules_data, f, indent=4)
#         self.accept()

#--- REPLACE the entire SettingsDialog class with this one ---

class SettingsDialog(QDialog):
    def __init__(self, current_icons, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings & Rules")
        self.setMinimumSize(800, 700)
        self.setStyleSheet(parent.styleSheet())
        
        self.current_icons = current_icons # Store the app's current icons
        self.custom_icon_paths = {} # Holds paths OR built-in identifiers
        self.icon_previews = {}

        main_layout = QVBoxLayout(self)
        
        # --- Base Directory Group (Unchanged) ---
        config_group = QFrame(self); config_group.setLayout(QVBoxLayout()); config_label = QLabel("PARA Base Directory"); config_label.setFont(QFont("Arial", 12, QFont.Weight.Bold)); self.path_edit = QLineEdit(); browse_button = QPushButton("Browse..."); browse_button.clicked.connect(self.browse_directory); path_layout = QHBoxLayout(); path_layout.addWidget(self.path_edit); path_layout.addWidget(browse_button); config_group.layout().addWidget(config_label); config_group.layout().addLayout(path_layout); main_layout.addWidget(config_group)

        # --- Custom Icons Group (Modified) ---
        icons_group = QFrame(self); icons_group.setLayout(QVBoxLayout()); icons_label = QLabel("Custom Category Icons"); icons_label.setFont(QFont("Arial", 12, QFont.Weight.Bold)); icons_group.layout().addWidget(icons_label)
        icons_grid = QGridLayout(); icons_grid.setColumnStretch(1, 1)
        
        para_categories = ["Projects", "Areas", "Resources", "Archives"]
        for i, category in enumerate(para_categories):
            self.icon_previews[category] = QLabel(); self.icon_previews[category].setFixedSize(32, 32); self.icon_previews[category].setAlignment(Qt.AlignmentFlag.AlignCenter)
            
            # Button to choose from a local file
            change_local_button = QPushButton("From File...")
            change_local_button.clicked.connect(partial(self.browse_for_icon, category))
            
            # NEW: Button to choose from built-in gallery
            change_builtin_button = QPushButton("Choose Built-in...")
            change_builtin_button.clicked.connect(partial(self.choose_builtin_icon, category))

            icons_grid.addWidget(QLabel(f"{category} Icon:"), i, 0)
            icons_grid.addWidget(self.icon_previews[category], i, 1, alignment=Qt.AlignmentFlag.AlignLeft)
            icons_grid.addWidget(change_builtin_button, i, 2)
            icons_grid.addWidget(change_local_button, i, 3)
            
        icons_group.layout().addLayout(icons_grid)
        main_layout.addWidget(icons_group)

        # --- Automation Rules & Dialog Buttons (Unchanged) ---
        rules_group = QFrame(self); rules_group.setLayout(QVBoxLayout()); rules_label = QLabel("Custom Automation Rules"); rules_label.setFont(QFont("Arial", 12, QFont.Weight.Bold)); self.rules_table = QTableWidget(); self.setup_rules_table(); rules_buttons_layout = QHBoxLayout(); add_rule_button = QPushButton("Add Rule"); add_rule_button.clicked.connect(self.add_rule); remove_rule_button = QPushButton("Remove Selected Rule"); remove_rule_button.clicked.connect(self.remove_rule); rules_buttons_layout.addStretch(); rules_buttons_layout.addWidget(add_rule_button); rules_buttons_layout.addWidget(remove_rule_button); rules_group.layout().addWidget(rules_label); rules_group.layout().addWidget(self.rules_table); rules_group.layout().addLayout(rules_buttons_layout); main_layout.addWidget(rules_group)
        dialog_buttons_layout = QHBoxLayout(); dialog_buttons_layout.addStretch(); cancel_button = QPushButton("Cancel"); cancel_button.clicked.connect(self.reject); save_button = QPushButton("Save & Close"); save_button.setDefault(True); save_button.clicked.connect(self.save_and_accept); dialog_buttons_layout.addWidget(cancel_button); dialog_buttons_layout.addWidget(save_button); main_layout.addLayout(dialog_buttons_layout)
        
        self.load_settings()

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
                # This fixes the bug: Show the app's current default icon
                label.setPixmap(self.current_icons[category].pixmap(32, 32))
    
    def browse_for_icon(self, category):
        file_path, _ = QFileDialog.getOpenFileName(self, f"Select Icon for {category}", "", "Image Files (*.png *.ico *.jpg *.jpeg)")
        if file_path:
            self.custom_icon_paths[category] = file_path
            self._update_icon_previews()

    def load_settings(self):
        try:
            with open(resource_path("config.json"), "r") as f:
                config = json.load(f)
            self.path_edit.setText(config.get("base_directory", ""))
            self.custom_icon_paths = config.get("custom_icons", {})
        except (FileNotFoundError, json.JSONDecodeError):
            self.path_edit.setText("")
            self.custom_icon_paths = {}
        
        self._update_icon_previews() # Update UI after loading
            
        try:
            with open(resource_path("rules.json"), "r") as f: rules = json.load(f); self.rules_table.setRowCount(len(rules));
            for i, rule in enumerate(rules): self.add_rule_to_table(i, rule)
        except (FileNotFoundError, json.JSONDecodeError): self.rules_table.setRowCount(0)
    
    # --- Other methods are unchanged from your last full version ---
    def setup_rules_table(self): self.rules_table.setColumnCount(5); self.rules_table.setHorizontalHeaderLabels(["Category", "Condition Type", "Condition Value", "Action", "Action Value"]); self.rules_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    def save_and_accept(self):
        try:
            with open(resource_path("config.json"), "r") as f_read: config = json.load(f_read)
        except (FileNotFoundError, json.JSONDecodeError): config = {}
        config["base_directory"] = self.path_edit.text(); config["custom_icons"] = self.custom_icon_paths
        with open(resource_path("config.json"), "w") as f: json.dump(config, f, indent=4)
        rules_data = []
        for i in range(self.rules_table.rowCount()):
            cond_item = self.rules_table.item(i, 2); act_item = self.rules_table.item(i, 4)
            rules_data.append({"category": self.rules_table.cellWidget(i, 0).currentText(), "condition_type": self.rules_table.cellWidget(i, 1).currentText(), "condition_value": cond_item.text() if cond_item else "", "action": self.rules_table.cellWidget(i, 3).currentText(), "action_value": act_item.text() if act_item else ""})
        with open(resource_path("rules.json"), "w") as f: json.dump(rules_data, f, indent=4)
        self.accept()
    def add_rule_to_table(self, row, rule_data=None):
        categories = ["Projects", "Areas", "Resources", "Archives"]; condition_types = ["extension", "keyword"]; actions = ["subfolder", "prefix"]; cat_combo = QComboBox(); cat_combo.addItems(categories); cond_combo = QComboBox(); cond_combo.addItems(condition_types); act_combo = QComboBox(); act_combo.addItems(actions)
        if rule_data: cat_combo.setCurrentText(rule_data.get("category")); cond_combo.setCurrentText(rule_data.get("condition_type")); act_combo.setCurrentText(rule_data.get("action"))
        self.rules_table.setCellWidget(row, 0, cat_combo); self.rules_table.setCellWidget(row, 1, cond_combo); self.rules_table.setCellWidget(row, 3, act_combo); self.rules_table.setItem(row, 2, QTableWidgetItem(rule_data.get("condition_value", "") if rule_data else "")); self.rules_table.setItem(row, 4, QTableWidgetItem(rule_data.get("action_value", "") if rule_data else ""))
    def add_rule(self): row_count = self.rules_table.rowCount(); self.rules_table.insertRow(row_count); self.add_rule_to_table(row_count, None)
    def remove_rule(self):
        if (current_row := self.rules_table.currentRow()) >= 0: self.rules_table.removeRow(current_row)
    def browse_directory(self):
        if (directory := QFileDialog.getExistingDirectory(self, "Select PARA Base Directory")): self.path_edit.setText(directory)
            
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

# --- ADD THIS NEW CLASS DEFINITION ---
# Place it right after the DropTreeView class definition.
#--- REPLACE the entire ThemedTreeView class with this corrected version ---

# class ThemedTreeView(DropTreeView):
#     """A QTreeView that can paint a large, faint icon in its background."""
#     def __init__(self, main_window):
#         super().__init__(main_window)
#         # Renamed for clarity: this now correctly holds a QIcon
#         self.background_icon = None

#     def setBackgroundIcon(self, icon):
#         """Sets the QIcon to be drawn in the background and triggers a repaint."""
#         self.background_icon = icon
#         self.viewport().update() # Crucial: tells the widget to repaint itself

#     def paintEvent(self, event):
#         """
#         Overrides the paint event. First, it draws our custom background,
#         then it calls the original paintEvent to draw the file tree on top.
#         """
#         if self.background_icon:
#             # --- FIX IS HERE ---
#             # 1. Request a large QPixmap from the QIcon container
#             # We ask for a 256x256 image; the QIcon will provide the best fit.
#             pixmap_to_draw = self.background_icon.pixmap(QSize(256, 256))

#             # 2. Check if a valid pixmap was returned before proceeding
#             if not pixmap_to_draw.isNull():
#                 painter = QPainter(self.viewport())
#                 painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                
#                 painter.setOpacity(0.08) 

#                 view_rect = self.viewport().rect()
                
#                 # Scale the pixmap to be large but fit within the view's width
#                 scaled_pixmap = pixmap_to_draw.scaled(
#                     view_rect.width(), view_rect.height(),
#                     Qt.AspectRatioMode.KeepAspectRatio,
#                     Qt.TransformationMode.SmoothTransformation
#                 )
                
#                 # Center the scaled pixmap
#                 x = (view_rect.width() - scaled_pixmap.width()) / 2
#                 y = (view_rect.height() - scaled_pixmap.height()) / 2
                
#                 painter.drawPixmap(int(x), int(y), scaled_pixmap)
#                 painter.end()

#         # VERY IMPORTANT: Call the original paint event to draw the actual tree
#         super().paintEvent(event)


# --- ADD THIS NEW CLASS DEFINITION ---

class ThemedTreeView(DropTreeView):
    """A QTreeView that can paint large, faint text in its background."""
    def __init__(self, main_window):
        super().__init__(main_window)
        self.background_text = ""

    def setBackgroundText(self, text):
        """Sets the text to be drawn in the background and triggers a repaint."""
        if self.background_text != text:
            self.background_text = text
            self.viewport().update() # Repaint only if text changes

    def paintEvent(self, event):
        """
        Overrides the paint event to draw the background text before drawing the tree.
        """
        # First, call the original paint event so the default background is drawn
        super().paintEvent(event)

        if self.background_text:
            painter = QPainter(self.viewport())
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            # Configure a very large, bold font
            font = QFont("Segoe UI", 120, QFont.Weight.ExtraBold)
            painter.setFont(font)

            # Set a very faint color for the text (light grey with low opacity)
            # The low alpha (15) is what makes it "faint"
            painter.setPen(QColor(200, 200, 200, 15))

            # Draw the text centered in the view
            painter.drawText(self.viewport().rect(), Qt.AlignmentFlag.AlignCenter, self.background_text)
            
            painter.end()
        
# --- MAIN APPLICATION WINDOW ---
class ParaFileManager(QMainWindow):
    def __init__(self, logger):
        super().__init__()
        self.logger = logger
        self.setWindowTitle("PARA File Manager EVO")
        self.setGeometry(100, 100, 1400, 900)
        self.APP_VERSION = "1.2.0"
        self.base_dir = None
        self.para_folders = {"Projects": "1_Projects", "Areas": "2_Areas", "Resources": "3_Resources", "Archives": "4_Archives"}
        
        # --- ADD THIS LINE ---
        self.folder_to_category = {v: k for k, v in self.para_folders.items()}
        self.para_category_icons = {} 
        
        self.rules = []
        self.file_index = []
        self.worker = None
        self.progress = None
        
        
        # --- ADD THESE FOR PAGINATION ---
        self.RESULTS_PER_PAGE = 50 # Show 50 results per page
        self.current_search_results = []
        self.current_search_page = 0
        # --- END ADD ---
        
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self.perform_search)
        
        self.setup_styles()
        self.setAcceptDrops(True)
        self.init_ui()
        self.reload_configuration()
        self.logger.info("Application Started.")

    

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

            /* ---- HOVER and SELECTION STYLES (柔和风格) ---- */
            QTreeView::item:hover, QListWidget::item:hover { 
                background-color: #3e4451; 
            }
            QTreeView::item:selected, QListWidget::item:selected {
                /* --- THIS IS THE CHANGE --- */
                /* OLD: background-color: #4b5263; */
                /* NEW: Using rgba to make it 75% opaque */
                background-color: rgba(75, 82, 99, 0.75);
                color: #d8dee9;
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

    # In class ParaFileManager, update this method
    def _create_top_bar(self):
        top_bar_layout = QHBoxLayout()
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Search all files and folders...")
        self.search_bar.setMinimumWidth(450)
        # self.search_bar.textChanged.connect(self.handle_search)
        
        self.search_bar.textChanged.connect(self.on_search_text_changed) # <-- CHANGE THIS
        top_bar_layout.addWidget(self.search_bar)
        
        top_bar_layout.addWidget(self.search_bar)
        
        top_bar_layout.addStretch(1)
        
        style = self.style()
        
        # --- START OF ADDED CODE ---
        about_button = QPushButton()
        about_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation))
        about_button.setToolTip("About this application")
        about_button.clicked.connect(self.open_about_dialog)
        # --- END OF ADDED CODE ---

        settings_button = QPushButton()
        settings_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
        settings_button.setToolTip("Open Settings")
        settings_button.clicked.connect(self.open_settings_dialog)

        log_button = QPushButton()
        log_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView))
        log_button.setToolTip("View Logs")
        log_button.clicked.connect(self.open_log_viewer)

        top_bar_layout.addWidget(about_button) # <-- ADD THIS LINE
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
# --- REPLACE your _create_tree_view method with this one ---
    # def _create_tree_view(self):
    #     # Use our new ThemedTreeView class
    #     tree_view = ThemedTreeView(self)
    #     self.file_system_model = QFileSystemModel()
    #     self.file_system_model.setFilter(QDir.Filter.AllDirs | QDir.Filter.NoDotAndDotDot | QDir.Filter.AllEntries)
    #     tree_view.setModel(self.file_system_model)
    #     tree_view.setSortingEnabled(True)
    #     tree_view.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        
    #     # Connect the clicked signal to update the background
    #     tree_view.clicked.connect(self.on_tree_item_clicked)
        
    #     return tree_view
    
    
    #--- REPLACE your _create_tree_view method with this one ---

    def _create_tree_view(self):
        # Use our new ThemedTreeView class
        tree_view = ThemedTreeView(self)
        self.file_system_model = QFileSystemModel()
        self.file_system_model.setFilter(QDir.Filter.AllDirs | QDir.Filter.NoDotAndDotDot | QDir.Filter.AllEntries)
        tree_view.setModel(self.file_system_model)
        tree_view.setSortingEnabled(True)
        tree_view.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        
        # Connect the clicked signal to update the background text
        tree_view.clicked.connect(self.on_tree_item_clicked)
        
        return tree_view
    
    # # --- ADD THIS NEW HELPER METHOD TO THE ParaFileManager CLASS ---

    # def _build_context_menu(self, path):
    #     """Builds a context menu for a given file/folder path."""
    #     menu = QMenu()
    #     if not path or not os.path.exists(path):
    #         return menu # Return an empty menu if path is invalid

    #     style = self.style()
        
    #     # Determine the target directory for new items
    #     target_dir = path if os.path.isdir(path) else os.path.dirname(path)
            
    #     # "New" Submenu
    #     new_menu = QMenu("New", menu)
    #     new_menu.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder))
    #     folder_action = new_menu.addAction("Folder..."); folder_action.triggered.connect(lambda: self.create_new_folder(target_dir))
    #     file_action = new_menu.addAction("File..."); file_action.triggered.connect(lambda: self.create_new_file(target_dir))
    #     menu.addMenu(new_menu)
    #     menu.addSeparator()

    #     # "Move To..." Submenu
    #     current_category = self.get_category_from_path(path)
    #     if current_category:
    #         move_menu = QMenu("Move To...", menu)
    #         move_menu.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ArrowRight))
    #         icons = {name: frame.findChild(QLabel).pixmap() for name, frame in self.drop_frames.items()}
    #         for cat_name in self.para_folders.keys():
    #             action = QAction(QIcon(icons.get(cat_name)), cat_name, self)
    #             if cat_name == current_category:
    #                 action.setEnabled(False); action.setToolTip(f"Item is already in {cat_name}")
    #             else:
    #                 action.triggered.connect(lambda checked, p=path, cat=cat_name: self.handle_move_to_category(p, cat))
    #             move_menu.addAction(action)
    #         menu.addMenu(move_menu)
    #         menu.addSeparator()

    #     # Standard Actions
    #     menu.addAction(style.standardIcon(QStyle.StandardPixmap.SP_DialogOkButton), "Open", lambda: self.open_item(path))
    #     menu.addAction(style.standardIcon(QStyle.StandardPixmap.SP_DirIcon), "Show in File Explorer", lambda: self.show_in_explorer(path))
    #     menu.addSeparator()
        
    #     # Get QModelIndex for rename/delete if possible (for tree view)
    #     index = self.file_system_model.index(path)
    #     menu.addAction(style.standardIcon(QStyle.StandardPixmap.SP_FileLinkIcon), "Rename...", lambda: self.rename_item(index))
    #     menu.addAction(style.standardIcon(QStyle.StandardPixmap.SP_TrashIcon), "Delete...", lambda: self.delete_item(index))
        
    #     return menu
    
    # --- REPLACE your _build_context_menu method with this one ---

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

        # "Move To..." Submenu
        current_category = self.get_category_from_path(path)
        if current_category:
            move_menu = QMenu("Move To...", menu)
            move_menu.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ArrowRight))
            # icons = {name: frame.findChild(QLabel).pixmap() for name, frame in self.drop_frames.items()}
            
            icons = self.para_category_icons
        
            for cat_name in self.para_folders.keys():
                action = QAction(icons.get(cat_name), cat_name, self) # Use the QIcon directly
            
            
            # for cat_name in self.para_folders.keys():
            #     action = QAction(QIcon(icons.get(cat_name)), cat_name, self)
                if cat_name == current_category:
                    action.setEnabled(False); action.setToolTip(f"Item is already in {cat_name}")
                else:
                    action.triggered.connect(lambda checked, p=path, cat=cat_name: self.handle_move_to_category(p, cat))
                move_menu.addAction(action)
            menu.addMenu(move_menu)
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
    
    # --- ADD this new method to the ParaFileManager class ---
    #--- In the ParaFileManager class, REPLACE the on_tree_item_clicked method ---

    # def on_tree_item_clicked(self, index):
    #     """When an item is clicked, update the tree view's background icon."""
    #     path = self.file_system_model.filePath(index)
    #     category = self.get_category_from_path(path)
        
    #     if category and category in self.para_category_icons:
    #         # A PARA category was clicked, set its icon as the background
    #         # Use the new, clearer method name: setBackgroundIcon
    #         self.tree_view.setBackgroundIcon(self.para_category_icons[category])
    #     else:
    #         # Not in a PARA category, clear the background
    #         self.tree_view.setBackgroundIcon(None)
    
    
    
    #--- ADD this method back to the ParaFileManager class ---

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
            
            
    # def on_tree_item_clicked(self, index):
    #     """When an item is clicked, update the tree view's background icon."""
    #     path = self.file_system_model.filePath(index)
    #     category = self.get_category_from_path(path)
        
    #     if category and category in self.para_category_icons:
    #         # A PARA category was clicked, set its icon as the background
    #         self.tree_view.setBackgroundPixmap(self.para_category_icons[category])
    #     else:
    #         # Not in a PARA category, clear the background
    #         self.tree_view.setBackgroundPixmap(None)
            
    # --- Core Logic with New Transparent Workflow ---
    def reload_configuration(self):
        self.log_and_show("Reloading configuration...", "info", 2000)
        try:
            # with open(resource_path("config.json"), "r") as f:
            #     config = json.load(f)
            #     path = config.get("base_directory")
            # if not path:
            #     raise ValueError("Base directory not set in config.")
            # self.base_dir = os.path.normpath(path)
            # os.makedirs(self.base_dir, exist_ok=True)
            # with open(resource_path("rules.json"), "r") as f:
            #     self.rules = json.load(f)

            with open(resource_path("config.json"), "r") as f:
                config = json.load(f)
            
            path = config.get("base_directory")
            if not path:
                raise ValueError("Base directory not set in config.")
            self.base_dir = os.path.normpath(path)
            os.makedirs(self.base_dir, exist_ok=True)
            
            # Load custom icons paths here
            custom_icons = config.get("custom_icons", {})
            self._load_para_icons(custom_icons)
            
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
        
        for name, frame in self.drop_frames.items():
            icon_label = frame.findChild(QLabel)
            if icon_label:
                # Get the loaded icon (custom or default) and set it
                pixmap = self.para_category_icons[name].pixmap(QSize(64, 64))
                icon_label.setPixmap(pixmap)

        self.bottom_pane.setCurrentWidget(self.tree_view)
        
        # self.bottom_pane.setCurrentWidget(self.tree_view)
        self.file_system_model.setRootPath(self.base_dir)
        self.tree_view.setRootIndex(self.file_system_model.index(self.base_dir))
        for i in range(1, self.file_system_model.columnCount()):
            self.tree_view.hideColumn(i)
        
        self.log_and_show(f"Configuration loaded. Root: {self.base_dir}", "info")
        # self.run_task(self._task_rebuild_file_index, on_success=lambda r: self.log_and_show(r, "info", 2000))
        self.run_task(self._task_rebuild_file_index, on_success=self.on_index_rebuilt)
        
    
    #--- REPLACE THE EXISTING process_dropped_items FUNCTION WITH THIS ONE ---

    def process_dropped_items(self, dropped_paths, category_name):
        if not self.base_dir:
            self.log_and_show("Please set a base directory first.", "warn")
            return

        dest_root = os.path.join(self.base_dir, self.para_folders[category_name])
        os.makedirs(dest_root, exist_ok=True)

        # --- NEW LOGIC: Determine how to handle folders ---
        folder_handling_mode = "merge" # Default behavior
        dropped_folders = [p for p in dropped_paths if os.path.isdir(p)]
        dropped_files = [p for p in dropped_paths if os.path.isfile(p)]

        if dropped_folders:
            dialog = FolderDropDialog(len(dropped_folders), len(dropped_files), self)
            if not dialog.exec():
                self.log_and_show("Operation cancelled.", "warn")
                return
            folder_handling_mode = dialog.result

        # --- PATH 1: User chose "Move Folders As-Is" ---
        if folder_handling_mode == "move_as_is":
            self.log_and_show("Moving files and folders as-is...", "info")
            self.run_task(self._task_process_hybrid_drop, on_success=self.on_final_refresh_finished,
                          dropped_paths=dropped_paths, # Pass the original list
                          dest_root=dest_root,
                          category_name=category_name)
            return

        # --- PATH 2: User chose "Merge" or only dropped files (Original Logic) ---
        # If we reach here, we are flattening all folders and processing only files.
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
            # Destination is empty, fast merge/move
            self.log_and_show("Destination is empty, performing fast merge of contents.", "info")
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
    
    #--- REPLACE your on_index_rebuilt method with this one ---

    def on_index_rebuilt(self, index_data):
        """This slot runs in the main thread to receive index results and update the UI."""
        self.log_and_show(f"Indexing complete. {len(index_data)} items indexed.", "info", 2000)
        self.file_index = index_data
        # Now it's safe to call perform_search to refresh the UI
        self.perform_search()
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
        
        # source_dirs = {p for p in get_all_files_in_paths(dropped_paths) if os.path.isdir(p)} # Needs re-evaluation
        # for folder in source_dirs:
        #     try:
        #         if not os.listdir(folder): shutil.rmtree(folder)
        #     except Exception: pass
        self.logger.info("Cleaning up empty source directories...")
        protected_paths = {os.path.normpath(os.path.join(self.base_dir, d)) for d in self.para_folders.values()}
        
        # We only care about the source directories of files that were actually moved (not deleted)
        moved_paths = [p for p in dropped_paths if choices.get(p) != "delete"]
        source_dirs = {os.path.dirname(p) for p in moved_paths}

        for folder in sorted(source_dirs, key=len, reverse=True):
            try:
                if os.path.normpath(folder) in protected_paths:
                    continue
                if not os.listdir(folder):
                    self.logger.info(f"Removing empty source directory: {folder}")
                    shutil.rmtree(folder)
            except Exception as e:
                self.logger.warn(f"Could not remove source directory {folder}: {e}")
        return "File processing complete."

    # In class ParaFileManager

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
        self.search_timer.start(300)  # Wait 300ms after last keystroke
    
    
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

# --- REPLACE the open_settings_dialog method ---


    # def perform_search(self):
    #     """
    #     The actual search and UI update logic, executed after the debounce delay.
    #     This is the fully optimized version of the old `handle_search`.
    #     """
    #     term = self.search_bar.text().lower().strip()

    #     if not term:
    #         if self.base_dir:
    #             self.bottom_pane.setCurrentWidget(self.tree_view)
    #         else:
    #             self.bottom_pane.setCurrentWidget(self.welcome_widget)
    #         return

    #     self.bottom_pane.setCurrentWidget(self.search_results_list)
    #     self.search_results_list.clear() # Clear previous results immediately

    #     if not self.file_index:
    #         return

    #     # Perform the search in-memory (this is fast)
    #     results = [item for item in self.file_index if term in item["name_lower"]]
        
    #     # If there are many results, inform the user and only show a portion
    #     if len(results) > 100:
    #         status_item = QListWidgetItem(f"Showing first 100 of {len(results)} results...")
    #         status_item.setFlags(Qt.ItemFlag.NoItemFlags) # Make it unselectable
    #         self.search_results_list.addItem(status_item)

    #     file_icon_provider = QFileIconProvider()

    #     # IMPORTANT: Limit the loop to a max of 50 items to keep the UI fluid
    #     for item_data in results[:100]:
    #         path = item_data["path"]
    #         item_widget = QWidget()
    #         item_layout = QHBoxLayout(item_widget)
    #         item_layout.setContentsMargins(8, 8, 8, 8)
    #         item_layout.setSpacing(12)

    #         icon = file_icon_provider.icon(QFileInfo(path))
    #         icon_label = QLabel()
    #         icon_label.setPixmap(icon.pixmap(QSize(32, 32)))
            
    #         rel_path = os.path.relpath(os.path.dirname(path), self.base_dir)
    #         if rel_path == '.': rel_path = 'Root'
            
    #         text_html = f"""
    #         <div>
    #             <span id='SearchResultName'>{os.path.basename(path)}</span><br>
    #             <span id='SearchResultPath'>{rel_path}</span>
    #         </div>
    #         """
    #         info_label = QLabel(text_html)
    #         info_label.setWordWrap(True)

    #         formatted_size = format_size(item_data['size'])
    #         mtime_str = datetime.fromtimestamp(item_data['mtime']).strftime('%Y-%m-%d %H:%M')
            
    #         meta_html = f"""
    #         <div style='text-align: right; font-size: 9pt;'>
    #             {formatted_size} <br>
    #             <span style='color: #98c379;'>Modified: {mtime_str}</span>
    #         </div>
    #         """
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
    
    
    # --- ADD these THREE new methods for pagination logic ---

    def go_to_next_page(self):
        if (self.current_search_page + 1) * self.RESULTS_PER_PAGE < len(self.current_search_results):
            self.current_search_page += 1
            self.display_search_page()

    def go_to_previous_page(self):
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
        # Pre-fetch PARA category icons
        # para_icons = {name: frame.findChild(QLabel).pixmap().scaled(45, 45, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation) for name, frame in self.drop_frames.items()}
        
        # 40*40 is fixed size
        para_icons = {name: icon.pixmap(40, 40) for name, icon in self.para_category_icons.items()}

        for item_data in page_items:
            path = item_data["path"]
            
            # --- NEW DYNAMIC WIDGET CREATION ---
            item_widget = QWidget()
            # Main horizontal layout: File Icon | Details (V) | Metadata (V)
            main_layout = QHBoxLayout(item_widget)
            main_layout.setContentsMargins(8, 8, 8, 8)
            main_layout.setSpacing(12)

            # 1. Left side: File type icon
            file_type_icon = file_icon_provider.icon(QFileInfo(path))
            file_type_label = QLabel()
            file_type_label.setPixmap(file_type_icon.pixmap(QSize(32, 32)))
            
            # 2. Center: Vertical layout for Filename and new Path display
            details_layout = QVBoxLayout()
            details_layout.setSpacing(2)
            
            # Filename
            filename_label = QLabel(f"<span id='SearchResultName'>{os.path.basename(path)}</span>")
            
            # Path (New iconic layout)
            path_layout = QHBoxLayout()
            path_layout.setSpacing(5)
            
            rel_path = os.path.relpath(os.path.dirname(path), self.base_dir)
            path_parts = rel_path.split(os.sep)
            root_folder = path_parts[0]
            sub_path = os.path.join(*path_parts[1:]) if len(path_parts) > 1 else ""

            category_name = self.folder_to_category.get(root_folder)
            if category_name and category_name in para_icons:
                # It's a PARA folder, use the icon
                root_icon_label = QLabel()
                root_icon_label.setPixmap(para_icons[category_name])
                path_layout.addWidget(root_icon_label)
                # Use a prettier separator
                path_layout.addWidget(QLabel("▶"))
                path_text = sub_path
            else:
                # Not a standard PARA folder, just show the text
                path_text = rel_path

            # path_label = QLabel(f"<span id='SearchResultPath'>{path_text}</span>")
            display_path = path_text.replace(os.sep, "  ▶  ")
            path_label = QLabel(f"<span id='SearchResultPath'>{display_path}</span>")
            
            path_layout.addWidget(path_label)
            path_layout.addStretch()

            details_layout.addWidget(filename_label)
            details_layout.addLayout(path_layout)
            
            # 3. Right side: Metadata
            formatted_size = format_size(item_data['size'])
            mtime_str = datetime.fromtimestamp(item_data['mtime']).strftime('%Y-%m-%d %H:%M')
            meta_html = f"<div style='text-align: right; font-size: 9pt;'>{formatted_size} <br><span style='color: #98c379;'>Modified: {mtime_str}</span></div>"
            meta_label = QLabel(meta_html)
            meta_label.setFixedWidth(160)
            meta_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            
            # Assemble main layout
            main_layout.addWidget(file_type_label)
            main_layout.addLayout(details_layout, 1) # The '1' makes this section stretch
            main_layout.addWidget(meta_label)
            
            # Add to list
            list_item = QListWidgetItem(self.search_results_list)
            list_item.setData(Qt.ItemDataRole.UserRole, path)
            list_item.setSizeHint(item_widget.sizeHint())
            self.search_results_list.addItem(list_item)
            self.search_results_list.setItemWidget(list_item, item_widget)
            
# --- And REPLACE perform_search with this new version ---

    def perform_search(self):
        """
        Performs a search, stores all results, and displays the first page.
        """
        term = self.search_bar.text().lower().strip()
        if not term:
            self.current_search_results = []
            if self.base_dir: self.bottom_pane.setCurrentWidget(self.tree_view)
            else: self.bottom_pane.setCurrentWidget(self.welcome_widget)
            return

        self.bottom_pane.setCurrentWidget(self.bottom_pane.findChild(QWidget, 'SearchPageWidget') or self.search_results_list.parentWidget())

        if self.file_index:
            self.current_search_results = [item for item in self.file_index if term in item["name_lower"]]
        else:
            self.current_search_results = []
            
        self.current_search_page = 0
        self.display_search_page()
            
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
    
# --- EXECUTION BLOCK ---
if __name__ == "__main__":
    # Set the global exception hook. This MUST be the first thing to do.
    # sys.excepthook = global_exception_hook
    app = QApplication(sys.argv)
    try:
        main_logger = Logger()
        window = ParaFileManager(main_logger)
        sys.excepthook = partial(global_exception_hook, window=window)
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
        

# # --- 文件夹模式 (推荐用于调试) ---
# coll = COLLECT(
#     exe,
#     a.zipfiles,
#     a.datas,
#     strip=False,
#     upx=True,
#     upx_exclude=[],
#     name='ParaManager',
# )

# --- 单文件模式 (用于最终发布) ---
# 如果要使用单文件模式，请取消下面的注释，并注释掉上面的 coll 块
# coll = BUNDLE(
#     exe,
#     name='ParaFileManagerEVO.exe',
#     icon='icon.ico',
#     bundle_identifier=None,
# )