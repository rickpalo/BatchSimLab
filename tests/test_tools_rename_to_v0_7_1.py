"""Tests for tools/rename_to_v0_7_1.py — the pre-v0.7.1 → v0.7.1 name migrator."""
import importlib.util
import os
import sys

import pytest


# Load the tool as a module (it's in tools/, not on the test import path).
_TOOL_PATH = os.path.join(os.path.dirname(__file__), "..", "tools",
                          "rename_to_v0_7_1.py")
_spec = importlib.util.spec_from_file_location("rename_to_v0_7_1", _TOOL_PATH)
_tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_tool)

migrate_name = _tool.migrate_name
_fmt_num     = _tool._fmt_num


# ── _fmt_num parity with addon's helper ─────────────────────────────────────

class TestFmtNumMatchesAddon:
    """The migrator's _fmt_num must produce the SAME output as the addon's
    _fmt_num (defined in __init__.py).  Otherwise renamed-on-disk names
    won't match what the addon generates for the same params."""

    def test_int_floats(self):
        assert _fmt_num("0.0") == "0"
        assert _fmt_num("1.0") == "1"
        assert _fmt_num("-2.0") == "-2"

    def test_single_decimal(self):
        assert _fmt_num("0.5") == "0.5"
        assert _fmt_num("0.50") == "0.5"

    def test_multi_decimal_kept(self):
        assert _fmt_num("2.25") == "2.25"

    def test_three_decimal_rounding(self):
        # Matches the addon's round(x, 3):g behaviour.
        assert _fmt_num("0.333333") == "0.333"
        assert _fmt_num("-0.666667") == "-0.667"

    def test_integer_string(self):
        assert _fmt_num("5") == "5"
        assert _fmt_num("128") == "128"

    def test_non_number_passes_through(self):
        # Defensive: arbitrary strings don't crash; they pass through.
        assert _fmt_num("hello") == "hello"


# ── migrate_name: basic compaction (TODO-48 A) ──────────────────────────────

class TestCompactsTrailingZeros:
    def test_v_a_b_compacted(self):
        new, _reason = migrate_name("R128_V0.0_A1.0_B1.0_D5-Fast_N2_NS2.0_SC2.0")
        assert new == "R128_V0_A1_B1_D5-Fast_N2_NS2_SC2"

    def test_already_compact_returns_none(self):
        """Names already in v0.7.1 format return (None, 'already in...')."""
        new, reason = migrate_name("R128_V0_A1_B1_D5-Fast_N2_NS2_SC2")
        assert new is None
        assert "already" in reason

    def test_non_default_floats_kept(self):
        """Non-default float values that don't need compaction return None
        (already in v0.7.1 format)."""
        new, reason = migrate_name(
            "R128_V0.25_A0.5_B-0.5_D5-Fast_N2_NS1.5_SC1.5"
        )
        assert new is None
        assert "already" in reason

    def test_three_decimal_input_compacted(self):
        new, _ = migrate_name("R128_V0.333_A1.000_B1.0_D5-Fast_Nx")
        assert new == "R128_V0.333_A1_B1_D5-Fast_Nx"


# ── migrate_name: OFF suffix (TODO-48 B) ────────────────────────────────────

class TestOffSuffixConversion:
    def test_d_off_to_dx(self):
        new, _ = migrate_name("R128_V0.0_A1.0_B1.0_D-OFF_N-OFF")
        assert new == "R128_V0_A1_B1_Dx_Nx"

    def test_n_off_to_nx(self):
        new, _ = migrate_name("R128_V0.0_A1.0_B1.0_D5-Fast_N-OFF")
        assert new == "R128_V0_A1_B1_D5-Fast_Nx"

    def test_both_off(self):
        new, _ = migrate_name("R128_V0.0_A1.0_B1.0_D-OFF_N-OFF")
        assert "_Dx_" in new
        assert new.endswith("_Nx")


# ── Bare D<N> ambiguity handling ────────────────────────────────────────────

class TestBareDDissolveMode:
    """Pre-v0.6.2 dissolve-on names with no -Slow/-Fast suffix are
    ambiguous.  The --bare-d=MODE flag picks the assumption."""

    def test_bare_d_skip_returns_none(self):
        new, reason = migrate_name(
            "R128_V0.0_A1.0_B1.0_D5_N2_NS2.0_SC2.0", bare_d_mode="skip"
        )
        assert new is None
        assert "ambiguous" in reason.lower()
        assert "D5" in reason

    def test_bare_d_slow_appends_slow(self):
        new, reason = migrate_name(
            "R128_V0.0_A1.0_B1.0_D5_N2_NS2.0_SC2.0", bare_d_mode="slow"
        )
        assert new == "R128_V0_A1_B1_D5-Slow_N2_NS2_SC2"
        assert "Slow" in reason

    def test_bare_d_fast_appends_fast(self):
        new, reason = migrate_name(
            "R128_V0.0_A1.0_B1.0_D5_N2_NS2.0_SC2.0", bare_d_mode="fast"
        )
        assert new == "R128_V0_A1_B1_D5-Fast_N2_NS2_SC2"
        assert "Fast" in reason

    def test_bare_d_only_triggers_on_bare_form(self):
        """D5-Slow and D5-Fast already have suffix → not bare, no ambig handling."""
        new, _ = migrate_name(
            "R128_V0.0_A1.0_B1.0_D5-Slow_N2_NS2.0_SC2.0", bare_d_mode="skip"
        )
        assert new == "R128_V0_A1_B1_D5-Slow_N2_NS2_SC2"


# ── End-to-end realistic name samples ───────────────────────────────────────

class TestRealisticBatchNames:
    """Names taken from actual user batches in the conversation history."""

    def test_user_r128_no_dissolve(self):
        # Pattern from the v0.6.0Test user screenshots.
        new, _ = migrate_name("R128_V0.0_A0.0_B0.0_D100_N-OFF", bare_d_mode="slow")
        assert new == "R128_V0_A0_B0_D100-Slow_Nx"

    def test_user_r256_with_noise(self):
        new, _ = migrate_name(
            "R256_V0.0_A1.0_B1.0_D-OFF_N2_NS2.0_SC2.0"
        )
        assert new == "R256_V0_A1_B1_Dx_N2_NS2_SC2"

    def test_user_r512_all_off(self):
        new, _ = migrate_name("R512_V0.0_A1.0_B1.0_D-OFF_N-OFF")
        assert new == "R512_V0_A1_B1_Dx_Nx"


# ── Non-cache strings are passed through unchanged ──────────────────────────

class TestPassthroughBehaviour:
    def test_empty_string(self):
        new, reason = migrate_name("")
        assert new is None
        assert "empty" in reason.lower()

    def test_arbitrary_string_components_pass_through(self):
        # Anything that doesn't match a known pattern is just kept as-is.
        new, _ = migrate_name("R128_unknown_component_D-OFF_N-OFF")
        # D-OFF and N-OFF converted; the rest passes through.
        assert new == "R128_unknown_component_Dx_Nx"


# ── Mirror addon make_name() round-trip ─────────────────────────────────────
# Sanity check: take a job dict, run it through make_name() to generate the
# v0.7.1 name, then verify migrate_name() leaves that name unchanged (it's
# already in the new format).  This catches drift between the addon's
# _fmt_num and the migrator's _fmt_num.

class TestRoundTripWithAddon:
    def test_migrator_leaves_addon_output_alone(self):
        # Import the addon's make_name (needs bpy stub from conftest).
        # sys.path needs the PARENT of SmokeSimLab/ for `import SmokeSimLab`
        # to resolve as a package.
        sys.path.insert(
            0, os.path.join(os.path.dirname(__file__), "..", "scripts"),
        )
        from SmokeSimLab import make_name

        p = dict(
            resolution=128, vorticity=0.25, alpha=1.0, beta=0.5,
            use_dissolve=True, slow_dissolve=False, dissolve_speed=5,
            use_noise=True, noise_upres=2, noise_strength=2.0,
            noise_spatial_scale=1.5,
            time_scale=1.0, use_adaptive_timesteps=True,
            cfl_number=4.0, timesteps_max=4, timesteps_min=1,
            use_fire=False,
            burning_rate=0.75, flame_smoke=1.0, flame_vorticity=0.5,
            flame_max_temp=1.7, flame_ignition=1.5,
        )
        name = make_name(p)
        new, reason = migrate_name(name)
        assert new is None, (
            f"migrate_name should leave addon-generated v0.7.1 name alone; "
            f"got {new!r} (reason: {reason})"
        )
        assert reason == "already in v0.7.1 format"
