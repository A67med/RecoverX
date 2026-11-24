# Third-party notices

RecoverX's own code is under the licence in [`LICENSE`](LICENSE). RecoverX **does not
modify** the recovery tools below; it runs them as separate programs. The source
repository contains **no third-party binaries**: the Windows desktop dependencies are
downloaded from their official publishers and verified against pinned SHA-256 values by
[`scripts/windows/provision_desktop.ps1`](scripts/windows/provision_desktop.ps1). Anyone
who redistributes a packaged build must ship the licence texts in [`licenses/`](licenses/)
and offer the corresponding source (provisioned into `vendor-source/`).

| Component | Version | Licence | Used for | Official source (SHA-256 of the archive) |
|---|---|---|---|---|
| The Sleuth Kit (TSK) | 4.15.0 (Windows), 4.12.1 (Ubuntu 24.04, research runs) | CPL 1.0 / IBM Public License / GPL / Apache-2.0 / MIT parts — see [`licenses/sleuthkit`](licenses/sleuthkit) | metadata-based recovery (`tsk_recover`), analysis (`mmls`, `fsstat`, `fls`) | [sleuthkit-4.15.0-win32.zip](https://github.com/sleuthkit/sleuthkit/releases/tag/sleuthkit-4.15.0) (`c2ebab81…b20ce`); source `sleuthkit-4.15.0.tar.gz` (`3a8c1e7d…6eca9`) |
| PhotoRec / TestDisk | 7.2 (Windows), 7.1 (Ubuntu, research runs) | GPL-2.0-or-later | signature-based carving | [testdisk-7.2.win64.zip](https://www.cgsecurity.org/wiki/TestDisk_Download) (`e97e203c…29f38`); source `testdisk-7.2.tar.bz2` (`f8343be2…c283f`) |
| PhotoRec MinGW build (optional) | 7.2 | GPL-2.0-or-later; links libjpeg-turbo (IJG/BSD), zlib, GCC runtime (GPL-3.0 with runtime exception) — see [`licenses/`](licenses/) | native Windows build used by the RC1 desktop | built from `testdisk-7.2.tar.bz2` with [`native/build_photorec.py`](native/build_photorec.py) and [`native/photorec_port.py`](native/photorec_port.py) |
| CPython embeddable | 3.12.7 x64 | PSF License | desktop worker runtime | [python-3.12.7-embed-amd64.zip](https://www.python.org/downloads/release/python-3127/) (`0d57bb6c…6bf44`) |
| pytsk3 | 20260715 (cp312, win_amd64) | Apache-2.0 | file-system metadata in the desktop worker | [PyPI](https://pypi.org/project/pytsk3/20260715/) (`65c73909…20eb7`) |
| scikit-learn, NumPy, SciPy, pandas | see `pyproject.toml` | BSD-3-Clause | CART training, analysis | PyPI |
| Pillow | see `pyproject.toml` | MIT-CMU (HPND) | synthetic corpus, previews | PyPI |
| Streamlit | see `pyproject.toml` | Apache-2.0 | cross-platform web UI | PyPI |
| Plotly | see `pyproject.toml` | MIT | dashboard charts | PyPI |
| ReportLab | see `pyproject.toml` | BSD | PDF case reports | PyPI |
| .NET Framework 4.8 / WPF | OS component | Microsoft terms | native desktop | ships with Windows 10/11 |

Notes

* `native/pytsk3_build_backend.py` is the pytsk3 project's own build back-end
  (Copyright 2010 Michael Cohen, Apache-2.0), kept for reference when rebuilding the
  binding; it is not imported by RecoverX.
* An earlier local bundle contained a `sleuthkit-4.15.0.tar.gz` whose hash differed from
  the official release archive; the provisioning script uses the official archive only.
* The Windows desktop executable and installer are unsigned.
