RULE_POLICY_VERSION = "rule-v1"
RULE_POLICY_TEXT = """rule-v1 (frozen before test evaluation; pre-recovery features only)
  if fs_detected == 0            -> photorec   (no metadata to follow)
  elif n_deleted_nonzero == 0    -> photorec   (deleted entries carry no usable size/pointers)
  elif frac_deleted_nonzero < 1 or n_realloc > 0 -> combined (metadata partly damaged)
  else                           -> tsk"""


def rule_select(f: dict) -> tuple[str, str]:
    if f["fs_detected"] == 0:
        return "photorec", "no filesystem detected"
    if f["n_deleted_nonzero"] == 0:
        return "photorec", "no deleted entry with size > 0"
    if f["frac_deleted_nonzero"] < 1 or f["n_realloc"] > 0:
        return "combined", f"partial metadata (frac_nonzero={f['frac_deleted_nonzero']}, realloc={f['n_realloc']:.0f})"
    return "tsk", "all deleted entries retain size metadata"

