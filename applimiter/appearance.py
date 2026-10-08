from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap


def app_icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#2463eb"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(2, 2, 60, 60, 16, 16)
    from PySide6.QtGui import QPen
    painter.setPen(QPen(QColor("white"), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawEllipse(15, 15, 34, 34)
    painter.drawLine(32, 22, 32, 33)
    painter.drawLine(32, 33, 41, 37)
    painter.end()
    return QIcon(pixmap)


STYLE = """
QWidget { font-family: 'Microsoft YaHei UI', 'Segoe UI'; font-size: 13px; color: #172238; }
QMainWindow, QDialog { background: #f5f7fb; }
QLabel#title { font-size: 25px; font-weight: 600; }
QLabel#muted { color: #64748b; }
QPushButton { background: white; border: 1px solid #d6dfec; border-radius: 6px; padding: 7px 13px; }
QPushButton:hover { background: #edf3ff; }
QPushButton#primary { color: white; background: #2463eb; border-color: #2463eb; }
QPushButton:disabled { color: #94a3b8; }
QTableWidget, QListWidget { background: white; border: 1px solid #dce3ed; gridline-color: #eff2f7; }
QHeaderView::section { background: #edf2fa; border: 0; padding: 9px; }
QTableWidget::item:selected, QListWidget::item:selected { background: #dce8ff; color: #172238; }
QProgressBar { border: 0; border-radius: 4px; background: #e7edf7; text-align: center; min-height: 20px; }
QProgressBar::chunk { background: #79a4ff; border-radius: 4px; }
QLineEdit, QSpinBox, QDateEdit { background: white; border: 1px solid #d6dfec; border-radius: 4px; padding: 6px; }
QTabWidget::pane { border: 0; }
QTabBar::tab { padding: 10px 18px; }
QTabBar::tab:selected { color: #2463eb; }
"""


def duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
