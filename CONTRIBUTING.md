# Contributing to Anchor

Thanks for taking the time. This is a small, single-maintainer project — expect a friendly but not always fast response.

## Report a bug

Open a [bug report](https://github.com/Hans-Tandt/Anchor/issues/new?template=bug_report.yml). Please include:

- What you did, what you expected, what happened.
- Your Windows version and Anchor version.
- Steps to reproduce (small enough for someone else to follow).
- The relevant lines from `logs/anchor-YYYYMM.log` (or `%APPDATA%\Anchor\logs\` if you installed the app elsewhere).

If you can attach the output of `python diagnose.py` (with paths redacted if needed), even better.

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
python -m pip install -r requirements.txt
python -m anchor
```

Python 3.10 or newer. No virtualenv required, but recommended.

To regenerate the app icon, also install Pillow:

```bat
python -m pip install "Pillow>=10.0"
python scripts/make_icon.py
```

## Submit a pull request

1. Fork the repo and create a branch off `main`.
2. Make your change. Keep it focused — one thing per PR.
3. If it's a bug fix, please try to add a small script that reproduces the bug (put it under `scripts/`, or share it in the PR description).
4. Run `python -m anchor` and confirm the GUI still launches cleanly.
5. Open the PR against `main` with a clear title and a short "what and why" description.

By contributing, you agree that your contributions are licensed under the [MIT licence](LICENSE) of this project.
