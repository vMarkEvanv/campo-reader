import sys
from pathlib import Path

import pytest
from PyQt6.QtCore import QEvent, QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication
from PyQt6.QtWebEngineCore import QWebEngineProfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from campo_reader import scripts, sync
from campo_reader.core import Store, calendar_fingerprint

URL = "https://www.campo.fau.de/qisserver/pages/cm/exa/timetable/individualTimetableCalendarExport.faces?user=alice&hash=secret"


class FakeJob(QObject):
    result = pyqtSignal(object)
    error = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, url, parent=None):
        super().__init__(parent)

    def start(self):
        self.result.emit({"events":[],"range_start":"2026-01-01","range_end":"2027-01-01"})
        self.finished.emit()

    def isRunning(self): return False
    def requestInterruption(self): pass


@pytest.fixture
def context(tmp_path,monkeypatch,app):
    monkeypatch.setattr(sync.QWebEngineView,"setUrl",lambda *args:None)
    monkeypatch.setattr(sync,"CalendarJob",FakeJob)
    store = Store(tmp_path / "sync.db")
    account = store.add("Alice")
    profile = QWebEngineProfile()
    dialog = sync.SyncDialog(account,"Alice",{},profile,[])
    dialog.timer.stop()
    payloads = []
    dialog.synced.connect(lambda key,payload:(store.save(key,payload),payloads.append(payload)))
    def js(source,callback):
        if source == scripts.STATE:
            callback({"logged_in":True,"identity":"Alice Test"})
        else:
            callback(True)
    monkeypatch.setattr(dialog,"_js",js)
    yield dialog,store,account,payloads
    dialog.reject()
    # Destroy the dialog and its Chromium page before releasing its profile.
    # processEvents alone does not guarantee DeferredDelete delivery here.
    dialog.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    profile.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    store.close()


def test_sync_commits_only_after_both_parts_and_complete_grades(context):
    dialog,store,key,payloads = context
    dialog.check_login({"logged_in":True,"identity":"Alice Test"})
    # check_login also checks the actual page URL; set the draft as after the verified official login.
    dialog.draft={"identity":"Alice Test"}
    dialog.move_to("timetable","",15)
    dialog.process_state({"logged_in":True,"identity":"Alice Test","timetable":True,"semester":"WiSe"})
    dialog.process_state({"logged_in":True,"identity":"Alice Test","calendar_url":URL})
    assert dialog.stage == "transcript"
    assert store.read(key) == {} and not payloads
    dialog.process_state({"logged_in":True,"identity":"Alice Test","transcript":True})
    grades={"table_found":True,"columns_ok":True,"collapsed":0,"rows":[{"name":"Math","kind":"exam","grade":"2.3"}]}
    dialog.process_grades(grades)
    dialog.stable_since-=1
    dialog.process_grades(grades)
    assert store.read(key)["grades"][0]["name"] == "Math"
    assert store.read(key)["fingerprint"] == calendar_fingerprint(URL)
    assert len(payloads) == 1


def test_wrong_account_and_failed_sync_leave_previous_snapshot(context):
    dialog,store,key,payloads = context
    original={"identity":"Alice Test","fingerprint":calendar_fingerprint(URL),"grades":[{"name":"Old grade"}]}
    store.save(key,original)
    dialog.previous=original
    dialog.draft={"identity":"Bob Test"}
    dialog.stage="calendar"
    dialog.process_state({"logged_in":True,"identity":"Bob Test","calendar_url":URL.replace("alice","bob")})
    assert dialog.stage == "login" and not payloads
    assert store.read(key) == original
    dialog.draft={"identity":"Alice Test"}
    dialog.stage="grades"
    dialog.process_grades({"table_found":True,"columns_ok":False})
    assert dialog.stage == "login" and store.read(key) == original
    dialog.alive=False
    dialog.calendar_ready({"events":[{"title":"late response"}]})
    assert store.read(key) == original and not payloads


@pytest.mark.parametrize("first",["calendar","grades"])
def test_parallel_completion_orders_commit_once(context,first):
    dialog,store,key,payloads=context
    dialog.draft={"identity":"Alice Test","fingerprint":calendar_fingerprint(URL)}
    dialog.stage="grades"
    def calendar():
        dialog.calendar_ready({"events":[],"range_start":"2026-01-01","range_end":"2027-01-01"})
    def grades():
        data={"table_found":True,"columns_ok":True,"collapsed":0,"quiet_ms":1000,"rows":[{"name":"Math","kind":"exam","grade":"2.3"}]}
        dialog.process_grades(data)
        dialog.stable_since-=1
        dialog.process_grades(data)
    (calendar if first=="calendar" else grades)()
    assert store.read(key)=={} and not payloads
    (grades if first=="calendar" else calendar)()
    assert len(payloads)==1 and "events" in store.read(key) and "grades" in store.read(key)
    calendar()
    assert len(payloads)==1


def test_ajax_in_flight_or_recent_mutation_never_commits(context):
    dialog,store,key,payloads=context
    dialog.stage="grades"
    dialog.draft={"identity":"Alice Test","fingerprint":calendar_fingerprint(URL)}
    dialog.calendar_done=True
    data={"table_found":True,"columns_ok":True,"collapsed":0,"rows":[{"name":"partial","kind":"exam"}]}
    for _ in range(10):dialog.process_grades({**data,"ajax_pending":True,"quiet_ms":1000})
    for _ in range(10):dialog.process_grades({**data,"ajax_pending":False,"quiet_ms":100})
    assert not payloads and store.read(key)=={}


def test_failed_parallel_part_and_late_reply_preserve_cache(context):
    dialog,store,key,payloads=context
    original={"identity":"Alice Test","fingerprint":calendar_fingerprint(URL),"grades":[{"name":"old"}]}
    store.save(key,original)
    dialog.stage="waiting_calendar"
    dialog.grades_done=True
    dialog.draft={**original,"grades":[{"name":"new"}]}
    dialog.fail("Network failed")
    dialog.calendar_ready({"events":[]})
    assert store.read(key)==original and not payloads


@pytest.mark.parametrize("busy,ready",[(True,True),(False,False)])
def test_stalled_page_and_callback_still_time_out(context,busy,ready):
    dialog,store,key,payloads=context
    dialog.stage="transcript"
    dialog.busy,dialog.ready=busy,ready
    dialog.deadline=0
    dialog.poll()
    assert dialog.stage=="login" and "超时" in dialog.note.text()
