# How to Release SmokeSimLab

## Repository structure

```
smokeSimulationLab/          ← repo root
├── SmokeSimLab/
│   ├── __init__.py          ← addon code
│   └── smoke_worker.py      ← headless batch worker
├── documentation/
├── README.md
├── LICENSE
└── .gitignore
```

Your local working copies live in `scripts/SmokeSimLab/` (ignored by git).
When ready to release, copy them into `SmokeSimLab/` at the repo root.

---

## Releasing a new version

### 1. Update the version number

Open `SmokeSimLab/__init__.py` and bump the version in `bl_info`:

```python
bl_info = {
    ...
    "version": (1, 3, 0),   # <-- change this
    ...
}
```

Use the format `(major, minor, patch)`:
- **patch** (1.2.1) — small bug fixes
- **minor** (1.3.0) — new features, backwards compatible
- **major** (2.0.0) — breaking changes

### 2. Copy your updated scripts into the repo folder

```
scripts/SmokeSimLab/__init__.py   →   SmokeSimLab/__init__.py
scripts/SmokeSimLab/smoke_worker.py   →   SmokeSimLab/smoke_worker.py
```

### 3. Commit your changes

```bash
git add SmokeSimLab/__init__.py SmokeSimLab/smoke_worker.py
git commit -m "Release v1.3.0 — description of what changed"
```

### 4. Tag the commit and push

```bash
git tag v1.3.0
git push origin main --tags
```

The tag must start with `v` followed by numbers, e.g. `v1.3.0`.
Pushing the tag triggers the GitHub Actions release workflow automatically.

### 5. Check the release on GitHub

Go to: https://github.com/rickpalo/smokeSimulationLab/releases

GitHub Actions will create the release and attach `SmokeSimLab.zip`
(the installable Blender addon) within a minute or two.

---

## If you need to redo a release tag

```bash
git tag -d v1.3.0                    # delete local tag
git push origin :refs/tags/v1.3.0   # delete remote tag
# then re-tag and push as normal
```

---

## Version history

| Version | Notes |
|---------|-------|
| 1.0.0   | Initial release |
| 1.1.0   | Added alpha/beta buoyancy parameters, float epsilon fix |
| 1.2.0   | Added Limited/All Combinations iteration mode, docs button |
