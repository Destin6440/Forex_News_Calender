from __future__ import annotations
import logging,sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from . import __version__

def main(argv=None):
    from PySide6.QtCore import QCoreApplication,QStandardPaths,QTimer,QUrl
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QIcon
    from PySide6.QtQml import QQmlApplicationEngine
    QCoreApplication.setOrganizationName("Destin"); QCoreApplication.setApplicationName("Forex Calendar Lab"); QCoreApplication.setApplicationVersion(__version__)
    app=QApplication(argv or sys.argv)
    logdir=Path(QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation))/"logs"; logdir.mkdir(parents=True,exist_ok=True)
    handler=RotatingFileHandler(logdir/"app.log",maxBytes=1_000_000,backupCount=3); logging.getLogger().addHandler(handler)
    from .controller import AppController
    controller=AppController(Path(__file__).resolve().parents[2]);app.setWindowIcon(QIcon(str(Path(__file__).parent/"assets/icon.svg")))
    engine=QQmlApplicationEngine();engine.rootContext().setContextProperty("controller",controller);engine.rootContext().setContextProperty("ruleModel",controller.ruleModel);engine.rootContext().setContextProperty("resultModel",controller.resultModel);engine.rootContext().setContextProperty("eventModel",controller.eventModel);engine.rootContext().setContextProperty("savedSearchModel",controller.savedSearchModel)
    qml=Path(__file__).parent/"qml/Main.qml"; engine.load(QUrl.fromLocalFile(str(qml)))
    if not engine.rootObjects(): return 1
    if not controller.databasePath:
        QTimer.singleShot(0, controller.chooseDatabase)
    exit_code=app.exec()
    # Context properties must outlive every binding that uses them. Destroying
    # the engine synchronously tears down its root window before the controller.
    for root in engine.rootObjects():root.close()
    del engine
    controller.shutdown()
    del controller
    return exit_code

if __name__=="__main__": raise SystemExit(main())
