"""Blender extension manifest (blender_manifest.toml) sanity + version sync.

Guards the constraints the Blender validator enforces (so we catch them in CI
instead of at `extension build` time) and keeps the manifest version locked to
bl_info's ADDON_VERSION.
"""
import os
import sys
import tomllib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "BatchSimLab"))

import BatchSimLab as ssl

_MANIFEST = os.path.join(
    os.path.dirname(__file__), "..", "scripts", "BatchSimLab", "blender_manifest.toml"
)


def _manifest():
    with open(_MANIFEST, "rb") as fh:
        return tomllib.load(fh)


class TestManifestRequiredFields:
    def test_parses_and_has_required_keys(self):
        m = _manifest()
        for key in ("schema_version", "id", "version", "name", "tagline",
                    "maintainer", "type", "blender_version_min", "license"):
            assert key in m, f"manifest missing required key {key!r}"

    def test_type_is_addon(self):
        assert _manifest()["type"] == "add-on"

    def test_blender_min_is_42_plus(self):
        # Extensions didn't exist before 4.2.
        parts = tuple(int(x) for x in _manifest()["blender_version_min"].split("."))
        assert parts >= (4, 2, 0)

    def test_license_is_spdx_list(self):
        lic = _manifest()["license"]
        assert isinstance(lic, list) and lic
        assert all(x.startswith("SPDX:") for x in lic)


class TestManifestConstraints:
    def test_tagline_max_64_no_trailing_punctuation(self):
        tag = _manifest()["tagline"]
        assert len(tag) <= 64
        assert tag[-1] not in ".!?,"

    def test_permissions_files_max_64(self):
        # Blender caps each permission string at 64 chars (learned the hard way).
        perms = _manifest().get("permissions", {})
        if "files" in perms:
            assert len(perms["files"]) <= 64


class TestManifestVersionSync:
    def test_version_matches_bl_info(self):
        assert _manifest()["version"] == ssl.ADDON_VERSION

    def test_id_is_stable(self):
        # The id keys the install dir + update-repo entry — must not drift.
        assert _manifest()["id"] == "batchsimlab"
