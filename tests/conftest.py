import pytest
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def app():
    # A Qt/Chromium process must keep one QApplication alive for its whole lifetime.
    instance = QApplication.instance() or QApplication(["campo-reader-tests"])
    yield instance
