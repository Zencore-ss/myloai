from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QPlainTextEdit

from myloai.core.operations import (  # noqa: F401 - re-exported for existing imports
    LineBufferedStream,
    OperationStreamParser,
    OperationUpdate,
)


def append_output(widget: QPlainTextEdit, text: str) -> None:
    """Append text at the document end regardless of the user's cursor or selection."""
    if not text:
        return
    cursor = widget.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    cursor.clearSelection()
    cursor.insertText(text)
    widget.setTextCursor(cursor)
    widget.ensureCursorVisible()


class DiagnosticsSignals(QObject):
    log_line = Signal(str)
    console_text = Signal(str)


class QtLogHandler(logging.Handler):
    def __init__(self, signals: DiagnosticsSignals) -> None:
        super().__init__()
        self.signals = signals
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.signals.log_line.emit(self.format(record) + "\n")
        except Exception:  # noqa: BLE001 - logging handlers must not escape
            self.handleError(record)


