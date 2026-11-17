"""Read-only database-to-frozen-output audit for left sections42-47, 2026-11-12 night."""
from pathlib import Path
from datetime import datetime,timedelta,timezone
from collections import Counter
import csv,hashlib,json,math,re,sqlite3,struct,warnings
import numpy as np

ROOT=Path(__file__).resolve().parents[1];BASE=ROOT.parent;OUT=ROOT/'reports';TZ=timezone(timedelta(hours=8))
DEVS=['780638310097','780638327479','780638349768']
def ms(s):return int(datetime.fromisoformat(s).replace(tzinfo=TZ).timestamp()*1000)
def local(t):return datetime.fromtimestamp(int(t)/1000,TZ).isoformat(timespec='milliseconds')
START=ms('2026-11-12T22:00');END=ms('2026-11-13T08:00')
WINDOWS={'22_08':(START,END),'23_07':(START+3600000,END-3600000),'22_23_baseline':(START,START+3600000),'23_2320_entry':(START+3600000,START+4800000),'2320_07_full_gate':(START+4800000,END-3600000),'07_0720_exit':(END-3600000,END-2400000),'0720_08_post_exit':(END-2400000,END)}
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(4194304),b''):h.update(b)
    return h.hexdigest()
def target(name):return bool(re.fullmatch(r'ZD(?:42|43|44|45|46|47)\d{2}',name))
def refs(name):return name.startswith(('ZJ','ZXJ'))
def finite(v):return isinstance(v,(int,float)) and math.isfinite(v)
def corr(a,b):
    ok=np.isfinite(a)&np.isfinite(b)
    return float(np.corrcoef(a[ok],b[ok])[0,1]) if ok.sum()>2 and np.std(a[ok])>1e-12 and np.std(b[ok])>1e-12 else None
def median(a):
    a=np.asarray(a);a=a[np.isfinite(a)]
    return float(np.median(a)) if len(a) else None
def metrics(t,v,lo,hi):
    take=(t>=lo)&(t<hi);tt=t[take];vv=v[take];ok=np.isfinite(vv);tt=tt[ok];vv=vv[ok]
    if not len(vv):return {'valid':0,'expected':int((hi-lo)/60000)}
    first=median(vv[tt<lo+1800000]);last=median(vv[tt>=hi-1800000])
    return {'valid':len(vv),'expected':int((hi-lo)/60000),'min':float(vv.min()),'max':float(vv.max()),'p2p':float(np.ptp(vv)),
        'p95p5':float(np.quantile(vv,.95)-np.quantile(vv,.05)),'min_local':local(tt[np.argmin(vv)]),'max_local':local(tt[np.argmax(vv)]),
        'first30_median':first,'last30_median':last,'last30_minus_first30':last-first if first is not None and last is not None else None}

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    inv=json.loads((BASE/'reports/data_inventory.json').read_text(encoding='utf8'))
    entry=next(e for e in inv if e['line']=='left' and Path(e['source']).name=='1793507670403_DataBaseFile_8.db')
    source=Path(entry['source']);before=source.stat();source_sha=sha(source)
    assert source_sha.lower()==entry['source_sha256'].lower() and before.st_size==entry['bytes'] and before.st_mtime_ns==entry['mtime_ns']
    assert entry['source']==entry['read_path'] and not entry.get('recovery')
    updated=[]
    for e in inv:
        if e['line']!='left':continue
        p=Path(e['source']);st=p.stat()
        if st.st_size!=e['bytes'] or st.st_mtime_ns!=e['mtime_ns']:
            updated.append({'path':str(p),'frozen_bytes':e['bytes'],'current_bytes':st.st_size,'frozen_mtime_ns':e['mtime_ns'],'current_mtime_ns':st.st_mtime_ns,
                'current_boundary_scan_completed':False,'prior_readonly_attempt_error':'database disk image is malformed' if p.name=='1793507670403_DataBaseFile_10.db' else None,
                'note':'No repair, additional deep scan, or database mutation performed. The verified target source is unchanged file8; no all-directory health claim.'})
    c=sqlite3.connect(source.as_uri()+'?mode=ro',uri=True);c.execute('PRAGMA query_only=ON')
    devices=[];point_rows=[];identities={};totalrows=0
    for dev in DEVS:
        datadir=BASE/'data/left'/dev
        with np.load(datadir/'input.npz') as z:
            all_ts=z['timestamp'];names=[str(v) for v in z['names']];sel=(all_ts>=START)&(all_ts<END);ts=all_ts[sel]
            raw=z['x'][sel];old=z['online_x'][sel];roi=z['roi'][sel];y=z['y'][sel];oldy=z['online_y'][sel]
        ix={int(t):i for i,t in enumerate(ts)};jx={n:j for j,n in enumerate(names)};p=len(names)
        fullraw=np.full(raw.shape,np.nan);fullold=np.full(raw.shape,np.nan);fullrawy=np.full(raw.shape,np.nan);fulloldy=np.full(raw.shape,np.nan)
        table='Marker_'+dev;columns=[v[1] for v in c.execute(f'PRAGMA table_info("{table}")')];ci={k:i for i,k in enumerate(columns)}
        seen=set();bindings={};dbcount=0;invalid=0;equal_checks=Counter()
        for full in c.execute(f'SELECT rowid,* FROM "{table}" NOT INDEXED WHERE timestamp>=? AND timestamp<? ORDER BY timestamp,rowid',(START,END)):
            rowid=full[0];v=full[1:];t=int(v[ci['timestamp']]);name=v[ci['markerName']];key=(t,name)
            assert key not in seen;seen.add(key);i,j=ix[t],jx[name];state=v[ci['RoiCalState']];assert state==roi[i,j]
            b=bindings.setdefault(name,{'markerIndex':set(),'markerPos':set(),'first_rowid':rowid,'last_rowid':rowid})
            b['markerIndex'].add(v[ci['markerIndex']]);b['markerPos'].add(v[ci['markerPos']]);b['last_rowid']=rowid
            if state!=1:invalid+=1
            for field,cache,arr in [('x',raw,fullraw),('calX',old,fullold),('y',y,fullrawy),('calY',oldy,fulloldy)]:
                value=v[ci[field]]
                if finite(value):arr[i,j]=value
                if state==1 and finite(value):assert cache[i,j]==value;equal_checks[field]+=1
                else:assert np.isnan(cache[i,j]);equal_checks[field+'_masked']+=1
            dbcount+=1
        assert dbcount==len(ts)*p and len(ts)==600
        totalrows+=dbcount
        for b in bindings.values():b['markerIndex']=sorted(b['markerIndex']);b['markerPos']=sorted(b['markerPos'])
        outpath=BASE/'round2_waveform_10n/results/current_fade07/left'/dev/'output.bin'
        with outpath.open('rb') as f:m,n=struct.unpack('<II',f.read(8))
        native=np.memmap(outpath,dtype=np.dtype([('timestamp','<i8'),('xy','<f8',(2,m))]),offset=8,mode='r',shape=(n,))
        assert m==p and np.array_equal(native['timestamp'],all_ts)
        new=native['xy'][sel,0,:];newy=native['xy'][sel,1,:]
        assert np.array_equal(np.isfinite(new),np.isfinite(raw))
        coverage=json.loads((datadir/'coverage.json').read_text(encoding='utf8'));verification=json.loads(outpath.with_name('verification.json').read_text(encoding='utf8'))
        assert sha(outpath)==verification['output_sha256'] and sha(datadir/'input.bin').lower()==verification['input_sha256'].lower()==coverage['input_sha256'].lower()
        assert any(e['source']==str(source) and e['source_sha256'].lower()==source_sha for e in coverage['sources'])
        statuses=[]
        with outpath.with_name('status.csv').open(encoding='utf8',newline='') as f:
            for row in csv.DictReader(f):
                if START<=int(row['timestamp'])<END:statuses.append(row)
        assert len(statuses)==600
        curves={'raw_roi_valid':raw,'db_calX_roi_valid':old,'current_fade07':new,'raw_database_all_roi':fullraw,'db_calX_database_all_roi':fullold}
        selected=[name for name in names if target(name)];references=[name for name in names if refs(name)]
        baseline=(ts>=START)&(ts<START+3600000);main=(ts>=START+3600000)&(ts<END-3600000)
        ordinary=[j for j,name in enumerate(names) if not refs(name)]
        with warnings.catch_warnings():
            warnings.simplefilter('ignore',RuntimeWarning)
            base=np.nanmedian(raw[baseline],axis=0);centered=raw[:,ordinary]-base[ordinary];common=np.nanmedian(centered,axis=1)
        common[np.isfinite(centered).sum(axis=1)<int(np.ceil(.8*len(ordinary)))]=np.nan
        commons={}
        for label in ['raw_roi_valid','db_calX_roi_valid','current_fade07']:
            peer_values=curves[label][:,ordinary]-base[ordinary]
            with warnings.catch_warnings():
                warnings.simplefilter('ignore',RuntimeWarning);value=np.nanmedian(peer_values,axis=1)
            value[np.isfinite(peer_values).sum(axis=1)<int(np.ceil(.8*len(ordinary)))]=np.nan
            commons[label]=value
        for name in selected+references:
            j=jx[name];windowmetrics={w:{label:metrics(ts,a[:,j],lo,hi) for label,a in curves.items()} for w,(lo,hi) in WINDOWS.items()}
            rec=dict(device=dev,marker=name,is_target_section=target(name),role='XJ' if name.startswith('ZXJ') else 'J' if name.startswith('ZJ') else 'ordinary',
                source_identity=bindings[name],raw_baseline_valid=int(np.isfinite(raw[baseline,j]).sum()),baseline_expected=60,baseline_min_required=10,
                missing_baseline=bool(np.isfinite(raw[baseline,j]).sum()<10),invalid_roi_23_07=int(np.sum(roi[main,j]!=1)),
                invalid_roi_22_08=int(np.sum(roi[:,j]!=1)),raw_device_common_correlation_23_07=corr(raw[main,j]-base[j],common[main]),windows=windowmetrics,
                ordinary_peer_diagnostic_23_07={label:{'correlation':corr(curves[label][main,j]-base[j],cm[main]),
                    'target_minus_peer_common':metrics(ts,curves[label][:,j]-base[j]-cm,START+3600000,END-3600000)} for label,cm in commons.items()},
                y_23_07={'raw':metrics(ts,y[:,j],START+3600000,END-3600000),'db_calY':metrics(ts,oldy[:,j],START+3600000,END-3600000),'new_y':metrics(ts,newy[:,j],START+3600000,END-3600000)})
            point_rows.append(rec)
            if target(name):identities.setdefault(name,[]).append(dev)
        devices.append(dict(device=dev,all_marker_count=p,target_count=len(selected),targets=selected,references=references,all_source_rows=dbcount,
            full_frames=len(ts),invalid_roi_all_markers=invalid,source_columns=columns,all_valid_cache_fields_exact=True,field_check_counts=dict(equal_checks),
            input_npz_sha256=sha(datadir/'input.npz'),input_bin_sha256=verification['input_sha256'],output_sha256=verification['output_sha256'],
            raw_device_common={'method':'ordinary marker raw X minus fixed per-marker22-23 median; frame median over >=80% ordinary peers, no smoothing or fitted slope',
                'peer_count':len(ordinary),'window23_07':metrics(ts,common,START+3600000,END-3600000)},
            peer_common_by_profile={label:metrics(ts,value,START+3600000,END-3600000) for label,value in commons.items()},
            status_by_window={w:{'state_x':dict(Counter(row['state_x'] for row in statuses if lo<=int(row['timestamp'])<hi)),
                'history_x':dict(Counter(row['history_x'] for row in statuses if lo<=int(row['timestamp'])<hi)),
                'modes_x':dict(Counter(row['modes_x'] for row in statuses if lo<=int(row['timestamp'])<hi)),
                'corrected_x_min':min(int(row['corrected_x']) for row in statuses if lo<=int(row['timestamp'])<hi),
                'corrected_x_max':max(int(row['corrected_x']) for row in statuses if lo<=int(row['timestamp'])<hi)} for w,(lo,hi) in WINDOWS.items()}))
        print('DEVICE_OK',dev,dbcount,len(selected),flush=True)
    c.close();after=source.stat();assert after.st_size==before.st_size and after.st_mtime_ns==before.st_mtime_ns
    targets=[p for p in point_rows if p['is_target_section']]
    summary={}
    for w in ['23_07','22_08']:
        summary[w]={}
        for profile in ['raw_roi_valid','db_calX_roi_valid','current_fade07']:
            vals=[p['windows'][w][profile]['p2p'] for p in targets]
            summary[w][profile]={'points':len(vals),'within1':sum(v<=1 for v in vals),'within2':sum(v<=2 for v in vals),'median_range':float(np.median(vals)),'max_range':max(vals),'min_range':min(vals)}
    report=dict(scope='Left sections42-47 by exact ZD42xx..ZD47xx names, per-device identities retained; 2026-11-12 night. Read-only source verification, no native DLL execution.',
        user_confirmed_scope='The user reviewed the exported10-night CSV/atlas for23:00-07:00, not an initialization-state replay. Post07:00 raw behavior is accepted. Therefore exit behavior does not explain away the main-window complaint.',
        auxiliary_window_scope='22:00-08:00 and exit subwindows use frozen R2 current_fade07 internal outputs only. They are not the R8 release routing outputs or the delivered23:00-07:00 CSV. These auxiliary metrics are not acceptance failures for the user-confirmed window.',
        source={'path':str(source),'sha256':source_sha,'hash_matches_frozen_inventory':True,'metadata_matches_frozen_inventory':True,'stable_before_after_read':True,
            'recovery_used':False,'query_mode':'SQLite mode=ro + PRAGMA query_only=ON, NOT INDEXED, timestamp,rowid order','source_rows_compared':totalrows,
            'valid_xy_calxy_match_cache_exactly':True,'roi_invalid_cache_cells_masked_not_zeroed':True},
        latest_directory_limitations=updated,selection_rule='fullmatch ^ZD(?:42|43|44|45|46|47)\\d{2}$; section identity inferred from marker name, actual markerIndex/markerPos preserved separately',
        same_name_cross_device={n:v for n,v in identities.items() if len(v)>1},distinct_marker_names=len(identities),device_marker_pairs=len(targets),
        windows={w:{'start_inclusive':local(lo),'end_exclusive':local(hi)} for w,(lo,hi) in WINDOWS.items()},summary=summary,devices=devices,points=point_rows,
        target_missing_baseline_count=sum(p['missing_baseline'] for p in targets),
        worst23_07=[{'device':p['device'],'marker':p['marker'],'raw':p['windows']['23_07']['raw_roi_valid'],'old':p['windows']['23_07']['db_calX_roi_valid'],'new':p['windows']['23_07']['current_fade07']} for p in sorted(targets,key=lambda p:p['windows']['23_07']['current_fade07']['p2p'],reverse=True)[:10]],
        metrics_note='Ranges use actual samples without smoothing/interpolation. Primary comparisons apply RoiCalState==1, matching replay input. Original finite database x/calX including invalid ROI are separately reported. Endpoint trend is last30-minute median minus first30-minute median, not a fitted slope.',
        field_evidence_note='User reports total-station confirmation that the target phenomenon is equipment disturbance, not true displacement. This report does not independently verify that measurement and does not equate curve range reduction with physical accuracy.',
        audit_script_sha256=sha(__file__))
    (OUT/'source_data_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
    lines=['# 左线42–47断面：11/12夜数据源与残留波动审查','','用户确认查看的是已导出的十夜CSV/图册，主窗23–07，并已允许07点后恢复raw。因此主问题应聚焦327479/ZXJ6在主窗内的反向残留，不能用退出时段解释掉本次反馈。普通测点37组均低于2 pixel并不代表整台设备的参考相关观测已经合格。', '',
        '按测点名ZD42xx–ZD47xx核对，共3台设备、37组设备+测点观测。同名跨设备分开，不能合并；实际markerIndex、markerPos及rowid来源见JSON。', '',
        '目标时段来自左线file8，当前SHA与冻结清单完全相同。只读逐行核对3台设备共99,000条原始记录：ROI和有效x/y/calX/calY与冻结缓存完全一致，600帧均齐全；原库未修改。左file10已于11/17增长，但此前只读边界扫描报database disk image is malformed，未恢复或进一步深扫，不能宣称整个当前数据库目录健康。该独立限制不改变已核验的file8目标窗口结论。','',
        '**辅助窗口边界：下表22–08及07点后分段使用冻结R2 current_fade07内部输出做诊断，既不是R8发布路由输出，也不是交付的23–07 CSV。它们不作为用户主窗验收失败项。**', '',
        '| 窗口 | 曲线 | ≤1 pixel | ≤2 pixel | 最大峰谷差 |','|---|---|---:|---:|---:|']
    for w in ['23_07','22_08']:
        for profile,label in [('raw_roi_valid','数据库raw X（ROI有效）'),('db_calX_roi_valid','数据库旧calX（ROI有效）'),('current_fade07','新current_fade07')]:
            s=summary[w][profile];lines.append(f"| {w.replace('_','–')} | {label} | {s['within1']}/37 | {s['within2']}/37 | {s['max_range']:.6f} |")
    lines += ['', '23–07目标测点基准有效58–60/60帧，主窗有效476–480/480；没有缺基准或大量ROI缺失导致整夜跳过修复的证据。23–07全部37组新曲线低于2 pixel，32组低于1 pixel；残留最大的5组见下。', '',
        '| 设备 | 测点 | raw峰谷差 | 旧calX峰谷差 | 新峰谷差 | 新P95−P5 |','|---|---|---:|---:|---:|---:|']
    for p in report['worst23_07'][:5]:lines.append(f"| {p['device']} | {p['marker']} | {p['raw']['p2p']:.6f} | {p['old']['p2p']:.6f} | {p['new']['p2p']:.6f} | {p['new']['p95p5']:.6f} |")
    lines += ['', '## 关键残留与退出行为', '',
        '327479的普通点原始共趋势（固定22–23原始中位基准后的逐帧中位）在主窗内上升约3.983 pixel，峰谷差5.513 pixel。该设备ZD4403/4503/4603/4703的新输出仍有反向缓慢变化，首末30分钟中位差分别约−0.770/−0.628/−0.501/−0.887 pixel；旧calX对应约−0.472/−0.353/−0.313/−0.454。虽然相对raw幅度大幅降低，不能忽略新输出比旧输出更大的残留反向趋势。此处仅定位现象，不据相关性指定哪一级算法造成。', '',
        '同设备ZXJ6需要单列：23–07的raw/旧calX/新幅度为13.7019/6.8111/6.8436 pixel，新输出首末中位差−4.2105 pixel。该点基准60/60、主窗480/480有效，不能归因于缺基准或ROI缺测。它与原始普通点共趋势相关系数约0.6065，不能仅因全设备在动就当作完全相同共模。若后续平差使用ZXJ6，这个剩余趋势可能重要；是否实际引入解算偏差须核对平差输入和公式。ZJ5–7新幅度0.596/0.605/0.805，ZJ8为1.129 pixel。', '',
        '辅助冻结内部输出中，07–07:20各设备均20帧RAMP；07:20–08均40帧PASSTHROUGH（核心模态已退出，W3仍可影响X输出）。327479/ZD4703在23–07幅度1.4954，但该辅助22–08为5.4106，最大值出现在07:24。用户已接受07点后raw，因此这里只记录退出机制，不将其作为本次23–07问题的解释或新增修复目标。', '',
        'JSON同时列出22–23基准、23–23:20进入、23:20–07满门控、07–07:20退出和07:20–08结束后的各点范围与状态计数。22–08包含基准/退出/退出后时段，不能拿该整窗幅度直接解释为23–07未修复。', '',
        '源数据库的无效ROI行仍可能有有限x/calX；主比较按ROI有效样本，与实际算法输入一致，另列原库全部有限数值范围。峰谷和时间均来自实际样本，无平滑、插值或拟合。趋势值仅为末30分钟中位数减首30分钟中位数。', '',
        '用户给出全站仪核实“属于设备扰动”的现场证据；本审查记录该信息，但未独立复核全站仪测量。曲线范围缩小、状态CORRECTING或历史3夜均不能单独证明物理精度。','']
    (OUT/'source_data_audit.md').write_text('\n'.join(lines),encoding='utf8')
    print(json.dumps(summary,ensure_ascii=True))

if __name__=='__main__':main()
