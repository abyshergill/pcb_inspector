import json
import os
import time

from core.models import MasterTemplate, ComponentAnnotation, CodeRegionAnnotation
from core.template_manager import MasterTemplateManager, sanitize_template_name


def _template(golden="golden.png"):
    t = MasterTemplate("Board A", golden, 85.0)
    t.add_component(ComponentAnnotation("U1", 1, 2, 30, 40, similarity_threshold=90.0, shape="circle"))
    t.add_code_region(CodeRegionAnnotation("QR", 5, 6, 20, 20, enabled=False))
    return t


def test_roundtrip():
    t = _template()
    back = MasterTemplate.from_dict(t.to_dict())
    assert back == t


def test_unknown_keys_are_ignored():
    d = _template().to_dict()
    d["components"][0]["future_field"] = 1
    d["code_regions"][0]["other"] = "x"
    back = MasterTemplate.from_dict(d)
    assert back.components[0].name == "U1"


def test_has_component_named():
    t = _template()
    assert t.has_component_named("U1") and not t.has_component_named("U2")


def test_sanitize_template_name():
    assert sanitize_template_name("../../etc/passwd") == "_.._etc_passwd"
    assert "/" not in sanitize_template_name("a/b\\c")
    assert sanitize_template_name("   ") == "UnnamedTemplate"
    assert sanitize_template_name('bad:*?"<>|') == "bad_______"


def test_save_load_and_absolute_golden_path(tmp_path):
    mgr = MasterTemplateManager(str(tmp_path / "tpl"))
    path = mgr.save(_template("golden.png"))
    assert path.parent == tmp_path / "tpl"
    loaded = mgr.load("Board A")
    assert os.path.isabs(loaded.golden_image_path)
    assert loaded.components[0].shape == "circle"
    assert loaded.code_regions[0].enabled is False
    assert not list((tmp_path / "tpl").glob("*.tmp"))


def test_traversal_name_stays_in_folder(tmp_path):
    mgr = MasterTemplateManager(str(tmp_path / "tpl"))
    t = _template()
    t.template_name = "../escape"
    path = mgr.save(t)
    assert path.parent == tmp_path / "tpl"


def test_list_templates_newest_first(tmp_path):
    mgr = MasterTemplateManager(str(tmp_path / "tpl"))
    for name in ("old", "new"):
        t = _template()
        t.template_name = name
        mgr.save(t)
        time.sleep(0.02)
    os.utime(mgr.path_for("old"), (time.time() - 100, time.time() - 100))
    assert mgr.list_templates() == ["new", "old"]
    assert mgr.latest_template() == "new"


def test_default_storage_uses_config(tmp_path):
    import config
    mgr = MasterTemplateManager()
    assert str(mgr.storage_dir) == config.TEMPLATES_DIR
    assert str(tmp_path) in config.TEMPLATES_DIR


def test_saved_file_is_valid_json(tmp_path):
    mgr = MasterTemplateManager(str(tmp_path))
    path = mgr.save(_template())
    assert json.loads(path.read_text())["template_name"] == "Board A"
