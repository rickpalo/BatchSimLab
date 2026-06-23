"""
BatchSimLab/ui.py
=================
TODO-58 module #7 (the final extraction): the N-panel and everything that draws
it -- the main panel ``SMOKE_PT_panel``, the three ``SMOKE_UL_*`` UILists, and
the ``_*_ui`` draw helpers -- plus the two UI-only pure helpers the panel
consumes (the noise up-res bake-ceiling validators and the velocity entry-format
hint).

Imports are one-way (no cycles): the data/logic this module draws comes from the
leaf modules -- ``jobgen`` (job preview + velocity parse), ``settings_io``
(preset dirty check), ``operators`` (``_batch_ready``) and ``engine``
(``_batch_is_running`` plus the in-memory Job Log state ``_job_log_rows`` /
``_job_statuses``, which are mutated in place and never rebound -- so importing
the references here is safe).

``ADDON_VERSION`` lives with the addon metadata in ``__init__`` and is pulled in
with a function-local deferred import inside ``draw()`` (the same pattern engine
uses) to avoid a ui -> __init__ -> ui import cycle.  ``SmokeSimLabPreferences``
and the load handlers + ``register()`` stay in ``__init__``.
"""
import bpy
import os
import re

from .jobgen import _parse_velocity_vector, generate_jobs
from .settings_io import _is_settings_dirty
from .operators import _batch_ready
from .engine import _batch_is_running, _job_log_rows, _job_statuses


# v0.9.0 TODO-55: emitter Initial Velocity is swept as a list of "x, y, z"
# vectors.  The velocity-text helpers (_VELOCITY_DEFAULT / _parse_velocity_vector
# / _format_velocity_vector) now live in jobgen.py and are re-imported above so
# the UI and job generation share one definition; only this UI-only entry-format
# hint stays here.
_VELOCITY_FORMAT_HINT = "x, y, z  (e.g. 0, 0, 1)"


# ---------------------------------------------------------------------------
# Noise (up-res) bake ceiling
# ---------------------------------------------------------------------------
# The noise pass bakes a separate up-resolution grid whose edge length is
# (domain resolution × noise up-res factor).  At high effective resolutions
# Mantaflow's noise bake has been observed to either crash with an
# EXCEPTION_ACCESS_VIOLATION in tbbmalloc.dll or hang at "Baking 500 of 500"
# (the data pass finishes, the noise pass never returns).  Observed on a
# 128 GB / i9-13900 machine, Blender 5.1.1:
#   • 128×3 = 384³  — fine (many jobs completed)
#   • 256×2 = 512³  — fine
#   • 256×3 = 768³  — crashed (tbbmalloc) until re-exported + retried
#   • 256×4 = 1024³ — hung, killed by the launcher's stale-log watchdog
# It is NOT a hard limit on THIS hardware: every config eventually completed
# after re-export and restart, so callers warn the user rather than block.
# BUG-023 (2026-06-22): on a second machine the same 256×2 = 512³ case crashed
# on every one of 12+ attempts over 31h, never completing — the threshold is
# hardware-dependent, not a universal constant (exact mechanism unconfirmed;
# the dev-machine RAM stayed ~40 GB even at 768³/1024³, so simple memory
# exhaustion doesn't obviously explain why 512³ differs on other hardware).
# The edge threshold below sits just above the dev-machine's known-good 512³
# case so it flags only the flaky zone there; it will under-warn on weaker
# hardware until/unless this becomes per-machine-configurable.
_NOISE_UPRES_EDGE_WARN = 512   # warn when (resolution × noise_upres) exceeds this


def noise_grid_edge(resolution, use_noise, noise_upres):
    """Effective edge length of the noise up-res grid = resolution × up-res factor.

    Returns 0 when noise is disabled, since no separate noise grid is baked then.
    """
    if not use_noise:
        return 0
    return int(resolution) * int(noise_upres)


def noise_grid_exceeds_ceiling(resolution, use_noise, noise_upres):
    """True when the noise up-res grid is large enough to risk a crash or hang.

    See _NOISE_UPRES_EDGE_WARN for the empirical basis.  This is advisory only —
    the bake may still succeed — so the UI warns and lets the user continue.
    """
    return noise_grid_edge(resolution, use_noise, noise_upres) > _NOISE_UPRES_EDGE_WARN


class SMOKE_UL_value_list(bpy.types.UIList):
    """
    Custom UIList: checkbox on the left marks items for deletion; the float
    field on the right is the editable value.  Press the - button to remove
    all checked items (or the highlighted item if none are checked).
    """
    def draw_item(self, context, layout, data, item, icon,
                  active_data, active_propname):
        row = layout.row(align=True)
        row.prop(item, "marked", text="")
        row.prop(item, "value", text="", emboss=True)


class SMOKE_UL_job_log(bpy.types.UIList):
    """Job Log list — one row per exported job, colour-coded by status."""

    # Icons that work reliably across Blender 4.x and 5.x.
    # SEQUENCE_COLOR_XX icons are unavailable in Blender 5.1.1 and cause
    # silent row blanking, so they have been replaced with stable alternatives.
    _STATUS_ICONS = {
        'NOT_STARTED': 'RADIOBUT_OFF',
        'IN_PROGRESS': 'PLAY',           # active during bake phase
        'BAKED':       'CHECKBOX_HLT',   # bake done, render pending (two-phase)
        'RENDERING':   'RENDER_ANIMATION',  # active during render phase
        'RETRYING':    'FILE_REFRESH',
        'COMPLETE':    'CHECKMARK',
        'FAILED':      'CANCEL',
        'CRASHED':     'ERROR',
    }

    # Unicode prefix prepended to the job name for a second colour-free status
    # indicator that is visible even when icons fail to render.
    _STATUS_PREFIX = {
        'NOT_STARTED': '',
        'IN_PROGRESS': '▶ ',   # ▶  active in bake phase
        'BAKED':       '◐ ',   # ◐  bake done, awaiting render pass
        'RENDERING':   '◉ ',   # ◉  active in render phase
        'RETRYING':    '↻ ',   # ↻
        'COMPLETE':    '✓ ',   # ✓
        'FAILED':      '✗ ',   # ✗
        'CRASHED':     '⚠ ',   # ⚠
    }

    def draw_item(self, context, layout, data, item, icon,
                  active_data, active_propname, index=0, _flt_flag=0):
        if self.layout_type not in {'DEFAULT', 'COMPACT'}:
            return
        # Blender passes `index` — the item's position in the displayed list.
        # Since we apply no filtering, this equals the collection index and maps
        # directly to _job_log_rows.  No RNA property reads needed at all.
        # _flt_flag=0 accepts Blender 5.x passing it as a positional argument.
        if index >= len(_job_log_rows):
            return
        job_number, job_name = _job_log_rows[index]
        status = _job_statuses.get(job_number, 'NOT_STARTED')
        status_icon   = self._STATUS_ICONS.get(status, 'NONE')
        status_prefix = self._STATUS_PREFIX.get(status, '')
        # Alert tint (red background) for terminal error states.
        if status in ('FAILED', 'CRASHED'):
            layout.alert = True
        split = layout.split(factor=0.10, align=True)
        try:
            split.label(icon=status_icon, text="")
        except Exception:
            split.label(icon='NONE', text="")
        inner = split.split(factor=0.22, align=True)
        inner.label(text=str(job_number))
        inner.label(text=status_prefix + job_name)

    def draw_filter(self, context, layout):
        pass  # suppress the filter / sort bar


class SMOKE_UL_velocity_list(bpy.types.UIList):
    """Initial-Velocity vectors: checkbox marks a row for deletion; the text
    field is the editable "x, y, z" value (tinted red when it can't be parsed)."""
    def draw_item(self, context, layout, data, item, icon,
                  active_data, active_propname):
        row = layout.row(align=True)
        row.prop(item, "marked", text="")
        if _parse_velocity_vector(item.text) is None:
            row.alert = True   # malformed vector — visible cue to fix it
        row.prop(item, "text", text="", emboss=True)


# Four major sub-tasks: Setup, Baking, Animation, Still
# Each row: (log_keyword, bar-3a label, completed_subtasks_when_detected)
# completed_subtasks = number of major sub-tasks DONE when this keyword first appears.
#
# v0.5.5: two keywords updated to match the actual worker log output —
#   * "Baking..." → "Baking (" — v0.5.0 changed the worker's bake-start log
#     line to "Baking (MODULAR resume — bake_data)..." or
#     "Baking (MODULAR full — bake_data)..."; neither contains the literal
#     substring "Baking..." so the stage never advanced.  Result: FULL bakes
#     were stuck on "Clearing cache" (the previous match) for the whole bake.
#   * "Use Existing Cache enabled" → "Decision : SKIP BAKE" — the worker has
#     never logged the former (looks like an artifact from an older addon
#     version); SKIP BAKE jobs were stuck on "Starting" because no later
#     keyword matched.  The Decision line is reliably logged at the moment
#     the worker picks SKIP BAKE.
def _sub_param_ui(box, s, name, label):
    """
    Draw range/list controls for a sub-parameter inside an existing box.

    Used for Gas sub-params (vorticity, alpha, beta) and Noise sub-params
    where the outer collapsible box already exists and we only need to draw
    the Value/Range/List controls.

    Parameters
    ----------
    box   : bpy UILayout — the enclosing box to draw into
    s     : SmokeSettings
    name  : str — base parameter name, e.g. "vorticity"
    label : str — human-readable label shown above the controls
    """
    box.separator()
    box.label(text=f"{label}:")

    row = box.row()
    row.prop(s, f"{name}_use_range", text="Range", toggle=True)
    row.prop(s, f"{name}_use_list",  text="List",  toggle=True)

    if getattr(s, f"{name}_use_range"):
        box.prop(s, f"{name}_begin", text="Begin")
        box.prop(s, f"{name}_end",   text="End")
        box.prop(s, f"{name}_step",  text="Step")
    elif getattr(s, f"{name}_use_list"):
        row = box.row()
        row.template_list("SMOKE_UL_value_list", f"{name}_list",
                          s, f"{name}_list", s, f"{name}_index")
        col = row.column(align=True)
        col.operator("smoke.add_value",    text="", icon='ADD').param    = name
        col.operator("smoke.remove_value", text="", icon='REMOVE').param = name
    else:
        box.prop(s, f"{name}_begin", text="Value")


def _settings_ui(layout, s):
    """Draw the preset save/load row at the top of Simulation Parameters."""
    row = layout.row(align=True)
    row.prop(s, "settings_file_enum", text="")
    if _is_settings_dirty(s):
        row.label(text="*")
    row.operator("smoke.save_settings", text="", icon='FILE_TICK')
    row.operator("smoke.load_settings", text="", icon='FILE_FOLDER')
    if s.settings_file_path:
        stem = os.path.splitext(os.path.basename(s.settings_file_path))[0]
        layout.label(text=f"Loaded: {stem}", icon='CHECKMARK')


def _standalone_param_ui(layout, s, name, label,
                         show_prop, enable_prop=None, extra_props=None):
    """
    Draw a standalone collapsible parameter section with its own box.

    Used for Resolution and Dissolve which are top-level sections rather
    than sub-params inside a group box.

    Parameters
    ----------
    layout      : bpy UILayout
    s           : SmokeSettings
    name        : str — base parameter name, e.g. "resolution"
    label       : str — section header label
    show_prop   : str — name of the BoolProperty controlling collapse
    enable_prop : str or None — if set, draws an enable checkbox in the header
    extra_props : list of items drawn before the value controls.  Each item
                  may be either:
                    • a (prop_name, label) tuple → drawn on its own row, OR
                    • a list of such tuples → drawn together on ONE row
                                              (v0.7.0 TODO-45 pairing).
    """
    box = layout.box()
    row = box.row()
    row.prop(s, show_prop,
             icon='TRIA_DOWN' if getattr(s, show_prop) else 'TRIA_RIGHT',
             emboss=False, text="")
    if enable_prop:
        row.prop(s, enable_prop, text="")
    row.label(text=label)

    if not getattr(s, show_prop):
        return box
    if enable_prop and not getattr(s, enable_prop):
        return box

    if extra_props:
        for item in extra_props:
            if isinstance(item, list):
                # Same-row pairing: draw all tuples in one row, equal-split.
                shared = box.row(align=True)
                for prop_name, prop_label in item:
                    shared.prop(s, prop_name, text=prop_label)
            else:
                prop_name, prop_label = item
                box.prop(s, prop_name, text=prop_label)

    row = box.row()
    row.prop(s, f"{name}_use_range", text="Range", toggle=True)
    row.prop(s, f"{name}_use_list",  text="List",  toggle=True)

    if getattr(s, f"{name}_use_range"):
        box.prop(s, f"{name}_begin", text="Begin")
        box.prop(s, f"{name}_end",   text="End")
        box.prop(s, f"{name}_step",  text="Step")
    elif getattr(s, f"{name}_use_list"):
        row = box.row()
        row.template_list("SMOKE_UL_value_list", f"{name}_list",
                          s, f"{name}_list", s, f"{name}_index")
        col = row.column(align=True)
        col.operator("smoke.add_value",    text="", icon='ADD').param    = name
        col.operator("smoke.remove_value", text="", icon='REMOVE').param = name
    else:
        box.prop(s, f"{name}_begin", text="Value")
    return box


def _gas_ui(layout, s):
    """
    Draw the Gas Parameters collapsible section.

    Contains three sub-parameters: Vorticity, Buoyancy Density (alpha),
    Buoyancy Heat (beta).  All share the show_gas collapse toggle.
    """
    box = layout.box()
    row = box.row()
    row.prop(s, "show_gas",
             icon='TRIA_DOWN' if s.show_gas else 'TRIA_RIGHT',
             emboss=False, text="")
    row.label(text="Gas Parameters")

    if not s.show_gas:
        return

    # v0.6.0 TODO-37: order matches Blender's native Fluid Domain panel
    # (Buoyancy Density → Heat → Vorticity).  Underlying property names
    # (vorticity / alpha / beta), job-dict serialisation order, CSV column
    # order, and make_name() output are all unaffected — purely visual.
    _sub_param_ui(box, s, "alpha",     "Buoyancy Density")
    _sub_param_ui(box, s, "beta",      "Buoyancy Heat")
    _sub_param_ui(box, s, "vorticity", "Vorticity")


def _noise_ui(layout, s):
    """
    Draw the Noise collapsible section with enable checkbox in the header.

    Contains three sub-parameters: Scale (noise_upres), Strength, Position
    Scale.  The entire section is gated on use_noise.
    """
    box = layout.box()
    row = box.row()
    row.prop(s, "show_noise",
             icon='TRIA_DOWN' if s.show_noise else 'TRIA_RIGHT',
             emboss=False, text="")
    row.prop(s, "use_noise", text="")   # enable checkbox
    row.label(text="Noise")

    if not s.show_noise or not s.use_noise:
        return

    box.prop(s, "iterate_noise_both", text="Iterate Both On and Off")
    _sub_param_ui(box, s, "noise_upres",         "Scale")
    _sub_param_ui(box, s, "noise_strength",      "Strength")
    _sub_param_ui(box, s, "noise_spatial_scale", "Position Scale")


def _fire_ui(layout, s):
    """
    Draw the Fire Parameters collapsible section with enable checkbox in
    the header.  Parallel to _noise_ui.

    v0.7.0 TODO-42.  Contains five sub-parameters: Reaction Speed
    (burning_rate), Flames Smoke, Vorticity (separate from gas vorticity!),
    Temp Max, Ignition Temp.  When use_fire is unchecked the addon leaves
    the .blend's existing fire settings alone (same model as use_noise).
    """
    box = layout.box()
    row = box.row()
    row.prop(s, "show_fire",
             icon='TRIA_DOWN' if s.show_fire else 'TRIA_RIGHT',
             emboss=False, text="")
    row.prop(s, "use_fire", text="")   # enable checkbox
    row.label(text="Fire Parameters")

    if not s.show_fire or not s.use_fire:
        return

    _sub_param_ui(box, s, "burning_rate",    "Reaction Speed")
    _sub_param_ui(box, s, "flame_smoke",     "Flames Smoke")
    _sub_param_ui(box, s, "flame_vorticity", "Vorticity")
    _sub_param_ui(box, s, "flame_max_temp",  "Temp Max")
    _sub_param_ui(box, s, "flame_ignition",  "Ignition Temp")


def _emitter_sub_param_ui(box, em, ei, name, label):
    """Per-emitter analogue of _sub_param_ui — data block is the EmitterSettings
    element `em`; add/remove ops carry the emitter index `ei` and `param`."""
    box.separator()
    box.label(text=f"{label}:")

    row = box.row()
    row.prop(em, f"{name}_use_range", text="Range", toggle=True)
    row.prop(em, f"{name}_use_list",  text="List",  toggle=True)

    if getattr(em, f"{name}_use_range"):
        box.prop(em, f"{name}_begin", text="Begin")
        box.prop(em, f"{name}_end",   text="End")
        box.prop(em, f"{name}_step",  text="Step")
    elif getattr(em, f"{name}_use_list"):
        row = box.row()
        # Unique list-id per emitter+param so Blender doesn't share UI state.
        row.template_list("SMOKE_UL_value_list", f"em{ei}_{name}",
                          em, f"{name}_list", em, f"{name}_index")
        col = row.column(align=True)
        op = col.operator("smoke.add_emitter_value", text="", icon='ADD')
        op.emitter_index, op.param = ei, name
        op = col.operator("smoke.remove_emitter_value", text="", icon='REMOVE')
        op.emitter_index, op.param = ei, name
    else:
        box.prop(em, f"{name}_begin", text="Value")


def _emitter_velocity_ui(box, em, ei):
    """Draw the Initial Velocity block: the master toggle, then (when on) the
    Source / Normal scalars and the list of Initial X/Y/Z vectors."""
    box.separator()
    box.prop(em, "use_initial_velocity", text="Initial Velocity")
    if not em.use_initial_velocity:
        return
    _emitter_sub_param_ui(box, em, ei, "velocity_factor", "Source")
    _emitter_sub_param_ui(box, em, ei, "velocity_normal", "Normal")
    box.separator()
    box.label(text="Initial X/Y/Z vectors:")
    box.label(text=_VELOCITY_FORMAT_HINT, icon='INFO')
    row = box.row()
    row.template_list("SMOKE_UL_velocity_list", f"em{ei}_velocity",
                      em, "velocity_list", em, "velocity_index")
    col = row.column(align=True)
    col.operator("smoke.add_emitter_velocity", text="", icon='ADD').emitter_index = ei
    col.operator("smoke.remove_emitter_velocity", text="", icon='REMOVE').emitter_index = ei


def _emitters_ui(layout, s):
    """Draw the Emitters collapsible section — one sub-box per discovered
    emitter (default collapsed), each exposing its iterable flow params.

    v0.9.0 TODO-55.  Single-domain addon: emitters are the FLOW objects found
    inside the selected domain (Refresh icon re-scans)."""
    box = layout.box()
    row = box.row()
    row.prop(s, "show_emitters",
             icon='TRIA_DOWN' if s.show_emitters else 'TRIA_RIGHT',
             emboss=False, text="")
    row.label(text="Emitters")
    row.operator("smoke.refresh_emitters", text="", icon='FILE_REFRESH')

    if not s.show_emitters:
        return
    if not s.domain_obj:
        box.label(text="Select a domain to list its emitters.", icon='INFO')
        return
    if len(s.emitters) == 0:
        box.label(text="No emitters found inside the domain.", icon='INFO')
        box.label(text="Add flow objects, then click the refresh icon.")
        return

    for ei, em in enumerate(s.emitters):
        ebox = box.box()
        hrow = ebox.row()
        hrow.prop(em, "show",
                  icon='TRIA_DOWN' if em.show else 'TRIA_RIGHT',
                  emboss=False, text="")
        hrow.label(text=em.name, icon='OBJECT_DATA')
        if not em.show:
            continue
        _emitter_sub_param_ui(ebox, em, ei, "temperature",      "Initial Temperature")
        _emitter_sub_param_ui(ebox, em, ei, "density",          "Density")
        _emitter_sub_param_ui(ebox, em, ei, "surface_distance", "Surface Emission")
        _emitter_sub_param_ui(ebox, em, ei, "volume_density",   "Volume Emission")
        _emitter_velocity_ui(ebox, em, ei)


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------

class SMOKE_PT_panel(bpy.types.Panel):
    """
    Main BatchSimLab panel in the 3D Viewport N-panel (Sidebar → Batch Sim Lab tab).

    Layout order:
      • Header row with title and documentation link
      • Domain object + output path
      • Resolution section
      • Gas Parameters section (Vorticity, Buoyancy Density, Heat)
      • Dissolve section
      • Noise section
      • Text Objects section
      • Iteration mode selector
      • Render engine selector
      • Export Batch button + status
    """

    bl_label       = "Batch Sim Lab"
    bl_idname      = "SMOKE_PT_panel"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = 'BatchLab'

    def draw_header(self, context):
        """
        Draw the panel title bar.  Adds a documentation link icon to the
        right of the standard panel title so users can quickly open the docs.
        """
        self.layout.operator(
            "smoke.open_docs",
            text="", icon='HELP', emboss=False,
        )

    def draw(self, context):
        s      = context.scene.smoke_settings
        layout = self.layout

        # ADDON_VERSION lives with the addon metadata in __init__; pull it in via
        # a function-local deferred import (avoids a ui -> __init__ -> ui cycle).
        # It is the import-time string, NOT bl_info — Blender deletes `bl_info`
        # from the module namespace after loading a package as an *extension*
        # (4.2+), so a draw-time bl_info reference would NameError and blank the
        # panel body.  ADDON_VERSION survives.
        from . import ADDON_VERSION
        layout.label(text=f"BatchSimLab v{ADDON_VERSION}", icon='TOOL_SETTINGS')

        # ── Setup (collapsible) ───────────────────────────────────────────
        box_setup = layout.box()
        row = box_setup.row()
        row.prop(s, "show_setup",
                 icon='TRIA_DOWN' if s.show_setup else 'TRIA_RIGHT',
                 emboss=False, text="")
        row.label(text="Setup")
        if s.show_setup:
            box_setup.prop(s, "domain_obj", text="Domain Object")
            # Text Objects (moved inside Setup)
            box_to = box_setup.box()
            row_to = box_to.row()
            row_to.prop(s, "show_text_objects",
                        icon='TRIA_DOWN' if s.show_text_objects else 'TRIA_RIGHT',
                        emboss=False, text="")
            row_to.label(text="Text Objects")
            if s.show_text_objects:
                box_to.prop(s, "text_resolution", text="Resolution")
                box_to.prop(s, "text_noise",      text="Noise")
                box_to.prop(s, "text_dissolve",   text="Dissolve")
                box_to.prop(s, "text_time",       text="Bake Time")
            box_setup.prop(s, "output_path")

        layout.separator()

        # ── Simulation Parameters (outer collapsible) ─────────────────────
        box_sim = layout.box()
        row = box_sim.row()
        row.prop(s, "show_sim_params",
                 icon='TRIA_DOWN' if s.show_sim_params else 'TRIA_RIGHT',
                 emboss=False, text="")
        row.label(text="Simulation Parameters")

        if s.show_sim_params:
            # ── Settings save/load ────────────────────────────────────────
            _settings_ui(box_sim, s)
            box_sim.separator()

            # ── Frame range ───────────────────────────────────────────────
            fr_box = box_sim.box()
            fr_row = fr_box.row()
            fr_row.prop(s, "use_default_frames", text="Use Default Frames")
            sub = fr_box.column()
            sub.enabled = not s.use_default_frames
            sub.prop(s, "sim_frame_start", text="Frame Start")
            sub.prop(s, "sim_frame_end",   text="Frame End")
            box_sim.separator()

            res_box = _standalone_param_ui(box_sim, s, "resolution", "Resolution",
                                          show_prop="show_resolution")
            if s.show_resolution:
                res_box.prop(s, "maintain_density")
            box_sim.separator()

            _gas_ui(box_sim, s)
            box_sim.separator()

            # v0.7.0 TODO-45: Iterate Slow Dissolve checkbox paired on the
            # same row as the Slow Dissolve checkbox (nested list = one row).
            _standalone_param_ui(box_sim, s, "dissolve_speed", "Dissolve",
                                 show_prop="show_dissolve",
                                 enable_prop="use_dissolve",
                                 extra_props=[
                                     ("iterate_dissolve_both", "Iterate Both On and Off"),
                                     [
                                         ("slow_dissolve",         "Slow Dissolve"),
                                         ("iterate_slow_dissolve", "Iterate Slow"),
                                     ],
                                 ])
            box_sim.separator()

            _noise_ui(box_sim, s)
            box_sim.separator()

            # v0.7.0 TODO-41: Time / Adaptive Timesteps section.
            # Time Scale is a standalone always-on sweepable param; the
            # adaptive sub-block (CFL, Timesteps Max/Min) appears only
            # when use_adaptive_timesteps is checked.
            _standalone_param_ui(box_sim, s, "time_scale", "Time Scale",
                                 show_prop="show_time")
            if s.show_time:
                # Indent the Adaptive sub-block under the Time Scale box.
                box_adapt = box_sim.box()
                row_adapt = box_adapt.row()
                row_adapt.prop(s, "use_adaptive_timesteps",
                               text="Adaptive Time Step")
                if s.use_adaptive_timesteps:
                    _sub_param_ui(box_adapt, s, "cfl_number",     "CFL Number")
                    _sub_param_ui(box_adapt, s, "timesteps_max",  "Timesteps Max")
                    _sub_param_ui(box_adapt, s, "timesteps_min",  "Timesteps Min")
            box_sim.separator()

            # v0.7.0 TODO-42: Fire Parameters section.  Parallel to
            # Dissolve / Noise — enable checkbox gates the sub-params.
            _fire_ui(box_sim, s)
            box_sim.separator()

            # v0.9.0 TODO-55: per-emitter sweep sections (one per flow object
            # inside the domain; Refresh re-scans).
            _emitters_ui(box_sim, s)

        layout.separator()

        # v0.7.0 TODO-44: pre-compute _running here so both the Output and
        # Progress sections can reference it (and the Progress auto-expand
        # logic below).
        _running = _batch_is_running()

        # ── Output (collapsible: Iteration Mode + render settings + Run Batch) ──
        box_out = layout.box()
        row_out = box_out.row()
        row_out.prop(s, "show_output",
                     icon='TRIA_DOWN' if s.show_output else 'TRIA_RIGHT',
                     emboss=False, text="")
        row_out.label(text="Output")
        # job_count needed for both the in-section label and the Export Batch
        # button; compute outside the if so the button-enable logic below
        # has access regardless of collapse state (though the button only
        # draws inside the if).
        # Materialise the job list once: we need both the count and a scan for
        # oversized noise grids (the per-job dict carries resolution/up-res).
        _jobs_preview = list(generate_jobs(s))
        job_count = len(_jobs_preview)
        _noise_ceiling_jobs = sum(
            1 for p in _jobs_preview
            if noise_grid_exceeds_ceiling(
                p["resolution"], p["use_noise"], p["noise_upres"])
        )
        if s.show_output:
            # ── Iteration mode + job count ────────────────────────────────
            box_iter = box_out.box()
            box_iter.label(text="Iteration Mode:")
            box_iter.prop(s, "iteration_mode", expand=True)
            box_iter.label(text=f"{job_count} job(s) will be created")

            # Warn (don't block) when any job's noise up-res grid is in the zone
            # where Mantaflow's noise bake has crashed or hung.  edge =
            # resolution × noise_upres; see _NOISE_UPRES_EDGE_WARN.
            if _noise_ceiling_jobs:
                warn = box_iter.box()
                warn.alert = True
                warn.label(
                    text=f"{_noise_ceiling_jobs} job(s) exceed the noise up-res "
                         f"ceiling ({_NOISE_UPRES_EDGE_WARN}³)",
                    icon='ERROR')
                col_w = warn.column(align=True)
                col_w.scale_y = 0.75
                col_w.label(text="Noise bake may crash or hang at this size.")
                col_w.label(text="Baking can still succeed — retry if it stalls.")

            box_out.separator()

            # ── Render settings ──────────────────────────────────────────
            box_out.prop(s, "use_placeholders",   text="Use Placeholders")
            row_cache = box_out.row()
            row_cache.separator(factor=2.0)
            sub_cache = row_cache.column()
            sub_cache.enabled = not s.use_placeholders
            sub_cache.prop(s, "use_existing_cache", text="Use Existing Cache")
            box_out.prop(s, "auto_retry_failed",  text="Automatically Retry Failed Jobs")

            # Render Simulation Result (TODO-26): when off, run a bake-only batch and
            # grey out everything that only matters when rendering.
            box_out.prop(s, "render_simulation_result", text="Render Simulation Result")
            _render_on = s.render_simulation_result

            # Render Animation (TODO-33): still-only mode skips the PNG sequence + MP4.
            # Only meaningful when rendering is on at all.
            row_anim = box_out.row()
            row_anim.enabled = _render_on
            row_anim.prop(s, "render_animation", text="Render Animation")

            row = box_out.row()
            row.enabled = _render_on
            row.prop(s, "render_mode",    text="Render Engine")
            row.prop(s, "render_samples", text="Samples")

            # Disable Export/Append while a batch is running (TODO-28 safeguard): the
            # running cmd.exe already parsed the .bat, so editing it now can't help.
            row_mode = box_out.row(align=True)
            row_mode.enabled = not _running
            row_mode.prop(s, "export_mode", expand=True)
            export_row = box_out.row()
            # Grey out the button when no jobs would be created so the user can't
            # click it and get a misleading "Exported 0 job(s)" success message.
            # In LIMITED mode the fallback baseline ensures count >= 1, so this
            # only fires in pathological cases (e.g. all-empty lists in ALL mode).
            export_row.enabled = job_count > 0 and not _running
            export_row.operator(
                "smoke.export_batch",
                text=f"Export Batch  ({job_count} jobs)",
                icon='EXPORT',
            )

            # Status line from last export (word-wrapped at 60 chars)
            if s.last_export_info:
                col = box_out.column(align=True)
                col.scale_y = 0.75
                info = s.last_export_info
                col.label(text=info[:60])
                if len(info) > 60:
                    col.label(text=info[60:])

            box_out.separator()
            # "Display Results When Finished" is meaningless in bake-only mode; grey
            # it out there (the property is also force-cleared by its update callback).
            row_show = box_out.row()
            row_show.enabled = _render_on
            row_show.prop(s, "show_results")
            # Run Batch is enabled only when a runnable batch exists on disk (TODO-25)
            # and no batch is already running (TODO-28 safeguard).
            run_row = box_out.row()
            run_row.enabled = _batch_ready(bpy.path.abspath(s.output_path)) and not _running
            run_row.operator("smoke.run_batch", text="Run Batch", icon='PLAY')

        layout.separator()

        # ── Progress (collapsible: bars + summary + Job Log) ──────────────
        # v0.7.0 TODO-44: progress display lives in its own collapsible.
        # Auto-expand whenever a batch is running OR a post-batch summary
        # is visible — overrides the user's manual collapse so they can't
        # accidentally hide active progress.  The toggle still binds to
        # show_progress so the manual choice persists for the next batch.
        _progress_active = (
            _running
            or bool(s.batch_summary_line1)
            or bool(s.batch_progress)
            or bool(s.job_log_items)
        )
        _effective_show_progress = s.show_progress or _progress_active

        box_prog = layout.box()
        row_prog = box_prog.row()
        row_prog.prop(s, "show_progress",
                      icon='TRIA_DOWN' if _effective_show_progress else 'TRIA_RIGHT',
                      emboss=False, text="")
        row_prog.label(text="Progress")
        if _progress_active and not s.show_progress:
            # Visual hint that the section is force-opened (subtle — the
            # arrow icon already shows DOWN).  Skip an extra label to keep
            # the header tight.
            pass

        if _effective_show_progress:
            if s.batch_summary_line1:
                box_prog.label(text=s.batch_summary_line1, icon='CHECKMARK')
                box_prog.label(text=s.batch_summary_line2)
                if s.batch_summary_line3:
                    box_prog.label(text=s.batch_summary_line3)
                if s.batch_summary_line4:
                    box_prog.label(text=s.batch_summary_line4)
                    box_prog.operator("smoke.retry_failed", icon='FILE_REFRESH')
                box_prog.operator("smoke.setup_results", icon='IMAGE_DATA')
            elif s.batch_progress:
                # Bar 3a — current sub-task (what is happening right now)
                if s.batch_subtask_text:
                    try:
                        box_prog.progress(factor=s.batch_subtask_factor, type='BAR',
                                          text=s.batch_subtask_text)
                    except AttributeError:
                        box_prog.label(text=s.batch_subtask_text)

                # Bar 3b — job stage progress (how many sub-tasks are complete)
                if s.batch_job_text:
                    try:
                        box_prog.progress(factor=s.batch_job_factor, type='BAR',
                                          text=s.batch_job_text)
                    except AttributeError:
                        box_prog.label(text=s.batch_job_text)

                # Bar 3c — overall job count (X of Y jobs complete)
                try:
                    box_prog.progress(factor=s.batch_overall_factor, type='BAR',
                                      text=s.batch_progress)
                except AttributeError:
                    box_prog.label(text=s.batch_progress, icon='TIME')

                if s.batch_time_remaining:
                    box_prog.label(text=s.batch_time_remaining, icon='TIME')

            # ── Job Log (nested inside Progress; only shown once populated) ──
            if s.job_log_items:
                box_log = box_prog.box()
                row_log = box_log.row()
                row_log.prop(s, "show_job_log",
                             icon='TRIA_DOWN' if s.show_job_log else 'TRIA_RIGHT',
                             emboss=False, text="")
                row_log.label(text="Job Log")
                if s.show_job_log:
                    hdr = box_log.row()
                    hdr.label(text="", icon='BLANK1')
                    hdr.label(text="#")
                    hdr.label(text="Job Name")
                    box_log.template_list(
                        "SMOKE_UL_job_log", "",
                        s, "job_log_items",
                        s, "job_log_index",
                        rows=min(len(s.job_log_items), 8),
                    )

        layout.separator()

        # ── Utilities (collapsible, default collapsed) ────────────────────
        box_util = layout.box()
        row = box_util.row()
        row.prop(s, "show_utilities",
                 icon='TRIA_DOWN' if s.show_utilities else 'TRIA_RIGHT',
                 emboss=False, text="")
        row.label(text="Utilities")
        if s.show_utilities:
            box_util.prop(s, "collect_crash_logs")
            box_util.prop(s, "collect_estimation_data")
            box_util.prop(s, "collect_debug_log")
            box_util.separator()
            # Only useful when an exported jobs folder is present to monitor.
            _jobs_dir = os.path.join(bpy.path.abspath(s.output_path), "jobs")
            row_mon = box_util.row()
            row_mon.enabled = os.path.isdir(_jobs_dir) and any(
                re.match(r'^job_\d{4}\.json$', f) for f in os.listdir(_jobs_dir)
            )
            row_mon.operator("smoke.monitor_existing_jobs", text="Monitor Existing Jobs", icon='RECOVER_LAST')
            # Retry failed + unfinished jobs (the operator reports "No failed or
            # unfinished jobs found" if every job completed cleanly).  Enabled
            # once a run has produced any per-job output — a marker or a log —
            # so it also lights up for a batch interrupted before any unphased
            # .done was written.  Filename-only (no content reads) to keep
            # draw() off the Synology/Norton I/O path.
            row_retry = box_util.row()
            row_retry.enabled = os.path.isdir(_jobs_dir) and any(
                re.match(r'^job_\d{4}.*\.(done|worker_done|log)$', f)
                for f in os.listdir(_jobs_dir)
            )
            row_retry.operator("smoke.retry_failed", text="Retry Failed Jobs", icon='FILE_REFRESH')
            box_util.separator()
            box_util.operator("smoke.remove_all_jobs", text="Remove All Jobs", icon='TRASH')
            box_util.separator()
            row_reset = box_util.row()
            row_reset.alert = True
            row_reset.operator("smoke.reset_to_defaults", text="Reset To Defaults", icon='LOOP_BACK')
