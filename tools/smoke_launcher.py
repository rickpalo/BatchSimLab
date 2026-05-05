# This file is a reference copy. The installed version lives in:
#   scripts/SmokeSimLab/smoke_launcher.py
# and is copied to <output_path>/ by Export Batch.
#
# To test manually (from the output folder):
#   python smoke_launcher.py "C:\path\to\blender.exe" jobs\job_0000.json

from scripts.SmokeSimLab.smoke_launcher import main  # noqa: F401

if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    from SmokeSimLab.smoke_launcher import main as _main
    _main()
