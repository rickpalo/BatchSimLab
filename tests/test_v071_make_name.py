"""v0.7.1 regression tests: make_name() compact format + v0.7.0 param inclusion.

TODO-47: Include v0.7.0 sim params (time_scale, adaptive timesteps, fire)
         in make_name() with defaults-suppressed format so cache names
         stay collision-free.
TODO-48: Compact format — trim trailing zeros via :g, 'x' single-char
         OFF indicator (Dx / Nx / ATx / Fx instead of D-OFF / N-OFF / etc).

Cache-orphan note: v0.7.1 reformats ALL filenames.  Pre-v0.7.1 caches
no longer match.  Both TODOs ship together in one commit so users see
one rename event, not two.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "BatchSimLab"))

from BatchSimLab import make_name, _fmt_num


def _base(**overrides):
    """Minimum job dict matching v0.7.0 _default_job schema, all defaults."""
    p = dict(
        resolution=128, vorticity=0.0, alpha=1.0, beta=1.0,
        use_dissolve=False, slow_dissolve=False, dissolve_speed=5,
        use_noise=False, noise_upres=2, noise_strength=2.0,
        noise_spatial_scale=2.0,
        # v0.7.0 defaults
        time_scale=1.0, use_adaptive_timesteps=True,
        cfl_number=4.0, timesteps_max=4, timesteps_min=1,
        use_fire=False,
        burning_rate=0.75, flame_smoke=1.0, flame_vorticity=0.5,
        flame_max_temp=1.7, flame_ignition=1.5,
    )
    p.update(overrides)
    return p


# ── TODO-48 A: _fmt_num helper ──────────────────────────────────────────────

class TestFmtNumTrimsTrailingZeros:
    def test_integer_float_to_int_string(self):
        assert _fmt_num(0.0) == "0"
        assert _fmt_num(1.0) == "1"
        assert _fmt_num(-2.0) == "-2"

    def test_single_decimal_kept(self):
        assert _fmt_num(0.5) == "0.5"
        assert _fmt_num(-0.5) == "-0.5"

    def test_trailing_zero_stripped(self):
        assert _fmt_num(0.50) == "0.5"
        assert _fmt_num(1.20) == "1.2"

    def test_multi_decimal_preserved(self):
        assert _fmt_num(2.25) == "2.25"

    def test_rounds_to_three_decimals(self):
        # 0.123456 rounds to 0.123 (3 decimals); :g then strips no zeros.
        assert _fmt_num(0.123456) == "0.123"
        assert _fmt_num(0.333333) == "0.333"
        assert _fmt_num(-0.666667) == "-0.667"

    def test_integer_input_accepted(self):
        assert _fmt_num(5) == "5"
        assert _fmt_num(0) == "0"


# ── TODO-48 B: 'x' single-char OFF indicator ────────────────────────────────

class TestOffSuffix:
    def test_dissolve_off_uses_dx(self):
        p = _base(use_dissolve=False)
        assert "_Dx_" in make_name(p), f"expected '_Dx_' in {make_name(p)!r}"

    def test_noise_off_uses_nx(self):
        p = _base(use_noise=False)
        assert make_name(p).endswith("_Nx"), (
            f"expected name to end with '_Nx', got {make_name(p)!r}"
        )

    def test_adaptive_off_uses_atx(self):
        p = _base(use_adaptive_timesteps=False)
        assert "_ATx" in make_name(p)

    def test_old_off_suffix_never_appears(self):
        """v0.7.1: '-OFF' is GONE; only 'x' (or actual values) appear."""
        for setup in (
            _base(use_dissolve=False),
            _base(use_noise=False),
            _base(use_adaptive_timesteps=False),
            _base(use_dissolve=False, use_noise=False,
                  use_adaptive_timesteps=False),
        ):
            name = make_name(setup)
            assert "-OFF" not in name, (
                f"v0.7.1 must remove '-OFF' suffix; got {name!r}"
            )


# ── TODO-47: v0.7.0 params included in name with default-suppression ───────

class TestDefaultSuppression:
    """v0.6.x cache names must match exactly when nothing v0.7.x has been
    touched — defaults for the new params get suppressed from the name."""

    def test_all_defaults_no_extras_appended(self):
        """Default-everything job produces the v0.6.x-style core name
        with no v0.7.0-param suffixes."""
        name = make_name(_base())
        # Core form: R128_V0_A1_B1_D5-Fast (wait, dissolve is OFF in
        # _base) — actually _base has use_dissolve=False so Dx.
        # The end of the name should be just _Nx, no TS/AT/F suffixes.
        assert name == "R128_V0_A1_B1_Dx_Nx", (
            f"defaults-only job got unexpected extras: {name!r}"
        )

    def test_v060_backwards_compat_dissolve_on_noise_on(self):
        """Job with v0.6.x-equivalent settings (dissolve on, noise on,
        no v0.7.x touch) should produce a v0.6.2-compatible-looking
        name (modulo TODO-48 compaction)."""
        p = _base(
            use_dissolve=True, slow_dissolve=False, dissolve_speed=5,
            use_noise=True, noise_upres=2, noise_strength=2.0,
            noise_spatial_scale=2.0,
        )
        name = make_name(p)
        # No v0.7.0 extras.
        for suffix in ("_TS", "_AT", "_CFL", "_TMx", "_TMn", "_F-Y", "_BR",
                       "_FS", "_FV", "_TMax", "_TIgn"):
            assert suffix not in name, (
                f"defaults should suppress {suffix!r}; got {name!r}"
            )

    def test_time_scale_default_suppressed(self):
        p = _base(time_scale=1.0)
        assert "_TS" not in make_name(p)

    def test_time_scale_nondefault_included(self):
        p = _base(time_scale=2.0)
        assert "_TS2" in make_name(p)
        # And trimmed — not "TS2.0"
        assert "_TS2.0" not in make_name(p)

    def test_adaptive_on_default_suppressed(self):
        """use_adaptive_timesteps=True is the Blender default → no suffix."""
        p = _base(use_adaptive_timesteps=True)
        assert "_AT" not in make_name(p)

    def test_adaptive_off_included(self):
        p = _base(use_adaptive_timesteps=False)
        assert "_ATx" in make_name(p)

    def test_cfl_default_suppressed_when_adaptive_on(self):
        p = _base(use_adaptive_timesteps=True, cfl_number=4.0)
        assert "_CFL" not in make_name(p)

    def test_cfl_nondefault_included_when_adaptive_on(self):
        p = _base(use_adaptive_timesteps=True, cfl_number=8.0)
        assert "_CFL8" in make_name(p)

    def test_cfl_skipped_when_adaptive_off(self):
        """Even with non-default CFL, suffix is skipped when adaptive
        is off because CFL has no effect then."""
        p = _base(use_adaptive_timesteps=False, cfl_number=8.0)
        assert "_CFL" not in make_name(p)
        # But ATx is present (the override flag).
        assert "_ATx" in make_name(p)

    def test_timesteps_max_default_suppressed(self):
        p = _base(timesteps_max=4)
        assert "_TMx" not in make_name(p)

    def test_timesteps_max_nondefault_included(self):
        p = _base(timesteps_max=8)
        assert "_TMx8" in make_name(p)

    def test_timesteps_min_default_suppressed(self):
        p = _base(timesteps_min=1)
        assert "_TMn" not in make_name(p)

    def test_timesteps_min_nondefault_included(self):
        p = _base(timesteps_min=2)
        assert "_TMn2" in make_name(p)


# ── Fire suffix behaviour ──────────────────────────────────────────────────

class TestFireSuffix:
    def test_fire_off_suppresses_entirely(self):
        """use_fire=False (default) → no fire-related suffix at all."""
        p = _base(use_fire=False)
        name = make_name(p)
        for suffix in ("F-Y", "_BR", "_FS", "_FV", "_TMax", "_TIgn", "_Fx"):
            assert suffix not in name, (
                f"fire=off should suppress {suffix!r}; got {name!r}"
            )

    def test_fire_on_appends_full_fire_block(self):
        p = _base(use_fire=True)
        name = make_name(p)
        assert "_F-Y" in name
        assert "_BR" in name
        assert "_FS" in name
        assert "_FV" in name
        assert "_TMax" in name
        assert "_TIgn" in name

    def test_fire_block_values_match_inputs(self):
        p = _base(use_fire=True,
                  burning_rate=1.5, flame_smoke=2.0,
                  flame_vorticity=0.75, flame_max_temp=2.5,
                  flame_ignition=1.75)
        name = make_name(p)
        assert "_BR1.5" in name
        assert "_FS2" in name
        assert "_FV0.75" in name
        assert "_TMax2.5" in name
        assert "_TIgn1.75" in name


# ── End-to-end: real example strings from RELEASING.md v0.7.1 ───────────────

class TestEndToEnd:
    def test_documented_default_form(self):
        """Mirror the example in RELEASING.md / TODO-48 spec."""
        p = _base(
            use_dissolve=True, slow_dissolve=False, dissolve_speed=5,
            use_noise=True, noise_upres=2, noise_strength=2.0,
            noise_spatial_scale=2.0,
        )
        assert make_name(p) == "R128_V0_A1_B1_D5-Fast_N2_NS2_SC2"

    def test_documented_fire_on_form(self):
        """Mirror the example in TODO-48 spec for fire-on names."""
        p = _base(
            use_dissolve=True, slow_dissolve=False, dissolve_speed=5,
            use_noise=True, noise_upres=2, noise_strength=2.0,
            noise_spatial_scale=2.0,
            use_fire=True,
            burning_rate=1.5, flame_smoke=1.0,
            flame_vorticity=0.5, flame_max_temp=1.7,
            flame_ignition=1.5,
        )
        name = make_name(p)
        assert name == (
            "R128_V0_A1_B1_D5-Fast_N2_NS2_SC2_F-Y_BR1.5_FS1_FV0.5_TMax1.7_TIgn1.5"
        )


# ── Collision-prevention contract (TODO-47 primary motivation) ─────────────

class TestNoCacheCollisions:
    """Two jobs that differ in ANY simulation param must produce
    different names — otherwise they'd share a cache and one would
    silently SKIP-bake using the other's data."""

    def test_time_scale_differs(self):
        p1 = _base(time_scale=1.0)
        p2 = _base(time_scale=2.0)
        assert make_name(p1) != make_name(p2)

    def test_adaptive_on_off_differs(self):
        p1 = _base(use_adaptive_timesteps=True)
        p2 = _base(use_adaptive_timesteps=False)
        assert make_name(p1) != make_name(p2)

    def test_cfl_differs_when_adaptive_on(self):
        p1 = _base(use_adaptive_timesteps=True, cfl_number=4.0)
        p2 = _base(use_adaptive_timesteps=True, cfl_number=8.0)
        assert make_name(p1) != make_name(p2)

    def test_fire_on_off_differs(self):
        p1 = _base(use_fire=False)
        p2 = _base(use_fire=True)
        assert make_name(p1) != make_name(p2)

    def test_each_fire_subparam_differs(self):
        """Vary each fire sub-param individually and confirm distinct names."""
        baseline = _base(use_fire=True)
        for field, default, alt in (
            ("burning_rate", 0.75, 1.5),
            ("flame_smoke", 1.0, 2.0),
            ("flame_vorticity", 0.5, 1.0),
            ("flame_max_temp", 1.7, 2.5),
            ("flame_ignition", 1.5, 2.0),
        ):
            p_alt = _base(use_fire=True, **{field: alt})
            assert make_name(baseline) != make_name(p_alt), (
                f"changing {field} from {default} to {alt} did not produce "
                f"a distinct filename — cache collision risk"
            )
