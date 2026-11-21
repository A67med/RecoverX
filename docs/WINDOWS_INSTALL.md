# Installing RecoverX on Windows 10 / 11 — step by step

This guide needs no programming knowledge. Setup takes about 5–10 minutes and needs an internet
connection once.

## What you need

* Windows 10 or Windows 11, **64-bit**.
* About 1.5 GB of free space for RecoverX, plus space for recovered files. To recover a USB drive you
  need free space at least as large as the **whole USB drive** on a *different* disk (for example your
  internal C: or D: drive).
* An administrator password (or approval) — only at the moment you image a USB drive.

## 1. Install Python 3.12 (64-bit)

Choose **one** of these:

* **Python install manager** (Windows 11): open *PowerShell* and run `py install 3.12`.
* **python.org installer:** go to <https://www.python.org/downloads/windows/>, download
  *Windows installer (64-bit)* for **Python 3.12**, run it and tick **“Add python.exe to PATH”**.

Python 3.11 and 3.13 (64-bit) also work, but 3.12 is the tested version.

## 2. (Optional) Enable PhotoRec through WSL

TSK recovery works without this. PhotoRec (file carving, for files whose metadata is gone) runs
inside Windows Subsystem for Linux.

1. Open **PowerShell as administrator** and run `wsl --install -d Ubuntu-24.04`. Restart Windows.
2. Ubuntu opens once: create a normal Linux user name and password (not `root`).
3. Setup in step 3 detects WSL. If TestDisk/PhotoRec is missing it **asks** whether to install the
   `testdisk` package into Ubuntu — type **Y** to agree. RecoverX never installs WSL or Linux itself.

## 3. Run setup

1. Extract the RecoverX ZIP to a short path such as `C:\RecoverX` (long paths can break Python installs).
2. Double-click **`SETUP_WINDOWS.cmd`**. A window shows each step:
   * finds Python 3.12;
   * downloads The Sleuth Kit 4.15.0 from its official GitHub release, verifies its SHA-256 and checks
     that `tsk_recover.exe` really starts;
   * creates a private Python environment in `.venv` (a damaged one is renamed `.venv.broken-…`, not deleted);
   * installs the tested Python packages;
   * activates the bundled CART model;
   * checks PhotoRec in WSL;
   * creates a **RecoverX** shortcut on your desktop.
3. When you see **SUCCESS**, press a key to close the window.

Setup never asks for administrator rights, never changes UAC or security settings, and never formats,
mounts or writes to any disk.

## 4. Start RecoverX

Double-click the **RecoverX** desktop icon (or `START_RECOVERX_WINDOWS.cmd`). A small console window
starts the local server (keep it open) and RecoverX opens in its own window. It is only reachable from
this PC (`127.0.0.1`). Close the console window to stop RecoverX.

## 5. Recover deleted files from a USB flash drive

1. Plug in the USB drive. **Do not save anything new to it** — new files can overwrite deleted ones.
2. In **1 · Select source**, choose *USB drive* and select your drive (press *Refresh* if needed).
   Internal disks and the Windows disk are listed under *Protected storage* and cannot be selected.
3. In **2 · Recovery method**, *Smart Recovery* or *TSK + PhotoRec* are good choices.
4. In **3 · Output folder**, choose a folder on your computer (not on the USB drive).
5. In **4 · Start recovery**, tick the authorization box and press **Image USB drive & recover**.
   Check the disk name, size and serial in the confirmation dialog, tick it and press
   **Start read-only imaging**. Approve the Windows permission prompt.
6. Watch the progress (bytes copied, speed, remaining time). Recovery starts automatically after the
   image is verified.
7. In **5 · Recovery results**, filter, preview and download files, or press **Open output folder**.
   The PDF report and JSON manifest describe exactly what happened.

## Troubleshooting

| Message | What to do |
|---|---|
| *Compatible 64-bit Python not found* | Install Python 3.12 64-bit (step 1), then run setup again. |
| *tsk_recover.exe … did not run correctly* | Install the Microsoft Visual C++ Redistributable (x86): <https://aka.ms/vs/17/release/vc_redist.x86.exe>. |
| *PhotoRec unavailable* | Complete step 2, or use *TSK only*. |
| *The default WSL distribution logs in as root* | In Ubuntu create a normal user and make it the default, then rerun setup. |
| *No eligible USB storage device found* | Reconnect the drive, press *Refresh*. Card readers without a card show no media. |
| *Administrator permission was declined* | Nothing was read or written. Start again and approve the prompt. |
| *The output folder is on the source disk* | Choose a folder on your internal drive. |
| *Not enough free space* | The image is as large as the whole USB drive; free space or choose another disk. |
| *Image has unreadable sectors* | The drive has bad areas. Review the listed ranges; you may start recovery from the image explicitly. |
| *Device disconnected* | Reconnect and start again. The partial image is kept as `*.img.partial` and is never used. |
| RecoverX window does not open | Open `http://127.0.0.1:8501` (or the address shown in the console) in your browser. |
| *RecoverX is not set up yet* | Run `SETUP_WINDOWS.cmd` again; it repairs a damaged environment. |
