import uuid
from PySide6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsRectItem, QGraphicsEllipseItem,
    QGraphicsSimpleTextItem, QGraphicsItem, QInputDialog, QLineEdit
)
from PySide6.QtGui import QPixmap, QPen, QBrush, QColor, QFont, QPainterPath
from PySide6.QtCore import Qt, QRectF, QPointF, Signal

COMPONENT_COLOR = "#00C853"   # green
CODE_REGION_COLOR = "#FF9800"  # orange

class ResizableShapeItem:
    """Shared behavior: fixed-but-editable text label, drag-to-resize
    corner handles shown whenever the item is selectable (Edit mode)."""

    HANDLE_SIZE = 8

    def _init_resizable(self, name: str, line_width: int, font_size: int, color: str):
        self.name = name
        self._resize_handle = None
        self.setPen(QPen(QColor(color), line_width))
        self.setBrush(QBrush(Qt.NoBrush))
        self.setAcceptHoverEvents(True)
        self.label = QGraphicsSimpleTextItem(name, self)
        self.label.setBrush(QBrush(QColor(color)))
        self._apply_font_size(font_size)
        self._update_label_pos()

    def _apply_font_size(self, font_size: int):
        self.label.setFont(QFont("Arial", font_size))

    def _update_label_pos(self):
        r = self.rect()
        offset = 10 + self.label.font().pointSize()
        self.label.setPos(r.x(), r.y() - offset)

    def _handle_rects(self):
        r = self.rect()
        s = self.HANDLE_SIZE
        return {
            "tl": QRectF(r.left() - s / 2, r.top() - s / 2, s, s),
            "tr": QRectF(r.right() - s / 2, r.top() - s / 2, s, s),
            "bl": QRectF(r.left() - s / 2, r.bottom() - s / 2, s, s),
            "br": QRectF(r.right() - s / 2, r.bottom() - s / 2, s, s),
        }

    def _handle_at(self, pos: QPointF):
        for name, rect in self._handle_rects().items():
            if rect.contains(pos):
                return name
        return None

    def _resizable_enabled(self) -> bool:
        return bool(self.flags() & QGraphicsItem.ItemIsSelectable)

    def boundingRect(self):
        base = super().boundingRect()
        pad = self.HANDLE_SIZE
        return base.adjusted(-pad, -pad, pad, pad)

    def shape(self):
        # The corner handles of an ellipse lie outside the ellipse itself, so
        # without this they could never be clicked and circles could not be
        # resized. Include them in the hit area while in Edit mode.
        path = QPainterPath(super().shape())
        if self._resizable_enabled():
            for rect in self._handle_rects().values():
                path.addRect(rect)
        return path

    def paint(self, painter, option, widget=None):
        super().paint(painter, option, widget)
        if self._resizable_enabled():
            painter.setBrush(QBrush(QColor("#2196F3")))
            painter.setPen(QPen(Qt.NoPen))
            for rect in self._handle_rects().values():
                painter.drawRect(rect)

    def mousePressEvent(self, event):
        if self._resizable_enabled():
            handle = self._handle_at(event.pos())
            if handle:
                self._resize_handle = handle
                event.accept()
                return
        self._resize_handle = None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resize_handle:
            r = self.rect()
            pos = event.pos()
            if self._resize_handle == "tl":
                new_rect = QRectF(pos, r.bottomRight())
            elif self._resize_handle == "tr":
                new_rect = QRectF(QPointF(r.left(), pos.y()), QPointF(pos.x(), r.bottom()))
            elif self._resize_handle == "bl":
                new_rect = QRectF(QPointF(pos.x(), r.top()), QPointF(r.right(), pos.y()))
            else:
                new_rect = QRectF(r.topLeft(), pos)
            new_rect = new_rect.normalized()
            if new_rect.width() > 10 and new_rect.height() > 10:
                self.prepareGeometryChange()
                self.setRect(new_rect)
                self._update_label_pos()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resize_handle:
            self._resize_handle = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

class LabeledRectItem(ResizableShapeItem, QGraphicsRectItem):
    def __init__(self, rect: QRectF, name: str, line_width: int = 2, font_size: int = 10, color: str = COMPONENT_COLOR):
        QGraphicsRectItem.__init__(self, rect)
        self._init_resizable(name, line_width, font_size, color)

class LabeledEllipseItem(ResizableShapeItem, QGraphicsEllipseItem):
    def __init__(self, rect: QRectF, name: str, line_width: int = 2, font_size: int = 10, color: str = COMPONENT_COLOR):
        QGraphicsEllipseItem.__init__(self, rect)
        self._init_resizable(name, line_width, font_size, color)

class AnnotationCanvas(QGraphicsView):
    """
    Draw mode: click-and-drag to draw a shape. Annotation Type decides
    what happens on release:
      - "component": prompts for name + acceptance threshold (pass/fail).
      - "code_region": prompts for code type (QR/Barcode/OCR/Auto) used
        purely for output file naming, not compared for pass/fail.

    Edit mode: click a shape to select/move it; drag corner handles to
    resize. Editing details are driven by the host widget's edit panels.
    """

    componentAdded = Signal(dict)
    codeRegionAdded = Signal(dict)
    componentSelected = Signal(str)
    componentTransformed = Signal(str, int, int, int, int)
    codeRegionSelected = Signal(str)
    codeRegionTransformed = Signal(str, int, int, int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pixmap_item = None
        self._start_point = None
        self._rubber_band_item = None
        self._edit_target = None

        self.mode = "draw"              # "draw" or "edit"
        self.drawing_mode = "rect"      # "rect" or "circle"
        self.annotation_type = "component"  # "component" or "code_region"
        self.line_width = 2
        self.font_size = 10

        self._items_by_id: dict[str, QGraphicsItem] = {}

    # ---- configuration ----
    def set_mode(self, mode: str) -> None:
        self.mode = mode
        is_edit = (mode == "edit")
        for item in self._items_by_id.values():
            self._apply_mode_flags(item)
            item.update()  # repaint so resize handles appear/disappear immediately

    def _apply_mode_flags(self, item) -> None:
        is_edit = (self.mode == "edit")
        item.prepareGeometryChange()
        item.setFlag(QGraphicsItem.ItemIsMovable, is_edit)
        item.setFlag(QGraphicsItem.ItemIsSelectable, is_edit)
        if not is_edit:
            item.setSelected(False)

    def set_drawing_mode(self, mode: str) -> None:
        self.drawing_mode = mode

    def set_annotation_type(self, annotation_type: str) -> None:
        self.annotation_type = annotation_type

    def set_line_width(self, width: int) -> None:
        self.line_width = width

    def set_font_size(self, size: int) -> None:
        self.font_size = size

    def load_image(self, image_path: str) -> bool:
        """Loads a new background image and clears all shapes. Returns False
        if the image could not be read."""
        self._scene.clear()
        self._items_by_id.clear()
        self._rubber_band_item = None
        self._edit_target = None
        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            self._pixmap_item = None
            return False
        self._pixmap_item = self._scene.addPixmap(pixmap)
        self._scene.setSceneRect(QRectF(pixmap.rect()))
        self.fitInView(self._pixmap_item, Qt.KeepAspectRatio)
        return True

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._pixmap_item is not None:
            self.fitInView(self._pixmap_item, Qt.KeepAspectRatio)

    def _image_rect(self) -> QRectF:
        return self._pixmap_item.boundingRect() if self._pixmap_item is not None else QRectF()

    def _clamp_to_image(self, rect: QRectF) -> QRectF:
        """Keeps drawn shapes inside the image, so their saved coordinates
        are never negative or beyond the image edge."""
        if self._pixmap_item is None:
            return rect
        return rect.intersected(self._image_rect())

    # ---- creating shape items (also used to show a loaded template) ----
    def add_component_item(self, comp_id: str, x: int, y: int, w: int, h: int, name: str,
                           shape: str = "rect", line_width: int = 2, font_size: int = 10):
        cls = LabeledEllipseItem if shape == "circle" else LabeledRectItem
        item = cls(QRectF(x, y, w, h), name, line_width, font_size, COMPONENT_COLOR)
        item.setData(0, comp_id)
        item.setData(1, "component")
        self._scene.addItem(item)
        self._items_by_id[comp_id] = item
        self._apply_mode_flags(item)
        return item

    def add_code_region_item(self, region_id: str, x: int, y: int, w: int, h: int, code_type: str,
                             shape: str = "rect", line_width: int = 2):
        cls = LabeledEllipseItem if shape == "circle" else LabeledRectItem
        item = cls(QRectF(x, y, w, h), f"CODE:{code_type}", line_width, 10, CODE_REGION_COLOR)
        item.setData(0, region_id)
        item.setData(1, "code_region")
        self._scene.addItem(item)
        self._items_by_id[region_id] = item
        self._apply_mode_flags(item)
        return item

    def has_item(self, item_id: str) -> bool:
        return item_id in self._items_by_id

    # ---- edit-mode helpers (called by the host widget) ----
    def update_component_item(self, comp_id: str, x: int, y: int, w: int, h: int,
                               name: str, line_width: int, font_size: int) -> None:
        item = self._items_by_id.get(comp_id)
        if item is None:
            return
        item.prepareGeometryChange()
        item.setPos(0, 0)
        item.setRect(QRectF(x, y, w, h))
        item.setPen(QPen(QColor(COMPONENT_COLOR), line_width))
        item.name = name
        item.label.setText(name)
        item._apply_font_size(font_size)
        item._update_label_pos()

    def update_code_region_item(self, region_id: str, x: int, y: int, w: int, h: int,
                                 code_type: str, line_width: int) -> None:
        item = self._items_by_id.get(region_id)
        if item is None:
            return
        item.prepareGeometryChange()
        item.setPos(0, 0)
        item.setRect(QRectF(x, y, w, h))
        item.setPen(QPen(QColor(CODE_REGION_COLOR), line_width))
        item.label.setText(f"CODE:{code_type}")
        item._update_label_pos()

    def remove_item(self, item_id: str) -> None:
        item = self._items_by_id.pop(item_id, None)
        if item is not None:
            if self._edit_target is item:
                self._edit_target = None
            self._scene.removeItem(item)

    # Old name kept for compatibility (it removes code regions too).
    remove_component_item = remove_item

    def _resolve_labeled_item(self, item):
        while item is not None and not isinstance(item, (LabeledRectItem, LabeledEllipseItem)):
            item = item.parentItem()
        return item

    # ---- mouse handling ----
    def mousePressEvent(self, event):
        if self.mode == "edit":
            # Remember which shape the drag started on: on release the cursor
            # may be over a different (overlapping) shape, or outside the one
            # that was resized, and that one must be the one committed.
            self._edit_target = self._resolve_labeled_item(self.itemAt(event.pos()))
            super().mousePressEvent(event)
            return
        if self._pixmap_item and event.button() == Qt.LeftButton:
            self._start_point = self.mapToScene(event.pos())
            if self.drawing_mode == "circle":
                self._rubber_band_item = QGraphicsEllipseItem(QRectF(self._start_point, self._start_point))
            else:
                self._rubber_band_item = QGraphicsRectItem(QRectF(self._start_point, self._start_point))
            self._rubber_band_item.setPen(QPen(QColor("#2196F3"), 1, Qt.DashLine))
            self._scene.addItem(self._rubber_band_item)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.mode == "edit":
            super().mouseMoveEvent(event)
            return
        if self._rubber_band_item:
            current = self.mapToScene(event.pos())
            rect = QRectF(self._start_point, current).normalized()
            self._rubber_band_item.setRect(rect)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.mode == "edit":
            super().mouseReleaseEvent(event)
            self._handle_edit_release(event)
            return

        if self._rubber_band_item:
            rect = self._clamp_to_image(self._rubber_band_item.rect())
            self._scene.removeItem(self._rubber_band_item)
            self._rubber_band_item = None

            if rect.width() > 5 and rect.height() > 5:
                if self.annotation_type == "code_region":
                    self._finish_code_region(rect)
                else:
                    self._finish_component(rect)
        super().mouseReleaseEvent(event)

    def _finish_component(self, rect: QRectF):
        name, ok = QInputDialog.getText(
            self, "Component Name", "Enter a unique name for this component:", QLineEdit.Normal, ""
        )
        if not (ok and name.strip()):
            return
        clean_name = name.strip()

        threshold, ok2 = QInputDialog.getDouble(
            self, "Acceptance Criteria", f"Acceptable similarity % for '{clean_name}':",
            95.0, 0.0, 100.0, 1
        )
        if not ok2:
            threshold = 95.0

        comp_id = str(uuid.uuid4())
        x, y, w, h = int(rect.x()), int(rect.y()), int(rect.width()), int(rect.height())
        self.add_component_item(comp_id, x, y, w, h, clean_name, self.drawing_mode,
                                self.line_width, self.font_size)

        self.componentAdded.emit({
            "component_id": comp_id, "name": clean_name,
            "x": x, "y": y, "w": w, "h": h,
            "similarity_threshold": threshold, "shape": self.drawing_mode,
            "line_width": self.line_width, "font_size": self.font_size,
        })

    def _finish_code_region(self, rect: QRectF):
        code_type, ok = QInputDialog.getItem(
            self, "Code Region Type",
            "What should be read from this marked area?",
            ["QR", "Barcode", "OCR", "Auto"], 0, False
        )
        if not ok:
            return

        region_id = str(uuid.uuid4())
        x, y, w, h = int(rect.x()), int(rect.y()), int(rect.width()), int(rect.height())
        self.add_code_region_item(region_id, x, y, w, h, code_type, self.drawing_mode, self.line_width)

        self.codeRegionAdded.emit({
            "region_id": region_id, "code_type": code_type,
            "x": x, "y": y, "w": w, "h": h,
            "shape": self.drawing_mode, "line_width": self.line_width,
        })

    def _handle_edit_release(self, event):
        target = self._edit_target or self._resolve_labeled_item(self.itemAt(event.pos()))
        self._edit_target = None
        if target is None or target.scene() is not self._scene:
            return
        item_id = target.data(0)
        item_type = target.data(1)
        if not item_id:
            return

        new_rect = QRectF(
            target.rect().x() + target.pos().x(),
            target.rect().y() + target.pos().y(),
            target.rect().width(), target.rect().height()
        )
        target.prepareGeometryChange()
        target.setRect(new_rect)
        target.setPos(0, 0)
        target._update_label_pos()

        x, y, w, h = int(new_rect.x()), int(new_rect.y()), int(new_rect.width()), int(new_rect.height())
        if item_type == "code_region":
            self.codeRegionSelected.emit(item_id)
            self.codeRegionTransformed.emit(item_id, x, y, w, h)
        else:
            self.componentSelected.emit(item_id)
            self.componentTransformed.emit(item_id, x, y, w, h)
