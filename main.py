# -*- coding: utf-8 -*-
"""نقطة إقلاع التطبيق: python main.py"""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app import APP_TITLE
from app.core import db
from app.ui.theme import apply_theme


def main() -> int:
    db.init_db()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    apply_theme(app)

    from app.ui.main_window import MainWindow
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
