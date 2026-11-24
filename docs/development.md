# Development

## Setup

```bat
git clone https://github.com/Hans-Tandt/Anchor.git
cd Anchor
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
python -m anchor
```

## Tests and lint

```bat
python -m pytest          :: headless; uses a throw-away APPDATA
ruff check .
```

The tests never touch your real profiles: `tests/conftest.py` points `APPDATA` at a temp folder and runs
Qt with the `offscreen` platform. GUI tests live in `tests/test_gui.py`, engine and security tests in
`tests/test_engine.py` and `tests/test_security.py`.

## Build the exe

```bat
scripts\build.bat
```

This produces `dist\Anchor\Anchor.exe` plus `dist\Anchor\_internal\` (the two must stay together; zip
the whole folder). Under the hood: `python -m PyInstaller --noconfirm packaging/Anchor.spec`. The spec
reads the version from `anchor/__init__.py` and stamps it into the exe's file properties.

## CI/CD

| Workflow | When | What |
|---|---|---|
| [`ci.yml`](../.github/workflows/ci.yml) | Every push to `main` and every PR | Ruff · pytest on Windows with Python 3.10–3.13 · PyInstaller build + start-up smoke test · build uploaded as an artifact (14 days) |
| [`release.yml`](../.github/workflows/release.yml) | Started by hand (Actions tab → Release → Run workflow) for an existing tag `vX.Y.Z` | Checks the tag matches `__version__` · tests · build · `Anchor-X.Y.Z-win64.zip` + `.sha256` · GitHub Release with the CHANGELOG section as notes |
| [`dependabot.yml`](../.github/dependabot.yml) | Monthly | Update PRs for pip packages and GitHub Actions |

### Cutting a release

1. Bump `__version__` in `anchor/__init__.py`.
2. Add a `## [X.Y.Z] — YYYY-MM-DD` section at the top of `CHANGELOG.md`.
3. Commit and push. Build with `scripts\build.bat` and publish the release by hand; pushing a tag
   does not start a build.
4. Optional: to let GitHub build it instead, create the tag `vX.Y.Z` and start **Release** by hand
   in the Actions tab.

## Regenerating images

| Command | Output |
|---|---|
| `python scripts/make_icon.py` | `anchor/resources/icons/anchor.ico` + `.png`, `docs/images/logo.png`, icon previews |
| `python scripts/make_brand.py` | Transparent TechEase logo for the sidebar (from `docs/brand/techease-banner.png`) |
| `python scripts/record_demo.py` | All screenshots and GIFs in `docs/images/` |

`record_demo.py` builds a sandbox in `<drive>:\AnchorDemo` (so no personal paths show up in the
images), points `APPDATA` there, drives the real UI and deletes the sandbox when done. It renders
offscreen by default; pass `--onscreen` to watch it.
