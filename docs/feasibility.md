# Milestone 0 — Feasibility Report (Gate A)

Date: 2026-10-30. Everything below was observed in the build environment, not assumed.

## 1. Environment (observed)

| Item | Observed |
|---|---|
| OS | Ubuntu 24.04.5 LTS, Linux 6.18 x86_64 (VM), running as root |
| Python | 3.13.18 |
| Disk | ~30 GB free |
| Prior repository | none — project created from scratch |
| Packages | scikit-learn 1.9.1, pandas 3.0.5, numpy, scipy 1.18.1, joblib 1.6.0, streamlit 1.66.1, plotly 7.1.0, Pillow 12.3.0, pytest 9.1.1 |
| Forensic tools | installed with `apt-get install sleuthkit testdisk` → **TSK 4.12.1**, **PhotoRec 7.1** (testdisk 7.1-5) |
| Kernel filesystems | **ext4 only** (`/proc/filesystems`); no vfat module, so FAT cannot be loop-mounted |

## 2. Verified tool behaviour

| Question | Verified answer | How |
|---|---|---|
| `tsk_recover` default scope | recovers **unallocated** files only (`-a` allocated, `-e` all) | `tsk_recover` usage text |
| `fls -r -l -p` columns | type, `*` if deleted, inode, `(realloc)` flag, path, 4 times, **size (6th tab field)**, uid, gid | ran on FAT16 and ext4 images |
| `mmls` on partition-less image | exit code 1 ("cannot determine partition type") → treat as no volume system, offset 0 | ran |
| PhotoRec unattended mode | `photorec /log /d <dir>/recup /cmd <image> <script>` — **`/cmd` must be its own argument**; with it fused into the script PhotoRec tried to open the script as a file | first attempt failed, second succeeded |
| PhotoRec log location | `photorec.log` is written to the **current working directory** → adapter sets cwd to the run directory | observed |
| PhotoRec `freespace` | restricts carving to unallocated space; log shows `fat16_remove_used_space` / `ext2_remove_used_space` | ran on FAT16 and ext4 |
| PhotoRec provenance | `recup.1/report.xml` (DFXML-style) lists carved byte runs → parsed into `original_metadata.carved_byte_runs` | ran |
| PhotoRec names | not restored (`f0000160.png`) | observed |
| Kernel ext4 deletion | removes names (`$OrphanFiles/OrphanFile-N`), size 0 → **TSK recovered 0/2**, PhotoRec 2/2 exact | loop mount test |
| `debugfs rm` deletion | leaves extents intact → TSK recovers. **Not realistic** → generator uses the kernel for ext4 | compared |
| `mdel` (mtools) | zeroes the FAT chain, like real FAT deletion | dumped FAT before/after |
| `istat` on FAT | pads the last cluster's sector list with `0` entries → filtered (would otherwise fake fragmentation) | inspected raw output |
| TSK FAT deleted-file recovery | skips clusters that are currently allocated → recovers fragments separated only by allocated data | explained 100 % TSK recall on some "fragmented" FAT16 images |
| `mkfs.ext4` re-format | with lazy inode-table init, old inodes can survive → TSK still recovered some files after "format" | observed in phase-1 data |

**Incident recorded:** during an early manual test, a FAT loop-mount silently failed (no vfat driver)
and a filler `dd` wrote to the host directory until the disk was full. The file was removed
immediately (disk back to 30 GB free). The generator now (a) refuses to write unless
`os.path.ismount()` is true, and (b) caps any filler at the image size.

## 3. Supported scope (claimed only where verified)

- Image format: **raw** (`.img .dd .raw .bin .001`). E01/VMDK libraries are installed with TSK but were **not tested** → not claimed.
- Filesystems exercised: FAT16, FAT32, ext4. NTFS/exFAT/APFS: **not tested**.
- Partitioned images: `mmls` offsets are parsed and passed to TSK; PhotoRec runs with `partition_none` (scans the whole image). Covered by a unit test of the parser only; no partitioned image in the benchmark.

## 4. Public datasets

NIST CFTT publishes deleted-file-recovery specifications and test results (Lyle, 2013; nist.gov). CFReDS images were **not downloaded** (shell network access is limited to package registries in this environment). They are the recommended independent test set for future work; the team must check each image's documentation and usage terms before use.

## 5. Literature review — Table L1 (seed; team to extend)

| # | Reference | Objective / method | Data | Relation to RecoverX | Verification status |
|---|---|---|---|---|---|
| 1 | Garfinkel, *Carving contiguous and fragmented files with fast object validation*, Digital Investigation 4(S), 2–12, 2007, doi:10.1016/j.diin.2007.06.017 | Fast validators (JPEG, MSOLE, ZIP) to reassemble fragmented files; argues fragmentation matters (secondary-market drive survey) | used drives | Motivates fragmentation as a carving weakness | ✅ ScienceDirect + DFRWS page |
| 2 | Gladyshev & James, *Decision-theoretic file carving*, Digital Investigation, 2017 (PII S1742287617301329) | Decision-theoretic carving for triage | — | Closest conceptual neighbour (decisions under time) | ⚠️ title/authors/journal/year seen in search results; **volume, pages, DOI and abstract not verified** (publisher pages blocked) |
| 3 | Marturana & Tacconi, *A machine learning-based triage methodology for automated categorization of digital media*, Digital Investigation 10(2), 193–204, 2013, doi:10.1016/j.diin.2013.01.001 | Supervised ML for triage | — | ML in triage, but for content categorisation | ✅ via secondary bibliographic listing; check the publisher page |
| 4 | Laurenson, *Performance analysis of file carving tools*, SEC 2013, IFIP AICT 405, 419–433, doi:10.1007/978-3-642-39218-4_31 | Benchmarks six carvers; new dataset | own dataset | Carver performance varies with file types | ✅ Springer page (tool names not visible: paywall) |
| 5 | Lyle, *Deleted file recovery tool testing results*, AAFS 2013, NIST CFTT | Tool testing over deletion scenarios | CFTT test sets | Ground-truth evaluation design | ✅ nist.gov |
| 6 | Carrier, *File System Forensic Analysis*, Addison-Wesley, 2005 | Filesystem internals | — | Background for TSK behaviour | ⚠️ well-known; ISBN to verify |

Searches still to do (Week 1–2): automated forensic tool selection; combining metadata recovery with carving; cost-sensitive selection under time limits; automated ground-truth evaluation (e.g., Garfinkel et al. on forensic corpora). **Originality is not claimed**; the contribution is an empirical evaluation.

## 6. Risks and mitigations

| Risk | Effect | Mitigation taken |
|---|---|---|
| Engine runtimes are milliseconds on small images | Timing differences tiny, selection overhead dominates | Reported as the main finding; larger images listed as future work |
| Class imbalance (Combined = 5/96 labels) | CART never predicts Combined | Reported; rule baseline compared; sensitivity to τ reported |
| FAT via mtools, not kernel | Construct validity | Documented in paper (Threats) |
| Synthetic "fragmentation" is easy for TSK | Overstates TSK on fragmented FAT | Documented; observed extents stored per file |
| Small validation set (12 images) | Noisy model selection | Pre-registered tie rule favouring simple trees |
| Windows untested | Students on Windows may struggle | `docs/installation_and_user_guide.md` gives WSL2 path as the supported route |
