# Security model

To report a vulnerability, see [SECURITY.md](../SECURITY.md).

## Credentials

- SFTP / WebDAV passwords are stored in **Windows Credential Manager** (service `Anchor`, one entry per
  destination id) through `keyring`. They never appear in profile files or logs.
- **Test connection** uses the typed password without saving it. It is saved only when you click **Save**.

## SFTP host keys (trust on first use)

The first time Anchor connects to an SFTP server, it saves the server's host key to
`%APPDATA%\Anchor\known_hosts`. On every later connection the key must match. If it changes, the
connection is **refused** with the new fingerprint shown, because that is exactly what a
man-in-the-middle attack looks like. If you really did reinstall or replace the server, delete its line
from `known_hosts` and connect again.

Versions before 1.5.0 accepted any host key.

## WebDAV / TLS

HTTPS and certificate verification are on by default. Turning either off shows a warning in the
destination dialog and writes a warning to the log on every run.

## Untrusted data from destinations

A destination's file listing is treated as untrusted. Names containing `..`, absolute paths, drive
letters or control characters are dropped from listings. Every restore target is resolved with
`safe_local_target()` and must stay inside the chosen folder, so a malicious server or a tampered
`_anchor_versions` tree cannot make a restore write elsewhere on your PC.

## Profiles and scheduled tasks

Profile and destination ids end up in file names and in the Task Scheduler command line, so they must
match `[A-Za-z0-9_-]{1,64}`. A profile file with any other id is rejected. Schedule fields (frequency,
time, days) are checked against a fixed allow-list before `schtasks` is called, and arguments are passed
as a list, never through a shell.

## Data safety

- Writes go to a `.bkp.tmp` sibling first and are then renamed atomically. Local writes are `fsync`ed.
  Profiles and settings are saved the same way.
- Mirror-delete is skipped for a source that is missing or only partly readable, after a cancelled run,
  and whenever it would delete more than the safety-cap percentage of files.
- A run lock stops two runs (for example the GUI and a scheduled task) from backing up the same profile
  at the same time.
