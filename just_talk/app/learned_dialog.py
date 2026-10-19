"""Shows what Just Talk has learned about the user, and lets them remove anything wrong."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .onboarding_widgets import FlowLayout, chip

_SOURCE_NAMES = {
    "setup": "voice setup",
    "setup-confirmed": "voice setup",
    "dictation": "your dictations",
    "cleanup": "AI cleanup",
    "review": "AI review",
    "user": "you",
}


def _label(text: str, name: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName(name)
    lbl.setWordWrap(True)
    return lbl


class LearnedDialog(QDialog):
    def __init__(self, learner, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.learner = learner
        self.setWindowTitle("What Just Talk learned")
        self.resize(600, 560)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 20)
        outer.setSpacing(6)
        outer.addWidget(_label("What Just Talk learned", "h1"))
        outer.addWidget(_label("From your voice setup and dictations. Remove anything wrong and it won't be learned again.", "lead"))
        outer.addSpacing(14)

        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body_host = QWidget()
        self.body = QVBoxLayout(self.body_host)
        self.body.setContentsMargins(0, 0, 6, 0)
        self.body.setSpacing(0)
        area.setWidget(self.body_host)
        outer.addWidget(area, 1)

        buttons = QHBoxLayout()
        buttons.addStretch()
        close = QPushButton("Done")
        close.setObjectName("primaryBtn")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        outer.addLayout(buttons)
        self._render()

    def _clear(self) -> None:
        while self.body.count():
            item = self.body.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _render(self) -> None:
        self._clear()
        mixups = self.learner.known_mixups()
        terms = self.learner.known_terms()

        self.body.addWidget(_label("Mix-ups it now corrects", "eyebrow"))
        self.body.addSpacing(6)
        if not mixups:
            self.body.addWidget(_label("None yet. Mix-ups show up after voice setup, an AI review, or once the same one is seen twice.", "caption"))
        for heard, meant in mixups:
            ev = self.learner.mixups.get((heard, meant))
            row = QFrame()
            row.setObjectName("hairRow")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 10, 0, 10)
            text = QVBoxLayout()
            text.setSpacing(2)
            text.addWidget(_label(f"“{heard}”  →  {meant}", "rowTitle"))
            if ev is not None:
                sources = ", ".join(dict.fromkeys(_SOURCE_NAMES.get(s, s) for s in ev.sources))
                detail = f"Seen {ev.count}× · from {sources}"
                if ev.example:
                    detail += f" · “{ev.example[:70]}”"
                text.addWidget(_label(detail, "caption"))
            rl.addLayout(text, 1)
            remove = QPushButton("Remove")
            remove.setObjectName("linkBtn")
            remove.clicked.connect(lambda _=False, h=heard, m=meant: self._forget_mixup(h, m))
            rl.addWidget(remove)
            self.body.addWidget(row)

        self.body.addSpacing(24)
        self.body.addWidget(_label("Your words", "eyebrow"))
        self.body.addSpacing(8)
        if not terms:
            self.body.addWidget(_label("None yet. Names and terms you use often appear here.", "caption"))
        else:
            host = QWidget()
            flow = FlowLayout(host, spacing=8)
            for term in terms:
                b = chip(f"{term}   ×", checkable=False)
                b.setToolTip("Remove")
                b.clicked.connect(lambda _=False, t=term: self._forget_term(t))
                flow.addWidget(b)
            self.body.addWidget(host)
        self.body.addStretch()

    def _forget_mixup(self, heard: str, meant: str) -> None:
        self.learner.forget_mixup(heard, meant)
        self.learner.save()
        self._render()

    def _forget_term(self, term: str) -> None:
        self.learner.forget_term(term)
        self.learner.save()
        self._render()
