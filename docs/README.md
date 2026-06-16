# BatchSimLab — extension update feed

This folder is a self-hosted **Blender extension repository**, served by GitHub
Pages from `main`/`docs`.

## Add it to Blender (4.2+)

Edit → Preferences → Get Extensions → **Repositories** (top-left ▾) → **＋ Add
Remote Repository**, then paste:

```
https://rickpalo.github.io/smokeSimulationLab/index.json
```

Enable it, then **Get Extensions** lists *BatchSimLab* for install/update. Future
versions appear automatically once published here.

## Files

- `index.json` — the repository manifest (generated, do not hand-edit).
- `batchsimlab-<version>.zip` — the installable extension build(s).

## Republish after a version bump

From the repo root:

```sh
# 1. build the new zip into the feed folder
blender --command extension build --source-dir scripts/SmokeSimLab --output-dir docs
# 2. regenerate the index from whatever zips are present
blender --command extension server-generate --repo-dir docs
# 3. commit + push docs/ ; Pages redeploys in ~1 min
```

Keep only the version(s) you want offered in `docs/`; `server-generate` indexes
every zip it finds. (Binary zips live here intentionally — the global `*.zip`
gitignore has a `!docs/*.zip` exception. For many releases, hosting zips as
GitHub **Release assets** instead keeps the repo slimmer.)
