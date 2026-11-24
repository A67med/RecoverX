# Windows changes in v0.4.0

- Direct USB flash-drive recovery: discovery, system-disk protection, read-only imaging with SHA-256
  verification, then automatic recovery. Administrator permission (UAC) is requested only for imaging.
- Single five-step Quick Recovery page; advanced tools behind the in-page *Advanced workspace* switch.
- Setup prefers Python 3.12 (64-bit), verifies and test-runs Sleuth Kit, repairs a damaged `.venv`,
  installs tested package versions, offers (with your consent) to install TestDisk in an existing WSL
  distribution, and creates the RecoverX desktop shortcut with the new icon.
- RecoverX opens in its own app window (Edge/Chrome app mode) and listens on 127.0.0.1 only.
- Physical USB imaging has not been verified on real hardware yet — see docs/USB_RECOVERY_TESTING.md.
