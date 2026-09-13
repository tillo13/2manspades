"""Fit with Python + numpy; runtime uses only exported coefficients. See WIN_PROBABILITY.md."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utilities.win_probability import FEATURES, features

# Score/strength directions prevent sparse high-strength games from reversing their meaning.
BOUNDS = [(None,None),(0,None),(None,0),(0,None),(None,0),(None,0),(0,None),
          (None,0),(None,0),(None,None),(None,None),(None,None)]


def expit(z):
    return 1 / (1 + np.exp(-np.clip(z, -35, 35)))


def fit(x, y):
    penalty = np.eye(x.shape[1]); penalty[0,0] = 0
    lower = np.array([-np.inf if lo is None else lo for lo,hi in BOUNDS])
    upper = np.array([np.inf if hi is None else hi for lo,hi in BOUNDS])
    def loss(w):
        z = x @ w
        return np.logaddexp(0,z).sum() - y @ z + .5 * w @ penalty @ w
    w = np.zeros(x.shape[1])
    for iteration in range(1000):
        p = expit(x @ w)
        grad = x.T @ (p-y) + penalty @ w
        free = ~(((w <= lower + 1e-10) & (grad > 0)) | ((w >= upper - 1e-10) & (grad < 0)))
        if np.max(np.abs(grad[free]), initial=0) < 1e-5: return w
        hessian = x.T @ ((p*(1-p))[:,None] * x) + penalty
        direction = np.zeros_like(w)
        direction[free] = -np.linalg.solve(hessian[np.ix_(free,free)], grad[free])
        old = loss(w)
        for step in range(40):
            candidate = np.clip(w + direction * .5**step, lower, upper)
            new = loss(candidate)
            if new <= old + 1e-4 * grad @ (candidate-w): break
        else: raise RuntimeError('Fit failed line search')
        if np.max(np.abs(candidate-w)) < 1e-8: return candidate
        w = candidate
    raise RuntimeError('Fit did not converge')


def metrics(rows, y, pred, baseline):
    bins=[]
    for lo in range(0,100,20):
        mask=(pred>=lo/100)&(pred<(lo+20)/100)
        if mask.any():
            bins.append(dict(range=f'{lo}-{lo+20}%',positions=int(mask.sum()),
                games=len({r['game'] for r,m in zip(rows,mask) if m}),
                predicted=round(float(pred[mask].mean())*100,1),observed=round(float(y[mask].mean())*100,1)))
    return dict(games=len({r['game'] for r in rows}),positions=len(rows),
                brier=round(float(np.mean((y-pred)**2)),4),
                baseline_brier=round(float(np.mean((y-baseline)**2)),4),
                mean_predicted=round(float(pred.mean())*100,1),observed=round(float(y.mean())*100,1),bins=bins)


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('input'); ap.add_argument('--output',default='utilities/win_probability_model.json')
    a=ap.parse_args()
    rows=json.loads(Path(a.input).read_text())
    x=np.array([features(r['p'],r['c'],r['pb'],r['cb'],r['difficulty'],r['next_player'],r['source']) for r in rows])
    y=np.array([r['won'] for r in rows])
    folds=np.array([int(hashlib.sha256(r['game'].encode()).hexdigest()[:8],16)%5 for r in rows])
    pred=np.zeros(len(rows)); baseline=np.zeros(len(rows))
    for fold in range(5):
        test=folds==fold; train=~test
        assert not ({r['game'] for r,t in zip(rows,test) if t}&{r['game'] for r,t in zip(rows,train) if t})
        pred[test]=expit(x[test]@fit(x[train],y[train]))
        for source in ('human','otto','persona'):
            cohort=np.array([r['source']==source for r in rows]); baseline[test&cohort]=y[train&cohort].mean()
    validation={'all':metrics(rows,y,pred,baseline)}
    for source in ('human','otto','persona'):
        mask=np.array([r['source']==source for r in rows])
        validation[source]=metrics([r for r,m in zip(rows,mask) if m],y[mask],pred[mask],baseline[mask])
    recent=np.array([r['source']=='human' and r['date']>='2026-09-07' for r in rows])
    if recent.any(): validation['recent_human']=metrics([r for r,m in zip(rows,recent) if m],y[recent],pred[recent],baseline[recent])
    if validation['human']['brier']>=validation['human']['baseline_brier']:
        raise RuntimeError('Model does not improve on the held-out human baseline')
    model=dict(version='win-v1',trained_at=datetime.now(timezone.utc).isoformat(),features=FEATURES,
        coefficients=[round(float(w),10) for w in fit(x,y)],
        training=dict(positions=len(rows),games=len({r['game'] for r in rows}),
                      sources=dict(Counter(r['source'] for r in rows)),first=min(r['date'] for r in rows),last=max(r['date'] for r in rows)),
        validation=validation)
    Path(a.output).write_text(json.dumps(model,indent=2)+'\n')
    print(json.dumps(model,indent=2))

if __name__=='__main__': main()
