import json
from pathlib import Path
from core.models import MasterTemplate

class MasterTemplateManager:
    """Persists MasterTemplate objects to/from disk as JSON."""

    def __init__(self, storage_dir: str = "templates"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def save(self, template: MasterTemplate) -> Path:
        out_path = self.storage_dir / f"{template.template_name}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(template.to_dict(), f, indent=2)
        return out_path

    def load(self, template_name: str) -> MasterTemplate:
        in_path = self.storage_dir / f"{template_name}.json"
        with open(in_path, "r", encoding="utf-8") as f:
            return MasterTemplate.from_dict(json.load(f))

    def list_templates(self) -> list[str]:
        return [p.stem for p in self.storage_dir.glob("*.json")]
