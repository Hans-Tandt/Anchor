# Contributing to Anchor

Thanks for taking the time. This is a small, single-maintainer project — expect a friendly but not always fast response.

## Report a bug

Open a [bug report](https://github.com/Hans-Tandt/Anchor/issues/new?template=bug_report.yml). Please include:

- What you did, what you expected, what happened.
- Your Windows version and Anchor version.
- Steps to reproduce (small enough for someone else to follow).
- The relevant lines from `logs/anchor-YYYYMM.log` (or `%APPDATA%\Anchor\logs\` if you installed the app elsewhere).

If you can attach the output of `python -m anchor.diagnose` (with paths redacted if needed), even better.

**Security issues do NOT belong here.** See [SECURITY.md](SECURITY.md).

## Suggest a feature

Open a [feature request](https://github.com/Hans-Tandt/Anchor/issues/new?template=feature_request.yml). Describe:

- The problem you have.
- Why the existing features don't cover it.
- One concrete idea of what a solution could look like (optional).

## Set up a dev environment

```bat
git clone https://github.com/Hans-Tandt/Anchor.git
cd Anchor
python -m venv .venv && .venv\Scripts\activate
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m anchor
```

Python 3.10 or newer. See [docs/development.md](docs/development.md) for building the exe, the CI/CD
pipeline and regenerating the icon, screenshots and GIFs.

## Submit a pull request

1. Fork the repo and create a branch off `main`.
2. Make your change. Keep it focused — one thing per PR.
3. If it's a bug fix, add a test under `tests/` that fails without the fix.
4. Run `python -m pytest` and `ruff check .` — CI runs both on every PR.
5. Run `python -m anchor` and confirm the GUI still launches cleanly. If the UI changed, regenerate the
   images with `python scripts/record_demo.py`.
6. Open the PR against `main` with a clear title and a short "what and why" description.

By contributing, you agree that your contributions are licensed under the [MIT licence](LICENSE) of this project.
