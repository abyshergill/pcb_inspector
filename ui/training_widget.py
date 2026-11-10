import os
import shutil
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QFileDialog,
    QListWidget, QListWidgetItem, QLineEdit, QLabel, QMessageBox,
    QDoubleSpinBox, QSpinBox, QComboBox, QFormLayout, QGroupBox, QCheckBox,
    QInputDialog, QApplication
)
from PySide6.QtCore import Qt, Signal
import cv2
from core.models import MasterTemplate, ComponentAnnotation, CodeRegionAnnotation
from core.template_manager import MasterTemplateManager, sanitize_template_name
from core.app_settings import AppSettings
from core.image_utils import read_image, write_image
from training.golden_image_builder import GoldenImageBuilder
from training.annotation_canvas import AnnotationCanvas

class TrainingModuleWidget(QWidget):
    """
    Master Registration workflow: build/upload a Golden Image, draw
    Components (pass/fail) and optional Code Regions (QR/Barcode/OCR,
    used only for output file naming when enabled), edit/delete either,
    then save. Edit panels stay hidden until a shape is actually
    selected, to keep the screen uncluttered.
    """

    # Emitted with the template name after a Master Template is saved, so
    # the inspection side can switch to it instead of a stale engine.
    templateSaved = Signal(str)

    WORKING_GOLDEN_NAME = "_working_golden_image.png"  # PNG: lossless, no JPEG artefacts in the baseline

    def __init__(self, settings: AppSettings, template_manager: MasterTemplateManager | None = None, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.template_manager = template_manager or MasterTemplateManager()
        self.current_template: MasterTemplate | None = None
        self.reference_paths: list[str] = []
        self._selected_component_id: str | None = None
        self._selected_region_id: str | None = None

        self.canvas = AnnotationCanvas()
        self.canvas.componentAdded.connect(self._on_component_added)
        self.canvas.componentSelected.connect(self._select_component)
        self.canvas.componentTransformed.connect(self._on_component_transformed)
        self.canvas.codeRegionAdded.connect(self._on_code_region_added)
        self.canvas.codeRegionSelected.connect(self._select_code_region)
        self.canvas.codeRegionTransformed.connect(self._on_code_region_transformed)

        # ---- Golden image controls ----
        self.image_count_label = QLabel("Reference images loaded: 0")
        self.template_name_edit = QLineEdit()
        self.module_threshold_spin = QDoubleSpinBox()
        self.module_threshold_spin.setRange(0, 100)
        self.module_threshold_spin.setValue(90.0)

        add_images_btn = QPushButton("Add Image(s)")
        clear_images_btn = QPushButton("Clear Images")
        build_btn = QPushButton("Build Golden Image")
        load_template_btn = QPushButton("Load Existing Template...")
        save_btn = QPushButton("Save Master Template")
        add_images_btn.clicked.connect(self._add_references)
        clear_images_btn.clicked.connect(self._clear_references)
        build_btn.clicked.connect(self._build_golden_image)
        load_template_btn.clicked.connect(self._choose_template_to_load)
        save_btn.clicked.connect(self._save_template)

        image_form = QFormLayout()
        image_form.addRow("Template Name:", self.template_name_edit)
        image_form.addRow("Module Threshold (%):", self.module_threshold_spin)

        images_row = QHBoxLayout()
        images_row.addWidget(add_images_btn)
        images_row.addWidget(clear_images_btn)

        golden_group = QGroupBox("Golden Image (built here, or uploaded via the Output Image Path tab)")
        golden_layout = QVBoxLayout(golden_group)
        golden_layout.addWidget(self.image_count_label)
        golden_layout.addLayout(images_row)
        golden_layout.addWidget(build_btn)
        golden_layout.addWidget(load_template_btn)
        golden_layout.addLayout(image_form)

        # ---- Draw settings ----
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Draw", "Edit"])
        self.mode_combo.currentTextChanged.connect(self._on_mode_changed)

        self.annotation_type_combo = QComboBox()
        self.annotation_type_combo.addItems(["Component (Pass/Fail)", "Code Region (QR/Barcode/OCR)"])
        self.annotation_type_combo.currentIndexChanged.connect(
            lambda i: self.canvas.set_annotation_type("code_region" if i == 1 else "component")
        )

        self.shape_combo = QComboBox()
        self.shape_combo.addItems(["Rectangle", "Circle"])
        self.shape_combo.currentTextChanged.connect(
            lambda t: self.canvas.set_drawing_mode("circle" if t == "Circle" else "rect")
        )

        self.new_line_width_spin = QSpinBox()
        self.new_line_width_spin.setRange(1, 10)
        self.new_line_width_spin.setValue(2)
        self.new_line_width_spin.valueChanged.connect(self.canvas.set_line_width)

        self.new_font_size_spin = QSpinBox()
        self.new_font_size_spin.setRange(6, 36)
        self.new_font_size_spin.setValue(10)
        self.new_font_size_spin.valueChanged.connect(self.canvas.set_font_size)

        draw_form = QFormLayout()
        draw_form.addRow("Mode:", self.mode_combo)
        draw_form.addRow("Annotation Type:", self.annotation_type_combo)
        draw_form.addRow("Shape:", self.shape_combo)
        draw_form.addRow("New Box Thickness:", self.new_line_width_spin)
        draw_form.addRow("New Text Size (Components):", self.new_font_size_spin)

        draw_group = QGroupBox("Draw Settings (used when Mode = Draw)")
        draw_group_layout = QVBoxLayout(draw_group)
        draw_group_layout.addLayout(draw_form)
        draw_group_layout.addWidget(QLabel(
            "Green = Component (pass/fail). Orange = Code Region (naming only, optional).\n"
            "Click a shape in Edit mode to open its editor below."
        ))

        # ---- Component list ----
        self.component_list = QListWidget()
        self.component_list.itemClicked.connect(self._on_component_list_clicked)

        # ---- Edit Selected Component (hidden until something is selected) ----
        self.edit_name_edit = QLineEdit()
        self.edit_threshold_spin = QDoubleSpinBox(); self.edit_threshold_spin.setRange(0, 100)
        self.edit_x_spin = QSpinBox(); self.edit_x_spin.setRange(0, 99999)
        self.edit_y_spin = QSpinBox(); self.edit_y_spin.setRange(0, 99999)
        self.edit_w_spin = QSpinBox(); self.edit_w_spin.setRange(1, 99999)
        self.edit_h_spin = QSpinBox(); self.edit_h_spin.setRange(1, 99999)
        self.edit_line_width_spin = QSpinBox(); self.edit_line_width_spin.setRange(1, 10)
        self.edit_font_size_spin = QSpinBox(); self.edit_font_size_spin.setRange(6, 36)

        apply_btn = QPushButton("Apply Changes")
        delete_btn = QPushButton("Delete Component")
        close_component_edit_btn = QPushButton("Close")
        apply_btn.clicked.connect(self._apply_component_edit)
        delete_btn.clicked.connect(self._delete_selected_component)
        close_component_edit_btn.clicked.connect(self._close_component_editor)

        edit_form = QFormLayout()
        edit_form.addRow("Name:", self.edit_name_edit)
        edit_form.addRow("Threshold (%):", self.edit_threshold_spin)
        edit_form.addRow("X:", self.edit_x_spin)
        edit_form.addRow("Y:", self.edit_y_spin)
        edit_form.addRow("Width:", self.edit_w_spin)
        edit_form.addRow("Height:", self.edit_h_spin)
        edit_form.addRow("Line Thickness:", self.edit_line_width_spin)
        edit_form.addRow("Text Size:", self.edit_font_size_spin)
        edit_btn_row = QHBoxLayout()
        edit_btn_row.addWidget(apply_btn); edit_btn_row.addWidget(delete_btn); edit_btn_row.addWidget(close_component_edit_btn)

        self.component_edit_group = QGroupBox("Edit Selected Component")
        component_edit_layout = QVBoxLayout(self.component_edit_group)
        component_edit_layout.addLayout(edit_form)
        component_edit_layout.addLayout(edit_btn_row)
        self.component_edit_group.setVisible(False)   # click-to-appear

        # ---- Code Region list ----
        self.code_region_list = QListWidget()
        self.code_region_list.itemClicked.connect(self._on_code_region_list_clicked)

        # ---- Edit Selected Code Region (hidden until something is selected) ----
        self.edit_code_type_combo = QComboBox()
        self.edit_code_type_combo.addItems(["QR", "Barcode", "OCR", "Auto"])
        self.edit_region_line_width_spin = QSpinBox(); self.edit_region_line_width_spin.setRange(1, 10)
        self.edit_region_enabled_check = QCheckBox("Use this Code Region for file naming")
        self.ocr_backend_status_label = QLabel()

        region_apply_btn = QPushButton("Apply Changes")
        region_delete_btn = QPushButton("Delete Code Region")
        close_region_edit_btn = QPushButton("Close")
        region_apply_btn.clicked.connect(self._apply_code_region_edit)
        region_delete_btn.clicked.connect(self._delete_selected_code_region)
        close_region_edit_btn.clicked.connect(self._close_region_editor)

        region_form = QFormLayout()
        region_form.addRow("Code Type:", self.edit_code_type_combo)
        region_form.addRow("Line Thickness:", self.edit_region_line_width_spin)
        region_form.addRow(self.edit_region_enabled_check)
        region_btn_row = QHBoxLayout()
        region_btn_row.addWidget(region_apply_btn); region_btn_row.addWidget(region_delete_btn); region_btn_row.addWidget(close_region_edit_btn)

        self.region_edit_group = QGroupBox("Edit Selected Code Region")
        region_edit_layout = QVBoxLayout(self.region_edit_group)
        region_edit_layout.addLayout(region_form)
        region_edit_layout.addWidget(self.ocr_backend_status_label)
        region_edit_layout.addLayout(region_btn_row)
        self.region_edit_group.setVisible(False)   # click-to-appear

        side_panel = QVBoxLayout()
        side_panel.addWidget(golden_group)
        side_panel.addWidget(draw_group)
        side_panel.addWidget(QLabel("Registered Components"))
        side_panel.addWidget(self.component_list)
        side_panel.addWidget(QLabel("Registered Code Regions"))
        side_panel.addWidget(self.code_region_list)
        side_panel.addWidget(self.component_edit_group)
        side_panel.addWidget(self.region_edit_group)
        side_panel.addWidget(save_btn)

        main_layout = QHBoxLayout(self)
        main_layout.addWidget(self.canvas, stretch=3)
        main_layout.addLayout(side_panel, stretch=1)

    def _on_mode_changed(self, text: str):
        self.canvas.set_mode("edit" if text == "Edit" else "draw")
        if text == "Draw":
            self._close_component_editor()
            self._close_region_editor()

    # ---- golden image: build from references ----
    def _add_references(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select PCB Reference Image(s)", "", "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)"
        )
        if paths:
            # Ignore images that were already added (same file picked twice).
            known = {os.path.abspath(p) for p in self.reference_paths}
            for p in paths:
                if os.path.abspath(p) not in known:
                    self.reference_paths.append(p)
                    known.add(os.path.abspath(p))
            self.image_count_label.setText(f"Reference images loaded: {len(self.reference_paths)}")

    def _clear_references(self):
        self.reference_paths = []
        self.image_count_label.setText("Reference images loaded: 0")

    def _build_golden_image(self):
        if not self.reference_paths:
            QMessageBox.warning(self, "No Images", "Add at least one reference image first.")
            return

        try:
            builder = GoldenImageBuilder(self.reference_paths)
            os.makedirs(self.settings.golden_image_dir, exist_ok=True)
            working_path = os.path.join(self.settings.golden_image_dir, self.WORKING_GOLDEN_NAME)
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                builder.save(working_path)
            finally:
                QApplication.restoreOverrideCursor()
        except (IOError, OSError, ValueError, cv2.error) as exc:
            QMessageBox.critical(self, "Golden Image Failed", f"Could not build the Golden Image:\n{exc}")
            return

        if len(self.reference_paths) < GoldenImageBuilder.RECOMMENDED_MIN_IMAGES:
            QMessageBox.information(
                self, "Golden Image Created",
                f"Golden Image created from {len(self.reference_paths)} image(s).\n"
                f"For best accuracy, at least {GoldenImageBuilder.RECOMMENDED_MIN_IMAGES} "
                f"reference images are recommended."
            )

        self._start_new_template(working_path)

    # ---- golden image: uploaded from Output Image Path tab ----
    def load_uploaded_golden_image(self, image_path: str) -> bool:
        ok = self._start_new_template(image_path)
        if ok:
            QMessageBox.information(self, "Golden Image Loaded",
                                    f"'{os.path.basename(image_path)}' loaded into the Training tab.")
        return ok

    def _start_new_template(self, golden_path: str) -> bool:
        if not self.canvas.load_image(golden_path):
            QMessageBox.critical(self, "Invalid Image", f"Could not open image:\n{golden_path}")
            return False
        name = self.template_name_edit.text().strip() or "UnnamedTemplate"
        self.current_template = MasterTemplate(
            template_name=name, golden_image_path=golden_path,
            module_similarity_threshold=self.module_threshold_spin.value(),
        )
        self._reset_selection_and_lists()
        return True

    def _reset_selection_and_lists(self):
        self._selected_component_id = None
        self._selected_region_id = None
        self._close_component_editor()
        self._close_region_editor()
        self._refresh_component_list()
        self._refresh_code_region_list()

    # ---- load a saved template for editing ----
    def _choose_template_to_load(self):
        names = self.template_manager.list_templates()
        if not names:
            QMessageBox.information(self, "No Templates", "No saved Master Templates were found.")
            return
        name, ok = QInputDialog.getItem(self, "Load Master Template", "Template:", names, 0, False)
        if ok and name:
            self.load_template(name)

    def load_template(self, name: str) -> bool:
        try:
            template = self.template_manager.load(name)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            QMessageBox.critical(self, "Load Failed", f"Could not load template '{name}':\n{exc}")
            return False
        if not self.canvas.load_image(template.golden_image_path):
            QMessageBox.critical(self, "Load Failed",
                                 f"Golden Image for '{name}' is missing:\n{template.golden_image_path}")
            return False
        self.current_template = template
        self.template_name_edit.setText(template.template_name)
        self.module_threshold_spin.setValue(template.module_similarity_threshold)
        for c in template.components:
            self.canvas.add_component_item(c.component_id, c.x, c.y, c.w, c.h, c.name,
                                           c.shape, c.line_width, c.font_size)
        for r in template.code_regions:
            self.canvas.add_code_region_item(r.region_id, r.x, r.y, r.w, r.h, r.code_type,
                                             r.shape, r.line_width)
        self._reset_selection_and_lists()
        return True

    # ---- components ----
    def _on_component_added(self, data: dict):
        if not self.current_template:
            self.canvas.remove_item(data["component_id"])
            QMessageBox.warning(self, "No Template", "Build or upload a Golden Image first.")
            return
        if self.current_template.has_component_named(data["name"]):
            # Names must be unique: they identify components in results and logs.
            self.canvas.remove_item(data["component_id"])
            QMessageBox.warning(self, "Duplicate Name",
                                f"A component named '{data['name']}' already exists. Please draw it again "
                                f"with a different name.")
            return
        self.current_template.add_component(ComponentAnnotation(**data))
        self._refresh_component_list()

    def _find_component(self, comp_id: str) -> ComponentAnnotation | None:
        if not self.current_template:
            return None
        return next((c for c in self.current_template.components if c.component_id == comp_id), None)

    def _select_component(self, comp_id: str):
        comp = self._find_component(comp_id)
        if not comp:
            return
        self._close_region_editor()
        self._selected_component_id = comp_id
        self.edit_name_edit.setText(comp.name)
        self.edit_threshold_spin.setValue(comp.similarity_threshold)
        self.edit_x_spin.setValue(comp.x)
        self.edit_y_spin.setValue(comp.y)
        self.edit_w_spin.setValue(comp.w)
        self.edit_h_spin.setValue(comp.h)
        self.edit_line_width_spin.setValue(comp.line_width)
        self.edit_font_size_spin.setValue(comp.font_size)
        self.component_edit_group.setVisible(True)

    def _close_component_editor(self):
        self._selected_component_id = None
        self.component_edit_group.setVisible(False)

    def _on_component_list_clicked(self, list_item: QListWidgetItem):
        comp_id = list_item.data(Qt.UserRole)
        if comp_id:
            self._select_component(comp_id)

    def _on_component_transformed(self, comp_id, new_x, new_y, new_w, new_h):
        comp = self._find_component(comp_id)
        if not comp:
            return
        comp.x, comp.y, comp.w, comp.h = new_x, new_y, new_w, new_h
        if self._selected_component_id == comp_id:
            self.edit_x_spin.setValue(new_x); self.edit_y_spin.setValue(new_y)
            self.edit_w_spin.setValue(new_w); self.edit_h_spin.setValue(new_h)
        self._refresh_component_list()

    def _apply_component_edit(self):
        if not self._selected_component_id:
            return
        comp = self._find_component(self._selected_component_id)
        if not comp:
            return
        new_name = self.edit_name_edit.text().strip() or comp.name
        if new_name != comp.name and self.current_template.has_component_named(new_name):
            QMessageBox.warning(self, "Duplicate Name", f"A component named '{new_name}' already exists.")
            return
        comp.name = new_name
        comp.similarity_threshold = self.edit_threshold_spin.value()
        comp.x = self.edit_x_spin.value(); comp.y = self.edit_y_spin.value()
        comp.w = self.edit_w_spin.value(); comp.h = self.edit_h_spin.value()
        comp.line_width = self.edit_line_width_spin.value()
        comp.font_size = self.edit_font_size_spin.value()
        self.canvas.update_component_item(
            comp.component_id, comp.x, comp.y, comp.w, comp.h, comp.name, comp.line_width, comp.font_size
        )
        self._refresh_component_list()

    def _delete_selected_component(self):
        if not self._selected_component_id or not self.current_template:
            return
        self.current_template.components = [
            c for c in self.current_template.components if c.component_id != self._selected_component_id
        ]
        self.canvas.remove_item(self._selected_component_id)
        self._close_component_editor()
        self._refresh_component_list()

    def _refresh_component_list(self):
        self.component_list.clear()
        if not self.current_template:
            return
        for c in self.current_template.components:
            item = QListWidgetItem(
                f"{c.name}  [{c.shape}]  ({c.w}x{c.h})  thresh={c.similarity_threshold:.1f}%  "
                f"thickness={c.line_width}  text={c.font_size}pt"
            )
            item.setData(Qt.UserRole, c.component_id)
            self.component_list.addItem(item)

    # ---- code regions ----
    def _on_code_region_added(self, data: dict):
        if not self.current_template:
            self.canvas.remove_item(data["region_id"])
            QMessageBox.warning(self, "No Template", "Build or upload a Golden Image first.")
            return
        self.current_template.add_code_region(CodeRegionAnnotation(**data))
        self._refresh_code_region_list()

    def _find_region(self, region_id: str) -> CodeRegionAnnotation | None:
        if not self.current_template:
            return None
        return next((r for r in self.current_template.code_regions if r.region_id == region_id), None)

    def _select_code_region(self, region_id: str):
        region = self._find_region(region_id)
        if not region:
            return
        self._close_component_editor()
        self._selected_region_id = region_id
        self.edit_code_type_combo.setCurrentText(region.code_type)
        self.edit_region_line_width_spin.setValue(region.line_width)
        self.edit_region_enabled_check.setChecked(region.enabled)
        self._refresh_ocr_backend_status()
        self.region_edit_group.setVisible(True)

    def _close_region_editor(self):
        self._selected_region_id = None
        self.region_edit_group.setVisible(False)

    def _on_code_region_list_clicked(self, list_item: QListWidgetItem):
        region_id = list_item.data(Qt.UserRole)
        if region_id:
            self._select_code_region(region_id)

    def _on_code_region_transformed(self, region_id, new_x, new_y, new_w, new_h):
        region = self._find_region(region_id)
        if not region:
            return
        region.x, region.y, region.w, region.h = new_x, new_y, new_w, new_h
        self._refresh_code_region_list()

    def _apply_code_region_edit(self):
        if not self._selected_region_id:
            return
        region = self._find_region(self._selected_region_id)
        if not region:
            return
        region.code_type = self.edit_code_type_combo.currentText()
        region.line_width = self.edit_region_line_width_spin.value()
        region.enabled = self.edit_region_enabled_check.isChecked()
        self.canvas.update_code_region_item(
            region.region_id, region.x, region.y, region.w, region.h, region.code_type, region.line_width
        )
        self._refresh_code_region_list()

    def _delete_selected_code_region(self):
        if not self._selected_region_id or not self.current_template:
            return
        self.current_template.code_regions = [
            r for r in self.current_template.code_regions if r.region_id != self._selected_region_id
        ]
        self.canvas.remove_item(self._selected_region_id)
        self._close_region_editor()
        self._refresh_code_region_list()

    def _refresh_code_region_list(self):
        self.code_region_list.clear()
        if not self.current_template:
            return
        for r in self.current_template.code_regions:
            status = "ON" if r.enabled else "off"
            item = QListWidgetItem(f"[{r.code_type}]  naming={status}  [{r.shape}]  ({r.w}x{r.h})  thickness={r.line_width}")
            item.setData(Qt.UserRole, r.region_id)
            self.code_region_list.addItem(item)

    def _refresh_ocr_backend_status(self):
        path = self.settings.tesseract_path
        if path and os.path.isfile(path):
            self.ocr_backend_status_label.setText(f"OCR backend: Tesseract ({path})")
            self.ocr_backend_status_label.setStyleSheet("color: #2e7d32;")
        else:
            self.ocr_backend_status_label.setText(
                "OCR backend: Tesseract path not set — automatically using EasyOCR instead.\n "
                "Set a Tesseract path in the Output Image Path tab if preferred."
            )
            self.ocr_backend_status_label.setStyleSheet("color: #e65100;")

    # ---- save ----
    def _save_template(self):
        if not self.current_template or not self.current_template.components:
            QMessageBox.warning(self, "Incomplete", "Add at least one component before saving.")
            return

        template_name = sanitize_template_name(self.template_name_edit.text())
        self.template_name_edit.setText(template_name)
        self.current_template.template_name = template_name
        self.current_template.module_similarity_threshold = self.module_threshold_spin.value()

        if self.template_manager.path_for(template_name).exists():
            answer = QMessageBox.question(
                self, "Overwrite Template?",
                f"A Master Template named '{template_name}' already exists. Overwrite it?"
            )
            if answer != QMessageBox.Yes:
                return

        os.makedirs(self.settings.golden_image_dir, exist_ok=True)
        default_path = os.path.join(self.settings.golden_image_dir, f"{template_name}.png")
        golden_save_path, _ = QFileDialog.getSaveFileName(
            self, "Save Golden Image As", default_path,
            "PNG Image (*.png);;JPEG Image (*.jpg *.jpeg);;Bitmap (*.bmp)"
        )
        if not golden_save_path:
            QMessageBox.information(self, "Cancelled", "Master Template was not saved (no Golden Image location chosen).")
            return
        if not Path(golden_save_path).suffix:
            golden_save_path += ".png"

        try:
            self._store_golden_image(self.current_template.golden_image_path, golden_save_path)
            self.current_template.golden_image_path = golden_save_path
            path = self.template_manager.save(self.current_template)
        except (IOError, OSError) as exc:
            QMessageBox.critical(self, "Save Failed", f"Could not save the Master Template:\n{exc}")
            return
        QMessageBox.information(self, "Saved", f"Master Template saved to {path}\nGolden Image saved to {golden_save_path}")
        self.templateSaved.emit(self.current_template.template_name)

    @staticmethod
    def _store_golden_image(src: str, dst: str) -> None:
        """Copies the golden image to its chosen location. If the file type
        changes (e.g. working PNG saved as .jpg), the image is re-encoded
        instead of byte-copied, so the extension always matches the content."""
        if os.path.abspath(src) == os.path.abspath(dst):
            return
        os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
        if Path(src).suffix.lower() == Path(dst).suffix.lower():
            shutil.copyfile(src, dst)
            return
        image = read_image(src, cv2.IMREAD_UNCHANGED)
        if image is None:
            raise IOError(f"Cannot read golden image {src}")
        write_image(dst, image)
