# -*- mode: python ; coding: utf-8 -*-

# A robust .spec file for ParaManager

a = Analysis(
    ['para_manager.py'],
    pathex=['.'],  # Explicitly add the current directory to the path
    binaries=[],
    # 'datas' is for read-only assets you want inside the package.
    # Config files are correctly OMITTED here and handled by the app's code.
    datas=[
        ('icon.ico', '.'),
        ('release_notes.md', '.')
    ],
    # hiddenimports tells PyInstaller about libraries that might be missed.
    hiddenimports=['send2trash', 'numba'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 'excludes' is a good practice to keep the package size down,
    # but the virtual environment is the primary way we avoid unwanted packages.
    excludes=[], 
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ParaManager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    runtime_tmpdir=None,
    console=False,  # This creates a windowed GUI application (no console pops up).
    icon='icon.ico',
)

# Using COLLECT for a one-folder bundle is great for testing.
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ParaManager_App' # The name of the output folder in the 'dist' directory.
)

# For a final single-file executable, comment out the 'coll = COLLECT(...)' block above
# and uncomment the 'bundle = BUNDLE(...)' block below.
#
# bundle = BUNDLE(
#     exe,
#     name='ParaManager.exe',
#     icon='icon.ico',
#     bundle_identifier=None,
# )