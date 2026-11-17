"""Create the local readable framework page and a verified offline atlas package."""
from pathlib import Path
import re, html, json, zipfile, hashlib, sys

ROOT=Path(__file__).resolve().parents[1]


def inline(s):
    s=html.escape(s)
    s=re.sub(r'`([^`]+)`',r'<code>\1</code>',s)
    s=re.sub(r'\*\*([^*]+)\*\*',r'<strong>\1</strong>',s)
    def link(match):
        target=match.group(2)
        if re.match(r'^[A-Za-z]:/',target):
            # Markdown app links support :line; browsers require the real file path.
            target='file:///'+re.sub(r':\d+$','',target)
        return f'<a href="{target}">{match.group(1)}</a>'
    return re.sub(r'\[([^\]]+)\]\(([^)]+)\)',link,s)


def markdown_body(source):
    out=[];lines=source.splitlines();i=0
    while i<len(lines):
        line=lines[i]
        if line.startswith('```'):
            lang=line[3:].strip();block=[];i+=1
            while i<len(lines) and not lines[i].startswith('```'):
                block.append(lines[i]);i+=1
            body='<pre><code>'+html.escape('\n'.join(block))+'</code></pre>'
            out.append('<details><summary>框架图 Mermaid 源码</summary>'+body+'</details>' if lang=='mermaid' else body)
        elif line.startswith('|'):
            rows=[]
            while i<len(lines) and lines[i].startswith('|'):
                cells=lines[i].strip('|').split('|')
                if not all(re.fullmatch(r'[\s:\-]+',c) for c in cells):rows.append(cells)
                i+=1
            out.append('<div class="table-wrap"><table>'+''.join('<tr>'+''.join(f'<{"th" if r==0 else "td"}>{inline(c.strip())}</{"th" if r==0 else "td"}>' for c in cells)+'</tr>' for r,cells in enumerate(rows))+'</table></div>');continue
        elif re.match(r'^#{1,6} ',line):
            rank=len(line)-len(line.lstrip('#'));out.append(f'<h{rank}>{inline(line[rank+1:])}</h{rank}>')
        elif re.match(r'^\s*[-*] ',line):out.append('<p class="item">• '+inline(line.lstrip()[2:])+'</p>')
        elif line.strip():out.append('<p>'+inline(line)+'</p>')
        i+=1
    return '\n'.join(out)


STYLE='''body{margin:28px auto;padding:0 24px;max-width:1180px;background:#f4f7fa;color:#233747;font:16px/1.8 "Microsoft YaHei",sans-serif}main,header{background:white;border:1px solid #dce4ea;border-radius:9px;padding:26px;margin:18px 0}a{color:#17648a}h1{font-size:28px}h2{font-size:23px;margin-top:32px}h3{font-size:19px}code{background:#eef3f6;padding:2px 5px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#eef3f6;padding:18px;font-size:13px}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:9px 12px;border-bottom:1px solid #dce4ea;text-align:left}th{background:#edf3f7}.table-wrap{overflow:auto}.flow{display:flex;gap:8px;align-items:stretch;flex-wrap:wrap}.node{flex:1 1 125px;border:1px solid #bdd0dc;border-radius:5px;padding:13px;background:#f0f6f9}.node b{display:block;color:#155a7f}.arrow{align-self:center;color:#628297}.hint{border-left:4px solid #bf8731;padding:12px 18px;background:#fff5df}.item{margin:6px 0}.sub{color:#546b79;font-size:14px}@media print{body{background:white}header,main{border:0}details{display:none}}'''


def main():
    source=(ROOT/'算法框架.md').read_text(encoding='utf8')
    flow='<section><h2>当前帧的处理顺序</h2><div class="flow">'
    nodes=[('输入','raw X / Y；无效ROI留空'),('W3','X向因果3帧滤波'),('模态补偿','用冻结历史模型估计当帧共同分量'),('S2','X向共同慢漂抑制'),('S1','X向因果阻尼'),('发布','23—07修后X；其余raw X')]
    flow+=''.join(('<span class="arrow">→</span>' if i else '')+f'<div class="node"><b>{title}</b>{text}</div>' for i,(title,text) in enumerate(nodes))+'</div>'
    flow+='<p class="sub">历史支路：22—23参考基线 ＋ 22—02夜间统计 → 最近最多3个合格历史夜 → 通常23点冻结当夜模型。新夜统计收录后，通常用于下一夜更新。</p><p class="hint">1—2 pixel是看图和评价的幅度参考，当前算法没有在末端把整夜波形强行缩放到这个范围，也没有自动针对失败单点专项重训。</p></section>'
    page='<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>V54-Astra 当前算法框架</title><style>'+STYLE+'</style></head><body><header><nav><a href="plots/index.html">逐点图册总入口</a>　<a href="plots/left/index.html">左线六设备</a>　<a href="plots/right/index.html">右线六设备</a></nav>'+flow+'</header><main>'+markdown_body(source)+'</main></body></html>'
    (ROOT/'算法框架.html').write_text(page,encoding='utf8')
    summary=json.loads((ROOT/'reports/independent_audit.json').read_text(encoding='utf8'))
    rows=[]
    for line in summary['lines']:
        rows.append(f"|{'左线' if line['line']=='left' else '右线'}|{line['devices']}|{line['markers']}|{line['eligible']}/{line['nominal']}|{line['new_reference_bound_pct']:.2f}%|{line['new_all_le1_pct']:.2f}%|")
    readme='''# V54-Astra 六设备十夜逐点图册

本次提供左右线各一套六设备图册：2026-11-06至11-15共10个日历夜，每夜23:00至次日07:00（不含07:00）。所有测点展开，不挑好看的点、不只列超幅点。左线11/06缺测明确留空，不补其他日期。

- [全部图册入口](plots/index.html)
- [左线六设备](plots/left/index.html)
- [右线六设备](plots/right/index.html)
- [当前算法框架](算法框架.html)

每图三条曲线：灰色数据库raw X、蓝色虚线数据库calX、红色新算法X。新算法使用已验证的current_fade07原生输出；本轮23—07发布路由在该窗口与它完全相同。保持原采集时间、原坐标基准和缺失段，不做时间平移、额外平滑、压幅或插值。图可按设备/日期看全点，也可按某测点连续看10夜。

|线路|设备|点数|合格/名义点夜|原幅度参考界内|全部≤1 pixel|
|---|---:|---:|---:|---:|---:|
'''+ '\n'.join(rows)+'''

范围为全部有效样本max−min。每点夜应有480帧，至少384帧计入汇总；缺测及覆盖不足均留在图册，不计通过。原幅度参考是普通点2 pixel、J/XJ 1 pixel；XJ共趋势是否可用于平差需结合整体趋势，图中绝对超参考不等于业务失败。

当前历史滚动能逐夜适应，但不保证每个失败单点自动改善。图册沿用已冻结结果，本轮没有为了使图更好看重新训练或调整算法。看完波形再决定是否生成同事解算用CSV；本次没有生成该CSV数据包。

源文件哈希、逐图元数据、独立全量核对记录均在reports；生成脚本在tools。目录为离线交付，未写回数据库、未部署现场版本。
'''
    (ROOT/'README.md').write_text(readme,encoding='utf8')
    if '--no-package' in sys.argv:
        print('Framework HTML and README created; package deferred.')
        return
    files=[p for p in ROOT.rglob('*') if p.is_file() and p.suffix!='.zip' and '__pycache__' not in p.parts and p.name!='delivery_verification.json']
    archive=ROOT/'V54-Astra_左右线各六设备_10夜全部逐点图.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in files:z.write(p,'V54-Astra_十夜逐点图/'+p.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        names=z.namelist();assert len(names)==len(set(names))
    validation=dict(archive_bytes=archive.stat().st_size,archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),entries=len(files),zip_crc_passed=True,csv_files_in_package=[str(p.relative_to(ROOT)) for p in files if p.suffix=='.csv'])
    assert not validation['csv_files_in_package']
    (ROOT/'reports/delivery_verification.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(validation,ensure_ascii=True))


if __name__=='__main__':main()
