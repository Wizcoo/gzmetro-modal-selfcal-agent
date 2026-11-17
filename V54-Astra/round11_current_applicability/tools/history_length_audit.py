"""3/5/7 qualified historical nights; modal-only, frozen target-night model.

Reads the validated mathematical helpers, never executes a native DLL. Every
variant recomputes its history-energy gain from its own actual historical nights.
"""
from pathlib import Path
from datetime import datetime,timedelta,timezone
from collections import Counter
import ast,hashlib,json,re,struct,warnings
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1];BASE=ROOT.parent;OUT=ROOT/'reports';OUT.mkdir(parents=True,exist_ok=True)
TZ=timezone(timedelta(hours=8));NIGHT='2026-11-12'
def ms(s):return int(datetime.fromisoformat(s).replace(tzinfo=TZ).timestamp()*1000)
def iso(t):return datetime.fromtimestamp(int(t)/1000,TZ).isoformat(sep=' ',timespec='milliseconds')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
HELPERS=[(BASE/'round4_window_causality/tools/yd_stage_audit.py',{'w3','inverse_s1','read'}),
 (BASE/'round9_left_42_47_1112/tools/algorithm_cause_audit.py',{'night_data','solve','evaluate'}),
 (BASE/'round10_history_design/tools/history_window_sensitivity.py',{'history_stat'})]
for path,nameset in HELPERS:
    tree=ast.parse(path.read_text(encoding='utf8'))
    exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in nameset],type_ignores=[]),str(path),'exec'))
# Reuse the already validated complete gain implementation with one mechanical
# change: receive preselected histories rather than hardcoding11/09–11.
MODEL_SOURCE=BASE/'round10_history_design/tools/history_window_sensitivity.py'
fn=next(n for n in ast.parse(MODEL_SOURCE.read_text(encoding='utf8')).body if isinstance(n,ast.FunctionDef) and n.name=='make_model')
assert isinstance(fn.body[0],ast.Assign) and fn.body[0].targets[0].id=='hist'
fn.name='model_from_history';fn.body=fn.body[1:]
fn.args=ast.arguments(posonlyargs=[],args=[ast.arg(arg='names'),ast.arg(arg='hist')],vararg=None,kwonlyargs=[],kw_defaults=[],kwarg=None,defaults=[])
assert not ({'t','x','hours'} & {n.id for n in ast.walk(fn) if isinstance(n,ast.Name)})
exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),str(MODEL_SOURCE),'exec'))
ALL_DATES=[f'2026-11-{d:02d}' for d in range(2,16)]

def number(v):return float(v) if np.isfinite(v) else None
def stat(v):
    a=np.asarray(v);a=a[np.isfinite(a)]
    return {'valid':len(a),'range':float(np.ptp(a)) if len(a) else None,'p95p5':float(np.diff(np.quantile(a,[.05,.95]))[0]) if len(a) else None}
def median(a,axis=None):
    with warnings.catch_warnings():
        warnings.simplefilter('ignore',RuntimeWarning);return np.nanmedian(a,axis=axis)
def masks(t,date):
    lo=ms(date+' 22:00');return (t>=lo)&(t<lo+3600000),(t>=lo+3600000)&(t<lo+9*3600000),(t>=lo+5*3600000)&(t<lo+8*3600000)
def point_metrics(x,raw,t,date):
    ref,night,late=masks(t,date);z=stat(x[night]);z.update(late_range=stat(x[late])['range'],late_offset=number(median(x[late])-median(raw[ref])))
    return z
def summary_changes(rows):
    valid=[r for r in rows if r['valid']>=384 and r['range'] is not None]
    return {'nominal_point_nights':len(rows),'eligible':len(valid),'median_range':float(np.median([r['range'] for r in valid])) if valid else None,
            'range_p95':float(np.quantile([r['range'] for r in valid],.95)) if valid else None,
            'median_abs_late_offset':float(np.median([abs(r['late_offset']) for r in valid if r['late_offset'] is not None])) if valid else None,
            'range_le_1':sum(r['range']<=1 for r in valid),'range_le_2':sum(r['range']<=2 for r in valid),
            'range_above_raw_by_gt_0p1':sum(r['range']>r['raw_range']+.1 for r in valid),
            'abs_late_offset_above_raw_by_gt_0p1':sum(abs(r['late_offset'])>abs(r['raw_late_offset'])+.1 for r in valid if r['late_offset'] is not None and r['raw_late_offset'] is not None)}

def main():
    prepared=[];raw_stats={};eligibility=[]
    inputs=sorted((BASE/'data').glob('*/*/input.npz'));inputs.sort(key=lambda p:(p.parent.name!='780638327479',str(p)))
    for path in inputs:
        line,dev=path.parent.parent.name,path.parent.name
        with np.load(path) as d:t=d['timestamp'];raw=d['x'];names=list(map(str,d['names']))
        fed=w3(t,raw);history={}
        for date in ALL_DATES:
            with warnings.catch_warnings():warnings.simplefilter('ignore',RuntimeWarning);h=history_stat(t,fed,date,4)
            # Native commits a night after02:00 only if at least144 learning
            # frames have any finite baseline-referenced point.
            complete_window=bool(np.any(t>=h['end_exclusive_ms']))
            qualifies=h['n_frames']>=144 and complete_window
            if qualifies:history[date]=h
            ref,night,late=masks(t,date)
            for j,name in enumerate(names):raw_stats[(line,dev,date,name)]=point_metrics(raw[:,j],raw[:,j],t,date)
            eligibility.append({'line':line,'device':dev,'night':date,'frames':h['n_frames'],'qualifies':qualifies,'commit_time_observed_after_02':complete_window})
        possible=[date for date in ALL_DATES if sum(h<date for h in history)>=7 and np.any(masks(t,date)[1])]
        prepared.append({'line':line,'device':dev,'path':path,'t':t,'names':names,'raw':raw,'fed':fed,'history':history,'possible':possible})
        print('HISTORY_READY',line,dev,'qualified',list(history),'tests',possible,flush=True)
    common=sorted(set.intersection(*(set(d['possible']) for d in prepared)));assert common
    print('COMMON_TEST_NIGHTS',common,flush=True)
    rows=[];device_rows=[];model_records=[];native_checks=[];artifacts=[]
    for d in prepared:
        line,dev,t,names,raw,fed=d['line'],d['device'],d['t'],d['names'],d['raw'],d['fed'];p=len(names)
        folder=BASE/'round2_waveform_10n/results/no_s2'/line/dev
        no_s2=read(folder/'output.bin');status=pd.read_csv(folder/'status.csv');assert np.array_equal(t,no_s2['timestamp']) and np.array_equal(t,status.timestamp)
        frozen_core=inverse_s1(t,no_s2['xy'][:,0,:],status.gate_x.to_numpy())
        js=[i for i,n in enumerate(names) if n.startswith(('ZJ','YJ'))];xjs=[i for i,n in enumerate(names) if 'XJ' in n];ordinary=[i for i,n in enumerate(names) if 'J' not in n]
        arrays={'names':np.asarray(names)}
        for date in common:
            prior=sorted(h for h in d['history'] if h<date)
            chosen3=prior[-3:]
            calendar3=[(datetime.fromisoformat(date)-timedelta(days=k)).date().isoformat() for k in [3,2,1]]
            for length in [3,5,7]:
                dates=prior[-length:];hist=[d['history'][a] for a in dates];assert len(hist)==length and max(h['end_exclusive_ms'] for h in hist)<=ms(date+' 23:00')
                model=model_from_history(names,hist);ev=evaluate(t,fed,model,date=date);tt=ev['t'];xx=ev['core'];rr=raw[ev['sel']]
                ref,night,late=masks(tt,date)
                if length==3:
                    both=night;native=frozen_core[ev['sel']][both];actual=xx[both];assert np.array_equal(np.isfinite(native),np.isfinite(actual))
                    err=float(np.nanmax(abs(native-actual)));native_checks.append({'line':line,'device':dev,'night':date,'frames':int(both.sum()),'markers':p,'max_abs_error':err})
                    assert err<1e-7,(line,dev,date,err)
                rawj=median(rr[:,js],axis=1) if js else None;corej=median(xx[:,js],axis=1) if js else None
                rawxj=median(rr[:,xjs],axis=1) if xjs else None;corexj=median(xx[:,xjs],axis=1) if xjs else None
                for j,name in enumerate(names):
                    r=point_metrics(xx[:,j],rr[:,j],tt,date);rawm=raw_stats[(line,dev,date,name)]
                    ps=[raw_stats[(line,dev,a,name)] for a in calendar3]
                    comparable=all(a['valid']>=384 and a['p95p5'] is not None for a in ps) and rawm['valid']>=384
                    strict=bool(comparable and all(a['p95p5']>=1.5 for a in ps) and rawm['p95p5']<=.5 and abs(rawm['late_offset'])<=.5)
                    rawquiet=bool(rawm['valid']>=384 and rawm['range']<=1 and abs(rawm['late_offset'])<=.5)
                    row={'line':line,'device':dev,'night':date,'history_length':length,'marker':name,'role':'XJ' if 'XJ' in name else 'J' if name.startswith(('ZJ','YJ')) else 'ordinary',
                         **r,'raw_range':rawm['range'],'raw_p95p5':rawm['p95p5'],'raw_late_offset':rawm['late_offset'],'raw_quiet':rawquiet,'three_large_then_quiet':strict,
                         'prior3_calendar_dates':','.join(calendar3),'selected_history_dates':','.join(dates),'learn':bool(model['learn'][j]),'use':bool(model['use'][j]),'gain':float(model['gains'][j]),
                         'relative_J_range':None,'relative_J_late_offset':None,'relative_XJ_range':None,'relative_XJ_late_offset':None}
                    for label,cg,rg in [('J',corej,rawj),('XJ',corexj,rawxj)]:
                        if cg is not None:
                            rel=point_metrics(xx[:,j]-cg,rr[:,j]-rg,tt,date);row['relative_'+label+'_range']=rel['range'];row['relative_'+label+'_late_offset']=rel['late_offset']
                    rows.append(row)
                model_records.append({'line':line,'device':dev,'night':date,'history_length':length,'history_dates':dates,'history_frames':[h['n_frames'] for h in hist],
                                      'learn_names':[n for j,n in enumerate(names) if model['learn'][j]],'gain_detail':model['gain_detail'],'last_history_end':iso(max(h['end_exclusive_ms'] for h in hist))})
                dr={'line':line,'device':dev,'night':date,'history_length':length,'J_count':len(js),'XJ_count':len(xjs),'ordinary_count':len(ordinary)}
                if js and xjs:
                    dr.update({('XJ_minus_J_'+k):v for k,v in point_metrics(corexj-corej,rawxj-rawj,tt,date).items()})
                if xjs and ordinary:
                    co=median(xx[:,ordinary],axis=1);ro=median(rr[:,ordinary],axis=1)
                    dr.update({('XJ_minus_ordinary_'+k):v for k,v in point_metrics(corexj-co,rawxj-ro,tt,date).items()})
                device_rows.append(dr)
                key=date.replace('-','_');arrays[key+'_timestamp']=tt;arrays[key+'_modal_h'+str(length)]=xx
                if length==3:arrays[key+'_raw']=rr;arrays[key+'_w3']=fed[ev['sel']]
            if dev=='780638327479' and date=='2026-11-12':
                focus=[r for r in rows if r['device']==dev and r['night']==date and r['marker'] in ['ZXJ6','ZD4703','ZJ7']]
                print('FOCUS_327479',json.dumps([{k:r[k] for k in ['marker','history_length','range','late_offset','relative_J_range','relative_J_late_offset']} for r in focus]),flush=True)
            print('NIGHT_DONE',line,dev,date,flush=True)
        arpath=OUT/f'history_length_arrays_{line}_{dev}.npz';np.savez_compressed(arpath,**arrays);artifacts.append({'file':str(arpath),'sha256':sha(arpath),'input_sha256':sha(d['path']),'native_no_s2_sha256':sha(folder/'output.bin')})
    summary={str(n):summary_changes([r for r in rows if r['history_length']==n]) for n in [3,5,7]}
    quiet_summary={str(n):summary_changes([r for r in rows if r['history_length']==n and r['raw_quiet']]) for n in [3,5,7]}
    transitions=[r for r in rows if r['three_large_then_quiet']]
    transition_summary={str(n):summary_changes([r for r in transitions if r['history_length']==n]) for n in [3,5,7]}
    lookup={(r['line'],r['device'],r['night'],r['marker'],r['history_length']):r for r in rows}
    comparisons={}
    for n in [5,7]:
        pair=[]
        for r in rows:
            if r['history_length']!=n or r['valid']<384:continue
            old=lookup[(r['line'],r['device'],r['night'],r['marker'],3)]
            pair.append({'line':r['line'],'device':r['device'],'night':r['night'],'marker':r['marker'],'role':r['role'],'history_length':n,'range_change':r['range']-old['range'],
                         'abs_offset_change':abs(r['late_offset'])-abs(old['late_offset']),'old_range':old['range'],'new_range':r['range'],'old_offset':old['late_offset'],'new_offset':r['late_offset']})
        comparisons[str(n)]={'eligible_pairs':len(pair),'range_better_gt_0p1':sum(a['range_change']<-.1 for a in pair),'range_worse_gt_0p1':sum(a['range_change']>.1 for a in pair),
                             'abs_offset_better_gt_0p1':sum(a['abs_offset_change']<-.1 for a in pair),'abs_offset_worse_gt_0p1':sum(a['abs_offset_change']>.1 for a in pair),
                             'worst_range':sorted(pair,key=lambda r:-r['range_change'])[:10],'worst_offset':sorted(pair,key=lambda r:-r['abs_offset_change'])[:10]}
        pd.DataFrame(pair).to_csv(OUT/f'history_length_vs3_h{n}.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(rows).to_csv(OUT/'history_length_point_metrics.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(device_rows).to_csv(OUT/'history_length_reference_differences.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(transitions).to_csv(OUT/'history_length_three_large_then_quiet.csv',index=False,encoding='utf-8-sig')
    result={'scope':'Independent Python modal-only3/5/7 historical-night sensitivity over12 devices; no new native DLL, no algorithm/DB changes, no physical acceptance claim.',
            'test_nights_common_to_all_devices_and_lengths':common,'history_window':'22–02, reference22–23; target model frozen23:00; no target-night future data in any history or gain',
            'history_qualification':'At least144 frames with any finite baseline-referenced coordinate and an observed post02 timestamp, matching min_learn_ratio0.6; latest qualified nights selected, no invented missing11/06 left night.',
            'classification':{'raw_quiet':'current raw range<=1px and |late03–06 median minus raw22–23 median|<=0.5px; >=384 valid night samples',
                              'three_large_then_quiet':'each of previous3 CALENDAR nights raw P95-P5>=1.5px, current P95-P5<=0.5px and |late offset|<=0.5px; all4 >=384 samples. Descriptive observational class, not physical truth.'},
            'summary':summary,'quiet_summary':quiet_summary,'three_large_then_quiet_summary':transition_summary,'comparisons_to3':comparisons,
            'native_baseline_checks':native_checks,'native_baseline_max_error':max(c['max_abs_error'] for c in native_checks),'qualified_history_inventory':eligibility,'models':model_records,'artifacts':artifacts,
            'helper_sha256':{str(p):sha(p) for p,_ in HELPERS},'model_math_source_sha256':sha(MODEL_SOURCE),'script_sha256':sha(Path(__file__)),
            'limitations':['Modal core only; S2/S1, new state migration/native execution and physical motion preservation are not tested.','Historical size alone does not test whether the current point-to-point relationship remains valid.','Reference differences are pixel-space observations, not calibrated physical adjustment errors.','Low-coverage records are retained in point metrics, but comparison summary denominators require>=384 samples.']}
    (OUT/'history_length_summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
    print('SUMMARY',json.dumps(summary),flush=True);print('QUIET',json.dumps(quiet_summary),flush=True);print('TRANSITIONS',json.dumps(transition_summary),flush=True);print('AUDIT_DONE',len(rows),'rows',len(native_checks),'native_checks',result['native_baseline_max_error'],flush=True)

if __name__=='__main__':main()
