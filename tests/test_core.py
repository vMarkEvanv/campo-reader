from datetime import date, datetime
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from campo_reader.core import Store, DataError, calendar_fingerprint, parse_calendar, validate_grades, display_semester, should_auto_sync, BERLIN


def test_accounts_cannot_overwrite_each_other_or_change_remote_identity(tmp_path):
    store = Store(tmp_path / "cache.db")
    a, b = store.add("Alice"), store.add("Bob")
    store.save(a, {"identity":"Alice", "fingerprint":"alice", "grades":[{"name":"Math"}]})
    store.save(b, {"identity":"Bob", "fingerprint":"bob", "grades":[{"name":"Physics"}]})
    with pytest.raises(DataError):
        store.save(a, {"identity":"Bob", "fingerprint":"bob", "grades":[]})
    assert store.read(a)["grades"] == [{"name":"Math"}]
    assert store.read(b)["grades"] == [{"name":"Physics"}]
    store.delete(a)
    assert store.read(b)["identity"] == "Bob"
    store.close()
    reopened = Store(tmp_path / "cache.db")
    assert reopened.read(b)["grades"] == [{"name":"Physics"}]
    reopened.close()


def test_windows_payload_is_not_plaintext(tmp_path):
    import os
    if os.name != "nt": pytest.skip("Windows DPAPI")
    store = Store(tmp_path / "cache.db")
    key = store.add("account")
    store.save(key, {"identity":"Sensitive Person", "fingerprint":"sensitive", "grades":["SecretGrade"]})
    blob = store.db.execute("SELECT payload FROM accounts WHERE id=?", (key,)).fetchone()[0]
    assert b"SecretGrade" not in blob
    assert store.read(key)["grades"] == ["SecretGrade"]
    store.close()


def test_calendar_recurring_exceptions_dst_and_cancelled():
    data = b"""BEGIN:VCALENDAR\r
VERSION:2.0\r
PRODID:-//Test//EN\r
BEGIN:VEVENT\r
UID:course\r
DTSTART;TZID=Europe/Berlin:20261019T081500\r
DTEND;TZID=Europe/Berlin:20261019T094500\r
RRULE:FREQ=WEEKLY;COUNT=3\r
EXDATE;TZID=Europe/Berlin:20261026T081500\r
SUMMARY:Lecture\r
LOCATION:H6\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:course\r
RECURRENCE-ID;TZID=Europe/Berlin:20261102T081500\r
DTSTART;TZID=Europe/Berlin:20261102T101500\r
DTEND;TZID=Europe/Berlin:20261102T114500\r
SUMMARY:Moved lecture\r
LOCATION:H11\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:cancelled\r
DTSTART:20261020T100000Z\r
DTEND:20261020T110000Z\r
STATUS:CANCELLED\r
SUMMARY:Cancelled\r
END:VEVENT\r
END:VCALENDAR\r
"""
    events = parse_calendar(data, date(2026,10,1), date(2026,12,1))
    assert len(events) == 2
    assert events[0]["start"] == "2026-10-19T08:15:00+02:00"
    assert events[1]["start"] == "2026-11-02T10:15:00+01:00"
    assert events[1]["room"] == "H11"


def test_all_day_and_empty_calendar():
    data = b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:day\r\nDTSTART;VALUE=DATE:20261014\r\nSUMMARY:All day\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    events = parse_calendar(data,date(2026,10,1),date(2026,11,1))
    assert events[0]["all_day"]
    assert datetime.fromisoformat(events[0]["end"]).date() == date(2026,10,15)
    assert parse_calendar(b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n",date(2026,1,1),date(2027,1,1)) == []
    with pytest.raises(DataError): parse_calendar(b"<html>Log in</html>",date(2026,1,1),date(2027,1,1))


def test_calendar_link_account_id_and_token_validation():
    url = "https://www.campo.fau.de:443/qisserver/pages/cm/exa/timetable/individualTimetableCalendarExport.faces?user=alice&hash=secret"
    assert calendar_fingerprint(url) == calendar_fingerprint(url.replace("secret", "new-token"))
    assert calendar_fingerprint(url) != calendar_fingerprint(url.replace("alice", "bob"))
    for bad in [url.replace("www.campo.fau.de", "evil.test"),url.replace("https", "http"),url.replace(":443", ":444"),url.replace("user=alice", "user=alice&user=bob")]:
        with pytest.raises(DataError): calendar_fingerprint(bad)


def test_incomplete_grades_are_rejected_instead_of_erasing_cache():
    for payload in [{"table_found":False},{"table_found":True,"columns_ok":False},{"table_found":True,"columns_ok":True,"rows":[],"collapsed":1}]:
        with pytest.raises(DataError): validate_grades(payload)
    assert validate_grades({"table_found":True,"columns_ok":True,"rows":[],"collapsed":0}) == []


def test_old_semester_dropdown_is_not_shown_as_paragraph():
    assert display_semester("Winter semester 2027/28\nSommersemester 2027\nWinter semester 2026/27") == ""
    assert display_semester("  Winter semester 2026/27  ") == "Winter semester 2026/27"


def test_saved_credentials_are_encrypted_and_per_account(tmp_path):
    import os
    if os.name != "nt": pytest.skip("Windows DPAPI")
    store=Store(tmp_path / "credentials.db")
    a,b=store.add("Alice"),store.add("Bob")
    store.save_credentials(a,"alice","password-alice")
    store.save_credentials(b,"bob","password-bob")
    assert store.credentials(a)=={"username":"alice","password":"password-alice"}
    assert store.credentials(b)["username"]=="bob"
    assert b"password-alice" not in store.db.execute("SELECT secret FROM credentials WHERE account_id=?",(a,)).fetchone()[0]
    store.forget_credentials(a)
    assert not store.credentials(a) and store.credentials(b)
    store.delete(b)
    assert store.db.execute("SELECT count(*) FROM credentials").fetchone()[0]==0
    store.close()


def test_automatic_refresh_reuses_recent_complete_cache():
    from datetime import timedelta
    now=datetime(2026,10,14,20,0,tzinfo=BERLIN)
    cache={"events":[],"grades":[],"synced_at":(now-timedelta(minutes=5)).isoformat()}
    assert not should_auto_sync(cache,now)
    assert should_auto_sync({**cache,"synced_at":(now-timedelta(minutes=11)).isoformat()},now)
    assert should_auto_sync({**cache,"synced_at":(now+timedelta(minutes=5)).isoformat()},now)
    assert should_auto_sync({"synced_at":cache["synced_at"]},now)
