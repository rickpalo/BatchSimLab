"""TODO-58 module #7 (the LAST extraction) regression tests: the N-panel + the
three UILists + the ``_*_ui`` draw helpers live in ``BatchSimLab.ui``.

The seventh extraction moved everything that DRAWS the panel — ``SMOKE_PT_panel``,
``SMOKE_UL_value_list`` / ``SMOKE_UL_job_log`` / ``SMOKE_UL_velocity_list``, the
``_*_ui`` helpers — plus the two UI-only pure helpers the panel consumes (the
noise up-res ceiling validators ``noise_grid_edge`` / ``noise_grid_exceeds_ceiling``
+ ``_NOISE_UPRES_EDGE_WARN``, and ``_VELOCITY_FORMAT_HINT``) into ``BatchSimLab.ui``,
re-imported back into the package ``__init__`` so the ``classes = [...]``
registration list (which names the panel + the three UILists) and the
``from BatchSimLab import …`` test entry points resolve unchanged.

DELIBERATELY LEFT in ``__init__`` (registration + addon metadata): the
``classes`` list + ``register()`` / ``unregister()``, ``SmokeSimLabPreferences``
(whose ``bl_idname = __name__`` must resolve to the package name), the load
handlers (``_reset_on_load`` / ``_restore_job_log_on_load`` / ``_default_output_path``),
and the ``ADDON_VERSION`` / ``DOCS_URL`` constants the panel reaches via a
function-local deferred import.  This test pins that boundary.
"""
import importlib
import inspect
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

# Re-exported from the package as the SAME object (classes + draw helpers +
# UI-only pure helpers/constants).
_UI_REEXPORTED = [
    "SMOKE_UL_value_list", "SMOKE_UL_job_log", "SMOKE_UL_velocity_list",
    "SMOKE_PT_panel",
    "_sub_param_ui", "_settings_ui", "_standalone_param_ui",
    "_gas_ui", "_noise_ui", "_fire_ui",
    "_emitter_sub_param_ui", "_emitter_velocity_ui", "_emitters_ui",
    "noise_grid_edge", "noise_grid_exceeds_ceiling", "_NOISE_UPRES_EDGE_WARN",
    "_VELOCITY_FORMAT_HINT",
]

# ADDON_VERSION is reached by the panel's draw() via `from . import ADDON_VERSION`
# at call time; it lives with the addon metadata in __init__, not ui.py.
_DEFERRED_TARGETS = ["ADDON_VERSION"]


@pytest.fixture(scope="module")
def pkg():
    return importlib.import_module("BatchSimLab")


@pytest.fixture(scope="module")
def ui():
    return importlib.import_module("BatchSimLab.ui")


def test_ui_is_a_submodule(ui):
    assert ui.__name__ == "BatchSimLab.ui"


def test_registration_and_metadata_stayed_in_init(ui):
    """register()/unregister(), the classes list, Preferences, the load handlers,
    and the addon-metadata constants belong to __init__; guard against any of them
    migrating into ui.py."""
    for stayed in (
        "register", "unregister", "classes",
        "SmokeSimLabPreferences",
        "_reset_on_load", "_restore_job_log_on_load", "_default_output_path",
        "ADDON_VERSION", "DOCS_URL", "bl_info",
    ):
        assert not hasattr(ui, stayed), f"{stayed} must stay in __init__, not ui.py"


def test_engine_state_not_a_module_global_here(ui):
    """The Job Log lists/dicts are engine-owned mutable state.  ui.py reads them
    via `from .engine import _job_log_rows, _job_statuses`, so they ARE ui module
    attributes — but they must be the SAME objects engine owns, never a second
    binding (verified below).  Pure-engine machinery must not have leaked in."""
    for state in ("_poll_batch_progress", "_poll_batch_progress_impl",
                  "_bt_set", "_estim", "_last_auto_index", "_auto_retry_count",
                  "_update_job_log_statuses"):
        assert not hasattr(ui, state), f"{state} (engine machinery) leaked into ui.py"


def test_job_log_state_is_the_engine_object(ui):
    """ui.draw_item reads _job_log_rows/_job_statuses; they must be the exact same
    objects engine mutates in place (a copy would silently go stale)."""
    engine = importlib.import_module("BatchSimLab.engine")
    assert ui._job_log_rows is engine._job_log_rows
    assert ui._job_statuses is engine._job_statuses


@pytest.mark.parametrize("name", _UI_REEXPORTED)
def test_name_defined_in_ui(ui, name):
    assert hasattr(ui, name), f"{name} must be defined in BatchSimLab.ui"


@pytest.mark.parametrize("name", _UI_REEXPORTED)
def test_name_reexported_from_package(pkg, name):
    assert hasattr(pkg, name), (
        f"{name} must remain importable from the BatchSimLab package "
        f"(re-export from ui in __init__)"
    )


@pytest.mark.parametrize("name", _UI_REEXPORTED)
def test_reexport_is_same_object(pkg, ui, name):
    assert getattr(pkg, name) is getattr(ui, name), (
        f"BatchSimLab.{name} and BatchSimLab.ui.{name} diverged — a duplicate "
        f"definition likely survived the extraction"
    )


@pytest.mark.parametrize("name", _DEFERRED_TARGETS)
def test_deferred_import_targets_reachable(pkg, name):
    """SMOKE_PT_panel.draw does `from . import ADDON_VERSION` at draw time; if it
    stopped being reachable the panel body would NameError (not caught by
    import-time tests — and exactly the BUG-015 failure shape)."""
    assert hasattr(pkg, name), (
        f"{name} must stay reachable from the BatchSimLab package for the "
        f"deferred import in SMOKE_PT_panel.draw"
    )


def test_panel_classes_in_registration_list(pkg):
    """The classes the registration list names must resolve to the ui.py objects."""
    for cls in ("SMOKE_UL_value_list", "SMOKE_UL_job_log", "SMOKE_UL_velocity_list",
                "SMOKE_PT_panel"):
        assert getattr(pkg, cls) in pkg.classes, f"{cls} missing from classes=[...]"


def test_panel_draw_uses_deferred_addon_version(ui):
    """Regression for BUG-015 shape: draw() must use the deferred ADDON_VERSION
    import, never bl_info (which Blender strips from an extension at runtime)."""
    src = inspect.getsource(ui.SMOKE_PT_panel.draw)
    assert "from . import ADDON_VERSION" in src
    assert "bl_info" not in "\n".join(
        ln for ln in src.splitlines() if not ln.lstrip().startswith("#")
    )


def test_noise_grid_helpers_behave(ui):
    """Sanity on the moved pure validators."""
    assert ui.noise_grid_edge(256, True, 2) == 512
    assert ui.noise_grid_edge(256, False, 2) == 0          # noise off → no grid
    assert ui.noise_grid_exceeds_ceiling(256, True, 3) is True   # 768 > 512
    assert ui.noise_grid_exceeds_ceiling(256, True, 2) is False  # 512 not > 512
