from pathlib import Path
from PySide6.QtCore import Qt,QRectF
from PySide6.QtGui import QImage,QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication
app=QApplication([])
root=Path(__file__).resolve().parents[1]
image=QImage(256,256,QImage.Format.Format_ARGB32);image.fill(Qt.GlobalColor.transparent)
painter=QPainter(image);QSvgRenderer(str(root/'public/campo-icon.svg')).render(painter,QRectF(0,0,256,256));painter.end()
assert image.save(str(root/'packaging/campo.ico'),'ICO')
