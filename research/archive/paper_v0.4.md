<!-- GENERATED FILE SOURCE. Edit this template, then run: python3 scripts/build_paper.py --exp workspace/experiments/exp1
     Every double-brace field is filled from saved experiment records. Do not hand-edit numbers in paper.md. -->

# Does Learned Strategy Selection Speed Up Deleted-File Recovery? An Empirical Evaluation of CART over The Sleuth Kit and PhotoRec

**Authors:** [Team member 1], [Team member 2], [Team member 3], [Team member 4] — [Course / University]

## Abstract

Examiners recovering deleted files choose between filesystem-aware recovery, which relies on surviving metadata, and signature-based carving, which does not. We built RecoverX, an application that inspects a disk image with The Sleuth Kit (TSK), extracts pre-recovery features, and uses a CART decision tree to choose between TSK, PhotoRec, or both. We evaluated it on a controlled corpus of 96 synthetic raw images (FAT16, FAT32, ext4; four deletion scenarios; 664 deleted ground-truth files) with SHA-256 ground-truth matching, image-grouped train/validation/test splits, and end-to-end timing that charges the selector for its own analysis. On 24 held-out images, CART-selected recovery was **not faster** than any fixed strategy: the median paired time difference was +4.5 ms versus running both tools, +30.5 ms versus PhotoRec alone, and +48.8 ms versus TSK alone, because the pre-recovery analysis (median 28.7 ms) cost more than the engine time it saved on images of this size. CART matched a hand-written rule baseline in recall and reached acceptable quality on 22/24 images versus 24/24 for the combined strategy. We report this as a negative result for small images and identify the conditions under which selection could pay off.

**Keywords:** digital forensics, deleted file recovery, file carving, The Sleuth Kit, PhotoRec, decision trees, CART, tool selection, evaluation methodology

## 1. Introduction

Deleted-file recovery tools fall into two families. Filesystem-aware tools such as TSK [1], [7] follow metadata left behind after deletion (directory entries, inodes, allocation structures) and can restore names, paths and timestamps — but only while that metadata survives. Carvers such as PhotoRec [8] ignore the filesystem and search raw data for file signatures, which works after metadata loss but discards names and struggles with fragmentation [2]. A natural question is whether an examiner, or a tool, can predict *in advance* which approach an image needs, and so avoid running both.

RecoverX tests that idea with a deliberately simple, inspectable model: a CART decision tree [10] implemented in scikit-learn [9]. Our question is not whether CART can classify images, but whether choosing a strategy with it reduces **end-to-end** time — including the analysis needed to make the choice — while keeping recovery quality acceptable.

## 2. Background and Related Work

*Status: seed review. Bibliographic details marked "verified" were checked against the publisher or official page during this project; see docs/feasibility.md, Table L1, for the verification status of each entry. The team must complete the review (Week 1–2 of the plan) before submission.*

- **File carving and fragmentation.** Garfinkel [2] showed that fragmentation is common enough on real drives to matter for carving and proposed fast object validation to reassemble fragmented files. Laurenson [5] benchmarked six carving tools on an existing and a new dataset and found most struggled with a wider variety of file types.
- **Decision-theoretic carving.** Gladyshev and James [3] framed carving decisions in decision-theoretic terms for triage settings. This is the closest conceptual neighbour to strategy selection we found; RecoverX differs in selecting *between tools* rather than steering a carver internally.
- **ML for forensic triage.** Marturana and Tacconi [4] used supervised learning to categorise digital media during triage. RecoverX applies supervised learning to the recovery-method decision rather than to content categorisation.
- **Tool testing.** NIST's CFTT programme publishes deleted-file-recovery test specifications and results [6]; its emphasis on controlled ground truth informs our evaluation design.

## 3. Research Gap and Contributions

We did not find, in the sources reviewed so far, a published empirical evaluation of learned selection between a metadata-based recovery tool and a carver under an end-to-end time budget. **This gap is provisional**: the review is incomplete and we do not claim novelty for combining TSK, PhotoRec and CART. Our contributions are:

1. An open, tested implementation (RecoverX) with real TSK 4.12.1 / PhotoRec 7.1 integration, evidence hashing, and provenance-preserving deduplication.
2. A reproducible controlled corpus generator that records *observed* fragmentation and overwrite conditions rather than intended ones.
3. A pre-registered evaluation (objective, rule baseline and hyper-parameter grid frozen before testing) with image-grouped splits and full overhead accounting.
4. A negative result, with its causes and boundary conditions.

## 4. Problem Formulation

For image *i* and strategy *s* ∈ {TSK, PhotoRec, Combined}, let *q(i,s)* be exact-file recall (fraction of deleted ground-truth files whose SHA-256 appears among outputs) and *t(i,s)* the median end-to-end time over repeats. The oracle training label is

  *s\*(i) = argmin_{s ∈ E(i)} t(i,s)*,  *E(i) = { s : q(i,s) ≥ max_s q(i,s) − τ }*,

with τ = 0.05 and ties broken in the order TSK < PhotoRec < Combined. A selector *f* maps pre-recovery features *x(i)* to a strategy. Its end-to-end cost is *a(i) + t(i, f(x(i)))*, where *a(i)* is the analysis, feature-extraction and inference time. Fixed strategies pay no *a(i)*.

## 5. RecoverX Architecture

RecoverX is a Python package with separate modules for evidence handling (hashing, case store, manifest), tool adapters (common interface; TSK and PhotoRec), machine learning (features, labels, CART), orchestration, benchmarking and a Streamlit dashboard. Tools run as subprocesses with argument lists (never a shell), timeouts and process-group termination. Each run writes to its own empty directory; the source image's SHA-256 is computed before and after every run. The combined strategy runs TSK then PhotoRec sequentially and merges outputs by SHA-256 while keeping every engine's original output and an auditable mapping.

## 6. CART Methodology

We used `sklearn.tree.DecisionTreeClassifier` (Gini criterion). Hyper-parameters were chosen from a pre-registered grid (max depth 1–5, minimum leaf size 1, 2, 4) by validation balanced accuracy, preferring simpler trees on ties, then refit on train+validation. The selected configuration was {'max_depth': 1, 'min_samples_leaf': 4, 'val_balanced_accuracy': 0.8125, 'val_accuracy': 0.8333333333333334}. The final tree:

```
|--- n_deleted_named <= 4.50
|   |--- class: photorec
|--- n_deleted_named >  4.50
|   |--- class: tsk
```

Feature importances are model-specific and are not causal claims.

## 7. Feature Engineering and Strategy Labelling

Eleven features are computed from `mmls`, `fsstat` and `fls` output only: filesystem detected/type, partition table present, image size, allocated-file count, deleted-entry count, named deleted entries, deleted entries with non-zero recorded size, their fraction, and reallocated entries. No feature uses ground truth, scenario labels or recovery outcomes. Labels are oracle-derived from measured phase-1 runs and are never available at prediction time. Label distribution (all images): {'tsk': 23, 'photorec': 68, 'combined': 5}; ties: 0; image/strategy cells whose recall varied across repeats: 0.

## 8. Experimental Setup

Hardware/software: Linux-6.18.44-fc-v185-x86_64-with-glibc2.39, 2 vCPUs, Python 3.13.18, TSK 4.12.1, PhotoRec 7.1. Each (image, method) pair was run 3 times in randomised order within each image block; caches were not dropped, and repeats are summarised by the median. Phase 1 ran the three fixed strategies on every image (864 runs) to derive labels. Phase 3 ran all five methods on the held-out test images only (360 runs). Selector methods were charged for analysis, feature extraction and inference; all methods were charged for source hashing, inventory hashing, verification and deduplication.

## 9. Dataset and Ground Truth

96 raw images were generated (48 or 96 MiB; FAT16, FAT32, ext4 × delete, overwrite, format, fragmented × 8 seeds). Seeds 0–4 form the training split (60 images), seed 5 validation (12), seeds 6–7 test (24); each image is its own group, so no image contributes to more than one split. ext4 images were modified through the Linux kernel (loop mount); FAT images with mtools because the generation kernel lacked a vfat driver. Deleted targets totalled 664; extents measured before deletion showed 33 fragmented targets, and 53 targets had measured overlap with data written after deletion. All images and file contents are synthetic and labelled as such; they do not represent real devices.

## 10. Evaluation Metrics

Exact recall (SHA-256 match; each ground-truth file counted once), pooled recall, false-candidate rate (outputs matching neither a deleted target nor a still-allocated file, divided by all outputs), duplicate outputs, end-to-end time and its components, source-hash consistency, and — for selectors — agreement with oracle labels. "Acceptable quality" means recall within τ of the best fixed strategy on the same image. No partial-match metric is reported because none was pre-defined.

## 11. Results

All runs completed and the source SHA-256 was unchanged after every run: **True**.

**Table 1. Held-out test images (n = 24).**

| Method | Median of per-image median time (s) | IQR (s) | Mean recall | Pooled recall | Images within tolerance | Mean false-candidate rate | Strategies used |
|---|---|---|---|---|---|---|---|
| TSK only | 0.154 | 0.075 | 0.400 | 0.269 | 8/24 | 0.110 | tsk:24 |
| PhotoRec only | 0.144 | 0.081 | 0.760 | 0.808 | 19/24 | 0.059 | photorec:24 |
| Combined (TSK→PhotoRec) | 0.174 | 0.089 | 0.842 | 0.850 | 24/24 | 0.106 | combined:24 |
| Rule-based (rule-v1) | 0.180 | 0.093 | 0.807 | 0.820 | 22/24 | 0.120 | tsk:10, photorec:12, combined:2 |
| CART-selected (RecoverX) | 0.182 | 0.091 | 0.815 | 0.832 | 22/24 | 0.120 | photorec:18, tsk:6 |

**Table 2. Paired comparisons, CART minus baseline, per test image (Wilcoxon signed-rank, two-sided; Holm correction over the four time comparisons).**

| CART vs | Median Δtime (s) | CART faster on | Wilcoxon p (time) | Holm-adjusted p | Rank-biserial r | Mean Δrecall | Images CART lower / higher recall | Wilcoxon p (recall) |
|---|---|---|---|---|---|---|---|---|
| TSK only | +0.0488 | 0/24 | 1.2e-07 | 4.8e-07 | +1.00 | +0.415 | 1 / 16 | 0.00091 |
| PhotoRec only | +0.0305 | 1/24 | 3e-05 | 9e-05 | +0.88 | +0.055 | 0 / 3 | 0.109 |
| Combined (TSK→PhotoRec) | +0.0045 | 4/24 | 0.006 | 0.012 | +0.63 | -0.027 | 2 / 0 | 0.180 |
| Rule-based (rule-v1) | +0.0023 | 5/24 | 0.039 | 0.039 | +0.48 | +0.008 | 1 / 2 | 1.000 |

**Table 3. Mean recall by scenario (test images).**

| Scenario | TSK only | PhotoRec only | Combined (TSK→PhotoRec) | Rule-based (rule-v1) | CART-selected (RecoverX) |
|---|---|---|---|---|---|
| delete | 0.667 | 0.893 | 1.000 | 1.000 | 0.917 |
| overwrite | 0.129 | 0.559 | 0.583 | 0.444 | 0.559 |
| format | 0.136 | 0.895 | 0.895 | 0.895 | 0.895 |
| fragmented | 0.667 | 0.694 | 0.889 | 0.889 | 0.889 |

**Table 4. Mean recall by filesystem (test images).**

| Filesystem | TSK only | PhotoRec only | Combined (TSK→PhotoRec) | Rule-based (rule-v1) | CART-selected (RecoverX) |
|---|---|---|---|---|---|
| ext4 | 0.102 | 0.783 | 0.783 | 0.783 | 0.783 |
| fat16 | 0.525 | 0.699 | 0.824 | 0.774 | 0.761 |
| fat32 | 0.571 | 0.799 | 0.918 | 0.864 | 0.900 |

**Table 5. Selector predictions vs oracle labels (test images).** CART accuracy 0.833; rule-v1 accuracy 0.708. Fraction of predictions inside the eligible set: CART 0.917, rule-v1 0.917.

CART:

| oracle \ predicted | tsk | photorec | combined |
|---|---|---|---|
| tsk | 4 | 1 | 0 |
| photorec | 2 | 16 | 0 |
| combined | 0 | 1 | 0 |

Rule-v1:

| oracle \ predicted | tsk | photorec | combined |
|---|---|---|---|
| tsk | 5 | 0 | 0 |
| photorec | 4 | 12 | 2 |
| combined | 1 | 0 | 0 |

**Table 6. Label sensitivity to the quality tolerance τ.**

| Tolerance | Label distribution (all 96 images) | CART agreement with re-derived test labels |
|---|---|---|
| 0.0 | {'tsk': 23, 'photorec': 68, 'combined': 5} | 0.833 |
| 0.05 | {'tsk': 23, 'photorec': 68, 'combined': 5} | 0.833 |
| 0.1 | {'tsk': 23, 'photorec': 69, 'combined': 4} | 0.833 |
| 0.2 | {'tsk': 29, 'photorec': 67} | 0.833 |

Selector overhead (median per test run): analysis 28.7 ms, inference 0.60 ms.

## 12. Statistical Analysis

Paired, per-image comparisons on medians of 3 repeats use the Wilcoxon signed-rank test with rank-biserial correlation as effect size and Holm adjustment across the four time comparisons. With 24 test images the recall comparisons have low power; non-significant recall differences should not be read as equivalence. Time differences of a few milliseconds can be statistically detectable here yet are practically negligible.

## 13. Discussion

The primary question is answered negatively for this corpus. Selection cannot beat a fixed strategy on time when the cost of deciding is comparable to the cost of simply running both tools; on 48–96 MiB images every engine finished in tens of milliseconds, so the analysis step dominated. CART reproduced roughly what a short hand-written rule does: it learned that images whose deleted entries have lost their names (e.g. kernel-deleted ext4, reformatted volumes) need carving, and others can use TSK. It never predicted Combined, which had only a handful of labels. The combined strategy reached acceptable quality on every test image at a small time premium, which on this corpus makes "always run both" the strongest practical choice.

Selection could plausibly pay off where engine time is large relative to analysis — multi-hundred-gigabyte images, where PhotoRec's scan of unallocated space grows with size while `fls` grows with metadata volume. That hypothesis is **not tested** here.

## 14. Threats to Validity

- **Construct.** "Fragmented" images separate fragments only with allocated data, which TSK's FAT recovery handles by skipping allocated clusters; harder fragmentation was not produced. FAT deletion used mtools, not Windows or the Linux kernel.
- **Internal.** Labels derive from timings measured on the same machine; millisecond-scale timing noise could flip TSK/PhotoRec labels on easy images. Caches were not dropped.
- **External.** Small synthetic images, three filesystems, five file types, one tool version each. Results may not transfer to real devices, NTFS/APFS, encrypted or damaged media.
- **Statistical.** 24 test images and 12 validation images; model selection on 12 images is noisy.

## 15. Limitations

PhotoRec is run with `partition_none`, so partition offsets found by `mmls` are used by TSK but not passed to PhotoRec. Only raw images were verified. The evidence manifest supports auditability but does not by itself establish chain of custody or legal admissibility.

## 16. Conclusion and Future Work

On a controlled corpus of small images, a CART strategy selector did not reduce end-to-end recovery time relative to fixed strategies, because its own analysis cost exceeded the savings; it matched a simple rule in quality. Future work: larger images to test the size hypothesis, kernel-level FAT and NTFS deletion, genuinely interleaved fragmentation, public corpora (e.g., NIST CFReDS) as an independent test set, and cost-sensitive objectives that weight recall loss explicitly.

## References

[1] B. Carrier, *File System Forensic Analysis*. Boston, MA, USA: Addison-Wesley, 2005. *(verify ISBN before submission)*

[2] S. L. Garfinkel, "Carving contiguous and fragmented files with fast object validation," *Digital Investigation*, vol. 4, suppl., pp. 2–12, 2007, doi: 10.1016/j.diin.2007.06.017.

[3] P. Gladyshev and J. I. James, "Decision-theoretic file carving," *Digital Investigation*, 2017. *(volume, pages and DOI not yet verified — ScienceDirect PII S1742287617301329)*

[4] F. Marturana and S. Tacconi, "A machine learning-based triage methodology for automated categorization of digital media," *Digital Investigation*, vol. 10, no. 2, pp. 193–204, 2013, doi: 10.1016/j.diin.2013.01.001.

[5] T. Laurenson, "Performance analysis of file carving tools," in *Security and Privacy Protection in Information Processing Systems (SEC 2013)*, IFIP AICT, vol. 405, pp. 419–433, 2013, doi: 10.1007/978-3-642-39218-4_31.

[6] J. R. Lyle, "Deleted file recovery tool testing results," presented at the AAFS 65th Annual Scientific Meeting, Washington, DC, USA, Feb. 2013. [Online]. Available: https://www.nist.gov/publications/deleted-file-recovery-tool-testing-results

[7] B. Carrier, "The Sleuth Kit," [Online]. Available: https://www.sleuthkit.org/ (version 4.12.1 used).

[8] C. Grenier, "PhotoRec," CGSecurity. [Online]. Available: https://www.cgsecurity.org/wiki/PhotoRec (version 7.1 used).

[9] F. Pedregosa *et al.*, "Scikit-learn: Machine learning in Python," *Journal of Machine Learning Research*, vol. 12, pp. 2825–2830, 2011. *(verify before submission)*

[10] L. Breiman, J. Friedman, R. Olshen, and C. Stone, *Classification and Regression Trees*. Wadsworth, 1984. *(verify before submission)*

*Generated from experiment `exp1`.*
