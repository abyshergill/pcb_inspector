from dataclasses import dataclass, field, fields, asdict
from typing import List
import uuid


def _known_fields(cls, d: dict) -> dict:
    """Drops keys a dataclass doesn't know about, so templates saved by a
    newer/older version of the app still load instead of raising TypeError."""
    names = {f.name for f in fields(cls)}
    return {k: v for k, v in d.items() if k in names}


@dataclass
class ComponentAnnotation:
    """Spatial + textual metadata for a single critical component."""
    name: str
    x: int
    y: int
    w: int
    h: int
    component_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    similarity_threshold: float = 95.0
    shape: str = "rect"
    line_width: int = 2
    font_size: int = 10

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "ComponentAnnotation":
        return ComponentAnnotation(**_known_fields(ComponentAnnotation, d))


@dataclass
class CodeRegionAnnotation:
    """
    A marked area used to locate a QR code / Barcode / OCR serial number
    for output file naming. Not compared for pass/fail like a component.
    enabled: whether this region should actually be used to derive the
    saved filename — lets users mark a region but keep timestamp naming
    active until they choose to switch it on (fully optional, per region).
    """
    code_type: str
    x: int
    y: int
    w: int
    h: int
    region_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    shape: str = "rect"
    line_width: int = 2
    enabled: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "CodeRegionAnnotation":
        return CodeRegionAnnotation(**_known_fields(CodeRegionAnnotation, d))


@dataclass
class MasterTemplate:
    """The saved Golden Image baseline + all component and code-region annotations."""
    template_name: str
    golden_image_path: str
    module_similarity_threshold: float = 90.0
    components: List[ComponentAnnotation] = field(default_factory=list)
    code_regions: List[CodeRegionAnnotation] = field(default_factory=list)

    def add_component(self, component: ComponentAnnotation) -> None:
        self.components.append(component)

    def add_code_region(self, region: CodeRegionAnnotation) -> None:
        self.code_regions.append(region)

    def has_component_named(self, name: str) -> bool:
        return any(c.name == name for c in self.components)

    def to_dict(self) -> dict:
        return {
            "template_name": self.template_name,
            "golden_image_path": self.golden_image_path,
            "module_similarity_threshold": self.module_similarity_threshold,
            "components": [c.to_dict() for c in self.components],
            "code_regions": [r.to_dict() for r in self.code_regions],
        }

    @staticmethod
    def from_dict(d: dict) -> "MasterTemplate":
        comps = [ComponentAnnotation.from_dict(c) for c in d.get("components", [])]
        regions = [CodeRegionAnnotation.from_dict(r) for r in d.get("code_regions", [])]
        return MasterTemplate(
            template_name=d["template_name"],
            golden_image_path=d["golden_image_path"],
            module_similarity_threshold=d.get("module_similarity_threshold", 90.0),
            components=comps,
            code_regions=regions,
        )
