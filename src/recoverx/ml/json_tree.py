"""Non-executable CART inference format; no pickle/joblib deserialization."""
from __future__ import annotations
from types import SimpleNamespace
import numpy as np
from ..exceptions import ModelError
from .features import FEATURE_NAMES


class JsonTree:
    def __init__(self, doc):
        try:
            classes = doc["classes"]
            nodes = doc["nodes"]
            if doc["format"] != "recoverx-cart-json-v1" or not 1 <= len(nodes) <= 100000:
                raise ValueError("unknown format or invalid node count")
            if not classes or len(set(classes)) != len(classes) or not set(classes) <= {"tsk", "photorec", "combined"}:
                raise ValueError("invalid classes")
            n, seen = len(nodes), set()
            pending = [0]
            while pending:
                index = pending.pop()
                if index in seen or index < 0 or index >= n:
                    raise ValueError("tree contains cycles, shared children or invalid indices")
                seen.add(index)
                node = nodes[index]
                left, right, feature = node["left"], node["right"], node["feature"]
                if not all(isinstance(v, int) for v in (left, right, feature)):
                    raise ValueError("node indices must be integers")
                if left == right == -1:
                    pass
                elif left > index and right > index and 0 <= feature < len(FEATURE_NAMES):
                    pending.extend((left, right))
                else:
                    raise ValueError("invalid branching node")
                values = np.asarray(node["values"], dtype=float)
                if values.shape != (len(classes),) or not np.isfinite(values).all() or (values < 0).any() or not np.isfinite(values.sum()) or values.sum() <= 0:
                    raise ValueError("invalid class frequencies")
                if not np.isfinite(node["threshold"]):
                    raise ValueError("non-finite threshold")
            if len(seen) != n:
                raise ValueError("unreachable nodes")
            self.nodes = nodes
            self.classes_ = np.array(classes)
            self.feature_importances_ = np.asarray(doc["feature_importances"], dtype=float)
            if self.feature_importances_.shape != (len(FEATURE_NAMES),) or not np.isfinite(self.feature_importances_).all():
                raise ValueError("invalid importances")
            self.tree_ = SimpleNamespace(children_left=np.array([x["left"] for x in nodes]),
                                        children_right=np.array([x["right"] for x in nodes]),
                                        feature=np.array([x["feature"] for x in nodes]),
                                        threshold=np.array([x["threshold"] for x in nodes]))
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            raise ModelError(f"Invalid CART JSON: {exc}") from exc

    def _path(self, row):
        row = np.asarray(row, dtype=np.float32)  # sklearn CART uses float32 input
        path, index = [], 0
        while True:
            path.append(index)
            node = self.nodes[index]
            if node["left"] == -1:
                return path
            index = node["left"] if row[node["feature"]] <= node["threshold"] else node["right"]

    def predict_proba(self, X):
        values = [np.asarray(self.nodes[self._path(row)[-1]]["values"], dtype=float) for row in X]
        return np.array([v / v.sum() for v in values])

    def predict(self, X):
        return self.classes_[self.predict_proba(X).argmax(axis=1)]

    def decision_path(self, X):
        return SimpleNamespace(indices=np.array(self._path(X[0])))


def export_tree(model):
    tree = model.tree_
    return {"format": "recoverx-cart-json-v1", "classes": model.classes_.tolist(),
            "feature_importances": model.feature_importances_.tolist(),
            "nodes": [{"left": int(tree.children_left[i]), "right": int(tree.children_right[i]),
                       "feature": int(tree.feature[i]), "threshold": float(tree.threshold[i]),
                       "values": tree.value[i][0].tolist()} for i in range(tree.node_count)]}
