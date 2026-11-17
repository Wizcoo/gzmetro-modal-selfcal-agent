"""Full-roster Chinese SVG atlas from frozen native output; no resampling or CSV export."""
from pathlib import Path
from datetime import datetime,timedelta,timezone
import argparse,hashlib,html,json,math,os,re,struct,time
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT.parent
OUT=ROOT/'plots'
REPORT=ROOT/'reports'
PROFILE='current_fade07'
TZ=timezone(timedelta(hours=8))
NIGHTS=[f'2026-11-{i:02d}' for i in range(6,16)]
COLORS={'raw':'#7b8692','calx':'#2873b9','new':'#cb4d40'}
CSS='''*{box-sizing:border-box}body{max-width:1540px;margin:28px auto;padding:0 22px;color:#263b4b;background:#f4f7f9;font:16px/1.7 "Microsoft YaHei","Noto Sans CJK SC",sans-serif}h1{font-size:30px;line-height:1.4}h2{font-size:23px}h3{font-size:19px;margin:4px 0}a{color:#13678f;text-decoration:none}a:hover{text-decoration:underline}header,.panel,figure{background:#fff;border:1px solid #d8e1e8;border-radius:9px;padding:20px;margin:22px 0}nav{display:flex;flex-wrap:wrap;gap:10px 22px;margin-bottom:14px}figure{scroll-margin-top:10px}figcaption{margin-bottom:12px}img{display:block;width:100%;height:auto;background:white}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:9px 12px;text-align:left;border-bottom:1px solid #e0e7ed}th{background:#ecf2f6}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:16px}.card{border:1px solid #d8e1e8;border-radius:7px;padding:16px;background:#fff}.tag{display:inline-block;background:#eaf0f5;border-radius:4px;padding:2px 8px;font-size:13px;margin-left:7px}.small{color:#5c6e7c;font-size:14px}.notice{border-left:4px solid #d39b3a;background:#fff4df;padding:15px 18px;margin:20px 0}.stats{display:flex;flex-wrap:wrap;gap:12px}.stats span{background:#edf3f6;padding:10px 16px;border-radius:6px}.stats b{font-size:24px}.marker-links{display:flex;flex-wrap:wrap;gap:5px 14px}.muted{color:#7b858e}.scroll{overflow:auto}.missing{color:#966822}.legend{display:flex;gap:16px;flex-wrap:wrap}.legend span:before{content:"";display:inline-block;width:30px;margin:0 7px 4px 0;border-top:3px solid;vertical-align:middle}.raw{color:#64717f}.calx{color:#2873b9}.calx:before{border-top-style:dashed!important}.new{color:#cb4d40}@media print{body{background:white;margin:0;padding:0}nav,.marker-links{display:none}figure{break-inside:avoid;border:0;padding:0}.panel{border:0}}'''

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def ms(s):return int(datetime.fromisoformat(s).replace(tzinfo=TZ).timestamp()*1000)
def local(t):return datetime.fromtimestamp(int(t)/1000,TZ)
def esc(v):return html.escape(str(v),quote=True)
def lc(line):return '左线' if line=='left' else '右线'
def role(name):return 'XJ普通测点' if 'XJ' in name.upper() else 'J基准点' if 'J' in name.upper() else '普通测点'
def rank(name):return (1 if 'XJ' in name.upper() else 0 if 'J' in name.upper() else 2,[int(s) if s.isdigit() else s for s in re.split(r'(\d+)',name)])
def filename(name):
    candidate=re.sub(r'[^A-Za-z0-9_.-]','_',name)
    return candidate if candidate==name else candidate+'_'+hashlib.sha256(name.encode()).hexdigest()[:8]
def number(v):return '—' if v is None else f'{v:.3f}'
def metrics(v):
    z=np.asarray(v);z=z[np.isfinite(z)]
    if not len(z):return {'valid':0,'min':None,'max':None,'range':None}
    return {'valid':int(len(z)),'min':float(z.min()),'max':float(z.max()),'range':float(np.ptp(z))}
def page(title,body):
    return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+esc(title)+'</title><style>'+CSS+'</style></head><body>'+body+'</body></html>'
def link_from(page_path,target):return os.path.relpath(target,page_path.parent).replace('\\','/')
def framework(page_path):return f'<a href="{esc(link_from(page_path,ROOT/"算法框架.html"))}">算法框架与阅读说明</a>'
def legends():return '<div class="legend"><span class="raw">数据库 raw X</span><span class="calx">原算法 calX（数据库）</span><span class="new">新算法 X</span></div>'
def write_html(path,title,body):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(page(title,body),encoding='utf8')

def native(path):
    with path.open('rb') as f:m,n=struct.unpack('<II',f.read(8))
    dt=np.dtype([('timestamp','<i8'),('xy','<f8',(2,m))])
    assert path.stat().st_size==8+n*dt.itemsize
    return np.memmap(path,dtype=dt,mode='r',offset=8,shape=(n,))

def nice_axis(values):
    finite=values[np.isfinite(values)]
    if not len(finite):return -1.,1.,[-1.,0.,1.],1
    lower=float(finite.min());upper=float(finite.max());pad=max(.025,(upper-lower)*.06)
    lower-=pad;upper+=pad;target=(upper-lower)/5
    exponent=10**math.floor(math.log10(target));fraction=target/exponent
    step=next(s for s in [1.,2.,2.5,5.,10.] if s>=fraction)*exponent
    lo=math.floor(lower/step)*step;hi=math.ceil(upper/step)*step
    ticks=[lo+i*step for i in range(int(round((hi-lo)/step))+1)]
    decimals=max(0,-int(math.floor(math.log10(step))))+(1 if abs(step/exponent-2.5)<1e-8 else 0)
    return lo,hi,ticks,decimals

def curve_path(t,y,xx,yy):
    commands=[];isolated=[];last=None;segpoints=[];segments=0;points=0
    for timestamp,value in zip(t,y):
        if not np.isfinite(value):
            if len(segpoints)==1:isolated.append(segpoints[0])
            segpoints=[];last=None;continue
        px,py=xx(timestamp),yy(value)
        if last is None or timestamp-last>180000:
            if len(segpoints)==1:isolated.append(segpoints[0])
            commands.append(f'M {px:.3f} {py:.3f}');segpoints=[(px,py)];segments+=1
        else:commands.append(f'L {px:.3f} {py:.3f}');segpoints.append((px,py))
        last=timestamp;points+=1
    if len(segpoints)==1:isolated.append(segpoints[0])
    return ' '.join(commands),isolated,points,segments

def render_svg(path,line,dev,name,night,t,values,stats,expected=480):
    W,H=1440,450;left,right,top,bottom=100,28,114,86;pw=W-left-right;ph=H-top-bottom
    start=ms(night+' 23:00');end=start+8*3600000
    lo,hi,ticks,dec=nice_axis(values)
    xx=lambda v:left+(int(v)-start)/(end-start)*pw
    yy=lambda v:top+(hi-float(v))/(hi-lo)*ph
    limit=1 if 'J' in name.upper() else 2
    ref=f'原幅度参考 ≤{limit} pixel'+('；XJ绝对幅度仅作描述' if 'XJ' in name.upper() else '')
    desc=f'{lc(line)} {dev} / {name}；{night} 23:00至次日07:00；三条曲线原基准原时间，无插值或抽点'
    body=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="title desc">',
        f'<title id="title">{esc(lc(line)+" "+dev+" / "+name+" "+night)}</title><desc id="desc">{esc(desc)}</desc>',
        '<rect width="100%" height="100%" fill="white"/>',
        '<g font-family="Microsoft YaHei,Noto Sans CJK SC,sans-serif" fill="#283d4d">',
        f'<text x="24" y="27" font-size="19" font-weight="600">{esc(lc(line))} {esc(dev)} / {esc(name)}（{esc(role(name))}）</text>',
        f'<text x="24" y="52" font-size="14">{night} 23:00 — {local(end):%Y-%m-%d} 07:00　｜　{esc(ref)}　｜　有效 {stats["new"]["valid"]}/{expected} 帧</text>',
        f'<text x="24" y="76" font-size="14">范围 max−min：raw X {number(stats["raw"]["range"])}　／　calX {number(stats["calx"]["range"])}　／　新算法 {number(stats["new"]["range"])} pixel</text>']
    for x,key,label,dash in [(380,'raw','数据库 raw X',''),(655,'calx','原算法 calX（数据库）','stroke-dasharray="7 4"'),(1000,'new','新算法 X','')]:
        body.append(f'<line x1="{x}" x2="{x+35}" y1="96" y2="96" stroke="{COLORS[key]}" stroke-width="2" {dash}/><text x="{x+45}" y="101" font-size="14">{esc(label)}</text>')
    draw={}
    if len(t)==0:
        body.extend([f'<rect x="{left}" y="{top}" width="{pw}" height="{ph}" rx="5" fill="#f2f4f6" stroke="#e0e5e9"/>',f'<text x="{W/2}" y="{top+ph/2-8}" text-anchor="middle" font-size="24" fill="#8b6a39">本夜源数据缺失</text>',f'<text x="{W/2}" y="{top+ph/2+26}" text-anchor="middle" font-size="15">不补点，不用其他夜替代；该夜保留在10夜目录中</text>'])
        draw={key:{'points':0,'segments':0,'isolated_points':0} for key in ['raw','calx','new']}
    else:
        for tick in ticks:
            py=yy(tick);label=f'{tick:.{dec}f}'
            if abs(tick)<1e-12:label=f'{0:.{dec}f}'
            body.append(f'<line x1="{left}" x2="{W-right}" y1="{py:.3f}" y2="{py:.3f}" stroke="#e6ebef"/><text x="{left-12}" y="{py+4:.3f}" text-anchor="end" font-size="13">{label}</text>')
        for hour in range(9):
            ts=start+hour*3600000;px=xx(ts);dt=local(ts)
            body.append(f'<line x1="{px:.3f}" x2="{px:.3f}" y1="{top}" y2="{H-bottom}" stroke="#e6ebef"/><text x="{px:.3f}" y="{H-bottom+25}" text-anchor="middle" font-size="13">{dt:%m-%d}</text><text x="{px:.3f}" y="{H-bottom+44}" text-anchor="middle" font-size="13">{dt:%H:%M}</text>')
        body.extend([f'<line x1="{left}" x2="{left}" y1="{top}" y2="{H-bottom}" stroke="#788692"/>',f'<line x1="{left}" x2="{W-right}" y1="{H-bottom}" y2="{H-bottom}" stroke="#788692"/>',f'<defs><clipPath id="plotclip"><rect x="{left}" y="{top}" width="{pw}" height="{ph}"/></clipPath></defs><g clip-path="url(#plotclip)">'])
        for column,key in enumerate(['raw','calx','new']):
            pathdata,dots,points,segments=curve_path(t,values[:,column],xx,yy)
            assert points==stats[key]['valid']
            draw[key]={'points':points,'segments':segments,'isolated_points':len(dots)}
            dash=' stroke-dasharray="6 4"' if key=='calx' else ''
            body.append(f'<path data-series="{key}" data-samples="{points}" d="{pathdata}" fill="none" stroke="{COLORS[key]}" stroke-width="{1.6 if key=="new" else 1.1}" stroke-linejoin="round"{dash}/>')
            for px,py in dots:body.append(f'<circle cx="{px:.3f}" cy="{py:.3f}" r="1.6" fill="{COLORS[key]}"/>')
        body.append('</g>')
        if stats['new']['valid']<384:body.append(f'<text x="{W-right-10}" y="{top+22}" text-anchor="end" font-size="14" fill="#9c6c24">覆盖不足80%：仅显示已有有效样本</text>')
        body.append(f'<text x="23" y="{top+ph/2}" font-size="14" transform="rotate(-90 23 {top+ph/2})" text-anchor="middle">X（pixel，原数值基准）</text>')
    body.extend([f'<text x="{W/2}" y="{H-14}" text-anchor="middle" font-size="13" fill="#5d6e7b">采集时间（北京时间）；无效值留空，超过3分钟采集缺口断线，无额外平滑或抽点</text>','</g></svg>'])
    content='\n'.join(body);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(content,encoding='utf8')
    return {'svg_sha256':digest(path),'draw':draw,'y_axis':[lo,hi]}

def figure_card(rec,current,detail_link=True):
    svg=OUT/rec['svg'];href=link_from(current,svg)
    mp=OUT/rec['line']/rec['device']/'markers'/f'{rec["marker_file"]}.html'
    status='源数据缺失' if rec['frames']==0 else '覆盖不足，仅显示已有数据' if not rec['eligible'] else '有效覆盖充足'
    extra=f'<a href="{esc(link_from(current,mp))}">该测点10夜对比</a>' if detail_link else ''
    return f'<figure id="{esc(rec["marker_file"]+"_"+rec["night"])}"><figcaption><h3>{esc(rec["marker"])} <span class="tag">{esc(rec["role"])}</span> <span class="tag">{rec["night"]}夜</span></h3><p class="small">{status}；原幅度参考 ≤{rec["limit"]:g} pixel'+('（XJ绝对幅度仅作描述）' if 'XJ' in rec['marker'] else '')+f'。 {extra} · <a href="{esc(href)}">打开矢量图</a></p></figcaption><a href="{esc(href)}"><img loading="lazy" src="{esc(href)}" width="1440" height="450" alt="{esc(lc(rec["line"])+" "+rec["device"]+" "+rec["marker"]+" "+rec["night"]+" raw X、calX、新算法三曲线")}"></a></figure>'

def main():
    started=time.perf_counter();ap=argparse.ArgumentParser();ap.add_argument('--line',choices=['left','right','both'],default='both');args=ap.parse_args()
    selected=['left','right'] if args.line=='both' else [args.line]
    OUT.mkdir(parents=True,exist_ok=True);REPORT.mkdir(parents=True,exist_ok=True)
    metrics_path=BASE/'round4_window_causality/reports/window_xj_point_nights.csv'
    frozen=pd.read_csv(metrics_path,dtype={'device':str});frozen=frozen[frozen.profile==PROFILE].set_index(['line','device','marker','night'])
    rows=[];sources=[];devices=[];pagecount=0
    for source in sorted((BASE/'data').glob('*/*/input.npz')):
        line,dev=source.parent.parent.name,source.parent.name
        if line not in selected:continue
        with np.load(source) as d:ts=d['timestamp'];names=[str(n) for n in d['names']];x=d['x'];cal=d['online_x'];roi=d['roi']
        input_bin=source.with_name('input.bin')
        # The output stores positional markers; verify the positional input roster itself.
        with input_bin.open('rb') as f:
            m,=struct.unpack('<I',f.read(4));binary_names=[]
            for _ in range(m):length,=struct.unpack('<I',f.read(4));binary_names.append(f.read(length).decode('utf8'))
            input_frames,=struct.unpack('<I',f.read(4))
        assert names==binary_names and input_frames==len(ts)
        output=BASE/'round2_waveform_10n/results'/PROFILE/line/dev/'output.bin';n=native(output)
        assert n['xy'].shape[2]==len(names) and np.array_equal(ts,n['timestamp']) and np.array_equal(np.isfinite(n['xy'][:,0,:]),np.isfinite(x))
        assert np.all(np.diff(ts)>0)
        sources.append({'line':line,'device':dev,'input_npz':str(source),'input_npz_sha256':digest(source),'input_bin':str(input_bin),'input_bin_sha256':digest(input_bin),'output_bin':str(output),'output_sha256':digest(output),'marker_names':names,'marker_count':len(names),'frames':len(ts),'positional_marker_order_verified':True,'timestamp_equal':True,'finite_mask_equal':True})
        ordered=sorted(names,key=rank);marker_files={name:filename(name) for name in names};assert len(set(marker_files.values()))==len(names)
        local_rows=[]
        for night in NIGHTS:
            start=ms(night+' 23:00');sel=(ts>=start)&(ts<start+480*60000);t=ts[sel]
            for name in ordered:
                j=names.index(name);values=np.column_stack([x[sel,j],cal[sel,j],n['xy'][sel,0,j]])
                stats={key:metrics(values[:,i]) for i,key in enumerate(['raw','calx','new'])};r=frozen.loc[(line,dev,name,night)]
                assert stats['new']['valid']==int(r.valid)
                for st,reference in [(stats['new'],r.p2p),(stats['raw'],r.raw_p2p)]:
                    assert (st['range'] is None and not np.isfinite(reference)) or abs(st['range']-reference)<1e-8
                assert bool(r.eligible)==(stats['new']['valid']>=384)
                rel=Path(line)/dev/'svg'/f'{marker_files[name]}_{night}.svg'
                record={'line':line,'device':dev,'marker':name,'marker_file':marker_files[name],'role':role(name),'night':night,'window_start':local(start).isoformat(),'window_end_exclusive':local(start+480*60000).isoformat(),'frames':len(t),'expected':480,'eligible':bool(r.eligible),'limit':float(r.limit),'amplitude_reference_only':True,'xj_not_business_failure':bool('XJ' in name.upper()),'raw':stats['raw'],'calx':stats['calx'],'new':stats['new'],'raw_roi_invalid_finite':int(np.count_nonzero((roi[sel,j]!=1)&np.isfinite(values[:,0]))),'svg':rel.as_posix(),'gap_count_over3min':int(np.count_nonzero(np.diff(t)>180000)),'range_count_match_r4':True}
                record.update(render_svg(OUT/rel,line,dev,name,night,t,values,stats));local_rows.append(record)
        devices.append({'line':line,'device':dev,'markers':len(names),'J':sum(role(a)=='J基准点' for a in names),'XJ':sum(role(a)=='XJ普通测点' for a in names),'ordinary':sum(role(a)=='普通测点' for a in names),'nights':10,'nominal_point_nights':len(local_rows),'eligible_point_nights':sum(r['eligible'] for r in local_rows),'missing_point_nights':sum(r['frames']==0 for r in local_rows),'new_under1':sum(r['eligible'] and r['new']['range']<=1+1e-9 for r in local_rows),'index':(Path(line)/dev/'index.html').as_posix()})
        # Every night page contains every marker, in the same role-aware order.
        for night in NIGHTS:
            nr=[r for r in local_rows if r['night']==night];p=OUT/line/dev/'nights'/f'{night}.html'
            nav=f'<nav><a href="../index.html">设备目录</a><a href="../../index.html">{lc(line)}六设备</a>{framework(p)}</nav>'
            anchors=''.join(f'<a href="#{esc(r["marker_file"]+"_"+night)}">{esc(r["marker"])}</a>' for r in nr)
            body=nav+f'<header><h1>{lc(line)} {dev} · {night}夜</h1><p>23:00—次日07:00；本设备全部 {len(names)} 个测点依次展开。J／XJ置前，普通点完整保留。</p>{legends()}<p class="small">新算法：Astra＋07:00渐退（current_fade07），与本轮23—07路由内的数值相同。原幅度参考不等于业务失败；XJ还需结合设备整体趋势。</p><div class="marker-links">{anchors}</div></header>'
            body+=''.join(figure_card(r,p) for r in nr);write_html(p,f'{lc(line)} {dev} {night}全部测点',body);pagecount+=1
        # Every marker page contains all ten calendar nights, including no-data placeholders.
        for name in ordered:
            mr=[r for r in local_rows if r['marker']==name];p=OUT/line/dev/'markers'/f'{marker_files[name]}.html'
            nav=f'<nav><a href="../index.html">设备目录</a><a href="../../index.html">{lc(line)}六设备</a>{framework(p)}</nav>'
            anchors=''.join(f'<a href="#{esc(r["marker_file"]+"_"+r["night"])}">{r["night"][5:]}</a>' for r in mr)
            body=nav+f'<header><h1>{lc(line)} {dev} / {esc(name)} · 10夜对比</h1><p>{esc(role(name))}；每夜23:00—次日07:00。全部10个日历夜依次展开，缺测保留为空。</p>{legends()}<p class="small">三条曲线共用每幅图的原数值纵轴；不同夜按实际范围刻度，未按夜重新置零。比较夜间绝对值时请同时看纵轴刻度。</p><div class="marker-links">{anchors}</div></header>'
            body+=''.join(figure_card(r,p,False) for r in mr);write_html(p,f'{dev} {name}10夜波形',body);pagecount+=1
        p=OUT/line/dev/'index.html';nightrows=[]
        for night in NIGHTS:
            nr=[r for r in local_rows if r['night']==night];valid=sum(r['eligible'] for r in nr);missing=all(r['frames']==0 for r in nr)
            nightrows.append(f'<tr><td><a href="nights/{night}.html">{night} 23:00—次日07:00</a></td><td>{len(nr)}</td><td>{valid}</td><td>{"源数据缺失，留空" if missing else "全部点已列出"}</td></tr>')
        markerlinks=''.join(f'<a href="markers/{marker_files[name]}.html">{esc(name)}<span class="tag">{esc(role(name))}</span></a>' for name in ordered)
        body=f'<nav><a href="../index.html">{lc(line)}六设备</a><a href="../../index.html">左右线总览</a>{framework(p)}</nav><header><h1>{lc(line)} {dev}</h1><p>全部 {len(names)} 测点 × 10夜；可按夜查看全设备，也可按测点查看连续10夜。</p>{legends()}<p class="small">只展示原记录与已有算法输出；无额外平滑、插值、时间平移或抽点。下方“覆盖充分”指ROI有效帧不少于384/480，不是波形验收通过。</p></header><section class="panel"><h2>按夜查看：每页全部测点</h2><table><thead><tr><th>夜间</th><th>全部测点</th><th>覆盖充分点数</th><th>说明</th></tr></thead><tbody>{"".join(nightrows)}</tbody></table></section><section class="panel"><h2>按测点查看：每页完整10夜</h2><div class="marker-links">{markerlinks}</div></section>'
        write_html(p,f'{lc(line)} {dev}全部逐点波形',body);pagecount+=1
        rows.extend(local_rows);print(json.dumps({'line':line,'device':dev,'markers':len(names),'nominal_charts':len(local_rows),'total_charts':len(rows),'elapsed_s':round(time.perf_counter()-started,1)}),flush=True)
    line_data=[]
    for line in selected:
        ds=[d for d in devices if d['line']==line];assert len(ds)==6
        p=OUT/line/'index.html';cards=[]
        for d in ds:
            cards.append(f'<div class="card"><h3><a href="{d["device"]}/index.html">{d["device"]}</a></h3><p>{d["markers"]}个测点 · 10夜 · {d["nominal_point_nights"]}幅图</p><p class="small">J基准 {d["J"]} · XJ普通 {d["XJ"]} · 其他普通 {d["ordinary"]}</p><p><a href="{d["device"]}/index.html">进入全部逐点目录 →</a></p></div>')
        count=sum(d['markers'] for d in ds);missing=sum(d['missing_point_nights'] for d in ds)
        data={'line':line,'devices':6,'markers':count,'nominal_point_nights':count*10,'missing_point_nights':missing,'eligible_point_nights':sum(d['eligible_point_nights'] for d in ds)};line_data.append(data)
        body=f'<nav><a href="../index.html">左右线总览</a>{framework(p)}</nav><header><h1>{lc(line)} · 六设备10夜全量波形</h1><p>2026-11-06—11-15夜号；每天23:00—次日07:00。全部 {count} 个设备测点、{count*10} 个名义点夜。</p>{legends()}<p class="small">新算法为Astra＋07:00渐退；原算法calX直接取数据库。原幅度参考仅供观察，不作为这份图册的业务失败标签。</p></header>'
        if missing:body+='<div class="notice">左线11/06源数据缺失，6台设备该夜均保留缺测占位，不用其他日期替代。其他夜的低覆盖点只显示已有有效数据。</div>'
        body+='<div class="cards">'+''.join(cards)+'</div>';write_html(p,f'{lc(line)}六设备10夜全部逐点图册',body);pagecount+=1
    p=OUT/'index.html';cards=[]
    for d in line_data:cards.append(f'<div class="card"><h2><a href="{d["line"]}/index.html">{lc(d["line"])}六设备</a></h2><p>{d["markers"]} 个设备测点 · {d["nominal_point_nights"]} 个名义点夜</p><p>按设备→夜间看全部点，或按设备→测点看全部10夜。</p><a href="{d["line"]}/index.html">打开{lc(d["line"])}完整图册 →</a></div>')
    total_markers=sum(d['markers'] for d in devices)
    body=f'<header><h1>X向全量逐点波形图册</h1><p>2026年11月6日—15日，23:00—次日07:00。三条曲线保留原始时间与原数值基准。</p>{legends()}<div class="stats"><span><b>{len(devices)}</b> 台设备</span><span><b>{total_markers}</b> 个设备测点</span><span><b>{len(rows)}</b> 个名义点夜</span></div><nav>{framework(p)}</nav></header><div class="notice">“六设备”分别为左线6台和右线6台，两个入口独立。每页全部点展开，不按效果筛选、不省略普通点。图中标注的是原幅度参考，不是业务失败；XJ绝对波动还要结合设备整体趋势判断。</div><div class="cards">'+''.join(cards)+'</div><section class="panel"><h2>阅读口径</h2><p>灰色是数据库raw X，蓝色虚线是数据库calX，红色是新算法Astra＋07:00渐退。时间戳与测点顺序已核对，三条曲线共用每幅图纵轴；不同图会根据实际数值范围调整刻度，均不重新置零。</p><p>无效ROI与非有限值留空；超过3分钟采集缺口断线；不插值、额外平滑或抽点。单个孤立有效样本用小点显示。左线11/06缺测保留占位。当前只提供图册和内部JSON核验清单，没有导出给同事的CSV。</p></section>'
    write_html(p,'X向全量逐点波形图册',body);pagecount+=1
    assert len(rows)==total_markers*10
    if args.line=='both':assert total_markers==524 and len(rows)==5240
    assert all(r['raw_roi_invalid_finite']==0 for r in rows)
    for r in rows:
        assert r['draw']['raw']['points']==r['raw']['valid'] and r['draw']['calx']['points']==r['calx']['valid'] and r['draw']['new']['points']==r['new']['valid']
    manifest={'scope':'Full roster; no CSV export; 23:00 inclusive to next07:00 exclusive, local UTC+08','line_option':args.line,'profile':PROFILE,'new_algorithm':'Astra + 07:00 fade; identical values inside 23-07 route','metric_source':str(metrics_path),'metric_source_sha256':digest(metrics_path),'script_sha256':digest(Path(__file__)),'dates':NIGHTS,'summary':{'devices':len(devices),'markers':total_markers,'nominal_point_nights':len(rows),'eligible_point_nights':sum(r['eligible'] for r in rows),'missing_point_nights':sum(r['frames']==0 for r in rows),'html_pages':pagecount,'svg_charts':len(rows),'total_drawn_samples':{k:sum(r[k]['valid'] for r in rows) for k in ['raw','calx','new']}},'plot_rules':{'no_smoothing':True,'no_interpolation':True,'no_decimation':True,'no_time_shift':True,'no_rezero':True,'gap_break_ms':180000,'isolated_samples_visible':True,'j_xj_first':True,'all_other_markers_preserved':True,'amplitude_reference_not_business_failure':True},'framework_link_pending':str(ROOT/'算法框架.html'),'sources':sources,'lines':line_data,'devices':devices,'charts':rows}
    target=REPORT/f'all_point_atlas_manifest_{args.line}.json';target.write_text(json.dumps(manifest,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
    # Local URLs are checked, except the root-owned framework file that may be added next.
    links=0;pending=set()
    for file in OUT.rglob('*.html'):
        if args.line!='both' and file!=OUT/'index.html' and not file.is_relative_to(OUT/args.line):continue
        for ref in re.findall(r'(?:src|href)="([^"]+)"',file.read_text(encoding='utf8')):
            ref=html.unescape(ref).split('#')[0]
            if not ref:continue
            real=(file.parent/ref).resolve();links+=1
            if real== (ROOT/'算法框架.html').resolve() and not real.exists():pending.add(str(real));continue
            assert real.is_file(),(file,ref)
    check={'manifest':str(target),'charts':len(rows),'html_pages':pagecount,'links_checked':links,'pending_root_framework':sorted(pending),'elapsed_s':round(time.perf_counter()-started,2),'all_ranges_counts_match_r4':True,'all_actual_samples_in_svg':True,'no_csv_created':not any(OUT.rglob('*.csv'))}
    (REPORT/f'all_point_atlas_build_{args.line}.json').write_text(json.dumps(check,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(check,ensure_ascii=True),flush=True)

if __name__=='__main__':main()
