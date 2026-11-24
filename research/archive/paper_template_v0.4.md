<!-- GENERATED FILE SOURCE. Edit this template, then run: python3 scripts/build_paper.py --exp workspace/experiments/exp1
     Every double-brace field is filled from saved experiment records. Do not hand-edit numbers in paper.md. -->

# Does Learned Strategy Selection Speed Up Deleted-File Recovery? An Empirical Evaluation of CART over The Sleuth Kit and PhotoRec

**Authors:** [Team member 1], [Team member 2], [Team member 3], [Team member 4] — [Course / University]

## Abstract

Examiners recovering deleted files choose between filesystem-aware recovery, which relies on surviving metadata, and signature-based carving, which does not. We built RecoverX, an application that inspects a disk image with The Sleuth Kit (TSK), extracts pre-recovery features, and uses a CART decision tree to choose between TSK, PhotoRec, or both. We evaluated it on a controlled corpus of {{n_images}} synthetic raw images (FAT16, FAT32, ext4; four deletion scenarios; {{n_targets}} deleted ground-truth files) with SHA-256 ground-truth matching, image-grouped train/validation/test splits, and end-to-end timing that charges the selector for its own analysis. On {{n_test}} held-out images, CART-selected recovery was **not faster** than any fixed strategy: the median paired time difference was {{cart_vs_comb_dt_ms}} ms versus running both tools, {{cart_vs_pr_dt_ms}} ms versus PhotoRec alone, and {{cart_vs_tsk_dt_ms}} ms versus TSK alone, because the pre-recovery analysis (median {{ovh_analysis_ms}} ms) cost more than the engine time it saved on images of this size. CART matched a hand-written rule baseline in recall and reached acceptable quality on {{cart_acceptable}}/{{n_test}} images versus {{comb_acceptable}}/{{n_test}} for the combined strategy. We report this as a negative result for small images and identify the conditions under which selection could pay off.

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

with τ = {{tolerance}} and ties broken in the order TSK < PhotoRec < Combined. A selector *f* maps pre-recovery features *x(i)* to a strategy. Its end-to-end cost is *a(i) + t(i, f(x(i)))*, where *a(i)* is the analysis, feature-extraction and inference time. Fixed strategies pay no *a(i)*.

## 5. RecoverX Architecture

RecoverX is a Python package with separate modules for evidence handling (hashing, case store, manifest), tool adapters (common interface; TSK and PhotoRec), machine learning (features, labels, CART), orchestration, benchmarking and a Streamlit dashboard. Tools run as subprocesses with argument lists (never a shell), timeouts and process-group termination. Each run writes to its own empty directory; the source image's SHA-256 is computed before and after every run. The combined strategy runs TSK then PhotoRec sequentially and merges outputs by SHA-256 while keeping every engine's original output and an auditable mapping.

## 6. CART Methodology

We used `sklearn.tree.DecisionTreeClassifier` (Gini criterion). Hyper-parameters were chosen from a pre-registered grid (max depth 1–5, minimum leaf size 1, 2, 4) by validation balanced accuracy, preferring simpler trees on ties, then refit on train+validation. The selected configuration was {{selected_hp}}. The final tree:

```
{{tree}}
```

Feature importances are model-specific and are not causal claims.

## 7. Feature Engineering and Strategy Labelling

Eleven features are computed from `mmls`, `fsstat` and `fls` output only: filesystem detected/type, partition table present, image size, allocated-file count, deleted-entry count, named deleted entries, deleted entries with non-zero recorded size, their fraction, and reallocated entries. No feature uses ground truth, scenario labels or recovery outcomes. Labels are oracle-derived from measured phase-1 runs and are never available at prediction time. Label distribution (all images): {{label_dist}}; ties: {{label_ties}}; image/strategy cells whose recall varied across repeats: {{nondet}}.

## 8. Experimental Setup

Hardware/software: {{platform}}, {{cpu_count}} vCPUs, Python {{python}}, TSK {{tsk_version}}, PhotoRec {{photorec_version}}. Each (image, method) pair was run {{repeats}} times in randomised order within each image block; caches were not dropped, and repeats are summarised by the median. Phase 1 ran the three fixed strategies on every image ({{n_phase1_runs}} runs) to derive labels. Phase 3 ran all five methods on the held-out test images only ({{n_test_runs}} runs). Selector methods were charged for analysis, feature extraction and inference; all methods were charged for source hashing, inventory hashing, verification and deduplication.

## 9. Dataset and Ground Truth

{{n_images}} raw images were generated (48 or 96 MiB; FAT16, FAT32, ext4 × delete, overwrite, format, fragmented × 8 seeds). Seeds 0–4 form the training split ({{n_train}} images), seed 5 validation ({{n_val}}), seeds 6–7 test ({{n_test}}); each image is its own group, so no image contributes to more than one split. ext4 images were modified through the Linux kernel (loop mount); FAT images with mtools because the generation kernel lacked a vfat driver. Deleted targets totalled {{n_targets}}; extents measured before deletion showed {{n_fragmented}} fragmented targets, and {{n_overwritten}} targets had measured overlap with data written after deletion. All images and file contents are synthetic and labelled as such; they do not represent real devices.

## 10. Evaluation Metrics

Exact recall (SHA-256 match; each ground-truth file counted once), pooled recall, false-candidate rate (outputs matching neither a deleted target nor a still-allocated file, divided by all outputs), duplicate outputs, end-to-end time and its components, source-hash consistency, and — for selectors — agreement with oracle labels. "Acceptable quality" means recall within τ of the best fixed strategy on the same image. No partial-match metric is reported because none was pre-defined.

## 11. Results

All runs completed and the source SHA-256 was unchanged after every run: **{{all_unchanged}}**.

**Table 1. Held-out test images (n = {{n_test}}).**

{{summary_table}}

**Table 2. Paired comparisons, CART minus baseline, per test image (Wilcoxon signed-rank, two-sided; Holm correction over the four time comparisons).**

{{comparison_table}}

**Table 3. Mean recall by scenario (test images).**

{{scenario_table}}

**Table 4. Mean recall by filesystem (test images).**

{{fs_table}}

**Table 5. Selector predictions vs oracle labels (test images).** CART accuracy {{acc_cart}}; rule-v1 accuracy {{acc_rule}}. Fraction of predictions inside the eligible set: CART {{elig_cart}}, rule-v1 {{elig_rule}}.

CART:

{{cm_cart}}

Rule-v1:

{{cm_rule}}

**Table 6. Label sensitivity to the quality tolerance τ.**

{{sens_table}}

Selector overhead (median per test run): analysis {{ovh_analysis_ms}} ms, inference {{ovh_inference_ms}} ms.

## 12. Statistical Analysis

Paired, per-image comparisons on medians of {{repeats}} repeats use the Wilcoxon signed-rank test with rank-biserial correlation as effect size and Holm adjustment across the four time comparisons. With {{n_test}} test images the recall comparisons have low power; non-significant recall differences should not be read as equivalence. Time differences of a few milliseconds can be statistically detectable here yet are practically negligible.

## 13. Discussion

The primary question is answered negatively for this corpus. Selection cannot beat a fixed strategy on time when the cost of deciding is comparable to the cost of simply running both tools; on 48–96 MiB images every engine finished in tens of milliseconds, so the analysis step dominated. CART reproduced roughly what a short hand-written rule does: it learned that images whose deleted entries have lost their names (e.g. kernel-deleted ext4, reformatted volumes) need carving, and others can use TSK. It never predicted Combined, which had only a handful of labels. The combined strategy reached acceptable quality on every test image at a small time premium, which on this corpus makes "always run both" the strongest practical choice.

Selection could plausibly pay off where engine time is large relative to analysis — multi-hundred-gigabyte images, where PhotoRec's scan of unallocated space grows with size while `fls` grows with metadata volume. That hypothesis is **not tested** here.

## 14. Threats to Validity

- **Construct.** "Fragmented" images separate fragments only with allocated data, which TSK's FAT recovery handles by skipping allocated clusters; harder fragmentation was not produced. FAT deletion used mtools, not Windows or the Linux kernel.
- **Internal.** Labels derive from timings measured on the same machine; millisecond-scale timing noise could flip TSK/PhotoRec labels on easy images. Caches were not dropped.
- **External.** Small synthetic images, three filesystems, five file types, one tool version each. Results may not transfer to real devices, NTFS/APFS, encrypted or damaged media.
- **Statistical.** {{n_test}} test images and {{n_val}} validation images; model selection on 12 images is noisy.

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

*Generated from experiment `{{exp_name}}`.*
