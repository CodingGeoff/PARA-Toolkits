# -*- mode: python ; coding: utf-8 -*-

# a 是 Analysis 对象，它分析 main.py 的所有依赖
a = Analysis(
    ['para_manager.py'],
    pathex=[],
    binaries=[],
    # --- 添加数据文件 ---
    # 告诉 PyInstaller 将这些文件/文件夹包含到最终的包中。
    # (源文件, 在包内的目标文件夹)
    datas=[
        ('icon.ico', '.'),
        ('config.json', '.'),
        ('rules.json', '.')
    ],
    # --- 添加隐藏的导入 ---
    # 如果有 PyInstaller 未能自动发现的库，在这里添加。
    # send2trash 和 tqdm 有时需要显式声明。
    hiddenimports=['send2trash', 'tqdm'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # --- 关键选项 ---
    # 'bundle' 模式表示程序是独立的。
    # 'no-console' 在 Windows 上等同于 --windowed
    excludes=['pandas', 'numpy', 'scipy', 'matplotlib', 'hanlp', 'skll', 'wandb', 'pygame', 'PyQt5', 'PySide6'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

# pyz 是一个包含所有 Python 模块的压缩包
pyz = PYZ(a.pure)

# exe 是主要的可执行文件
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas, # 确保 datas 在这里被引用
    [],
    name='ParaManager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False, # 使用 UPX 压缩 (如果已安装)
    upx_exclude=[],
    runtime_tmpdir=None,
    # 控制台和图标设置
    console=False, # 设置为 False 等同于 --windowed
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico', # 再次确认图标
)

# 如果你想要单文件打包 (one-file)，coll 是不需要的。
# 如果你想要文件夹打包 (one-folder)，使用 coll。
# 文件夹模式更容易调试。建议先用文件夹模式，成功后再换成单文件模式。

coll = BUNDLE(
    exe,
    name='ParaManager.exe',
    icon='icon.ico',
    bundle_identifier=None,
)