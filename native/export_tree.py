"""Build-time conversion of the archived, pinned model; desktop never unpickles user data."""
from pathlib import Path
import hashlib
import json
import joblib
from itertools import product

root=Path(__file__).resolve().parents[1]/'research/results/exp1/models/cart-20261030-193546'
model=root/'model.joblib'
assert hashlib.sha256(model.read_bytes()).hexdigest()=='843a3bb5d6fde8a8cf56eaf7e6cbac1d9324c1cb80be8dfa1c01e7d0fba91ffd'
clf=joblib.load(model)
t=clf.tree_
tree={'names':json.loads((root/'meta.json').read_text())['feature_names'],'left':t.children_left.tolist(),
      'right':t.children_right.tolist(),'feature':t.feature.tolist(),'threshold':t.threshold.tolist(),
      'label':[str(clf.classes_[v[0].argmax()]) for v in t.value]}
for n in (0,1,4,4.5,5,6,12,1024):
    values=[0]*len(tree['names'])
    values[tree['names'].index('n_deleted_named')]=n
    node=0
    while tree['left'][node]>=0:
        node=(tree['left'] if values[tree['feature'][node]]<=tree['threshold'][node] else tree['right'])[node]
    assert tree['label'][node]==clf.predict([values])[0]
(root/'portable-tree.json').write_text(json.dumps(tree,indent=2))
print('Archived sklearn model and portable tree agree on eight inputs covering both leaves.')
