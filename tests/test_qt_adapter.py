"""Exercise the actual JS on Campo-shaped HTML using Chromium, plus account switching."""
import json
import sys
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication
from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
from PyQt6.QtCore import QEvent, QEventLoop, QTimer, QUrl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from campo_reader import scripts
from campo_reader.core import Store, validate_grades
from campo_reader.ui import MainWindow
from main import demo


def dispose_qt(app, *objects):
    # Explicitly deliver deferred deletion, preserving page/profile order.
    for obj in objects:
        obj.deleteLater()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def fixture_html(german=False):
    headers = ["Level", "Degree", "Number", "Withdrawal", "Grade", "Status", "ECTS credits", "Free trial", "Annotation", "Attempt", "Exception", "Additional attribute", "Grade release date", "Actions"]
    if german:
        headers = ["Ebene", "Abschluss", "Nummer", "Rücktritt", "Note", "Status", "ECTS-Punkte", "Freiversuch", "Vermerk", "Versuch", "Ausnahme", "Zusatzattribut", "Datum der Notenfreigabe", "Aktionen"]
    head = "".join(f'<th colspan="{8 if i==1 else 1}">{h}</th>' for i,h in enumerate(headers))
    def row(level, depth, name, icon, number="", grade="", status="", credits="", released=""):
        indent = "<td></td>" * depth
        rest = "".join(f"<td>{v}</td>" for v in [number,"",grade,status,credits,"","","1","","",released,""])
        return f'<tr><td>{level}</td>{indent}<td colspan="{8-depth}"><img alt="{icon}"><span id="row-{number}:defaulttext">{name}</span></td>{rest}</tr>'
    body = row("1.1",1,"M.Sc. Test","Examination regulations") + row("1.1.1",2,"Master's examination","Level","10000","2.3","PV","5.0") + row("1.1.1.1",3,"Test Module","Module","65718","2.3","BE","5.0") + row("1.1.1.1.1",4,"Test Examination","Examination","57181","2.3","EB","5.0","Oct 9, 2026")
    return f'<html><body><button id="header:avatarInfobox:open" data-title="My profile: Alice Test Student FAU"></button><a id="header:logoutLink"></a><form id="sessionTimeoutLoginForm" style="display:none"><input type="password"></form><div id="examsReadonly"><div id="examsReadonly:overviewAsTreeReadonly:collapsiblePanel"><table class="treeTableWithIcons"><tr>{head}</tr>{body}</table></div></div></body></html>'


def run_js(page, source):
    loop = QEventLoop()
    values = []
    page.runJavaScript(source, lambda result: (values.append(result), loop.quit()))
    QTimer.singleShot(10000, loop.quit)
    loop.exec()
    assert values, "JavaScript callback timed out"
    return values[0]


@pytest.mark.parametrize("german", [False,True])
def test_real_js_handles_colspans_language_and_hierarchy(app, german):
    profile = QWebEngineProfile()
    page = QWebEnginePage(profile)
    loop = QEventLoop()
    page.loadFinished.connect(loop.quit)
    page.setHtml(fixture_html(german), QUrl("https://www.campo.fau.de/"))
    QTimer.singleShot(10000, loop.quit)
    loop.exec()
    state = run_js(page, scripts.STATE)
    assert state["identity"] == "Alice Test" and state["logged_in"]
    payload = run_js(page, scripts.GRADES)
    rows = validate_grades(payload)
    assert [r["kind"] for r in rows] == ["program","group","module","exam"]
    assert rows[-1]["grade"] == "2.3" and rows[-1]["credits"] == "5.0"
    assert rows[-1]["number"] == "57181" and rows[-1]["released"] == "Oct 9, 2026"
    run_js(page, "document.getElementById('sessionTimeoutLoginForm').style.display='block'; true")
    assert not run_js(page, scripts.STATE)["logged_in"]
    dispose_qt(app, page, profile)


def test_gui_switching_uses_account_cache_only(app,tmp_path):
    store = Store(tmp_path / "ui.db")
    demo(store)
    window = MainWindow(store)
    assert window.grade_table.item(0,0).text() == "Example examination A"
    first = window.payload["fingerprint"]
    window.accounts.setCurrentIndex(1)
    assert window.grade_table.item(0,0).text() == "Example examination B"
    assert window.payload["fingerprint"] != first
    window.grade_filter.setCurrentIndex(1)
    assert window.grade_table.item(0,0).text() == "Example module"
    window.grade_search.setText("absent")
    assert window.grade_table.rowCount() == 0
    blank = store.add("Never synced")
    window.reload_accounts(blank)
    assert not window.payload
    assert window.grade_table.rowCount() == 0 and window.agenda.rowCount() == 0
    assert window.identity.text() == "尚未登录"
    window.payload={"semester":"Winter semester 2027/28\nSommersemester 2027\nWinter semester 2026/27",**window.payload}
    window.close()
    dispose_qt(app, window)
    store.close()


def test_selected_semester_and_background_login_form(app):
    profile=QWebEngineProfile()
    page=QWebEnginePage(profile)
    loop=QEventLoop()
    page.loadFinished.connect(loop.quit)
    html=fixture_html().replace('</body>', '''
    <div id="plan:scheduleConfiguration:anzeigeoptionen:changeTerm"><select>
    <option>Winter semester 2027/28</option><option selected>Winter semester 2026/27</option>
    <option>Summer semester 2026</option></select></div>
    <form id="mobileLoginForm" method="post" action="https://www.campo.fau.de/qisserver/rds?state=user&type=1&category=auth.login">
    <input name="asdf"><input name="fdsa" type="password"><input name="ajax-token" type="hidden" value="csrf">
    </form><div id="submission"></div></body>''')
    page.setHtml(html,QUrl("https://www.campo.fau.de/"))
    QTimer.singleShot(10000,loop.quit)
    loop.exec()
    assert run_js(page,scripts.STATE)["semester"]=="Winter semester 2026/27"
    run_js(page,"document.getElementById('examsReadonly').insertAdjacentHTML('beforeend','<button id=\"test:tree:expandAll2\">Expand</button>'); window.jsf={ajax:{addOnEvent:f=>{window.testAjaxEvent=f;},addOnError:f=>{window.testAjaxError=f;}}}; document.getElementById('test:tree:expandAll2').onclick=()=>window.testAjaxEvent({status:'begin'});true")
    assert run_js(page,scripts.EXPAND_GRADES)
    assert run_js(page,scripts.GRADES)["ajax_pending"]
    run_js(page,"window.testAjaxEvent({status:'success'});true")
    after=run_js(page,scripts.GRADES)
    assert not after["ajax_pending"] and after["quiet_ms"]<600
    assert run_js(page,scripts.LOGIN_FORM)["found"]
    run_js(page,"HTMLFormElement.prototype.submit=function(){document.getElementById('submission').textContent=JSON.stringify(Array.from(this.elements).map(e=>[e.name,e.value]));};true")
    password='quotes"\\ and unicode 密码'
    assert run_js(page,scripts.login_script("fake-user",password))
    values=json.loads(run_js(page,"document.getElementById('submission').textContent"))
    assert ["asdf","fake-user"] in values and ["fdsa",password] in values and ["ajax-token","csrf"] in values
    run_js(page,"document.getElementById('mobileLoginForm').action='https://evil.test/login';true")
    assert not run_js(page,scripts.login_script("fake-user",password))
    dispose_qt(app, page, profile)


def test_legacy_cache_cannot_push_timetable_offscreen(app,tmp_path):
    store=Store(tmp_path / "layout.db")
    demo(store)
    key=store.list_accounts()[0][0]
    payload=store.read(key)
    payload["semester"]="\n".join(f"Winter semester {year}/{year+1}" for year in range(2027,2015,-1))
    store.save(key,payload)
    window=MainWindow(store)
    window.resize(1100,720)
    window.show();app.processEvents()
    assert "\n" not in window.info.text()
    assert window.info.height()<=22
    assert window.week_scroll.viewport().height()>300
    assert window.canvas.height()<450
    window.close()
    dispose_qt(app, window)
    store.close()


def test_partial_preview_is_visible_but_failed_sync_restores_cache(app,tmp_path):
    store=Store(tmp_path / "preview.db")
    demo(store)
    window=MainWindow(store)
    key=window.accounts.currentData()
    before=store.read(key)
    update={"identity":before["identity"],"fingerprint":before["fingerprint"],"events":[],
            "range_start":before["range_start"],"range_end":before["range_end"]}
    window.show_preview(key,"calendar",update)
    assert window.payload["events"]==[] and "正在等待成绩" in window.info.text()
    assert store.read(key)==before
    window.account_changed()
    assert window.payload==before
    window.show_preview(key,"calendar",{**update,"fingerprint":"other-account"})
    assert window.payload==before
    window.close();dispose_qt(app,window);store.close()
