"""Read-only inspection of frozen current_fade07 states. No DLL execution or state writes."""
from pathlib import Path
from datetime import date, datetime, timedelta, timezone
import hashlib, json, struct, csv
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT.parent
R2=BASE/'round2_waveform_10n'
OUT=ROOT/'reports'
MAGIC=b'MSC_STATE_V54_ASTRA_HISTORY1\n'
NIGHTS=['2026-11-13','2026-11-14','2026-11-15']
TZ=timezone(timedelta(hours=8))
CONFIG='8,22,23,26,31,20,60,3,0.5,3,3,0.80000000000000004,0.59999999999999998,10,5,2.5,0,1,Astra-history-energy-v1,0,1,1,0.55000000000000004,1,1.5,3,Astra-window-v1,0,1:2:YJ:2:ZJ'

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''): h.update(b)
    return h.hexdigest()

def local(ts): return datetime.fromtimestamp(ts/1000,TZ).isoformat(timespec='milliseconds')
def ms(s): return int(datetime.fromisoformat(s).replace(tzinfo=TZ).timestamp()*1000)
def night_date(key): return str(date(1970,1,1)+timedelta(days=int(key)))
def numbers(s): return np.array([float(v) for v in s.split(',')]) if s else np.array([])

def decode(path):
    b=path.read_bytes();assert b.startswith(MAGIC)
    expected=struct.unpack_from('<Q',b,len(b)-8)[0]
    h=14695981039346656037
    for c in b[:-8]: h=((h^c)*1099511628211)&((1<<64)-1)
    assert h==expected,'FNV checksum mismatch'
    pos=len(MAGIC)
    def u():
        nonlocal pos
        assert pos+8<=len(b)
        n=struct.unpack_from('<Q',b,pos)[0];pos+=8;return n
    def text():
        nonlocal pos
        n=u();assert n<=256*1024*1024 and pos+n<=len(b)
        s=b[pos:pos+n].decode('utf8');pos+=n;return s
    revision,ts=u(),u();device,config=text(),text();count=u()
    assert 0<count<=10000
    names=[text() for _ in range(count)];axes=[text(),text()]
    assert pos+8==len(b) and len(set(names))==len(names)
    return dict(revision=revision,timestamp=ts,device=device,config=config,names=names,axes=axes,
                bytes=len(b),sha256=sha(path),checksum_fnv1a64=f'{expected:016x}',checksum_valid=True)

def inspect_axis(text,names,ts):
    assert text.startswith('# MODALSELFCAL_AXIS_V1\n')
    data={};hist=[];current=None
    for line in text.splitlines():
        if '=' not in line: continue
        k,v=line.split('=',1)
        if k=='hist_night_id':
            current={'night_id':int(v),'night':night_date(v)};hist.append(current)
        elif k.startswith('hist_') and k!='hist_n':
            assert current is not None;current[k]=v
        else: data.setdefault(k,[]).append(v)
    def single(k): assert len(data[k])==1;return data[k][0]
    assert single('names').split(',')==names
    assert int(single('last_ts'))==ts and int(single('has_last_ts'))==1
    assert int(single('hist_n'))==len(hist)==3
    assert [h['night'] for h in hist]==NIGHTS
    p=len(names);tri=p*(p+1)//2
    for key in ['ref_sum','ref_cnt','b','cbar','use','learn']:
        assert len(numbers(single(key)))==p,(key,p)
    for key in ['S','N']: assert len(numbers(single(key)))==tri
    assert len(numbers(single('A')))==3*p
    assert len(data.get('ref',[]))==int(single('ref_buf_n'))
    assert all(len(numbers(row))==p+1 for row in data.get('ref',[]))
    for h in hist:
        assert h['hist_names'].split(',')==names
        h['frames']=int(h.pop('hist_n_frames'));h.pop('hist_names')
        S=numbers(h.pop('hist_S'));N=numbers(h.pop('hist_N'))
        assert len(S)==len(N)==tri and np.isfinite(S).all() and np.isfinite(N).all()
        assert ((N>=0)&(N<=h['frames'])&(N==np.floor(N))).all()
        diag=[];at=0
        for j in range(p): diag.append(int(N[at]));at+=p-j
        h['valid_frames_by_marker']=dict(zip(names,diag))
        h['_N']=N
    result={k:int(single(k)) for k in ['has_night','night_id','frozen','learn_done','n_learn','modes_has','modes_from_tonight','n_learn_points','hist_n','ref_buf_n']}
    result.update(cfg=single('cfg'),current_night=night_date(result['night_id']),last_timestamp_ms=ts,
                  histories=hist,all_dimensions_valid=True,roster_order_exact=True)
    total=sum(h['frames'] for h in hist)
    valid={name:sum(h['valid_frames_by_marker'][name] for h in hist) for name in names}
    result['pooled_history_frames']=total
    result['pooled_valid_frames_by_marker']=valid
    result['pooled_below80_markers']=[name for name in names if valid[name]<0.8*total]
    return result,data

def enhancements(data,names,cutoff):
    p=len(names)
    w=data['w3'][0].split(';');assert len(w)==p
    counts=[]
    for row in w:
        vals=row.split(',');assert len(vals)==4
        count=int(vals[0]);assert 0<=count<=3
        assert np.isfinite([float(v) for v in vals[1:]]).all();counts.append(count)
    mount=data['mount'][0].split('|');assert len(mount)==7
    nid,shift,ready=int(mount[0]),int(mount[1]),int(mount[2]);ref=numbers(mount[3]);drift=numbers(mount[4]);n=int(mount[5])
    frames=[] if not mount[6] else mount[6].split(';')
    assert shift in [0,1] and ready in [0,1] and len(ref)==p and len(drift)<=15 and len(frames)==n
    assert (ready and n==30) or (not ready and 0<=n<30)
    assert np.isfinite(drift).all() and all(len(numbers(f))==p for f in frames)
    vel=data['vel'][0].split(';');assert len(vel)==p
    vel_ts=[]
    for row in vel:
        value,t=row.split(',');float(value);t=int(t);assert t<=cutoff;vel_ts.append(t)
    return dict(components=['w3','mount','vel'],all_dimensions_valid=True,w3_counts=counts,
                mount_night_id=nid,mount_in_shift=shift,mount_ready=ready,mount_reference_count=p,
                mount_drift_count=len(drift),mount_baseline_frame_count=n,velocity_timestamp_min=min(vel_ts),velocity_timestamp_max=max(vel_ts))

def read_input(path):
    b=path.read_bytes();at=0
    def u():
        nonlocal at
        v=struct.unpack_from('<I',b,at)[0];at+=4;return v
    p=u();names=[]
    for _ in range(p):
        n=u();names.append(b[at:at+n].decode('utf8'));at+=n
    count=u();stride=8+16*p
    assert at+count*stride==len(b)
    return names,count,struct.unpack_from('<q',b,at)[0],struct.unpack_from('<q',b,at+(count-1)*stride)[0]

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    manifest_path=R2/'build/native_window_manifest.json';manifest=json.loads(manifest_path.read_text(encoding='utf8'))
    sources=[]
    for rel,expected in manifest['source_sha256'].items():
        path=R2/rel;actual=sha(path);assert actual==expected
        sources.append({'path':str(path),'sha256':actual,'matches_native_manifest':True})
    dll=R2/manifest['binary'];assert sha(dll)==manifest['binary_sha256']
    devices=[]
    for path in sorted((R2/'results/current_fade07').glob('*/*/output.bin.state')):
        line,dev=path.parts[-3:-1];state=decode(path);assert state['device']==dev and state['config']==CONFIG
        names=state['names'];p=len(names);ts=state['timestamp']
        x,xdata=inspect_axis(state['axes'][0],names,ts);y,ydata=inspect_axis(state['axes'][1],names,ts)
        assert x['cfg']=='3,22,23,26,3,1' and y['cfg']=='3,22,23,26,3,0'
        enh=enhancements(xdata,names,ts)
        data_dir=BASE/'data'/line/dev;covpath=data_dir/'coverage.json';cov=json.loads(covpath.read_text(encoding='utf8'))
        verification_path=path.with_name('verification.json');verification=json.loads(verification_path.read_text(encoding='utf8'))
        binpath=data_dir/'input.bin';inputsha=sha(binpath)
        assert inputsha.lower()==cov['input_sha256'].lower()==verification['input_sha256'].lower()
        in_names,frames,first,last=read_input(binpath)
        assert in_names==names==cov['names'] and last==ts and frames==state['revision']==cov['frames']
        configpath=path.with_name('output.bin.config.json');config=json.loads(configpath.read_text(encoding='utf8'))
        assert config==verification['actual_config'] and config['profile_id']==14 and config['fade_x_enhancements_with_gate']
        with np.load(data_dir/'input.npz') as cache:
            times=cache['timestamp'];assert int(times[-1])==ts and [str(v) for v in cache['names']]==names
            history_sources=[]
            for night in NIGHTS:
                lo=ms(night+'T22:00');hi=lo+4*3600000
                target=(times>=lo)&(times<hi);baseline=(times>=lo)&(times<lo+3600000)
                close=times[times>=hi][0]
                history_sources.append(dict(night=night,night_id=(date.fromisoformat(night)-date(1970,1,1)).days,
                    baseline_frames=int(baseline.sum()),learn_frames=int(target.sum()),first_close_timestamp=int(close),first_close_local=local(int(close))))
                for key,axis in [('x',x),('y',y)]:
                    values=cache[key];valid=np.isfinite(values[target])&(np.isfinite(values[baseline]).sum(axis=0)>=10)[None,:]
                    count=valid.astype(np.int64).T@valid.astype(np.int64)
                    upper=count[np.triu_indices(p)]
                    hist=next(h for h in axis['histories'] if h['night']==night)
                    hist['pairwise_valid_counts_equal_frozen_input']=bool(np.array_equal(hist['_N'],upper))
                    assert hist['pairwise_valid_counts_equal_frozen_input'],(dev,key,night)
                    hist.pop('_N')
        output=path.with_name('output.bin');assert sha(output)==verification['output_sha256']
        with output.open('rb') as f:
            m,n=struct.unpack('<II',f.read(8));assert m==p and n==frames
            f.seek(8+(n-1)*(8+16*p));assert struct.unpack('<q',f.read(8))[0]==ts
        with path.with_name('status.csv').open(encoding='utf8',newline='') as f:
            laststatus=None
            for laststatus in csv.DictReader(f):pass
        assert int(laststatus['timestamp'])==ts and laststatus['history_x']==laststatus['history_y']=='3'
        devices.append(dict(line=line,device=dev,source_state=str(path),state_sha256=state['sha256'],bytes=state['bytes'],
            fnv1a64=state['checksum_fnv1a64'],checksum_valid=True,revision=state['revision'],timestamp_ms=ts,last_frame_local=local(ts),
            marker_count=p,marker_names_in_required_import_order=names,config_fingerprint=state['config'],config_matches_profile14=True,
            axis_x=x,axis_y=y,enhancements=enh,input_bin_sha256=inputsha,input_bin=str(binpath),
            input_first_local=local(first),input_last_matches_state=True,output_last_matches_state=True,
            output_sha256=verification['output_sha256'],coverage_sha256=sha(covpath),verification_sha256=sha(verification_path),
            config_file_sha256=sha(configpath),history_input_coverage=history_sources,final_status=laststatus,
            static_reuse_decision='CAN_COPY_BYTES_FOR_NEXT_NIGHT_WITH_EXACT_CONFIG_AND_ROSTER',
            external_native_roundtrip_performed=False))
        print('STATE_OK',line,dev,p,local(ts),x['pooled_below80_markers'],flush=True)
    assert len(devices)==12 and sum(d['marker_count'] for d in devices)==524
    report=dict(scope='Read-only serialization/source review; no state writes, no DLL load, no native execution.',
        recommendation='Reuse exact existing bytes for 2026-11-16 night with compatible current_fade07 source/config/roster. No history rebuild needed.',
        state_format={'magic':MAGIC.decode(),'outer_layout':['magic','u64le revision','u64le last_timestamp_ms','u64le-byte-length UTF8 device','u64le-byte-length UTF8 ConfigKey','u64le roster count','length-prefixed UTF8 names in exact order','length-prefixed X text including Scheme D','length-prefixed Y text','u64le FNV-1a64 over all preceding bytes'],
            'axis_format':'# MODALSELFCAL_AXIS_V1 text; hist_n and repeated hist_night_id/hist_n_frames/hist_names/hist_S/hist_N; symmetric matrices stored upper triangle in row order.',
            'night_key_rule':'Local UTC+8 date expressed as epoch-day, with local times before 12:00 attributed to previous date.',
            'learning_window':'22:00 inclusive to next 02:00 exclusive; first real frame at/after 02:00 appends night. This is not the 23:00-07:00 evaluation window.',
            'enhancement_components':['W3 point buffers','mount baseline, drift, warmup frames','velocity value and per-point timestamps']},
        required_history_nights=NIGHTS,summary={'devices':len(devices),'markers':sum(d['marker_count'] for d in devices),'both_axes_history3':True,'exact_requested_history_all_devices':True,'all_checksums_valid':True,'all_pairwise_hist_N_equal_frozen_input':True,'all_native_source_hashes_match_manifest':True,'external_native_roundtrips_this_audit':0},
        source_manifest=str(manifest_path),source_manifest_sha256=sha(manifest_path),source_files=sources,
        existing_native_binary={'path':str(dll),'sha256':sha(dll),'matches_manifest':True,'loaded_in_this_audit':False,
            'exported_entry_points':['replay_profile','window_native_checks'],'external_state_roundtrip_entry_point':False,
            'capability':'profile14 cold replay can export HISTORY1; native checks import snapshots generated internally using profiles11/15 and synthetic fade. Neither entry point accepts an external state path.'},
        incompatible_old_tools=[{'path':'delivery_20261111_V52_dev0/tools/verify.exe','reason':f'Legacy V50R magic/config and hardcoded outer-header offset15; incompatible with HISTORY1 magic length{len(MAGIC)}.'},
            {'path':'offline_state_builder_V50/generate_state.py','reason':'inspect_state asserts MSC_STATE_V50R; builder uses older V50 code. Do not migrate fingerprints to force acceptance.'}],
        native_execution_boundary={'attempted':False,'known_block_report':str(BASE/'round3_physics_failure/reports/native_execution_block.json'),
            'new_build_for_delivery_still_needs':'Approved native build environment should run Init(device, exact ordered roster, false), ImportState, ExportState byte equality and held-out resume checks against final delivered cpp/h.'},
        reuse_conditions=['Exact device ID, math ConfigKey, marker name order, and HISTORY1-compatible reader.',
            'Pass only timestamps greater than state cutoff; input order must match saved names or be explicitly mapped by name first.',
            'State current night remains11/15. Retained history is13/14/15; cached A/cbar were frozen for11/15. New night reset and23:00 freeze rebuild next-night A from retained history.',
            'Snapshot includes complete active/filter state, not merely three hist matrices. Copy unchanged; no fingerprint patch or manual reset.',
            'State correctness/import readiness does not establish physical correction accuracy or per-marker history eligibility.'],
        devices=devices,audit_script_sha256=sha(__file__))
    path=OUT/'state_source_review.json';path.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
    lines=['# 11/13、11/14、11/15 三夜状态源审查','','现有 12 份 current_fade07 原生导出状态可按原字节复用，作为 2026-11-16 夜的初始化状态；无需重新学习历史。条件是交付源码继续兼容 HISTORY1 格式，配置指纹和测点顺序与状态完全一致。本审查仅静态解析与输入绑定核对，未加载 DLL，未把静态通过描述成逐份原生 Import/Export 已通过。','',
        '12 台、524 个测点，两轴均恰好保存 2026-11-13、11-14、11-15，hist_n=3，每夜 hist_n_frames=240。全部 FNV-1a 校验、UTF-8/长度边界、数组维度、状态/输入/输出末时间、配置和 marker 顺序校验通过；历史 N 的全部测点两两有效样本计数与冻结 input.npz 逐项完全相等。','',
        '## 逐台来源','','| 线路 | 设备 | 点数 | 状态截止（北京时间） | X/Y历史 | 三夜帧数 | X池化有效率低于80%的点 |','|---|---|---:|---|---|---|---|']
    for d in devices:
        lines.append(f"| {'左线' if d['line']=='left' else '右线'} | {d['device']} | {d['marker_count']} | {d['last_frame_local']} | 13/14/15，3/3 | 240/240/240 | {', '.join(d['axis_x']['pooled_below80_markers']) or '无'} |")
    lines += ['', '学习窗为 22:00–次02:00；23:00–次07:00是图册评价窗，两者不能混同。每夜包含60帧基准窗和180帧后续学习数据，次02:00后的第一条真实数据触发收夜；具体触发时间见JSON。历史满3夜不代表所有测点都满足80%有效率，逐点有效数同时记录在JSON。', '',
        '## 复用与集成边界','','- 原封不动复制快照；不要只提取 history，不要改配置指纹，不要人工改夜号或清零滤波器。','- 快照当前夜号仍为11/15：保留历史已更新到13/14/15，但当前A/cbar仍是11/15冻结的模态。11/16本地中午后进入新夜会重置当夜缓存，23:00冻结基准时再从保留三夜计算模态。','- Init须使用该设备的精确保存测点顺序；本次顺序是缓存markerName顺序，与数据库rowid帧内顺序不同。业务程序需按名称映射输入输出，不能只保证点集合相同。','- 仅接收严格晚于状态截止的新帧；用于11/16夜合适，不能将该状态用于重新推理11/13–15的过去时段。','- current_fade07指纹包含 fade_x_enhancements_with_gate=true、x_apply_end_h=0、apply_end_h=31、max_frame_dev=0。旧window_candidate头文件默认fade=false，交付若使用默认构造需显式匹配profile14。','',
        '## 可用验证工具与未覆盖项','','已有 native_window.dll 的文件SHA与冻结原生构建清单一致；导出入口仅 replay_profile 和 window_native_checks。前者可profile14冷启动连续回放并导出状态，后者检查内部生成快照的重启一致性。两者都不能接收这12份外部state做直接往返。旧 verify.exe 和 offline_state_builder_V50 使用V50R格式或固定头偏移，不能用来验证HISTORY1。','',
        '最终交付cpp/h应在允许的原生环境运行逐份 Init → ImportState → ExportState 字节一致核验，并做后续真实帧恢复比较。本审查没有执行新DLL、没有重试已被代码完整性策略拒绝的程序，也没有绕过策略。此前已有重启证据可佐证实现曾运行，但不是此次12份外部state逐份重导入的替代。','',
        '详细magic/layout、源文件和DLL SHA、每台完整marker顺序、三夜有效样本、状态SHA和完整配置指纹见 `state_source_review.json`。','']
    (OUT/'state_source_review.md').write_text('\n'.join(lines),encoding='utf8')
    print(json.dumps(report['summary'],ensure_ascii=True))

if __name__=='__main__':main()
