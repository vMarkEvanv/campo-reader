from __future__ import annotations

import hashlib
import os
from datetime import date, datetime, timedelta
from html import escape

from PyQt6.QtCore import Qt, QDate, QRectF, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen, QFont, QGuiApplication
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QTabWidget, QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QScrollArea, QDateEdit, QMessageBox, QInputDialog, QFrame, QToolTip, QDialog,
    QFormLayout, QCheckBox, QDialogButtonBox,
)
from PyQt6.QtWebEngineCore import QWebEngineProfile

from .core import BERLIN, Store, DataError, display_semester, should_auto_sync
from .sync import SyncDialog

STYLE = """
QWidget { font-family: 'Segoe UI', 'Microsoft YaHei UI'; font-size: 13px; color: #22314a; }
QMainWindow, QDialog { background: #f5f7fb; }
QLabel#brand { font-size: 20px; font-weight: 700; color: #102b52; }
QLabel#subtitle, QLabel#muted { color: #617088; }
QFrame#card { background: white; border: 1px solid #e0e6f0; border-radius: 12px; }
QLabel#metric { font-size: 18px; font-weight: 700; color: #153a6c; }
QPushButton { background: white; border: 1px solid #d8e0ec; border-radius: 7px; padding: 8px 14px; }
QPushButton:hover { background: #edf3fd; border-color: #b4c7e4; }
QPushButton:disabled { color: #a4afbf; background: #edf0f5; }
QPushButton#primary { background: #2466d5; border: none; color: white; font-weight: 600; }
QPushButton#primary:hover { background: #1a54b5; }
QLineEdit, QComboBox, QDateEdit { background: white; border: 1px solid #d8e0ec; border-radius: 7px; padding: 8px; min-height: 18px; }
QComboBox::drop-down, QDateEdit::drop-down { border: none; width: 24px; }
QTabWidget::pane { background: white; border: 1px solid #e0e6f0; border-radius: 8px; }
QTabBar::tab { padding: 7px 24px; background: #eaf0f8; border-top-left-radius: 8px; border-top-right-radius: 8px; margin-right: 4px; }
QTabBar::tab:selected { background: white; color: #2466d5; font-weight: 700; }
QTableWidget { background: white; border: none; gridline-color: #edf0f5; selection-background-color: #e0ecff; selection-color: #153a6c; }
QHeaderView::section { background: #f2f5fa; color: #54647b; border: none; border-bottom: 1px solid #e0e6f0; padding: 10px; font-weight: 600; }
QScrollArea { background: white; border: none; }
QProgressBar { border: 1px solid #d8e0ec; border-radius: 5px; height: 8px; text-align: center; }
QProgressBar::chunk { background: #2466d5; border-radius: 4px; }
"""


def table(headers):
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.verticalHeader().setVisible(False)
    widget.setAlternatingRowColors(True)
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    widget.horizontalHeader().setStretchLastSection(True)
    return widget


def metric(title, value):
    frame = QFrame()
    frame.setObjectName("card")
    box = QVBoxLayout(frame)
    box.setContentsMargins(14, 6, 14, 6)
    box.setSpacing(2)
    label = QLabel(title)
    label.setObjectName("muted")
    box.addWidget(label)
    number = QLabel(value)
    number.setObjectName("metric")
    box.addWidget(number)
    return frame, number


class CredentialsDialog(QDialog):
    def __init__(self, label, credentials, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"FAU 登录信息 · {label}")
        self.setMinimumWidth(410)
        box = QVBoxLayout(self)
        box.addWidget(QLabel("填写 FAU 用户名和密码，程序会后台登录并同步。"))
        form = QFormLayout()
        self.username = QLineEdit(credentials.get("username", ""))
        self.username.setPlaceholderText("FAU 用户名，不是姓名")
        self.password = QLineEdit(credentials.get("password", ""))
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("FAU 用户名", self.username)
        form.addRow("密码", self.password)
        box.addLayout(form)
        self.remember = QCheckBox("记住登录信息（使用当前 Windows 用户加密）")
        self.remember.setChecked(os.name == "nt")
        self.remember.setEnabled(os.name == "nt")
        box.addWidget(self.remember)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("保存并同步")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        box.addWidget(buttons)

    def validate(self):
        if not self.username.text().strip() or not self.password.text():
            QMessageBox.warning(self, "登录信息不完整", "请输入 FAU 用户名和密码。")
            return
        self.accept()


class WeekCanvas(QWidget):
    selected = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.setMinimumWidth(750)
        self.setMouseTracking(True)
        self.monday = date.today()
        self.events = []
        self.hits = []
        self.setMinimumHeight(330)

    def set_data(self, monday, events):
        self.monday, self.events = monday, events
        timed = [datetime.fromisoformat(e["start"]).hour for e in events if not e["all_day"]]
        ends = [datetime.fromisoformat(e["end"]).hour + 1 for e in events if not e["all_day"]]
        self.first = min([8] + timed)
        self.last = min(24, max([16] + ends))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#ffffff"))
        self.hits = []
        first, last = getattr(self, "first", 8), getattr(self, "last", 16)
        left, top = 58, 78
        hour_height = max(1, (self.height() - top - 14) / (last - first))
        day_width = (self.width() - left - 12) / 7
        today = datetime.now(BERLIN).date()
        font = QFont(self.font())
        font.setPointSize(10)
        painter.setFont(font)
        for i in range(7):
            day = self.monday + timedelta(days=i)
            x = left + day_width * i
            if day == today:
                painter.fillRect(QRectF(x, 0, day_width, self.height()), QColor("#f2f7ff"))
            painter.setPen(QColor("#22314a"))
            painter.drawText(QRectF(x, 12, day_width, 24), Qt.AlignmentFlag.AlignCenter, ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][i])
            painter.setPen(QColor("#2466d5" if day == today else "#6b7b91"))
            painter.drawText(QRectF(x, 37, day_width, 24), Qt.AlignmentFlag.AlignCenter, day.strftime("%m/%d"))
            painter.setPen(QPen(QColor("#e9eef5")))
            painter.drawLine(int(x), top, int(x), self.height())
        for hour in range(first, last + 1):
            y = int(top + (hour - first) * hour_height)
            painter.setPen(QColor("#718096"))
            painter.drawText(QRectF(2, y - 9, 48, 20), Qt.AlignmentFlag.AlignRight, f"{hour:02}:00")
            painter.setPen(QPen(QColor("#e9eef5")))
            painter.drawLine(left, y, self.width() - 12, y)
        colors = ["#dceaff", "#e3e0fb", "#d9f1e9", "#fff0d7", "#fce3e7"]
        # Group overlapping appointments, then assign non-overlapping tracks in each group.
        for day_index in range(7):
            day = self.monday + timedelta(days=day_index)
            timed, all_days = [], []
            for entry in self.events:
                begin, finish = datetime.fromisoformat(entry["start"]), datetime.fromisoformat(entry["end"])
                midnight = datetime.combine(day, datetime.min.time(), BERLIN)
                next_day = midnight + timedelta(days=1)
                if begin >= next_day or finish <= midnight:
                    continue
                if entry["all_day"]:
                    all_days.append(entry)
                else:
                    s, e = max(begin, midnight), min(finish, next_day)
                    timed.append((s.hour + s.minute / 60, 24 if e == next_day else e.hour + e.minute / 60, entry))
            timed.sort(key=lambda item: item[0])
            groups, current, end = [], [], -1
            for item in timed:
                if current and item[0] >= end:
                    groups.append(current)
                    current = []
                current.append(item)
                end = max(end if len(current) > 1 else -1, item[1])
            if current:
                groups.append(current)
            for group in groups:
                tracks, placed = [], []
                for s, e, entry in group:
                    track = next((i for i, finish in enumerate(tracks) if finish <= s), len(tracks))
                    if track == len(tracks): tracks.append(e)
                    else: tracks[track] = e
                    placed.append((s, e, entry, track))
                for s, e, entry, track in placed:
                    width = (day_width - 8) / len(tracks)
                    rect = QRectF(left + day_index * day_width + 4 + track * width,
                                  top + (s - first) * hour_height + 2, width - 3, max(21, (e - s) * hour_height - 4))
                    color = colors[int(hashlib.sha256(entry["title"].encode()).hexdigest()[:4], 16) % len(colors)]
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(color))
                    painter.drawRoundedRect(rect, 6, 6)
                    painter.save()
                    painter.setClipRect(rect.adjusted(4, 3, -4, -3))
                    painter.setPen(QColor("#193452"))
                    begin = datetime.fromisoformat(entry["start"])
                    finish = datetime.fromisoformat(entry["end"])
                    painter.drawText(QRectF(rect.x()+7,rect.y()+3,rect.width()-14,17), Qt.AlignmentFlag.AlignLeft, f"{begin:%H:%M}–{finish:%H:%M}")
                    room = painter.fontMetrics().elidedText(entry['room'], Qt.TextElideMode.ElideRight, max(1,int(rect.width()-14)))
                    if rect.height()>=55:
                        painter.drawText(rect.adjusted(7,20,-7,-18),Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignTop,entry['title'])
                        painter.drawText(QRectF(rect.x()+7,rect.bottom()-17,rect.width()-14,17),Qt.AlignmentFlag.AlignLeft,room)
                    else:
                        title=painter.fontMetrics().elidedText(entry['title'],Qt.TextElideMode.ElideRight,max(1,int(rect.width()-14)))
                        painter.drawText(QRectF(rect.x()+7,rect.y()+20,rect.width()-14,17),Qt.AlignmentFlag.AlignLeft,title)
                    painter.restore()
                    self.hits.append((rect, entry))
            if all_days:
                rect = QRectF(left + day_index * day_width + 4, 60, day_width - 8, 17)
                painter.setBrush(QColor("#e7effc"))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRoundedRect(rect, 4, 4)
                painter.setPen(QColor("#264d87"))
                painter.drawText(rect.adjusted(3, 0, -3, 0), Qt.AlignmentFlag.AlignCenter, f"全天 · {len(all_days)} 项")
                self.hits.append((rect, {"title": "全天课程", "description": "\n\n".join(e["title"] + "\n" + e["room"] for e in all_days)}))
        if self.monday <= today <= self.monday + timedelta(days=6):
            now = datetime.now(BERLIN)
            h = now.hour + now.minute / 60
            if first <= h <= last:
                x = left + (today - self.monday).days * day_width
                y = top + (h - first) * hour_height
                painter.setPen(QPen(QColor("#df5968"), 2))
                painter.drawLine(int(x), int(y), int(x + day_width), int(y))

    def mouseMoveEvent(self, event):
        for rect, entry in self.hits:
            if rect.contains(event.position()):
                QToolTip.showText(event.globalPosition().toPoint(), escape(entry["title"]) + "<br>" + escape(entry.get("room", "")), self)
                return
        QToolTip.hideText()

    def mousePressEvent(self, event):
        for rect, entry in self.hits:
            if rect.contains(event.position()):
                self.selected.emit(entry)
                return


class MainWindow(QMainWindow):
    def __init__(self, store: Store):
        super().__init__()
        self.store = store
        self.profiles = {}
        self.session_credentials = {}
        self.remember_credentials = {}
        self.jobs = []
        self.dialog = None
        self.payload = {}
        self.active_account = None
        self.closing = False
        self.setWindowTitle("Campo Reader · 课表与成绩")
        self.setMinimumSize(900, 560)
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.resize(min(1240, screen.width() - 40), min(800, screen.height() - 60))
        self.setStyleSheet(STYLE)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(8)
        heading = QHBoxLayout()
        title_box = QVBoxLayout()
        brand = QLabel("Campo Reader")
        brand.setObjectName("brand")
        title_box.addWidget(brand)
        subtitle = QLabel("课表与成绩，一处查看")
        subtitle.setObjectName("subtitle")
        title_box.addWidget(subtitle)
        heading.addLayout(title_box)
        heading.addStretch()
        self.accounts = QComboBox()
        self.accounts.setMinimumWidth(160)
        self.accounts.currentIndexChanged.connect(self.account_changed)
        heading.addWidget(self.accounts)
        add = QPushButton("＋ 添加账号")
        add.clicked.connect(self.add_account)
        heading.addWidget(add)
        self.login_info = QPushButton("登录信息")
        self.login_info.clicked.connect(self.edit_login)
        heading.addWidget(self.login_info)
        self.remove = QPushButton("移除")
        self.remove.clicked.connect(self.remove_account)
        heading.addWidget(self.remove)
        self.sync_button = QPushButton("同步")
        self.sync_button.setObjectName("primary")
        self.sync_button.clicked.connect(self.open_sync)
        heading.addWidget(self.sync_button)
        layout.addLayout(heading)
        metrics = QHBoxLayout()
        for title, attr in [("本周课程", "week_count"), ("已记录考试", "exam_count"), ("当前 Campo 身份", "identity")]:
            frame, number = metric(title, "—")
            setattr(self, attr, number)
            metrics.addWidget(frame, 1)
        layout.addLayout(metrics)
        self.info = QLabel()
        self.info.setWordWrap(False)
        self.info.setMaximumHeight(22)
        self.info.setObjectName("muted")
        layout.addWidget(self.info)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.build_timetable(), "课表")
        self.tabs.addTab(self.build_grades(), "成绩")
        layout.addWidget(self.tabs, 1)
        self.statusBar().showMessage("本地查看 · 同步时间会显示在上方")
        self.reload_accounts()

    def build_timetable(self):
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(10, 10, 10, 10)
        toolbar = QHBoxLayout()
        previous = QPushButton("‹ 上一周")
        previous.clicked.connect(lambda: self.week_date.setDate(self.week_date.date().addDays(-7)))
        toolbar.addWidget(previous)
        self.week_date = QDateEdit(QDate.currentDate())
        self.week_date.setDisplayFormat("yyyy-MM-dd")
        self.week_date.setCalendarPopup(True)
        self.week_date.dateChanged.connect(self.refresh_timetable)
        toolbar.addWidget(self.week_date)
        next_week = QPushButton("下一周 ›")
        next_week.clicked.connect(lambda: self.week_date.setDate(self.week_date.date().addDays(7)))
        toolbar.addWidget(next_week)
        today = QPushButton("今天")
        today.clicked.connect(lambda: self.week_date.setDate(QDate.currentDate()))
        toolbar.addWidget(today)
        toolbar.addStretch()
        self.course_search = QLineEdit()
        self.course_search.setPlaceholderText("搜索课程 / 教室")
        self.course_search.textChanged.connect(self.refresh_timetable)
        toolbar.addWidget(self.course_search)
        box.addLayout(toolbar)
        self.week_label = QLabel()
        self.week_label.setObjectName("muted")
        box.addWidget(self.week_label)
        views = QTabWidget()
        self.canvas = WeekCanvas()
        self.canvas.selected.connect(self.event_detail)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.canvas)
        self.week_scroll = scroll
        views.addTab(scroll, "周视图")
        self.agenda = table(["日期", "时间", "课程", "教室"])
        self.agenda.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.agenda.cellDoubleClicked.connect(self.agenda_detail)
        views.addTab(self.agenda, "列表")
        box.addWidget(views, 1)
        return page

    def build_grades(self):
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(16, 16, 16, 16)
        toolbar = QHBoxLayout()
        self.grade_filter = QComboBox()
        for text, key in [("具体考试", "exam"), ("模块成绩", "module"), ("全部层级", "all")]:
            self.grade_filter.addItem(text, key)
        self.grade_filter.currentIndexChanged.connect(self.refresh_grades)
        toolbar.addWidget(self.grade_filter)
        self.program_filter = QComboBox()
        self.program_filter.currentIndexChanged.connect(self.refresh_grades)
        toolbar.addWidget(self.program_filter)
        toolbar.addStretch()
        self.grade_search = QLineEdit()
        self.grade_search.setPlaceholderText("搜索课程 / 编号 / 状态")
        self.grade_search.textChanged.connect(self.refresh_grades)
        toolbar.addWidget(self.grade_search)
        box.addLayout(toolbar)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        box.addWidget(self.summary)
        self.grade_table = table(["课程 / 模块", "编号", "成绩", "状态", "ECTS", "次数", "公布时间", "备注"])
        self.grade_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        box.addWidget(self.grade_table, 1)
        help_text = QLabel("BE / EB：通过　PV：进行中　NB：未通过　EN：最终未通过\n汇总使用 Campo 的原始记录；考试与模块学分不重复相加。")
        help_text.setObjectName("muted")
        box.addWidget(help_text)
        return page

    def reload_accounts(self, selected=None):
        self.accounts.blockSignals(True)
        self.accounts.clear()
        for key, label in self.store.list_accounts():
            self.accounts.addItem(label, key)
        if selected:
            idx = self.accounts.findData(selected)
            if idx >= 0: self.accounts.setCurrentIndex(idx)
        self.accounts.blockSignals(False)
        self.account_changed()

    def add_account(self):
        label, ok = QInputDialog.getText(self, "添加账号", "为这个账号取个名称（例如 FAU 用户名）：")
        if ok and label.strip():
            try:
                self.reload_accounts(self.store.add(label))
                self.open_sync()
            except DataError as exc:
                QMessageBox.warning(self, "无法添加", str(exc))

    def remove_account(self):
        key = self.accounts.currentData()
        if key and QMessageBox.question(self, "移除本地账号", "移除此账号和本机缓存？之后可重新添加并同步。") == QMessageBox.StandardButton.Yes:
            self.store.delete(key)
            self.session_credentials.pop(key, None)
            self.remember_credentials.pop(key, None)
            profile = self.profiles.pop(key, None)
            if profile: profile.deleteLater()
            self.reload_accounts()

    def account_changed(self, *_):
        key = self.accounts.currentData()
        changed = key != self.active_account
        self.active_account = key
        self.sync_button.setEnabled(bool(key))
        self.remove.setEnabled(bool(key))
        self.login_info.setEnabled(bool(key))
        self.payload = {}
        if key:
            try:
                self.payload = self.store.read(key)
            except DataError as exc:
                QMessageBox.warning(self, "缓存读取失败", str(exc))
        self.identity.setText(self.payload.get("identity", "尚未登录"))
        self.exam_count.setText(str(sum(r["kind"] == "exam" for r in self.payload.get("grades", []))) if self.payload else "—")
        timestamp = self.payload.get("synced_at")
        if timestamp:
            timestamp = datetime.fromisoformat(timestamp).astimezone(BERLIN).strftime("%Y-%m-%d %H:%M")
            semester = display_semester(self.payload.get('semester', ''))
            self.info.setText(f"上次同步：{timestamp}（德国时间） · 本地缓存" + (f" · {semester}" if semester else ""))
        else:
            self.info.setText("配置登录信息后，点击同步获取课表与成绩。" if key else "先添加一个账号。不同账号的登录会话与缓存独立保存。")
        self.program_filter.blockSignals(True)
        self.program_filter.clear()
        self.program_filter.addItem("全部专业", "")
        for program in dict.fromkeys(r.get("program", "") for r in self.payload.get("grades", [])):
            if program: self.program_filter.addItem(program, program)
        self.program_filter.blockSignals(False)
        self.refresh_timetable()
        self.refresh_grades()
        if changed and key and not self.dialog:
            QTimer.singleShot(400, lambda account=key: self.auto_sync(account))

    def auto_sync(self, account):
        if self.closing or account != self.accounts.currentData() or self.dialog or self.jobs:
            return
        try:
            if not should_auto_sync(self.payload):
                self.statusBar().showMessage("刚同步过此账号，直接显示缓存；点击“同步”可立即更新。",7000)
                return
            if self.store.credentials(account):
                self.open_sync()
        except DataError as exc:
            self.statusBar().showMessage(str(exc))

    def edit_login(self):
        key = self.accounts.currentData()
        if key:
            self.open_sync(edit=True)

    def open_sync(self, checked=False, edit=False):
        if self.closing:
            return
        key = self.accounts.currentData()
        if not key:
            return
        if self.dialog:
            self.dialog.raise_()
            return
        if self.jobs:
            QMessageBox.information(self, "稍等片刻", "上一条日历请求正在结束，请稍后重试。")
            return
        try:
            credentials = self.session_credentials.get(key) or self.store.credentials(key)
        except DataError as exc:
            QMessageBox.warning(self, "登录信息读取失败", str(exc))
            return
        if not credentials or edit:
            prompt = CredentialsDialog(self.accounts.currentText(), credentials, self)
            if prompt.exec() != QDialog.DialogCode.Accepted:
                prompt.deleteLater()
                return
            credentials = {"username":prompt.username.text().strip(),"password":prompt.password.text()}
            self.session_credentials[key] = credentials
            self.remember_credentials[key] = prompt.remember.isChecked()
            if not prompt.remember.isChecked():
                self.store.forget_credentials(key)
            prompt.password.clear()
            prompt.deleteLater()
            profile = self.profiles.pop(key, None)
            if profile: profile.deleteLater()
        if key not in self.profiles:
            # No storage name means a genuinely separate in-memory profile.
            self.profiles[key] = QWebEngineProfile(self)
        self.dialog = SyncDialog(key, self.accounts.currentText(), self.payload, self.profiles[key], self.jobs, self, credentials=credentials.copy())
        self.dialog.synced.connect(self.save_snapshot)
        self.dialog.preview.connect(self.show_preview)
        self.dialog.sync_failed.connect(self.account_changed)
        self.accounts.setEnabled(False)
        self.remove.setEnabled(False)
        self.login_info.setEnabled(False)
        self.dialog.finished.connect(self.sync_finished)
        self.dialog.show()

    def sync_finished(self, result):
        if self.dialog:
            self.dialog.deleteLater()
            self.dialog = None
        self.accounts.setEnabled(True)
        self.remove.setEnabled(True)
        self.login_info.setEnabled(True)
        if not self.closing:
            self.account_changed()

    def show_preview(self, account, part, payload):
        if self.closing or account!=self.accounts.currentData():
            return
        previous_fingerprint=self.payload.get("fingerprint")
        if previous_fingerprint and previous_fingerprint!=payload.get("fingerprint"):
            return
        self.payload={**self.payload,**payload}
        self.identity.setText(self.payload.get("identity",""))
        if part=="calendar":
            self.refresh_timetable()
            self.info.setText("课表已更新 · 正在等待成绩 · 完整同步后保存缓存")
        elif part=="grades":
            self.refresh_grades()
            self.exam_count.setText(str(sum(r["kind"]=="exam" for r in self.payload.get("grades",[]))))
            self.info.setText("成绩已更新 · 正在等待课表 · 完整同步后保存缓存")

    def save_snapshot(self, key, payload):
        try:
            self.store.save(key, payload)
            credentials = self.session_credentials.get(key)
            if credentials and self.remember_credentials.get(key):
                self.store.save_credentials(key, credentials["username"], credentials["password"])
            self.account_changed()
            duration = payload.get("sync_seconds")
            self.statusBar().showMessage("课表与成绩已同步到本地"+(f" · 用时 {duration:.1f} 秒" if isinstance(duration,(int,float)) else ""), 10000)
        except DataError as exc:
            QMessageBox.warning(self, "未保存此次同步", str(exc))

    def refresh_timetable(self, *_):
        chosen = self.week_date.date().toPyDate()
        monday = chosen - timedelta(days=chosen.weekday())
        end = monday + timedelta(days=7)
        search = self.course_search.text().strip().casefold()
        events = []
        for entry in self.payload.get("events", []):
            begin, finish = datetime.fromisoformat(entry["start"]), datetime.fromisoformat(entry["end"])
            if begin.date() >= end or finish <= datetime.combine(monday, datetime.min.time(), BERLIN):
                continue
            if search and search not in (entry["title"] + " " + entry["room"]).casefold():
                continue
            events.append(entry)
        self.visible_events = events
        self.canvas.set_data(monday, events)
        self.week_scroll.verticalScrollBar().setValue(0)
        self.week_count.setText(str(len(events)) if self.payload else "—")
        range_start, range_end = self.payload.get("range_start"), self.payload.get("range_end")
        message = f"{monday:%Y/%m/%d} — {end - timedelta(days=1):%m/%d} · {len(events)} 项课程 · 点击课程查看详情"
        if range_start and (monday.isoformat() < range_start or end.isoformat() > range_end):
            message += " · 本周超出缓存范围，请同步"
        elif self.payload and not events:
            message += " · 本周没有匹配课程"
        self.week_label.setText(message)
        self.agenda.setRowCount(len(events))
        for i, entry in enumerate(events):
            begin, finish = datetime.fromisoformat(entry["start"]), datetime.fromisoformat(entry["end"])
            values = [begin.strftime("%m/%d %a"), "全天" if entry["all_day"] else f"{begin:%H:%M}–{finish:%H:%M}", entry["title"], entry["room"]]
            for j, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.agenda.setItem(i, j, item)

    def refresh_grades(self, *_):
        grades = self.payload.get("grades", [])
        kind = self.grade_filter.currentData()
        program = self.program_filter.currentData()
        search = self.grade_search.text().strip().casefold()
        rows = [r for r in grades if (kind == "all" or r["kind"] == kind)
                and (not program or r.get("program") == program)
                and (not search or search in " ".join(r.values()).casefold())]
        summaries = []
        programs = set()
        for r in grades:
            if program and r.get("program") != program: continue
            if r["kind"] == "group" and (r["grade"] or r["credits"]) and r.get("program") not in programs:
                programs.add(r.get("program"))
                summaries.append(f"{r['name']}：成绩 {r['grade'] or '—'} · ECTS {r['credits'] or '—'}")
        self.summary.setText("　|　".join(summaries) or ("尚无 Campo 汇总记录" if self.payload else "同步后显示成绩和学分"))
        if self.payload and not rows:
            self.summary.setText(self.summary.text() + "\n当前筛选没有成绩记录，可切换模块成绩或全部层级。")
        self.grade_table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            values = [row[k] for k in ("name", "number", "grade", "status", "credits", "attempt", "released", "annotation")]
            for j, value in enumerate(values):
                item = QTableWidgetItem(value or "—")
                item.setToolTip(value)
                if j == 3:
                    item.setForeground(QColor("#16866a" if value in ("BE", "EB") else "#be3e51" if value in ("NB", "EN") else "#617088"))
                self.grade_table.setItem(i, j, item)

    def agenda_detail(self, row, column):
        self.event_detail(self.visible_events[row])

    def event_detail(self, entry):
        box = QMessageBox(self)
        box.setWindowTitle("课程详情")
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(entry["title"])
        text = entry.get("room", "")
        if entry.get("start"):
            text = datetime.fromisoformat(entry["start"]).strftime("%Y-%m-%d %H:%M") + "\n" + text
        box.setInformativeText(text + "\n\n" + entry.get("description", ""))
        box.exec()

    def closeEvent(self, event):
        if self.jobs:
            for job in self.jobs: job.requestInterruption()
            self.statusBar().showMessage("正在结束网络请求，请稍后关闭…")
            event.ignore()
            return
        # Destroy pages before their profiles.
        if self.dialog: self.dialog.reject()
        self.closing=True
        event.accept()
