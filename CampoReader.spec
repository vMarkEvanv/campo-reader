# Windows bundle. Runtime data and server configuration are deliberately excluded.
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_all,collect_data_files
root=Path(SPECPATH)
wv_data,wv_binaries,wv_hidden=collect_all('webview',filter_submodules=lambda name:not any(v in name for v in ('platforms.qt','platforms.gtk','platforms.cocoa','platforms.cef','platforms.android','platforms.mshtml')))

pw_data,pw_binaries,pw_hidden=collect_all('playwright')
data=[(str(root/'packaging/campo.ico'),'packaging'),(str(root/'packaging/MicrosoftEdgeWebview2Setup.exe'),'packaging'),(str(root/'update-public-key.txt'),'.'),(str(root/'public'),'public'),(str(root/'browsers'),'browsers'),(str(root/'THIRD_PARTY_NOTICES.md'),'.')]+pw_data+wv_data+collect_data_files('tzdata')
a=Analysis([str(root/'desktop.py')],pathex=[str(root)],binaries=pw_binaries+wv_binaries,datas=data,hiddenimports=pw_hidden+wv_hidden,excludes=['PyQt5','PyQt6','PySide2','PySide6','shiboken6','qtpy','tkinter','unittest'],noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='CampoReader',debug=False,bootloader_ignore_signals=False,strip=False,upx=False,console=False,icon=str(root/'packaging/campo.ico'))
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='CampoReader')
