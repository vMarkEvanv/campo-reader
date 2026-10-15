# Windows bundle. Runtime data and server configuration are deliberately excluded.
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_all,collect_data_files
root=Path(SPECPATH)
pw_data,pw_binaries,pw_hidden=collect_all('playwright')
data=[(str(root/'public'),'public'),(str(root/'browsers'),'browsers'),(str(root/'THIRD_PARTY_NOTICES.md'),'.')]+pw_data+collect_data_files('tzdata')
a=Analysis([str(root/'desktop.py')],pathex=[str(root)],binaries=pw_binaries,datas=data,hiddenimports=pw_hidden,excludes=['PyQt5','PyQt6','PySide2','tkinter','unittest'],noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='CampoReader',debug=False,bootloader_ignore_signals=False,strip=False,upx=False,console=False,icon=str(root/'packaging/campo.ico'))
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='CampoReader')
