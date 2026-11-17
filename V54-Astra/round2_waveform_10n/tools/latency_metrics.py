"""Causal-output waveform evaluation. Offline centered medians are evaluators only.

Positive lag means OUTPUT LAGS raw: corr(raw[t], output[t+lag]).
No output is shifted for zero-lag scores, range scores, or event detection.
Raw observations are a waveform reference, not physical displacement ground truth.
"""
import numpy as np


def _correlation(x,y,min_pairs=30):
    valid=np.isfinite(x)&np.isfinite(y)
    if valid.sum()<min_pairs:return float('nan'),int(valid.sum())
    a=x[valid]-np.mean(x[valid]);b=y[valid]-np.mean(y[valid])
    denominator=np.sqrt(np.dot(a,a)*np.dot(b,b))
    return (float(np.dot(a,b)/denominator) if denominator>1e-12 else float('nan')),int(valid.sum())


def _centered_median5(values):
    out=np.full_like(values,np.nan,dtype=float)
    if len(values)<5:return out
    windows=np.lib.stride_tricks.sliding_window_view(values,5)
    good=np.isfinite(windows).all(axis=1)
    out[2:-2][good]=np.median(windows[good],axis=1)
    return out


def _grid(ts,raw,out):
    ts=np.asarray(ts,dtype=np.int64);raw=np.asarray(raw,float);out=np.asarray(out,float)
    assert len(ts)==len(raw)==len(out)
    if not len(ts):return ts,raw,out,0
    assert np.all(np.diff(ts)>0),'Waveform evaluation requires strictly increasing timestamps'
    # Anchor the cadence to this window's first acquisition, not civil-minute
    # boundaries: 23:31:59.995 -> 23:33:00.000 is one frame, not a gap.
    first=int(ts[0]);bins=np.rint((ts-first)/60000.0).astype(np.int64);length=int(bins[-1])+1
    x=np.full(length,np.nan);y=x.copy();clock=first+np.arange(length,dtype=np.int64)*60000
    unique,counts=np.unique(bins,return_counts=True);duplicate=set(unique[counts>1].tolist())
    # A duplicate minute is omitted, never averaged or silently selected.
    keep=np.array([int(b) not in duplicate for b in bins],bool)
    x[bins[keep]]=raw[keep];y[bins[keep]]=out[keep];clock[bins[keep]]=ts[keep]
    return clock,x,y,len(duplicate)


def _lag_scores(raw,out,max_lag):
    scores=[]
    for lag in range(-max_lag,max_lag+1):
        if lag>0:a,b=raw[:-lag],out[lag:]
        elif lag<0:a,b=raw[-lag:],out[:lag]
        else:a,b=raw,out
        corr,n=_correlation(a,b);scores.append((lag,corr,n))
    finite=[v for v in scores if np.isfinite(v[1])]
    if not finite:return dict(corr_zero=float('nan'),corr_best=float('nan'),best_lag_min=float('nan'),
        lag_boundary=False,lag_gain=float('nan'),lag_peak_margin=float('nan'),pairs=0)
    best=max(finite,key=lambda v:(v[1],-abs(v[0]),-v[0]))
    zero=next(v for v in scores if v[0]==0)
    distant=[v[1] for v in finite if abs(v[0]-best[0])>=2]
    return dict(corr_zero=zero[1],corr_best=best[1],best_lag_min=best[0],lag_boundary=abs(best[0])==max_lag,
        lag_gain=best[1]-zero[1],lag_peak_margin=best[1]-max(distant) if distant else float('nan'),pairs=zero[2])


def _extrema(values,sign=1,radius=30,min_separation=15,prominence_fraction=.10):
    good=np.isfinite(values)
    if good.sum()<61:return []
    finite=values[good];span=float(np.quantile(finite,.95)-np.quantile(finite,.05))
    if span<.05:return []
    x=sign*values;threshold=prominence_fraction*span;candidates=[];i=1
    while i<len(x)-1:
        if not (np.isfinite(x[i-1]) and np.isfinite(x[i]) and x[i]>x[i-1]+1e-12):i+=1;continue
        j=i
        while j+1<len(x) and np.isfinite(x[j+1]) and abs(x[j+1]-x[i])<=1e-12:j+=1
        if j+1>=len(x) or not np.isfinite(x[j+1]) or x[j+1]>=x[i]-1e-12:i=j+1;continue
        center=(i+j)//2;lo=max(0,center-radius);hi=min(len(x),center+radius+1)
        left=x[lo:i];right=x[j+1:hi]
        # Require ten contiguous finite samples on each side; never bridge gaps.
        if len(left)>=10 and len(right)>=10 and np.isfinite(left).all() and np.isfinite(right).all():
            prominence=float(min(x[i]-left.min(),x[i]-right.min()))
            if prominence>=threshold:candidates.append((center,prominence))
        i=j+1
    chosen=[]
    for index,prominence in sorted(candidates,key=lambda p:p[1],reverse=True):
        if all(abs(index-v[0])>=min_separation for v in chosen):chosen.append((index,prominence))
    return sorted(chosen)


def _event_matches(ts,raw,out,max_shift_min=10):
    differences=[];reference_count=0;output_count=0
    for sign in [1,-1]:
        a=_extrema(raw,sign);b=_extrema(out,sign);reference_count+=len(a);output_count+=len(b)
        edges=[]
        for i,_ in a:
            for j,_ in b:
                delta=(ts[j]-ts[i])/60000.0
                if abs(delta)<=max_shift_min:edges.append((abs(delta),i,j,delta))
        used_a=set();used_b=set()
        for _,i,j,delta in sorted(edges):
            if i in used_a or j in used_b:continue
            used_a.add(i);used_b.add(j);differences.append(float(delta))
    return dict(reference_events=reference_count,output_events=output_count,matched_events=len(differences),
        event_recall=len(differences)/reference_count if reference_count else float('nan'),
        event_precision=len(differences)/output_count if output_count else float('nan'),
        event_signed_median_min=float(np.median(differences)) if differences else float('nan'),
        event_abs_p90_min=float(np.quantile(np.abs(differences),.9)) if differences else float('nan'))


def compute_metrics(ts,raw,out,max_lag_frames=10):
    clock,x,y,duplicates=_grid(ts,raw,out);valid=np.isfinite(x)&np.isfinite(y)
    sx,sy=_centered_median5(x),_centered_median5(y)
    native=_lag_scores(x,y,max_lag_frames);slow=_lag_scores(sx,sy,max_lag_frames)
    def spread(a):
        a=a[np.isfinite(a)];return float(np.quantile(a,.95)-np.quantile(a,.05)) if len(a) else float('nan')
    raw_span,out_span=spread(x),spread(y)
    metrics=dict(valid_pairs=int(valid.sum()),grid_minutes=len(x),duplicate_minute_bins=duplicates,
        raw_p95p5_px=raw_span,output_p95p5_px=out_span)
    for prefix,values in [('native',native),('slow',slow)]:metrics.update({prefix+'_'+key:value for key,value in values.items()})
    # A high lag-optimized correlation is only a phase measurability screen.
    # It is never substituted for the zero-lag waveform fidelity score.
    metrics['lag_interpretable']=bool(raw_span>=.1 and out_span>=.05 and
        np.isfinite(slow['corr_best']) and slow['corr_best']>=.8 and not slow['lag_boundary'] and slow['pairs']>=120)
    metrics['lag_resolved']=bool(metrics['lag_interpretable'] and slow['lag_peak_margin']>=.001)
    metrics.update(_event_matches(clock,sx,sy))
    metrics['event_timing_interpretable']=bool(metrics['lag_interpretable'] and metrics['matched_events']>=3 and metrics['event_recall']>=.5)
    dx=np.diff(sx);dy=np.diff(sy);threshold=max(.005,.01*raw_span) if np.isfinite(raw_span) else .005
    moving=np.isfinite(dx)&np.isfinite(dy)&(np.abs(dx)>=threshold)
    moving_out=moving&(np.abs(dy)>=max(.002,.01*out_span if np.isfinite(out_span) else .002))
    metrics['slope_reference_moves']=int(moving.sum())
    output_direction=np.where(np.abs(dy)>=max(.002,.01*out_span if np.isfinite(out_span) else .002),np.sign(dy),0)
    metrics['slope_direction_agreement']=float(np.mean(np.sign(dx[moving])==output_direction[moving])) if moving.any() else float('nan')
    metrics['slope_both_moving_agreement']=float(np.mean(np.sign(dx[moving_out])==np.sign(dy[moving_out]))) if moving_out.any() else float('nan')
    metrics['slope_output_flat_fraction']=float(np.mean(np.abs(dy[moving])<max(.002,.01*out_span))) if moving.any() else float('nan')
    return metrics


def self_test():
    t=np.arange(600,dtype=np.int64)*60000+1793592000000
    x=np.sin(np.arange(600)*2*np.pi/60)
    y=np.r_[np.full(2,np.nan),x[:-2]]*.3+4
    r=compute_metrics(t,x,y);assert r['slow_best_lag_min']==2 and r['slow_corr_best']>.9999
    assert r['slow_corr_zero']<r['slow_corr_best'];assert abs(r['event_signed_median_min']-2)<.1
    flat=compute_metrics(t,np.ones(600),np.ones(600));assert not flat['lag_interpretable']
    neg=compute_metrics(t,x,-x);assert not neg['lag_interpretable']
    missing=x.copy();missing[200:260]=np.nan
    test=compute_metrics(t,missing,missing);assert test['slow_best_lag_min']==0 and test['slow_corr_zero']>.9999
    jitter=t+59995+np.arange(600)%11
    jittered=compute_metrics(jitter,x,x)
    assert jittered['duplicate_minute_bins']==0 and jittered['valid_pairs']==600
    return dict(passed=True,lag_sign_test_min=r['slow_best_lag_min'],matched_event_lag_min=r['event_signed_median_min'])

if __name__=='__main__':print(self_test())
