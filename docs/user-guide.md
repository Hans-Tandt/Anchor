# User guide

## The window

- **Backups**: your profiles on the left, the selected one on the right: what it backs up, when it last
  ran, and the live progress of a run.
- **Activity**: everything Anchor did this session. A red badge appears on it when an error was logged
  while you were on another page.
- **Settings** (bottom left), and a **theme toggle** right above it.
- The **≡** button collapses the navigation to icons only.

Keyboard: `Ctrl+N` new profile · `F5` back up now · `Ctrl+E` edit · `Esc` stop the running job ·
`Ctrl+1` / `Ctrl+2` / `Ctrl+,` switch pages · `Ctrl+F` search profiles.

## Profiles

A profile says **what** to back up (sources) and **where** to (destinations). Create one with
**New profile**. The editor has four tabs:

| Tab | What you set |
|---|---|
| Sources | Folders or single files. Each source gets its own sub-folder at the destination. |
| Destinations | One or more targets, see below. All of them receive the same files. |
| Exclusions | Ready-made presets (temp files, `node_modules`, IDE folders…), specific folders, and your own glob patterns. Excluding `.git` drops your repositories' history, so Anchor warns about it. |
| Options | Hash verification, mirror deletions + safety cap, versions to keep, flat layout, verify after copy, confirm before copying, timestamps, symlinks. |

### Destinations

| Type | Notes |
|---|---|
| Local / USB / UNC | Any path: `E:\Backups`, `\\NAS\share\Backups`. A folder that doesn't exist yet is created on the first run. |
| OneDrive folder | A local path inside your OneDrive folder; OneDrive does the upload. |
| SFTP | Host, port, user, remote path. The password is stored in Windows Credential Manager. See [security](security.md) for host keys. |
| WebDAV | Same, plus HTTPS and certificate checks (keep both on unless you are on a trusted LAN; Anchor warns otherwise). |

**Test connection** tries the destination with the password you typed. The password is only saved when
you click **Save**.

## Running

- **Back up now** runs the selected profile. Scan works out what changed, Copy writes it, Verify checks it
  arrived. The ring on the right fills with the copy; speed and ETA are shown above it.
- **Stop** (or `Esc`) stops after the current file. Nothing half-written is left behind, and the next run
  continues where this one stopped. A stopped run never deletes anything at the destination.
- **Group run**: Ctrl/Shift-click several profiles, then **Run selected**. They run one after another; if
  one fails, the rest still run.
- **Verify** re-checks an existing backup without copying anything.
- When something went wrong, an **issues** button appears next to the actions. It lists every problem and
  can export them to CSV.

## Schedules

**Schedule** creates a Windows Task Scheduler task (daily, weekly on chosen days, or at sign-in) that runs
`Anchor.exe --cli --profile <id> --silent` (or `python -m anchor.cli …` from source). Scheduled runs need no
open window and log to the same log files.

## Restore

**Restore** opens the destination's file tree. Select a file, then a version (the current copy, or an
older one if the profile keeps versions), and choose:

- **Restore to original location**: back where it came from, based on the profile's source folders.
  Anchor asks before overwriting.
- **Restore to folder…**: into any folder you pick, keeping the sub-folder structure.

## Settings

| Setting | Meaning |
|---|---|
| App theme | Dark, light, or follow Windows. |
| SHA-256 for new profiles | New profiles start with hash verification switched on. |
| Parallel copies | Files copied at once to local and network drives (remote destinations copy one at a time). |
| Pause after scan | How long the "X to copy" summary stays up before copying starts. |
| Back up when the drive is plugged in | While Anchor is open, a profile starts as soon as its local destination comes back online. |
| Desktop notifications | Windows notification when a run finishes while Anchor is in the background. |
| Storage | Open the logs, profiles or app-data folders. |

## Where things live

| What | Where |
|---|---|
| Profiles, settings, state databases, SFTP host keys | `%APPDATA%\Anchor\` |
| Logs | `%APPDATA%\Anchor\logs\` (the exe), or `logs\` next to the source code |
| Passwords | Windows Credential Manager, service `Anchor` |
| Old versions of files | `_anchor_versions\` at the destination |

## Troubleshooting

`python -m anchor.diagnose` prints all paths, profiles and state-database counts.
`python -m anchor.diagnose --check "C:\path\to\file"` explains what the engine would do with one file
(excluded, new, unchanged…). Attach its output (with paths redacted if you like) to bug reports.
