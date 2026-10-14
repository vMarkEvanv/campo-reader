from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import sqlite3
import uuid
from datetime import date, datetime, time, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from icalendar import Calendar
import recurring_ical_events

BERLIN = ZoneInfo("Europe/Berlin")
HOST = "www.campo.fau.de"
HOME = f"https://{HOST}/qisserver/pages/cs/sys/portal/hisinoneStartPage.faces"
TIMETABLE = f"https://{HOST}/qisserver/pages/plan/individualTimetable.xhtml?_flowId=individualTimetableSchedule-flow"
TRANSCRIPT = f"https://{HOST}/qisserver/pages/sul/examAssessment/personExamsReadonly.xhtml?_flowId=examsOverviewForPerson-flow"


class DataError(ValueError):
    pass


def display_semester(value: str) -> str:
    # Old caches accidentally contain every dropdown option. Do not guess the selected one.
    lines = [line.strip() for line in str(value).splitlines() if line.strip()]
    if len(lines) != 1:
        return ""
    return re.sub(r"\s+", " ", lines[0])[:80] if lines else ""


def should_auto_sync(payload: dict, now: datetime | None = None) -> bool:
    """Manual refresh is unconditional; automatic refresh reuses a recent complete snapshot."""
    try:
        last = datetime.fromisoformat(payload["synced_at"])
        if last.tzinfo is None:
            return True
        age = ((now or datetime.now(BERLIN)) - last).total_seconds()
        return not (0 <= age < 600 and "events" in payload and "grades" in payload)
    except (KeyError, TypeError, ValueError):
        return True


def calendar_fingerprint(url: str) -> str:
    try:
        parts = urlsplit(url)
        query = parse_qs(parts.query)
        if (parts.scheme != "https" or parts.hostname != HOST or parts.port not in (None, 443)
                or parts.username or parts.password or parts.fragment
                or parts.path != "/qisserver/pages/cm/exa/timetable/individualTimetableCalendarExport.faces"
                or len(query.get("user", [])) != 1 or not query.get("hash")):
            raise DataError("日历链接格式不符合 Campo 官方导出格式。")
        return hashlib.sha256(query["user"][0].encode()).hexdigest()
    except ValueError as exc:
        raise DataError("日历链接格式不符合 Campo 官方导出格式。") from exc


def parse_calendar(data: bytes, start: date, end: date) -> list[dict]:
    if b"BEGIN:VCALENDAR" not in data[:4096].upper():
        raise DataError("Campo 返回的不是日历数据，可能需要重新登录。")
    try:
        calendar = Calendar.from_ical(data)
        occurrences = recurring_ical_events.of(calendar).between(start, end)
        result = []
        seen = set()
        for event in occurrences:
            if str(event.get("STATUS", "")).upper() == "CANCELLED":
                continue
            raw_start = event.decoded("DTSTART")
            raw_end = event.decoded("DTEND", None)
            all_day = not isinstance(raw_start, datetime)
            begin = datetime.combine(raw_start, time.min, BERLIN) if all_day else raw_start
            if begin.tzinfo is None:
                begin = begin.replace(tzinfo=BERLIN)
            begin = begin.astimezone(BERLIN)
            if raw_end is None:
                finish = begin + event.decoded("DURATION", timedelta(days=1) if all_day else timedelta())
            else:
                finish = datetime.combine(raw_end, time.min, BERLIN) if not isinstance(raw_end, datetime) else raw_end
                if finish.tzinfo is None:
                    finish = finish.replace(tzinfo=BERLIN)
                finish = finish.astimezone(BERLIN)
            if finish < begin:
                raise DataError("日历包含结束时间早于开始时间的课程。")
            key = (str(event.get("UID", "")), begin.isoformat(), finish.isoformat())
            if key in seen:
                continue
            seen.add(key)
            result.append({"uid": key[0], "title": str(event.get("SUMMARY", "未命名课程")),
                           "start": begin.isoformat(), "end": finish.isoformat(), "all_day": all_day,
                           "room": str(event.get("LOCATION", "")),
                           "description": str(event.get("DESCRIPTION", ""))})
        return sorted(result, key=lambda item: (item["start"], item["title"]))
    except DataError:
        raise
    except Exception as exc:
        raise DataError("无法解析 Campo 日历；旧缓存已保留。") from exc


def validate_grades(payload: dict) -> list[dict]:
    if not payload.get("table_found") or not payload.get("columns_ok"):
        raise DataError("未找到完整成绩表，请在成绩页展开全部后重试。")
    if payload.get("collapsed", 0):
        raise DataError("成绩表尚未展开完整，旧缓存已保留。")
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise DataError("成绩表格式发生变化。")
    fields = ("level", "name", "kind", "number", "grade", "status", "credits", "attempt", "released", "annotation", "program")
    result = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("name"):
            raise DataError("成绩表包含无法识别的行。")
        result.append({field: str(row.get(field, "")).strip() for field in fields})
    return result


class _Blob(ctypes.Structure):
    _fields_ = [("size", ctypes.c_uint32), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _crypt(data: bytes, decrypt: bool = False) -> bytes:
    """Windows DPAPI user scope for caches and opt-in credentials."""
    if os.name != "nt":
        return data
    buf = ctypes.create_string_buffer(data)
    source = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    target = _Blob()
    lib = ctypes.WinDLL("crypt32", use_last_error=True)
    fn = lib.CryptUnprotectData if decrypt else lib.CryptProtectData
    fn.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(_Blob)]
    fn.restype = ctypes.c_int
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise DataError("本地数据加密或解密失败，请使用创建缓存的 Windows 用户。")
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        free = ctypes.WinDLL("kernel32").LocalFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = ctypes.c_void_p
        free(target.data)


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS accounts (id TEXT PRIMARY KEY, label TEXT NOT NULL, payload BLOB NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS credentials (account_id TEXT PRIMARY KEY, secret BLOB NOT NULL)")
        self.db.commit()

    def list_accounts(self) -> list[tuple[str, str]]:
        return self.db.execute("SELECT id,label FROM accounts ORDER BY rowid").fetchall()

    def add(self, label: str) -> str:
        label = label.strip()
        if not label or len(label) > 80:
            raise DataError("账号名称需要 1–80 个字符。")
        key = uuid.uuid4().hex
        with self.db:
            self.db.execute("INSERT INTO accounts VALUES (?,?,?)", (key, label, self._encode({})))
        return key

    def read(self, account_id: str) -> dict:
        row = self.db.execute("SELECT payload FROM accounts WHERE id=?", (account_id,)).fetchone()
        if row is None:
            raise DataError("账号不存在。")
        try:
            return json.loads(_crypt(row[0], decrypt=True).decode("utf-8"))
        except DataError:
            raise
        except Exception as exc:
            raise DataError("本地缓存无法读取。") from exc

    @staticmethod
    def _encode(payload: dict) -> bytes:
        return _crypt(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def save(self, account_id: str, payload: dict) -> None:
        previous = self.read(account_id)
        if not payload.get("fingerprint") or not payload.get("identity"):
            raise DataError("缺少账号身份，拒绝保存。")
        if previous.get("fingerprint") and previous["fingerprint"] != payload["fingerprint"]:
            raise DataError("当前登录的 Campo 账号与此本地账号不一致，请切换到对应账号。")
        with self.db:
            self.db.execute("UPDATE accounts SET payload=? WHERE id=?", (self._encode(payload), account_id))

    def delete(self, account_id: str) -> None:
        with self.db:
            self.db.execute("DELETE FROM credentials WHERE account_id=?", (account_id,))
            self.db.execute("DELETE FROM accounts WHERE id=?", (account_id,))

    def credentials(self, account_id: str) -> dict:
        self.read(account_id)
        row = self.db.execute("SELECT secret FROM credentials WHERE account_id=?", (account_id,)).fetchone()
        if row is None:
            return {}
        if os.name != "nt":
            raise DataError("已保存的登录信息只能在 Windows 上解密。")
        return json.loads(_crypt(row[0], decrypt=True).decode("utf-8"))

    def save_credentials(self, account_id: str, username: str, password: str):
        self.read(account_id)
        if os.name != "nt":
            raise DataError("此版本只支持用 Windows 加密保存密码。")
        if not username.strip() or not password:
            raise DataError("请输入 FAU 用户名和密码。")
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO credentials VALUES (?,?)", (account_id, self._encode({"username":username.strip(),"password":password})))

    def forget_credentials(self, account_id: str):
        with self.db:
            self.db.execute("DELETE FROM credentials WHERE account_id=?", (account_id,))

    def close(self):
        self.db.close()
