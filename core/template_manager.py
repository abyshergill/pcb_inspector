import json
import os
import re
from pathlib import Path
from typing import Optional

import config
from core.models import MasterTemplate

_UNSAFE_NAME_RE = re.compile(r"[^A-Za-z0-9 _\-.]")


def sanitize_template_name(name: str) -> str:
    """Turns a user-entered template name into a safe file stem: no path
    separators (no writing outside the templates folder), no characters
    Windows rejects, and never empty."""
    cleaned = _UNSAFE_NAME_RE.sub("_", (name or "").strip()).strip(" .")
    return cleaned[:100] or "UnnamedTemplate"


class MasterTemplateManager:
    """Persists MasterTemplate objects to/from disk as JSON."""

    def __init__(self, storage_dir: Optional[str] = None):
        self.storage_dir = Path(storage_dir or config.TEMPLATES_DIR)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, template_name: str) -> Path:
        return self.storage_dir / f"{sanitize_template_name(template_name)}.json"

    def save(self, template: MasterTemplate) -> Path:
        template.template_name = sanitize_template_name(template.template_name)
        # Store an absolute golden image path so the template still works
        # when the app is started from a different working directory.
        template.golden_image_path = os.path.abspath(template.golden_image_path)
        out_path = self.path_for(template.template_name)
        tmp_path = out_path.with_suffix(".json.tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(template.to_dict(), f, indent=2)
        os.replace(tmp_path, out_path)  # atomic: never leaves a half-written template
        return out_path

    def load(self, template_name: str) -> MasterTemplate:
        in_path = self.path_for(template_name)
        with open(in_path, "r", encoding="utf-8") as f:
            template = MasterTemplate.from_dict(json.load(f))
        golden = Path(template.golden_image_path)
        if not golden.is_absolute():
            # Legacy templates stored cwd-relative paths; try the project folder.
            candidate = config.BASE_DIR / golden
            if candidate.exists():
                template.golden_image_path = str(candidate)
        return template

    def list_templates(self) -> list[str]:
        """Template names, most recently saved first."""
        paths = sorted(self.storage_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        return [p.stem for p in paths]

    def latest_template(self) -> Optional[str]:
        names = self.list_templates()
        return names[0] if names else None
