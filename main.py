from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from campo_reader.core import Store, BERLIN
from campo_reader.ui import MainWindow


def demo(store):
    if store.list_accounts():
        return
    today = datetime.now(BERLIN).date()
    monday = today - timedelta(days=today.weekday())
    for index, label in enumerate(["演示账号 A", "演示账号 B"]):
        key = store.add(label)
        events = []
        for offset, hour, title, room in [(0, 8, "Machine Learning · 示例", "H6"), (1, 10, "Pattern Recognition · 示例", "H11"), (3, 12, "Integrated Circuits · 示例", "SR 01.030")]:
            begin = datetime.combine(monday + timedelta(days=offset + index), datetime.min.time(), BERLIN).replace(hour=hour, minute=15)
            events.append({"uid":str(offset), "title":title,"room":room,"description":"此数据仅供演示。", "start":begin.isoformat(),"end":(begin+timedelta(minutes=90)).isoformat(),"all_day":False})
        rows = [{"level":"1.1.1","kind":"group","name":"Master's examination","number":"10000","grade":"2.0","status":"PV","credits":"10.0","attempt":"1","released":"","annotation":"","program":"示例专业"},
                {"level":"1.1.1.1","kind":"module","name":"Example module","number":"60000","grade":"2.0","status":"BE","credits":"5.0","attempt":"1","released":"","annotation":"","program":"示例专业"},
                {"level":"1.1.1.1.1","kind":"exam","name":"Example examination A" if index == 0 else "Example examination B","number":"50000","grade":"2.0","status":"EB","credits":"5.0","attempt":"1","released":"2026-10-09","annotation":"示例","program":"示例专业"}]
        store.save(key,{"identity":label + "（虚构）","fingerprint":"demo-"+str(index),"events":events,"grades":rows,"semester":"演示数据", "synced_at":datetime.now(BERLIN).isoformat(),"range_start":monday.isoformat(),"range_end":(monday+timedelta(days=14)).isoformat()})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parent / "data")
    parser.add_argument("--demo", action="store_true", help="Use a separate demo database with fictional data")
    parser.add_argument("--smoke-screenshot", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Campo Reader")
    app.setStyle("Fusion")
    store = Store(args.data_dir / ("demo.sqlite3" if args.demo else "campo.sqlite3"))
    if args.demo: demo(store)
    window = MainWindow(store)
    window.show()
    # A launcher may hide its console; bring the interactive Qt window into view separately.
    def show_window():
        window.showNormal()
        window.raise_()
        window.activateWindow()
    QTimer.singleShot(150, show_window)
    if args.smoke_screenshot:
        def capture():
            args.smoke_screenshot.parent.mkdir(parents=True, exist_ok=True)
            window.grab().save(str(args.smoke_screenshot))
            window.tabs.setCurrentIndex(1)
            QTimer.singleShot(200, capture_grades)
        def capture_grades():
            window.grab().save(str(args.smoke_screenshot.with_name("grades-preview.png")))
            app.quit()
        QTimer.singleShot(500, capture)
    result = app.exec()
    store.close()
    return result


if __name__ == "__main__":
    sys.exit(main())
