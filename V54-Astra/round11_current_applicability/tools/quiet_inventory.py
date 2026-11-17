"""Freeze quiet-night applicability cases from existing raw/native data; no model tuning or native execution."""
from pathlib import Path
from datetime import datetime,date,timedelta,timezone
from collections import Counter
import hashlib,json,struct,warnings
import numpy as np

ROOT=Path(__file__).resolve().parents[1];BASE=ROOT.parent;OUT=ROOT/'reports';TZ=timezone(timedelta(hours=8))
DATES=[f'2026-11-{i:02d}' for i in range(6,16)]
def ms(s):return int(datetime.fromisoformat(s).replace(tzinfo=TZ).timestamp()*1000)
def local(t):return datetime.fromtimestamp(int(t)/1000,TZ).isoformat(timespec='milliseconds') if t is not None else None
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(4194304),b''):h.update(b)
    return h.hexdigest()
def role(n):return 'XJ' if 'XJ' in n else 'J' if 'J' in n else 'ordinary'
def med(v):
    a=np.asarray(v);a=a[np.isfinite(a)];return float(np.median(a)) if len(a) else None
def stats(v):
    a=np.asarray(v);a=a[np.isfinite(a)]
    return {'valid':len(a),'range':float(np.ptp(a)) if len(a) else None,'p95p5':float(np.quantile(a,.95)-np.quantile(a,.05)) if len(a) else None,'median':med(a)}
def subtract(a,b):return a-b if a is not None and b is not None else None
def ratio(a,b):return a/b if a is not None and b is not None and b>1e-12 else None
def agg(rows):
    eligible=[r for r in rows if r['eligible']]
    return dict(nominal=len(rows),eligible=len(eligible),missing_or_low_coverage=len(rows)-len(eligible),
        raw_quiet=sum(r['raw_quiet'] for r in eligible),new_exceeds1=sum(r['new']['range']>1+1e-9 for r in eligible),
        new_exceeds_role_limit=sum(r['new']['range']>(2 if r['role']=='ordinary' else 1)+1e-9 for r in eligible),
        any_range_amplification=sum(r['range_increase']>1e-9 for r in eligible),
        material_range_amplification=sum(r['material_range_amplification'] for r in eligible),
        material_p95_amplification=sum(r['material_p95_amplification'] for r in eligible),
        median_raw_range=med([r['raw']['range'] for r in eligible]),median_new_range=med([r['new']['range'] for r in eligible]))
def step_features(ts,values,common):
    p=values.shape[1];result=[{} for _ in range(p)]
    if len(ts)<20:return result
    v=np.lib.stride_tricks.sliding_window_view(values,10,axis=0)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore',RuntimeWarning);m=np.nanmedian(v,axis=-1)
        cm=np.nanmedian(np.lib.stride_tricks.sliding_window_view(common,10),axis=-1)
    n=np.isfinite(v).sum(axis=-1)
    before=m[:-10];after=m[10:];delta=after-before;good=(n[:-10]>=8)&(n[10:]>=8)
    # Split index10..n-10: 10 actual samples on each side, no interpolation.
    split=np.arange(10,len(ts)-9)
    good&=((ts[split+9]-ts[split-10])<=21*60000)[:,None]
    delta[~good]=np.nan;common_delta=cm[10:]-cm[:-10]
    residual_delta=delta-common_delta[:,None]
    for j in range(p):
        ok=np.isfinite(delta[:,j])
        if ok.any():
            k=int(np.nanargmax(np.abs(delta[:,j])));result[j].update(max_adjacent10min_median_change=float(delta[k,j]),step_like_time=local(ts[split[k]]),
                common_change_at_that_time=float(common_delta[k]) if np.isfinite(common_delta[k]) else None,
                relative_change_at_that_time=float(residual_delta[k,j]) if np.isfinite(residual_delta[k,j]) else None)
            result[j]['local_step_like_observed']=bool(abs(delta[k,j])>=.5 and np.isfinite(residual_delta[k,j]) and abs(residual_delta[k,j])>=.5)
            result[j]['coherent_step_like_observed']=bool(abs(delta[k,j])>=.5 and np.isfinite(common_delta[k]) and abs(common_delta[k])>=.5 and abs(residual_delta[k,j])<.5)
    return result

def main():
    OUT.mkdir(parents=True,exist_ok=True);rows=[];device_nights=[];sourcechecks=[];history_records=[]
    for source in sorted((BASE/'data').glob('*/*/input.npz')):
        line,dev=source.parts[-3:-1]
        with np.load(source) as z:ts=z['timestamp'];names=[str(n) for n in z['names']];raw=z['x'];roi=z['roi']
        output=BASE/'round2_waveform_10n/results/current_fade07'/line/dev/'output.bin'
        with output.open('rb') as f:m,n=struct.unpack('<II',f.read(8))
        native=np.memmap(output,dtype=np.dtype([('timestamp','<i8'),('xy','<f8',(2,m))]),offset=8,mode='r',shape=(n,));new=native['xy'][:,0,:]
        assert m==len(names) and np.array_equal(ts,native['timestamp']) and np.array_equal(np.isfinite(raw),np.isfinite(new))
        verification=json.loads(output.with_name('verification.json').read_text(encoding='utf8'));outputsha=sha(output);inputsha=sha(source.with_name('input.bin'))
        assert outputsha==verification['output_sha256'] and inputsha==verification['input_sha256']
        sourcechecks.append(dict(line=line,device=dev,input_npz=str(source),input_npz_sha256=sha(source),input_bin_sha256=inputsha,output=str(output),output_sha256=outputsha,timestamps_and_masks_equal=True))
        roles=[role(n) for n in names];primary=np.array([j for j,r in enumerate(roles) if r!='XJ'],int)
        history=[]
        for day in range(2,16):
            night=f'2026-11-{day:02d}';lo=ms(night+'T22:00');baseline=(ts>=lo)&(ts<lo+3600000);learn=(ts>=lo)&(ts<lo+4*3600000);full=(ts>=lo+3600000)&(ts<lo+9*3600000)
            base_count=np.isfinite(raw[baseline]).sum(axis=0);learn_valid=np.isfinite(raw[learn])&(base_count>=10)[None,:]
            accumulation_frames=int(np.any(learn_valid,axis=1).sum());closing=ts[(ts>=lo+4*3600000)&(ts<lo+14*3600000)]
            qualified=bool(baseline.sum()>0 and accumulation_frames>=144 and len(closing)>0)
            h=dict(line=line,device=dev,night=night,baseline_frame_count=int(baseline.sum()),accumulation_frames=accumulation_frames,
                close_frame=local(int(closing[0])) if len(closing) else None,data_qualified=qualified,
                per_marker=[{'marker':name,'baseline_valid':int(base_count[j]),'raw_22_02':stats(raw[learn,j]),'raw_23_07':stats(raw[full,j])} for j,name in enumerate(names)])
            history.append(h)
        history_records.extend(history)
        for night in DATES:
            lo=ms(night+'T23:00');hi=lo+8*3600000;take=(ts>=lo)&(ts<hi);t=ts[take];x=raw[take];z=new[take]
            baseline=(ts>=lo-3600000)&(ts<lo);baseraw=raw[baseline];base_count=np.isfinite(baseraw).sum(axis=0)
            prior=[h for h in history if h['night']<night and h['data_qualified']][-3:]
            with warnings.catch_warnings():
                warnings.simplefilter('ignore',RuntimeWarning)
                bases=np.nanmedian(baseraw,axis=0) if len(baseraw) else np.full(m,np.nan)
                centered=x[:,primary]-bases[primary]
                common=np.nanmedian(centered,axis=1) if len(t) else np.array([])
            common[np.isfinite(centered).sum(axis=1)<max(3,int(np.ceil(.8*len(primary))))]=np.nan
            features=step_features(t,x,common)
            rawstats=[stats(x[:,j]) for j in range(m)];newstats=[stats(z[:,j]) for j in range(m)]
            eligible=[s['valid']>=384 for s in rawstats]
            goodprimary=[j for j in primary if eligible[j]]
            quietprimary=[j for j in goodprimary if rawstats[j]['range']<=1+1e-9]
            whole=bool(len(goodprimary)==len(primary) and len(quietprimary)==len(primary))
            observed_all_quiet=bool(goodprimary and len(quietprimary)==len(goodprimary))
            devrec=dict(line=line,device=dev,night=night,total_primary_points=len(primary),eligible_primary_points=len(goodprimary),quiet_primary_points=len(quietprimary),
                whole_device_quiet_complete=whole,all_observed_primary_quiet=observed_all_quiet,
                incomplete_coverage=bool(len(goodprimary)!=len(primary)),
                max_primary_raw_range=max([rawstats[j]['range'] for j in goodprimary],default=None),
                median_primary_raw_range=med([rawstats[j]['range'] for j in goodprimary]),prior_qualified_nights=[h['night'] for h in prior],
                raw_common=stats(common))
            device_nights.append(devrec)
            for j,name in enumerate(names):
                r,nr=rawstats[j],newstats[j];quiet=bool(eligible[j] and r['range']<=1+1e-9)
                hs=[h['per_marker'][j] for h in prior]
                hist22=[h['raw_22_02']['range'] for h in hs if h['raw_22_02']['valid']>=192]
                hist23=[h['raw_23_07']['range'] for h in hs if h['raw_23_07']['valid']>=384]
                hist22_med=med(hist22);hist23_med=med(hist23)
                first30=med(x[t<lo+1800000,j]);baseline_median=float(bases[j]) if np.isfinite(bases[j]) else None
                offset=subtract(first30,baseline_median)
                earlyfirst10=med(x[t<lo+600000,j]);lastbase10=med(raw[(ts>=lo-600000)&(ts<lo),j]);boundaryshift=subtract(earlyfirst10,lastbase10)
                entrycommon=med(common[t<lo+1800000]);relative_offset=subtract(offset,entrycommon)
                maxrawjump=None;gaps=0
                if len(t)>1:
                    dt=np.diff(t)/60000;ok=np.isfinite(x[1:,j])&np.isfinite(x[:-1,j])&(dt<=3)
                    jumps=np.abs(np.diff(x[:,j]));maxrawjump=float(jumps[ok].max()) if ok.any() else None;gaps=int((dt>3).sum())
                increase=subtract(nr['range'],r['range']);qinc=subtract(nr['p95p5'],r['p95p5'])
                classification='missing_or_low_coverage' if not eligible[j] else 'nonquiet' if not quiet else 'whole_device_quiet' if whole else 'quiet_point_mixed_device' if len(quietprimary)<len(goodprimary) else 'quiet_observed_but_device_coverage_incomplete'
                rec=dict(case_id=f'{line}/{dev}/{night}/{name}',line=line,device=dev,night=night,marker=name,role=roles[j],
                    primary_population=roles[j]!='XJ',eligible=eligible[j],raw_quiet=quiet,classification=classification,raw=r,new=nr,
                    range_increase=increase,p95_increase=qinc,
                    material_range_amplification=bool(eligible[j] and increase>max(.05,.1*r['range'])),
                    material_p95_amplification=bool(eligible[j] and qinc>max(.05,.1*r['p95p5'])),
                    raw_baseline_valid=int(base_count[j]),missing_baseline=bool(base_count[j]<10),
                    baseline_raw_median=baseline_median,first30_raw_median=first30,first30_minus_baseline=offset,
                    entry_common_first30_median=entrycommon,relative_baseline_offset=relative_offset,
                    first10_minus_last_baseline10=boundaryshift,
                    baseline_shift_like=bool(offset is not None and abs(offset)>=.5),
                    local_baseline_shift_like=bool(relative_offset is not None and abs(relative_offset)>=.5),
                    invalid_roi_samples=int(np.sum(roi[take,j]!=1)),observed_frames=len(t),missing_timestamp_frames=480-len(t),gap_over3min_count=gaps,max_adjacent_valid_raw_jump=maxrawjump,
                    prior_qualified_nights=[h['night'] for h in prior],prior_history_count=len(prior),
                    prior_per_marker=hs,prior22_02_eligible_count=len(hist22),prior23_07_eligible_count=len(hist23),
                    prior22_02_median_range=hist22_med,prior23_07_median_range=hist23_med,
                    prior22_02_to_current_range_ratio=ratio(hist22_med,r['range']),prior23_07_to_current_range_ratio=ratio(hist23_med,r['range']),
                    history_high22_02=bool(len(prior)==3 and len(hist22)==3 and hist22_med>2),
                    history_high23_07=bool(len(prior)==3 and len(hist23)==3 and hist23_med>2),
                    history_all_three_gt2_22_02=bool(len(hist22)==3 and all(v>2 for v in hist22)),
                    history_all_three_gt2_23_07=bool(len(hist23)==3 and all(v>2 for v in hist23)),
                    device_context=devrec,step_diagnostic=features[j])
                rows.append(rec)
        print('DEVICE_OK',line,dev,flush=True)
    primary=[r for r in rows if r['primary_population']];quiet=[r for r in primary if r['raw_quiet']];qall=[r for r in rows if r['raw_quiet']]
    assert len(rows)==5240 and len(qall)==124 and len(quiet)==121
    groups={'all_ordinary_J':primary,'quiet_ordinary_J':quiet,'nonquiet_ordinary_J':[r for r in primary if r['eligible'] and not r['raw_quiet']],
        'quiet_history_median_gt2_22_02':[r for r in quiet if r['history_high22_02']],
        'quiet_history_median_gt2_23_07':[r for r in quiet if r['history_high23_07']],
        'quiet_all3_history_gt2_22_02':[r for r in quiet if r['history_all_three_gt2_22_02']],
        'quiet_all3_history_gt2_23_07':[r for r in quiet if r['history_all_three_gt2_23_07']],
        'quiet_baseline_shift_like':[r for r in quiet if r['baseline_shift_like']],
        'quiet_local_step_like':[r for r in quiet if r['step_diagnostic'].get('local_step_like_observed')],
        'quiet_with_any_invalid_ROI':[r for r in quiet if r['invalid_roi_samples']>0],
        'quiet_with_missing_baseline':[r for r in quiet if r['missing_baseline']],
        'all_primary_baseline_shift_like':[r for r in primary if r['eligible'] and r['baseline_shift_like']],
        'all_primary_local_step_like':[r for r in primary if r['eligible'] and r['step_diagnostic'].get('local_step_like_observed')],
        'all_primary_missing_baseline':[r for r in primary if r['eligible'] and r['missing_baseline']],
        'all_primary_missing_or_low_coverage':[r for r in primary if not r['eligible']],
        'quiet_XJ_separate':[r for r in qall if r['role']=='XJ']}
    summary={name:agg(rr) for name,rr in groups.items()}
    representatives=[];chosen=set()
    def choose(tag,candidates,sortkey,limit=3):
        count=0
        for r in sorted(candidates,key=sortkey,reverse=True):
            if r['case_id'] in chosen:continue
            representatives.append({'selection':tag,'case_id':r['case_id'],'case':r});chosen.add(r['case_id']);count+=1
            if count>=limit:break
    choose('largest_prior22_02_to_current_ratio',quiet,lambda r:r['prior22_02_to_current_range_ratio'] or -1,4)
    choose('largest_prior23_07_to_current_ratio',quiet,lambda r:r['prior23_07_to_current_range_ratio'] or -1,3)
    choose('smallest_existing_range_improvement',quiet,lambda r:r['range_increase'],3)
    choose('largest_baseline_offset_in_quiet',quiet,lambda r:abs(r['first30_minus_baseline'] or 0),3)
    choose('quiet_local_step_like',groups['quiet_local_step_like'],lambda r:abs(r['step_diagnostic'].get('max_adjacent10min_median_change',0)),2)
    choose('lowest_valid_coverage_in_quiet',quiet,lambda r:-r['raw']['valid'],2)
    choose('ordinary_J_material_p95_regression',[r for r in primary if r['eligible'] and r['material_p95_amplification']],lambda r:r['p95_increase'],5)
    choose('nonquiet_observed_local_step_no_physical_truth',[r for r in groups['all_primary_local_step_like'] if not r['raw_quiet']],lambda r:abs(r['step_diagnostic'].get('max_adjacent10min_median_change',0)),3)
    choose('nonquiet_baseline_shift_no_physical_truth',[r for r in groups['all_primary_baseline_shift_like'] if not r['raw_quiet']],lambda r:abs(r['first30_minus_baseline']),2)
    near_quiet=sorted([d for d in device_nights if d['eligible_primary_points']],key=lambda d:d['max_primary_raw_range'])[:8]
    fixed_cases=[dict(case_id=r['case_id'],line=r['line'],device=r['device'],night=r['night'],marker=r['marker'],role=r['role'],raw_range=r['raw']['range'],baseline_new_range=r['new']['range'],baseline_new_p95p5=r['new']['p95p5'],valid=r['raw']['valid'],classification=r['classification'],prior_nights=r['prior_qualified_nights']) for r in quiet]
    report=dict(scope='Frozen12-device input.npz and current_fade07 outputs only;10 target nights2026-11-06..15,23:00 inclusive to next07:00 exclusive.',
        definitions={'primary_population':'ordinary and J points; XJ retained separately, never mixed into primary quiet count',
            'eligible':'at least384 valid ROI-masked samples out of480 expected in23-07',
            'quiet':'raw peak-to-peak<=1pixel; thresholds fixed before candidate validation, no noise fitting',
            'whole_device_quiet':'every ordinary/J point meets coverage and raw range<=1; no missing-point substitution',
            'history_qualification':'previous three device nights with baseline observations, >=144 accumulation frames in22-02 having at least one finite point with >=10 baseline samples, and a real close frame at/after02 before12. Derived from input validity, not a new native replay.',
            'history_point_eligible':'22-02 >=192/240 valid or23-07 >=384/480 valid, separately labeled. High history means median of all3 point-eligible raw ranges>2pixel; all3>2 listed separately.',
            'material_amplification':'new-minus-raw range orP95-P5 > max(0.05pixel,10% of corresponding raw value); diagnostic thresholds only',
            'baseline_offset':'first30-minute raw median after23 minus fixed22-23 raw median; shift-like if abs>=0.5pixel, not proof of real motion',
            'step_like':'maximum difference of adjacent10-sample medians, each>=8 valid, total support span<=21minutes; local if abs(point change)>=0.5 and abs(point change-common change)>=0.5. Offline descriptive label, not a controller rule or truth label.',
            'common':'frame median of ordinary/J raw minus each point fixed22-23 median, requiring>=80% peers; no fitted slope, scale or time shift'},
        summary=summary,whole_device_quiet_complete_count=sum(d['whole_device_quiet_complete'] for d in device_nights),
        observed_all_quiet_but_incomplete_count=sum(d['all_observed_primary_quiet'] and d['incomplete_coverage'] for d in device_nights),
        missing_data_summary={'primary_no_timestamp_observations':sum(r['observed_frames']==0 for r in primary),
            'primary_records_present_but_valid_below384':sum(r['observed_frames']>0 and not r['eligible'] for r in primary),
            'primary_records_present_but_zero_valid':sum(r['observed_frames']>0 and r['raw']['valid']==0 for r in primary),
            'quiet_any_invalid_roi':sum(r['invalid_roi_samples']>0 for r in quiet),
            'quiet_min_valid_count':min(r['raw']['valid'] for r in quiet),
            'quiet_missing_baseline':sum(r['missing_baseline'] for r in quiet)},
        low_coverage_cases=[{k:r[k] for k in ['case_id','observed_frames','raw','invalid_roi_samples','missing_timestamp_frames','raw_baseline_valid','missing_baseline']} for r in primary if not r['eligible']],
        primary_quiet_classifications=dict(Counter(r['classification'] for r in quiet)),closest_actual_device_nights=near_quiet,
        source_checks=sourcechecks,devices_by_night=device_nights,history_qualification_records=history_records,
        primary_quiet_cases=quiet,XJ_quiet_separate=[r for r in qall if r['role']=='XJ'],representative_cases=representatives,
        fixed_test_plan={'all121_primary_quiet_cases':fixed_cases,'all124_with_XJ_descriptive':len(qall),
            'supplemental_frozen_cases':[{'selection':a['selection'],'case_id':a['case_id']} for a in representatives],
            'closest_real_device_nights':near_quiet,
            'additional_context':'Retain every5240 point-night including missing/low-coverage separately when running candidate. Fixed quiet set is not a replacement for full10-night evaluation.',
            'candidate_report_requirements':['exact same input/output timestamps and finite masks','all121 raw-quiet cases: range/P95, any amplification and crossing1','all device-night groups and original class limits','all existing nonquiet regression cases and J/XJ separately','no relabeling after observing candidate output']},
        synthetic_test_recommendations=[
            {'name':'real_history_then_whole_device_constant','setup':'Replay exact real history, then use each marker fixed own value throughout next22-07 including baseline. Separately test real22-23 baseline followed by constant23-07, explicitly labeled baseline-to-current transition. Keep an all-valid variant and a separate variant with original ROI/gaps. Never fill actual missing data in real replay.','known_truth':'zero current-night per-marker motion in full-constant fixture; zero post23 motion in transition fixture','checks':'no generated range/drift, no delay, no ramp injection; source/replay fixture hashes and values frozen'},
            {'name':'real_strong_history_then_measured_quiet_current','setup':'Keep previous3 history nights unchanged; replay a frozen actual quiet-point or closest-device current night. Whole-device constant variant is synthetic, since absence of actual all-device quiet cases must not be hidden.','known_truth':'real data has observed low variation only; no absolute-motion truth','checks':'preserve waveform timing, do not amplify raw-quiet rows, compare fixed121 cases'},
            {'name':'local_true_step_plus_common_camera_disturbance','setup':'Use a real baseline/history; independently add an explicitly defined local persistent step to a selected ordinary point and a separately known common disturbance to all points. Run local-only, common-only, and combined as three fixtures; fixed J remain motion-free in truth.','known_truth':'local displacement step must remain; synthetic common nuisance may be removed; absolute units remainpixel','checks':'step onset timing/amplitude, non-target leakage, common removal, J response; do not treat all-point flattening as success'},
            {'name':'baseline_to_current_shift_and_missing','setup':'Separate coherent shift, one-marker shift, and observation-only ROI gaps at23 boundary. Do not combine unknown causes into a single test.','known_truth':'define physical versus nuisance component independently; missing data remains missing','checks':'no fake observations, no baseline borrowing across devices, no correction blow-up on resume'}],
        audit_script_sha256=sha(__file__))
    (OUT/'quiet_inventory.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
    (OUT/'quiet_inventory_fixed_tests.json').write_text(json.dumps(report['fixed_test_plan'],ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
    # Compact all-point metrics retain the complete baseline for candidate comparisons.
    compact=[{k:r[k] for k in ['case_id','line','device','night','marker','role','primary_population','eligible','raw_quiet','classification','raw','new','range_increase','p95_increase','material_range_amplification','material_p95_amplification']} for r in rows]
    (OUT/'quiet_inventory_all_point_baseline.json').write_text(json.dumps(compact,ensure_ascii=False,separators=(',',':'),allow_nan=False),encoding='utf8')
    lines=['# 平稳夜与历史强扰动后的适用性测试清单','','只读使用冻结12台输入与current_fade07输出。目标夜11/06–15，窗口23–次07；普通/J为主统计，XJ单列。raw范围≤1 pixel且有效≥384/480定义为平稳点夜，不回看候选结果改定义。','',
        f"主统计有{len(quiet)}个平稳点夜（普通115、J6），XJ另有3个；current_fade07对主统计既无峰谷差放大，也无跨越1 pixel。严格整台平稳夜共有{report['whole_device_quiet_complete_count']}个，不能把单点平稳替代为整台设备平稳。",'',
        '| 固定分组 | 合格点夜 | 有意义范围放大 | 有意义P95−P5放大 | 新范围>1 |','|---|---:|---:|---:|---:|']
    for key,a in summary.items():lines.append(f"| {key} | {a['eligible']} | {a['material_range_amplification']} | {a['material_p95_amplification']} | {a['new_exceeds1']} |")
    lines += ['', '历史前3夜按设备数据有效性挑选，必须有22–23基准、22–02至少144帧可累计数据及02点后真实收夜帧；各点历史22–02范围与23–07范围分别存储，历史强弱比仅诊断，不用于校准算法。完整3夜且各点有效率≥80%才进入“历史中位范围>2”分组；另列三个历史夜全都>2。','',
        '基准偏移和局部step-like是观测形态标签，不是假定真实位移。基准偏移用当夜首30分钟中位数减22–23固定基准；局部跃迁用相邻10样本中位数之差并扣除设备共趋势作辅助判别，未平滑原始回放数据。','',
        '除平稳集外，另固定观测到的局部跃迁/基准偏移作为补充场景。它们没有独立物理真值，不能称为真实位移，也不能将相关性低直接等同于算法应保留或应扣除。', '',
        '## 固定代表案例','','| 选择理由 | 设备/点/夜 | raw→新范围 | 前3夜22–02中位范围 | 历史/当夜比 |','|---|---|---:|---:|---:|']
    for x in representatives:
        r=x['case'];h=r['prior22_02_median_range'];q=r['prior22_02_to_current_range_ratio'];lines.append(f"| {x['selection']} | {r['line']}/{r['device']}/{r['marker']}/{r['night']} | {r['raw']['range']:.4f} → {r['new']['range']:.4f} | {h:.4f} | {q:.2f} |" if h is not None and q is not None else f"| {x['selection']} | {r['case_id']} | {r['raw']['range']:.4f} → {r['new']['range']:.4f} | 不足 | 不足 |")
    lines += ['', '全部121个固定平稳案例见quiet_inventory_fixed_tests.json；全5240点夜baseline数值见quiet_inventory_all_point_baseline.json。候选必须继续跑完整10夜，不能只在这个平稳子集上报告通过率。','',
        '## 有已知真值的合成验证建议','','- 真实历史后整台固定：保持真实三夜，下一夜22–07每点固定为自身单独的常数，连基准窗也固定；零位移是已知真值。另设真实22–23基准后23–07恒定的边界过渡变体，避免把两个场景混淆。ROI/gap另做独立变体，不改变真实数据回测。','- 强历史后真实平稳：冻结真实历史和当前平稳样本；这仅证明不放大观测波动，不证明真实位移为零。若没有整台平稳真夜，明确使用合成整台固定补充。','- 局部真实step与设备共扰动分开：构造局部位移真值、全点相同相机扰动、两者叠加三份独立fixture；固定J物理真值保持不动。要求保留局部step幅度和发生时间，不能以全部修平为通过。','- 基准跨界偏移与缺测：分别构造整台偏移、单点偏移、ROI掉线，不混成一个无法解释的测试。','',
        '本清单没有改算法、运行新DLL或改数据库；所有源hash、缺测、具体历史日期及诊断定义在quiet_inventory.json。','']
    (OUT/'quiet_inventory.md').write_text('\n'.join(lines),encoding='utf8')
    print(json.dumps({'summary':summary,'whole_device_quiet':report['whole_device_quiet_complete_count'],'quiet_class':report['primary_quiet_classifications']},ensure_ascii=True))

if __name__=='__main__':main()
