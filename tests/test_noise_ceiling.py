"""TODO-49: noise up-res bake ceiling warning.

noise_grid_edge / noise_grid_exceeds_ceiling decide when the panel warns that a
job's noise bake is large enough to risk a tbbmalloc crash or a hang.  The
thresholds are empirical (see _NOISE_UPRES_EDGE_WARN in __init__.py); these
tests pin the known-good / known-flaky cases observed on the i9-13900 run.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "BatchSimLab"))

import BatchSimLab as ssl


class TestNoiseGridEdge:
    def test_disabled_noise_is_zero(self):
        # No noise pass → no separate noise grid → no size to police.
        assert ssl.noise_grid_edge(256, False, 4) == 0

    def test_edge_is_resolution_times_upres(self):
        assert ssl.noise_grid_edge(256, True, 3) == 768
        assert ssl.noise_grid_edge(128, True, 3) == 384
        assert ssl.noise_grid_edge(256, True, 4) == 1024

    def test_float_inputs_coerced(self):
        # generate_jobs yields floats for resolution; edge must stay integer.
        assert ssl.noise_grid_edge(256.0, True, 2.0) == 512


class TestNoiseGridExceedsCeiling:
    def test_known_good_cases_do_not_warn(self):
        # 384³ and 512³ completed reliably in the field.
        assert ssl.noise_grid_exceeds_ceiling(128, True, 3) is False
        assert ssl.noise_grid_exceeds_ceiling(256, True, 2) is False

    def test_known_flaky_cases_warn(self):
        # 256×3 = 768³ crashed (tbbmalloc); 256×4 = 1024³ hung.
        assert ssl.noise_grid_exceeds_ceiling(256, True, 3) is True
        assert ssl.noise_grid_exceeds_ceiling(256, True, 4) is True

    def test_threshold_is_exclusive_at_512(self):
        # The known-good 512³ case sits exactly on the boundary and must pass.
        assert ssl.noise_grid_edge(256, True, 2) == ssl._NOISE_UPRES_EDGE_WARN
        assert ssl.noise_grid_exceeds_ceiling(256, True, 2) is False

    def test_disabled_noise_never_warns(self):
        # A huge up-res factor is irrelevant when noise is off.
        assert ssl.noise_grid_exceeds_ceiling(256, False, 8) is False
