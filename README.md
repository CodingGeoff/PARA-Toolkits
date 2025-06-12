# 🚀 PARA File Manager EVO

Welcome to **PARA File Manager EVO**, a file organizer built to master the PARA method. This tool moves beyond simple file management by offering an intelligent, transparent, and highly automated workflow to bring true order to your life.

![PARA File Manager Ultimate Screenshot](./assets/Screenshot.png)

## ✨ Ultimate Features

This application is engineered for power users who demand clarity, control, and automation. It transforms the PARA method from a concept into a seamless, interactive experience.

* **🗂️ Hybrid Drag & Drop Interface**
  * **Quick-File Zones:** Four large, always-visible drop zones at the top for instantly filing items into your **P**rojects, **A**reas, **R**esources, or **A**rchives.
  * **Precision Drops:** Drag files directly onto any folder within the detailed file browser for granular control.

* **🤖 Intelligent Automation Engine**
  * Create custom rules in a simple settings panel to automatically process your files upon dropping them.
  * **Auto-Prefixing:** Add prefixes to filenames based on keywords (e.g., add `[REPORT]` to any file containing "summary").
  * **Auto-Subfolding:** Move files into specific subfolders based on their file type (e.g., all `.pdf` files go into a "PDFs" folder).

* **👁️ Transparent Deduplication Workflow**
  * **No More Black Boxes:** When moving files into a non-empty folder, the app clearly explains that duplicates might occur.
  * **User-Driven Choices:** You are given the choice between a **Smart Scan** (to check file content for duplicates) or a **Fast Move** (to simply move and rename any conflicts).
  * **Integrated Selection:** Instead of a separate pop-up, "Smart Scan" mode overlays **interactive checkboxes** directly onto the main file tree, so you can select which destination files to check against without losing context.

* **⚡ Fine-Grained Progress & Logging**
  * A single, continuous progress bar shows the total workload and updates with the **name of the specific file** currently being processed (hashed, checked, or moved).
  * A comprehensive log records every key action, from starting a hash to finding a duplicate and processing the user's final choice. The **Log Viewer** allows you to review these detailed logs at any time.

* **🌳 Full File & System Control**
  * **Full Context Menu:** Right-click any file or folder to Open, Show in Explorer, Rename, or Delete.
  * **Safe Deletion:** All deleted items are sent to the system's **Recycle Bin (or Trash)**, ensuring you can always recover from a mistake.
  * **Interactive Duplicate Resolution:** In the final confirmation dialog, you can right-click on both the source and conflicting destination files to **open their locations directly** for easy inspection before making a decision.

* **⚙️ Effortless Configuration**
  * A clean, visual settings panel allows you to set your main PARA directory and manage all automation rules with interactive dropdowns and text fields.
  * **Smart Migration:** If you ever change your PARA base directory, the app offers to **automatically move all existing folders and their contents** to the new location.

### 🗂️ Core Organization

* **PARA Drop Zones:** Quickly sort files into Projects, Areas, Resources, and Archives with dedicated drag-and-drop targets.
* **Custom Folder Mode:** Go beyond PARA and analyze any folder on your system with the same powerful tools. (*GPU acceleration required for this mode*).
* **Full File System View:** A complete tree view for Browse, creating, renaming, and deleting files and folders.
* **Rich Context Menus:** Right-click on any file or folder to open it, show it in the native file explorer, copy its path, and more.

### 🧠 Intelligent Duplicate Finder

* **Developer-Aware Engine:** The scanner is smart enough to automatically ignore common development folders (`.git`, `node_modules`, `venv`), configuration files (`package.json`, `Dockerfile`), and library data (`nltk_data`, `.cache/huggingface`).
* **User-Configurable Rules:** Fine-tune the scanner's behavior by editing a simple `scan_rules.json` file.
* **Retention Scoring:** An advanced algorithm scores each file in a duplicate set to determine which one is most likely the "original" you want to keep.
* **One-Click Cleanup:** The results dialog pre-selects the best file to keep and marks all others for deletion, allowing for safe and confident one-click cleanup.
* **Safe Deletion:** All deleted items are grouped into a single, timestamped folder which is then moved to the Recycling Bin, preventing accidental data loss and making restoration easy.

### ⚡ Performance & Efficiency

* **Intelligent Hash Caching:** The application remembers the hashes of unchanged files. Subsequent scans are dramatically faster, often reducing scan times from minutes to seconds.
* **Auto-Pruning Cache:** The hash cache automatically cleans itself, removing entries for files that no longer exist.
* **Optional GPU Acceleration:** For users with compatible NVIDIA GPUs (and the `numba` library), hashing of very large files can be hardware-accelerated.
* **Multi-threaded Operations:** All long-running tasks (scanning, moving, indexing) are performed on a background thread to keep the UI responsive.

### ⚙️ Customization & Usability

* **Automated Sorting Rules:** Create custom rules in `rules.json` to automatically move files to subfolders or add prefixes based on file type or keywords.
* **Custom Icons:** Personalize the PARA category icons in the Settings dialog.
* **Advanced Search:** Search results are scored and sorted by relevance. Matched keywords are highlighted for clarity.
* **Persistent Data:** All settings, rules, and cache files are stored safely in your user's application data directory, ensuring they persist even with single-file executable builds.

## Installation

### For Users (Recommended)

1. Go to the [Releases](https://github.com/CodingGeoff/Para-Toolkits/releases) page.
2. Download the `ParaManager.exe` file from the latest release.
3. Run the executable. No installation is required.

On first run, the application will create a folder in your user's data directory to store settings and logs.

### For Developers (Running from Source)

1. Clone the repository:

    ```bash
    git clone [https://github.com/CodingGeoff/Para-Toolkits.git](https://github.com/CodingGeoff/Para-tookits.git)
    cd your-repo
    ```

2. Create and activate a Python virtual environment:

    ```bash
    python -m venv venv
    # On Windows
    .\venv\Scripts\activate
    # On macOS/Linux
    source venv/bin/activate
    ```

3. Install the required dependencies:

    ```bash
    pip install -r requirements.txt
    ```

4. Run the application:

    ```bash
    python para_manager.py
    ```

## Configuration

The application uses several JSON files for configuration, which are created on the first run in your user's data directory. You can edit these to customize behavior:

* `config.json`: Main settings, including operating mode and custom paths.
* `rules.json`: Automation rules for sorting dropped files.
* `scan_rules.json`: Exclusion rules for the Developer-Aware scanner.

## 🚀 Getting Started

1. **Run the Application:**
    * Execute `ParaManager.exe` (or your platform's equivalent).
    * On first launch, you'll see a welcome screen. Click "Open Settings."

2. **Set Your Base Directory:**
    * In the settings window, click "Browse..." and choose an empty folder where you want your PARA structure to live (e.g., `C:/Users/YourUser/Documents/`).
    * Click "Save & Close." The application will automatically create the `1_Projects`, `2_Areas`, `3_Resources`, and `4_Archives` folders for you.

3. **(Optional) Add Automation Rules:**
    * Open settings again to add rules. For example, to move all `.pdf` files dropped into "Resources" to a "PDFs" subfolder:
        * **Category:** Resources
        * **Condition Type:** extension
        * **Condition Value:** .pdf
        * **Action:** subfolder
        * **Action Value:** PDFs

4. **Organize!**
    * You're all set! Start dragging files and folders into the drop zones or directly into the file tree to experience automated, intelligent organization.

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.
