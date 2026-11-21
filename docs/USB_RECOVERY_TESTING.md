# Testing deleted JPG and PDF recovery on a disposable USB flash drive

This procedure verifies RecoverX v0.4 USB acquisition and recovery on **real hardware**. It has not yet
been performed for the v0.4.0 release (no USB hardware was available to the automated run); results
from it are what is needed to promote v0.4.x from pre-release to stable.

> Use a **disposable** USB flash drive that contains nothing you need. Step 2 erases it with Windows'
> own formatting tool — RecoverX itself never formats or writes to a source drive.

## Equipment

* A spare USB flash drive (1–16 GB is fastest to image), Windows 10/11 with RecoverX set up.
* A test JPG and a test PDF of your own (any photo and any PDF).
* Free space on an internal disk at least the size of the USB drive.

## 1. Record the originals' hashes

In PowerShell, in the folder with the test files:

```powershell
Get-FileHash .\test-photo.jpg, .\test-document.pdf -Algorithm SHA256 | Format-List Path, Hash
```

Keep the two hashes.

## 2. Prepare the drive (Windows tools, not RecoverX)

1. In File Explorer, right-click the USB drive → **Format…** → File system **FAT32** (or exFAT/NTFS for a
   second run), *Quick Format* → Start. Note the drive letter, e.g. `F:`.
2. Copy `test-photo.jpg` and `test-document.pdf` to the drive. Add one more file you will keep.
3. **Safely eject** and reconnect the drive (flushes the files to the media).
4. Delete the two test files from the drive with **Shift+Delete** (bypasses the Recycle Bin).
5. **Safely eject** the drive again, then reconnect it. Do not write anything else to it.

## 3. Image and recover with RecoverX

1. Start RecoverX. In **1 · Select source** choose *USB drive*, press *Refresh*.
   * Check: the drive shows the correct name, letter `F:`, filesystem, capacity and serial; the system
     disk and internal disks are listed as *Protected*.
2. **2 · Recovery method**: run once with **TSK + PhotoRec**; optionally repeat with every other method.
3. **3 · Output folder**: e.g. `C:\RecoverX-USB-test`. Check: free space and destination disk are shown;
   choosing a folder on `F:` is rejected.
4. **4 · Start**: open *Case details and known originals*, paste the two SHA-256 hashes, tick
   *After imaging, read the USB drive a second time* (recommended for this test), tick the authorization
   box, press **Image USB drive & recover**, verify the identity in the dialog and confirm. Approve UAC.
5. Watch: bytes copied must reach 100 %, throughput is shown, no unreadable sectors are expected on a
   healthy drive. Then *Register → Analyze → Recover → Verify → Export* complete.

## 4. Expected results

| Check | Where | Expected |
|---|---|---|
| Acquisition status | Results → *USB acquisition record* | `completed`, destination verified **yes** |
| Hashes | same | source-stream SHA-256 = image SHA-256 = source re-read SHA-256 |
| Case baseline | *Evidence integrity and audit trail* | baseline SHA-256 = image SHA-256; before = after |
| Partition layout | acquisition record | MBR/GPT or superfloppy, correct offsets |
| Recovered files | results table | the JPG and PDF with **✓ exact match**; validation **valid** |
| Names | results table | TSK: original name with the first character replaced (FAT) or intact (NTFS/exFAT) |
| Reports | output folder | `RecoverX-report.pdf`, `manifest.json`, `inventory.csv`, `export.json`, `disk-images\Disk…img` |
| Source unchanged | optional: image the drive a second time | identical SHA-256 to the first image (if nothing else wrote to it) |

## 5. Negative tests (recommended)

* **Cancel** during imaging → status *cancelled*, `*.img.partial` kept, no case created.
* **Unplug** the drive during imaging → status *disconnected*, partial file kept, no recovery started.
* **Decline** the UAC prompt → *Administrator permission was declined*, nothing read or written.
* Select the drive, then plug a **different** USB drive into the same slot before confirming →
  the dialog or worker reports *Disk identity changed* and blocks.
* Choose an output folder **on the USB drive** → blocked.

## 6. Reporting

Attach the PDF report, `manifest.json` and the `*.acquisition.json` record (they contain no file
contents) to a GitHub issue titled "USB hardware verification: <drive model>, <filesystem>, <Windows build>".
