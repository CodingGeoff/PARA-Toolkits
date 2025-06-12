# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['para_manager.py'],
    pathex=[],
    binaries=[],
    # datas should ONLY include read-only assets bundled with the app.
    # User-writable files like configs and logs are now handled automatically.
    datas=[
        ('icon.ico', '.'),
        ('release_notes.md', '.')
    ],
    # send2trash is needed. tqdm is not, as it's for command-line progress bars.
    hiddenimports=['send2trash'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # The excludes list is a good safety net, but a clean venv is the real solution.
    excludes=['pandas', 'numpy', 'scipy', 'matplotlib', 'PIL', 'IPython', 'pytest', 'jedi', 'tornado', 'zmq', 'hanlp', 'skll', 'wandb', 'pygame', 'PyQt5', 'PySide6'],
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
    upx=True, # Enable UPX compression. Ensure upx.exe is in your PATH.
    runtime_tmpdir=None,
    console=False, # This creates a windowed application (no console).
    icon='icon.ico',
)

# coll = COLLECT(
#     exe,
#     a.binaries,
#     a.zipfiles,
#     a.datas,
#     strip=False,
#     upx=True,
#     upx_exclude=[],
#     name='ParaManager' # This is the name of the output FOLDER.
# )

# For the final single-file bundle, uncomment the BUNDLE block
# and comment out the COLLECT block above.
BUNDLE(
exe,
    name='ParaManager.exe',
    icon='icon.ico',
    bundle_identifier=None,
)