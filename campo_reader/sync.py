from __future__ import annotations

import time
from datetime import datetime, timedelta

import requests
from PyQt6.QtCore import QThread, QTimer, QUrl, pyqtSignal
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QProgressBar
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PyQt6.QtWebEngineWidgets import QWebEngineView

from . import scripts
from .core import BERLIN, HOME, TIMETABLE, TRANSCRIPT, DataError, calendar_fingerprint, parse_calendar, validate_grades


class CalendarJob(QThread):
    result = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, url, parent=None):
        super().__init__(parent)
        self._url = url

    def run(self):
        try:
            calendar_fingerprint(self._url)
            # Never forward this personal token through redirects or log the URL.
            with requests.get(self._url, timeout=(10, 25), allow_redirects=False, stream=True) as response:
                if response.status_code != 200:
                    raise DataError(f"日历请求失败（HTTP {response.status_code}），请重新登录后重试。")
                data = bytearray()
                deadline = time.monotonic() + 45
                for chunk in response.iter_content(65536):
                    if self.isInterruptionRequested():
                        return
                    if time.monotonic() > deadline or len(data) + len(chunk) > 8_000_000:
                        raise DataError("日历响应超时或过大，旧缓存已保留。")
                    data.extend(chunk)
            today = datetime.now(BERLIN).date()
            start, end = today - timedelta(days=180), today + timedelta(days=365)
            events = parse_calendar(bytes(data), start, end)
            if len(events) > 20000:
                raise DataError("日历条目过多，旧缓存已保留。")
            if not self.isInterruptionRequested():
                self.result.emit({"events": events, "range_start": start.isoformat(), "range_end": end.isoformat()})
        except DataError as exc:
            self.error.emit(str(exc))
        except requests.RequestException:
            self.error.emit("连接 Campo 失败，请检查网络后重试。旧缓存已保留。")
        except Exception:
            self.error.emit("同步日历失败，旧缓存已保留。")
        finally:
            self._url = ""


class CampoPage(QWebEnginePage):
    blocked = pyqtSignal(str)

    def acceptNavigationRequest(self, url, kind, is_main_frame):
        if not is_main_frame:
            return True
        host = url.host().lower()
        allowed = (url.scheme() == "https" and (host == "fau.de" or host.endswith(".fau.de")))
        if not allowed and url.toString() != "about:blank":
            self.blocked.emit("此窗口仅支持 FAU 官方登录页面。")
            return False
        return True

    def javaScriptConsoleMessage(self, level, message, line, source):
        pass  # Do not put account data or tokens in console logs.


class SyncDialog(QDialog):
    synced = pyqtSignal(str, object)
    preview = pyqtSignal(str,str,object)
    sync_failed = pyqtSignal()

    def __init__(self, account_id, label, previous, profile: QWebEngineProfile, jobs: list, parent=None, credentials=None):
        super().__init__(parent)
        self.setWindowTitle(f"Campo 登录与同步 · {label}")
        self.resize(520, 180)
        self.credentials = credentials or {}
        self.profile = profile
        self.started = time.monotonic()
        self.calendar_done = False
        self.grades_done = False
        warm_session = bool(self.credentials and getattr(profile,"_campo_authenticated",False))
        self.home_fallback = not warm_session
        self.ready = False
        self.auth_response = False
        self.account_id, self.previous = account_id, previous
        self.jobs = jobs
        self.alive = True
        self.stage = "login"
        self.busy = False
        self.generation = 0
        self.expansions = 0
        self.stable = ""
        self.stable_count = 0
        self.stable_since = 0.0
        self.draft = {}
        self.job = None
        layout = QVBoxLayout(self)
        self.note = QLabel("在下面的 FAU 官方页面登录。登录完成后，点击“同步课表与成绩”。")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        toolbar = QHBoxLayout()
        self.begin = QPushButton("同步课表与成绩")
        self.begin.clicked.connect(self.start_sync)
        toolbar.addWidget(self.begin)
        retry = QPushButton("返回登录首页")
        retry.clicked.connect(self.reset_login)
        toolbar.addWidget(retry)
        toolbar.addStretch()
        cancel = QPushButton("关闭")
        cancel.clicked.connect(self.reject)
        toolbar.addWidget(cancel)
        layout.addLayout(toolbar)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.view = QWebEngineView(self)
        self.page = CampoPage(profile, self.view)
        self.view.setPage(self.page)
        self.page.blocked.connect(self.note.setText)
        self.view.hide()
        self.location = QLabel("https://www.campo.fau.de")
        layout.addWidget(self.location)
        self.page.urlChanged.connect(lambda url: self.location.setText(url.scheme() + "://" + url.host() + url.path()))
        self.page.loadStarted.connect(self.loading)
        self.page.loadFinished.connect(self.loaded)
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.poll)
        self.timer.start()
        if self.credentials:
            self.begin.hide()
            self.move_to("auth", "正在后台登录 Campo…", 5)
        self.view.setUrl(QUrl(TIMETABLE if warm_session else HOME))

    def loading(self):
        self.ready = False

    def loaded(self, ok):
        self.ready = True
        if self.stage == "auth_submitted":
            self.auth_response = True
        if not ok and self.stage=="auth" and not self.home_fallback:
            self.home_fallback=True
            self.view.setUrl(QUrl(HOME))
        elif not ok and self.stage in ("auth", "auth_submitted"):
            self.fail("无法连接 Campo，请检查网络后重试。")
        elif ok:
            QTimer.singleShot(0,self.poll)

    def reset_login(self):
        if self.job and self.job.isRunning():
            self.note.setText("正在结束日历读取，请稍后再试。")
            self.job.requestInterruption()
            return
        self.generation += 1
        self.busy = False
        self.stage = "login"
        self.begin.setEnabled(True)
        self.view.setEnabled(True)
        self.progress.setValue(0)
        self.draft = {}
        self.calendar_done = False
        self.grades_done = False
        self.started = time.monotonic()
        self.home_fallback = True
        self.auth_response = False
        if self.credentials:
            self.move_to("auth", "正在后台登录 Campo…", 5)
        self.view.setUrl(QUrl(HOME))
        self.note.setText("正在重新连接 Campo…" if self.credentials else "请配置 FAU 登录信息。")

    def _js(self, source, callback):
        if self.busy or not self.alive:
            return
        self.busy = True
        generation = self.generation
        def done(value):
            if not self.alive or generation != self.generation:
                return
            self.busy = False
            callback(value)
        self.page.runJavaScript(source, done)

    def start_sync(self):
        if self.stage != "login" or self.busy:
            return
        self._js(scripts.STATE, self.check_login)

    def check_login(self, state):
        if not state or not state.get("logged_in") or self.page.url().host() != "www.campo.fau.de":
            self.note.setText("请先完成 Campo 登录；账号密码直接填写在官方页面中。")
            return
        self.draft = {"identity": state["identity"]}
        self.profile._campo_authenticated=True
        self.begin.setEnabled(False)
        self.view.setEnabled(False)
        self.move_to("timetable", "正在读取课表导出入口…", 15)
        if state.get("timetable"):
            self.process_state(state)
        else:
            self.view.setUrl(QUrl(TIMETABLE))

    def move_to(self, stage, message, progress):
        self.stage = stage
        self.deadline = time.monotonic() + 90
        self.note.setText(message)
        self.progress.setValue(progress)

    def fail(self, message):
        if not self.alive:
            return
        self.generation += 1
        self.busy = False
        self.stage = "login"
        self.begin.setEnabled(True)
        self.view.setEnabled(True)
        self.note.setText(message)
        self.progress.setValue(0)
        self.draft = {}
        self.calendar_done = self.grades_done = False
        self.profile._campo_authenticated=False
        if self.job and self.job.isRunning():
            self.job.requestInterruption()
        self.sync_failed.emit()

    def poll(self):
        if self.stage in ("login", "done") or not self.alive:
            return
        if time.monotonic() > self.deadline:
            self.fail("Campo 响应超时。请重新登录或稍后重试；旧缓存已保留。")
            return
        if self.busy or not self.ready or self.stage == "waiting_calendar":
            return
        if self.page.url().host() != "www.campo.fau.de":
            return
        if self.stage in ("auth", "auth_submitted", "timetable", "calendar", "transcript"):
            self._js(scripts.STATE, self.process_state)
        elif self.stage == "grades":
            self._js(scripts.GRADES, self.process_grades)

    def process_state(self, state):
        if not state:
            return
        if self.stage in ("auth", "auth_submitted"):
            if state.get("logged_in"):
                self.check_login(state)
            elif self.stage == "auth_submitted" and self.auth_response:
                self.fail("登录未成功，请通过主窗口“登录信息”检查账号密码。若 FAU 要求额外验证，自动登录会停止。")
            elif self.stage == "auth":
                self._js(scripts.LOGIN_FORM, self.perform_login)
            return
        if not state.get("logged_in"):
            # During a navigation the DOM can briefly be incomplete; only fail on a real login form.
            self._js("Array.from(document.querySelectorAll('input[type=password]')).some(el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length))", lambda present: self.fail("Campo 会话已过期，请重新登录后同步。") if present else None)
            return
        if state.get("identity") != self.draft.get("identity"):
            self.fail("同步过程中登录身份发生变化，已停止保存。请重新登录对应账号。")
            return
        if self.stage == "timetable" and state.get("timetable"):
            self.draft["semester"] = state.get("semester", "").strip()
            self.move_to("calendar", "正在准备个人课表日历…", 25)
            self._js(scripts.OPEN_CALENDAR, lambda ok: None if ok else self.fail("找不到课表导出按钮，Campo 页面可能已更新。"))
        elif self.stage == "calendar" and state.get("calendar_url"):
            try:
                fingerprint = calendar_fingerprint(state["calendar_url"])
                if self.previous.get("fingerprint") and self.previous["fingerprint"] != fingerprint:
                    raise DataError("当前 Campo 账号与本地账号不一致。请切换本地账号或重新登录。")
                self.draft["fingerprint"] = fingerprint
                self.move_to("transcript", "课表下载与成绩读取正在并行进行…", 45)
                self.job = CalendarJob(state["calendar_url"], self.parent())
                self.jobs.append(self.job)
                generation=self.generation
                self.job.result.connect(lambda payload,epoch=generation: self.calendar_ready(payload) if self.alive and epoch==self.generation else None)
                self.job.error.connect(lambda message,epoch=generation: self.fail(message) if self.alive and epoch==self.generation else None)
                self.job.finished.connect(lambda job=self.job: self.release_job(job))
                self.view.setUrl(QUrl(TRANSCRIPT))
                self.job.start()
            except DataError as exc:
                self.fail(str(exc))
        elif self.stage == "transcript" and state.get("transcript"):
            self.move_to("grades", "正在展开成绩表，读取考试、模块和汇总…", 75)
            self.expansions = 1
            self.stable = ""
            self.stable_count = 0
            self.stable_since = 0.0
            self._js(scripts.EXPAND_GRADES, lambda ok: None if ok else self.fail("找不到成绩展开按钮，Campo 页面可能已更新。"))

    def perform_login(self, form):
        if not form:
            return
        if form.get("verification"):
            self.fail("FAU 要求验证码或额外验证，自动登录已停止。")
            return
        if not form.get("found"):
            if not self.home_fallback:
                self.home_fallback = True
                self.view.setUrl(QUrl(HOME))
            return
        self.auth_response = False
        self.move_to("auth_submitted", "正在验证账号并读取个人信息…", 10)
        self._js(scripts.login_script(self.credentials["username"], self.credentials["password"]),
                 lambda submitted: None if submitted else self.fail("无法找到 Campo 官方登录表单。"))

    def release_job(self, job):
        if job in self.jobs:
            self.jobs.remove(job)
        job.deleteLater()
        if self.job is job:
            self.job = None

    def calendar_ready(self, payload):
        if not self.alive or self.stage not in ("transcript","grades","waiting_calendar"):
            return
        self.draft.update(payload)
        self.calendar_done = True
        self.preview.emit(self.account_id,"calendar",{key:self.draft[key] for key in ("identity","fingerprint","events","range_start","range_end")})
        self.maybe_finish()

    def process_grades(self, payload):
        if not payload or not payload.get("table_found"):
            return
        if payload.get("ajax_error"):
            self.fail("Campo 成绩展开请求失败，旧缓存已保留。")
            return
        if payload.get("ajax_pending") or payload.get("quiet_ms",1000)<600:
            self.stable_since=0.0
            return
        if not payload.get("columns_ok"):
            self.fail("成绩表列无法识别，请恢复 Campo 默认表格列后重试。旧缓存已保留。")
            return
        if payload.get("collapsed"):
            if self.expansions < 4:
                self.expansions += 1
                self._js(scripts.EXPAND_GRADES, lambda ok: None)
            return
        signature = repr(payload.get("rows"))
        if signature != self.stable:
            self.stable = signature
            self.stable_count = 1
            self.stable_since = time.monotonic()
            return
        self.stable_count += 1
        if not self.stable_since:
            self.stable_since=time.monotonic()
            return
        if time.monotonic()-self.stable_since<0.6:
            return
        try:
            self.draft["grades"] = validate_grades(payload)
        except DataError as exc:
            self.fail(str(exc))
            return
        self._js(scripts.STATE, self.finish_sync)

    def finish_sync(self, state):
        if not state or not state.get("logged_in") or state.get("identity") != self.draft.get("identity"):
            self.fail("成绩读取结束时账号身份无法确认，旧缓存已保留。")
            return
        self.grades_done = True
        self.preview.emit(self.account_id,"grades",{key:self.draft[key] for key in ("identity","fingerprint","grades")})
        if not self.calendar_done:
            self.move_to("waiting_calendar","成绩已读取，正在等待课表下载…",90)
        self.maybe_finish()

    def maybe_finish(self):
        if not self.alive or not self.calendar_done or not self.grades_done or self.stage in ("login","done"):
            return
        self.draft["synced_at"] = datetime.now(BERLIN).isoformat()
        self.draft["sync_seconds"] = round(time.monotonic()-self.started,2)
        self.stage = "done"
        self.progress.setValue(100)
        self.synced.emit(self.account_id, self.draft.copy())
        self.accept()

    def done(self, result):
        self.alive = False
        self.generation += 1
        self.timer.stop()
        if self.job and self.job.isRunning():
            self.job.requestInterruption()
        self.view.stop()
        self.credentials = {}
        super().done(result)
