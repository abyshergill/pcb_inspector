import cv2
import numpy as np
import pytest

from core.app_settings import AppSettings
from core.file_naming import OutputFileNamer
from core.models import MasterTemplate, ComponentAnnotation
from core.template_manager import MasterTemplateManager
from inspection.inspection_engine import InspectionEngine
from inspection.inspection_worker import InspectionWorker


def _engine(golden_path):
    t = MasterTemplate("t", str(golden_path), 90.0, [ComponentAnnotation("U1", 15, 15, 80, 70)])
    return InspectionEngine(t)


def test_worker_saves_and_emits(qtbot, tmp_path, golden_path, pcb_image):
    namer = OutputFileNamer(str(tmp_path / "p"), str(tmp_path / "f"))
    worker = InspectionWorker(_engine(golden_path), namer, pcb_image)
    worker.setAutoDelete(False)
    got = {}
    worker.signals.finished.connect(lambda r, p: got.update(result=r, path=p))
    with qtbot.waitSignal(worker.signals.done, timeout=5000):
        worker.run()
    assert got["result"].module_passed
    assert got["path"].parent == tmp_path / "p" and got["path"].exists()


def test_worker_reports_errors(qtbot, tmp_path, golden_path):
    namer = OutputFileNamer(str(tmp_path / "p"), str(tmp_path / "f"))
    worker = InspectionWorker(_engine(golden_path), namer, np.zeros((4, 4, 2), np.uint8))
    worker.setAutoDelete(False)
    with qtbot.waitSignal(worker.signals.error, timeout=5000) as blocker:
        worker.run()
    assert "ValueError" in blocker.args[0]


def test_app_settings_follow_config(tmp_path):
    import config
    assert AppSettings().pass_dir == config.PASS_DIR


def test_inspection_widget_display(qtbot, golden_path, pcb_image):
    from ui.inspection_widget import InspectionWidget
    w = InspectionWidget()
    qtbot.addWidget(w)
    w.display_result(_engine(golden_path).inspect(pcb_image))
    assert "PASS" in w.status_label.text()
    assert w.result_list.count() == 1
    w._toggle_view()
    assert "Mono" in w.toggle_btn.text()
    w.set_logging_status(True, "x.csv")
    assert not w.start_log_btn.isEnabled() and w.stop_log_btn.isEnabled()


def test_canvas_items_and_clamp(qtbot, golden_path):
    from PySide6.QtCore import QRectF
    from training.annotation_canvas import AnnotationCanvas
    c = AnnotationCanvas()
    qtbot.addWidget(c)
    assert c.load_image(str(golden_path))
    assert c._clamp_to_image(QRectF(-10, -10, 50, 50)) == QRectF(0, 0, 40, 40)
    item = c.add_component_item("id1", 10, 10, 40, 40, "U1", shape="circle")
    c.set_mode("edit")
    # Corner handle of a circle must be clickable (regression).
    assert item.shape().contains(item.rect().topLeft())
    c.remove_item("id1")
    assert not c.has_item("id1")
    assert not c.load_image(str(golden_path.parent / "missing.png"))


def test_training_widget_load_and_duplicates(qtbot, golden_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from ui.training_widget import TrainingModuleWidget
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

    mgr = MasterTemplateManager()
    t = MasterTemplate("Saved", str(golden_path), 80.0, [ComponentAnnotation("U1", 15, 15, 80, 70, component_id="c1")])
    mgr.save(t)

    w = TrainingModuleWidget(AppSettings(), template_manager=mgr)
    qtbot.addWidget(w)
    assert w.load_template("Saved")
    assert w.component_list.count() == 1 and w.canvas.has_item("c1")
    assert w.module_threshold_spin.value() == 80.0

    w.canvas.add_component_item("c2", 0, 0, 20, 20, "U1")
    w._on_component_added({"component_id": "c2", "name": "U1", "x": 0, "y": 0, "w": 20, "h": 20})
    assert len(w.current_template.components) == 1  # duplicate rejected
    assert not w.canvas.has_item("c2")


def test_main_window_smoke(qtbot, golden_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from ui.main_window import MainWindow
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

    win = MainWindow()
    qtbot.addWidget(win)
    assert not win._ensure_engine()  # no templates yet, no crash

    MasterTemplateManager().save(MasterTemplate("Board", str(golden_path), 90.0,
                                                [ComponentAnnotation("U1", 15, 15, 80, 70)]))
    win._on_template_saved("Board")
    assert win.engine is not None and win.active_template_name == "Board"
    assert win.inspection_widget.template_combo.currentText() == "Board"

    with qtbot.waitSignal(win.inspection_widget.result_list.model().rowsInserted, timeout=10000):
        win._run_batch_image(str(golden_path))
    assert "PASS" in win.inspection_widget.status_label.text()
    win.close()
