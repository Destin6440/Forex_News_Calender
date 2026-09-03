"""Shared QML engine ownership helpers.

The controller and its models must outlive the engine: QML evaluates bindings
while its object tree is being destroyed.
"""
from __future__ import annotations

import gc
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QUrl
from PySide6.QtQml import QQmlApplicationEngine


def create_engine(controller, qml_path: Path | None = None):
    engine = QQmlApplicationEngine()
    context = engine.rootContext()
    for name, value in {
        "controller": controller,
        "ruleModel": controller.ruleModel,
        "resultModel": controller.resultModel,
        "eventModel": controller.eventModel,
        "savedSearchModel": controller.savedSearchModel,
    }.items():
        context.setContextProperty(name, value)
    source = qml_path or Path(__file__).parent / "qml" / "Main.qml"
    engine.load(QUrl.fromLocalFile(str(source)))
    roots = engine.rootObjects()
    if not roots or not roots[0].isVisible():
        raise RuntimeError(f"Main.qml did not create a visible root window: {source}")
    return engine, roots[0]


def destroy_engine(engine):
    """Synchronously make roots unreachable before their context properties."""
    for root in tuple(engine.rootObjects()):
        root.close()
        root.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    engine.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    QCoreApplication.processEvents()
    gc.collect()
