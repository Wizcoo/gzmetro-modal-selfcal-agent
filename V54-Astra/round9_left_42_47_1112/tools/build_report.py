from pathlib import Path
from html.parser import HTMLParser
import re,json,html,hashlib,zipfile
from collections import Counter

ROOT=Path(__file__).resolve().parents[1];BASE=ROOT.parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
esc=lambda x:html.escape(str(x),quote=True)
def inline(s):
    s=esc(s);s=re.sub(r'\*\*(.+?)\*\*',r'<strong>\1</strong>',s);return re.sub(r'`([^`]+)`',r'<code>\1</code>',s)
def simple_markdown(text):
    out=[];table=False;listing=False
    for line in text.splitlines():
        if not line.strip():
            if table:out.append('</table></div>');table=False
            if listing:out.append('</ul>');listing=False
            continue
        if line.startswith('|'):
            if re.fullmatch(r'[|:\- ]+',line):continue
            if not table:out.append('<div class="scroll"><table>');table=True
            out.append('<tr>'+''.join('<td>'+inline(c.strip())+'</td>' for c in line.strip('|').split('|'))+'</tr>');continue
        if line.startswith('- '):
            if not listing:out.append('<ul>');listing=True
            out.append('<li>'+inline(line[2:])+'</li>');continue
        if line.startswith('#'):
            level=min(3,len(line)-len(line.lstrip('#'))+1)
            out.append(f'<h{level}>'+inline(line.lstrip('#').strip())+f'</h{level}>')
        else:out.append('<p>'+inline(line)+'</p>')
    if table:out.append('</table></div>')
    if listing:out.append('</ul>')
    return ''.join(out)

manifest=json.loads((BASE/'round5_all_point_atlas/reports/all_point_atlas_manifest_both.json').read_text(encoding='utf8'))
rows=[r for r in manifest['charts'] if r['line']=='left' and r['night']=='2026-11-12' and re.fullmatch(r'ZD4[2-7]\d{2}',r['marker'])]
assert len(rows)==37
CSS='''*{box-sizing:border-box}body{max-width:1500px;margin:22px auto;padding:0 20px;font:16px/1.8 "Microsoft YaHei",sans-serif;color:#263b4b;background:#f3f6f8}header,section,figure,details{background:white;padding:20px;margin:18px 0;border:1px solid #d6e0e7;border-radius:8px}h1{font-size:28px;line-height:1.5}h2{font-size:23px}h3{font-size:19px}a{color:#136b8e}svg{display:block;width:100%;height:auto}.stats{display:flex;gap:14px;flex-wrap:wrap}.stats span{padding:10px 15px;background:#eef3f6;border-radius:5px}summary{font-size:19px;cursor:pointer;font-weight:bold}table{width:100%;border-collapse:collapse;font-size:14px}td,th{border-bottom:1px solid #dbe4eb;padding:9px;text-align:left}th,tr:first-child{background:#f1f5f7}.scroll{overflow:auto}.lead{border-left:4px solid #be5143;padding:8px 18px;background:#fff5f2}.small{font-size:14px;color:#587083}nav{display:flex;gap:18px;flex-wrap:wrap}code{background:#edf2f5;padding:1px 4px}figure h3{margin-top:0}'''
body='<header><h1>左线42–47断面 · 11月12夜残留扰动分析</h1><div class="lead"><strong>重点是327479的模态补偿过量，尤其ZXJ6出现大幅反向趋势。</strong><p>两版算法均消除了大量原始波动，但普通点、J基准点和XJ之间仍有显著相对变化；不能凭普通点低于2 pixel就认定设备扰动已经修复。</p></div><p>主窗：2026-11-12 23:00至11-13 07:00（结束不含）。使用此前已交付十夜CSV／图册对应的连续因果回放；没有把13–15初始状态倒用于11/12。</p><div class="stats"><span>3台设备</span><span>37组断面观测</span><span>ZXJ6修后范围 6.844 pixel</span><span>首页4张重点图，附录按设备折叠</span></div><p class="small">全站仪“属于设备扰动”的结论由用户提供，本轮未取得全站仪原始数据。像素量不直接换算成毫米解算误差。</p><nav><a href="#causes">原因和下一步</a><a href="#points">37个目标观测附录</a><a href="分析结论.md">完整中文说明</a></nav></header>'
captions=[
 'ZXJ6的旧calX与Astra都有大反向残留；基准60/60、主窗480/480有效，核心整夜有模态并在执行修正。',
 '反向变化在模态扣除阶段已经形成。中位偏移raw +6.148 → 模态 −5.119 → 最终 −5.206 pixel，S2/S1并非主贡献。',
 '327479视角的ZD4703有残留，349768视角同名点明显更平稳。不同相机投影不可直接当作同单位物理位移相减。',
 '目标组和ZXJ6即使形状相关，幅度与J组的关系仍不一致。这张图是空间中位数诊断，没有对时间方向平滑。',
]
for path,caption in zip(sorted((ROOT/'plots').glob('0[1-4]_*.svg')),captions):
    body+='<figure><figcaption><p>'+caption+'</p></figcaption>'+path.read_text(encoding='utf8')+'</figure>'
body+='<details id="causes" open><summary>原因、证据与下一步</summary>'+simple_markdown((ROOT/'分析结论.md').read_text(encoding='utf8'))+'</details>'
body+='<section id="points"><h2>37个目标观测：原始数据、数据库calX、Astra</h2><p>以下范围统一使用23–07全部有效样本，单位pixel。附录保留原始坐标；未按各曲线分别归零。按设备展开可看到全部点，避免只挑异常曲线。</p><div class="scroll"><table><tr><th>设备</th><th>测点</th><th>raw范围</th><th>calX范围</th><th>Astra范围</th></tr>'
for r in sorted(rows,key=lambda r:-r['new']['range']):
    body+='<tr>'+''.join('<td>'+v+'</td>' for v in [r['device'],r['marker']]+[f'{r[k]["range"]:.3f}' for k in ['raw','calx','new']])+'</tr>'
body+='</table></div></section>'
for device in sorted(set(r['device'] for r in rows)):
    group=sorted([r for r in rows if r['device']==device],key=lambda r:r['marker'])
    body+=f'<details><summary>{device} · {len(group)}个目标观测</summary>'
    for r in group:
        source=BASE/'round5_all_point_atlas/plots'/r['svg'];assert sha(source)==r['svg_sha256']
        svg=source.read_text(encoding='utf8');ident=device+'_'+r['marker']
        for key in ['title','desc','plotclip']:
            svg=svg.replace(f'id="{key}"',f'id="{ident}_{key}"').replace(f'url(#{key})',f'url(#{ident}_{key})')
        svg=svg.replace('aria-labelledby="title desc"',f'aria-labelledby="{ident}_title {ident}_desc"')
        body+='<figure>'+svg+'</figure>'
    body+='</details>'
body+='<section><h2>独立复核材料</h2><nav><a href="reports/source_data_audit.md">数据库来源与点位审查</a><a href="reports/algorithm_cause_audit.md">逐阶段与历史模态根因</a><a href="reports/reference_trend_audit.md">J／XJ与相对趋势审查</a></nav><p class="small">未修改算法、状态包、数据库或此前CSV。本页内嵌全部图，可离线阅读；Markdown审查材料随ZIP提供。</p></section>'
page='<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>左线42–47断面11/12夜残留扰动</title><style>'+CSS+'</style></head><body>'+body+'</body></html>'
file=ROOT/'index.html';file.write_text(page,encoding='utf8')
class Checker(HTMLParser):
    def __init__(self):super().__init__();self.ids=[];self.links=[];self.svg=0;self.external=[]
    def handle_starttag(self,tag,attrs):
        d=dict(attrs)
        if 'id' in d:self.ids.append(d['id'])
        if tag=='a':self.links.append(d.get('href',''))
        if tag=='svg':self.svg+=1
        if 'src' in d:self.external.append(d['src'])
c=Checker();c.feed(page);assert len(c.ids)==len(set(c.ids));assert c.svg==41;assert not c.external
for href in c.links:
    if href.startswith('#'):assert href[1:] in c.ids
    else:assert (ROOT/href).is_file(),href
qa={'passed':True,'main_figures':4,'appendix_original_svg':37,'inline_svg_total':c.svg,'unique_ids':True,'links_valid':True,'self_contained_html':True,'html_sha256':sha(file),'main_svg_visual_check':'offline PNG render reviewed; no browser automation'}
(ROOT/'reports/html_validation.json').write_text(json.dumps(qa,ensure_ascii=False,indent=2),encoding='utf8')
archive=ROOT/'V54-Astra_左线42-47断面_1112夜残留分析.zip'
files=[ROOT/'index.html',ROOT/'分析结论.md']+sorted((ROOT/'plots').glob('*'))+sorted((ROOT/'reports').glob('*'))+sorted((ROOT/'tools').glob('*'))
files=[p for p in files if p.is_file() and p.name!='package_verification.json']
with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
    for p in files:z.write(p,p.relative_to(ROOT).as_posix())
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    for p in files:assert z.read(p.relative_to(ROOT).as_posix())==p.read_bytes()
packed={'file':archive.name,'sha256':sha(archive),'bytes':archive.stat().st_size,'entries':len(files),'zip_crc_and_bytes':True}
(ROOT/'reports/package_verification.json').write_text(json.dumps(packed,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({'html_validation':qa,'package':packed},ensure_ascii=True))
