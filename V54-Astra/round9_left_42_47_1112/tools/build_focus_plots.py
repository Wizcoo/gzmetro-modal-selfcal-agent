"""Four focused diagnostic figures, with exact samples and a shared raw baseline."""
from pathlib import Path
from datetime import datetime,timezone,timedelta
import numpy as np
import importlib.util,sys,json,html,hashlib,re
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1];BASE=ROOT.parent
spec=importlib.util.spec_from_file_location('atlas_util',BASE/'round5_all_point_atlas/tools/build_all_point_atlas.py')
util=importlib.util.module_from_spec(spec);spec.loader.exec_module(util)
OUT=ROOT/'plots';OUT.mkdir(exist_ok=True)
TZ=timezone(timedelta(hours=8));T0=util.ms('2026-11-12 22:00');T1=util.ms('2026-11-13 07:00')
esc=lambda x:html.escape(str(x),quote=True)
COL={'raw':'#7c8794','old':'#2873b9','new':'#c9473c','modal':'#80569f','s2':'#d28a22','target':'#80569f','j':'#267f64'}
stages={device:np.load(ROOT/'reports'/f'algorithm_cause_audit_stage_{device}.npz') for device in ['780638310097','780638327479','780638349768']}
def datum(d,name):
    j=d['names'].tolist().index(name);t=d['timestamp'];return j,float(np.nanmedian(d['raw'][t<T0+3600000,j]))
def series(d,name,key):
    j,b=datum(d,name);v=d[key][:,j].copy()
    # Display contract: before23:00, published Astra is raw; use ONE raw baseline for all curves.
    if key=='new':v[d['timestamp']<T0+3600000]=d['raw'][d['timestamp']<T0+3600000,j]
    return v-b
def triple(d,name):
    return [('raw X',COL['raw'],series(d,name,'raw'),False),('数据库 calX',COL['old'],series(d,name,'calX'),True),('Astra X',COL['new'],series(d,name,'new'),False)]
records=[]
def figure(name,title,panels,footer):
    W=1440;H=120+340*len(panels);left=110;right=35;width=W-left-right
    parts=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">','<rect width="100%" height="100%" fill="white"/>',
      '<g font-family="Microsoft YaHei,Noto Sans CJK SC,sans-serif" fill="#263b4b">',f'<text x="24" y="32" font-size="23" font-weight="bold">{esc(title)}</text>',
      '<text x="24" y="60" font-size="15">11月12日22:00—13日07:00；灰区为22–23基准窗；每点三曲线统一减去本点raw基准中位数，单位pixel</text>']
    rec={'file':name+'.svg','title':title,'panels':[]}
    for pi,(label,t,items) in enumerate(panels):
        top=120+pi*340;ph=225;bottom=top+ph
        lo,hi,ticks,dec=util.nice_axis(np.column_stack([v for _,_,v,_ in items]))
        xx=lambda v:left+(int(v)-T0)/(T1-T0)*width
        yy=lambda v:top+(hi-float(v))/(hi-lo)*ph
        parts+=[f'<text x="24" y="{top-29}" font-size="17" font-weight="bold">{esc(label)}</text>',
             f'<rect x="{left}" y="{top}" width="{width/9}" height="{ph}" fill="#f0f2f4"/>']
        for k,(label0,color,v,dash) in enumerate(items):
            xpos=760+k*(620/max(1,len(items)))
            parts.append(f'<line x1="{xpos}" x2="{xpos+24}" y1="{top-25}" y2="{top-25}" stroke="{color}" stroke-width="2"'+(' stroke-dasharray="7 4"' if dash else '')+f'/><text x="{xpos+30}" y="{top-20}" font-size="13">{esc(label0)}</text>')
        for tick in ticks:
            y=yy(tick);parts.append(f'<line x1="{left}" x2="{W-right}" y1="{y}" y2="{y}" stroke="#e3e9ed"/><text x="{left-12}" y="{y+5}" text-anchor="end" font-size="13">{tick:.{dec}f}</text>')
        for h in range(10):
            ts=T0+h*3600000;x=xx(ts);local=datetime.fromtimestamp(ts/1000,TZ)
            parts.append(f'<line x1="{x}" x2="{x}" y1="{top}" y2="{bottom}" stroke="#e3e9ed"/><text x="{x}" y="{bottom+24}" text-anchor="middle" font-size="13">{local:%m-%d}</text><text x="{x}" y="{bottom+43}" text-anchor="middle" font-size="13">{local:%H:%M}</text>')
        parts.append(f'<text x="27" y="{top+ph/2}" font-size="14" transform="rotate(-90 27 {top+ph/2})" text-anchor="middle">ΔX（pixel，共用raw基准）</text>')
        clip=f'{name}_{pi}_clip';parts.append(f'<defs><clipPath id="{clip}"><rect x="{left}" y="{top}" width="{width}" height="{ph}"/></clipPath></defs><g clip-path="url(#{clip})">')
        pr={'title':label,'curves':[]}
        for label0,color,v,dash in items:
            path,dots,n,segs=util.curve_path(t,v,xx,yy)
            assert n==int(np.isfinite(v).sum())
            parts.append(f'<path data-label="{esc(label0)}" data-samples="{n}" d="{path}" stroke="{color}" fill="none" stroke-width="1.7"'+(' stroke-dasharray="7 4"' if dash else '')+'/>')
            for px,py in dots:parts.append(f'<circle cx="{px}" cy="{py}" r="1.5" fill="{color}"/>')
            pr['curves'].append({'label':label0,'samples':n,'segments':segs})
        parts.append('</g>');rec['panels'].append(pr)
    parts.append(f'<text x="24" y="{H-19}" font-size="14" fill="#526a7b">{esc(footer)}</text></g></svg>')
    file=OUT/(name+'.svg');file.write_text('\n'.join(parts),encoding='utf8');rec['sha256']=hashlib.sha256(file.read_bytes()).hexdigest();records.append(rec)

d=stages['780638327479'];t=d['timestamp']
figure('01_ZXJ6','最关键残留：327479 / ZXJ6 在两版算法中均出现反向趋势',[
  ('A. 原始扰动与两版修后值',t,triple(d,'ZXJ6')),
  ('B. 只放大查看两版修后曲线（与上图完全相同样本）',t,triple(d,'ZXJ6')[1:])],
  '23–07峰谷差：raw 13.702 / calX 6.811 / Astra 6.844；未平滑、未移动峰谷时间；XJ身份不等于静止参考。')
j,b=datum(d,'ZXJ6')
figure('02_stages','ZXJ6 逐阶段：反向趋势首先出现在模态扣除，随后增强只小幅改变',[
  ('A. 内部模态输出、S2后、最终输出',t,[(label,COL[key],d[key][:,j]-b,False) for label,key in [('模态核心','modal'),('S2后','s2'),('内部最终X','new')]]),
  ('B. 模态扣除量与送入核心的观测变化',t,[('W3观测变化',COL['raw'],d['w3'][:,j]-b,False),('模态扣除量',COL['modal'],d['w3'][:,j]-d['modal'][:,j],False)])],
  '阶段来自冻结原生结果和逐级等价重建；03–06相对raw基准：raw +6.148 → 模态 −5.119 → 最终 −5.206 pixel。')
e=stages['780638349768']
figure('03_ZD4703','同名测点ZD4703在两台设备的表现：按设备分开看',[
  ('A. 327479 / ZD4703：修后残留约1.50 pixel',t,triple(d,'ZD4703')),
  ('B. 349768 / ZD4703：修后范围约0.19 pixel',e['timestamp'],triple(e,'ZD4703'))],
  '两个视角分别减去各自raw基准；两图纵轴独立。相机投影不同，像素差不能直接解释成物理位移差。')
names=d['names'].tolist();target=[n for n in names if re.fullmatch(r'ZD4[2-7]\d{2}',n)];refs=[n for n in names if n.startswith('ZJ')]
group=lambda group:np.nanmedian(np.column_stack([series(d,n,'new') for n in group]),axis=1)
g_target=group(target);g_j=group(refs);xj=series(d,'ZXJ6','new')
figure('04_relative','相对关系仍未稳定：目标组、J基准组和ZXJ6的修后变化不同',[
  ('A. Astra修后：目标18点、J四点、ZXJ6',t,[('目标组中位',COL['target'],g_target,False),('J组中位',COL['j'],g_j,False),('ZXJ6',COL['new'],xj,False)]),
  ('B. 仅放大目标组与J组（与上图相同数据）',t,[('目标组中位',COL['target'],g_target,False),('J组中位',COL['j'],g_j,False)])],
  '组曲线为各点减自身raw基准后逐帧取中位数；无时间平滑。仅用于诊断，不作为额外修正或平差结果。')
(ROOT/'reports/focus_plot_manifest.json').write_text(json.dumps({'unit':'pixel','time_samples':'all actual frames; NaN and >3min gaps break lines','raw_reference':'per-marker raw22–23 median shared across raw/calX/new','figures':records},ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({'figures':len(records),'files':[r['file'] for r in records]},ensure_ascii=True))
