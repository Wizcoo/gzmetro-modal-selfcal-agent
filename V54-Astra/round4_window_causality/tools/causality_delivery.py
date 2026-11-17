"""Chinese read-only report figures and the user's complete 34-point window."""
from pathlib import Path
import sys,json,html,re,zipfile,hashlib
from datetime import datetime
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];BASE=ROOT.parent;OUT=ROOT/'plots';OUT.mkdir(exist_ok=True)
sys.path.insert(0,str(BASE/'round3_physics_failure/tools'))
import chinese_failure_atlas as atlas
plt=atlas.plt

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    report=json.loads((ROOT/'reports/yd_influence_summary.json').read_text(encoding='utf8'))
    fig,axes=plt.subplots(1,2,figsize=(14,5.8),layout='constrained')
    values=np.array([r['window_23_07']['p95p5'] for r in report['crossed_history_live_intervention']]).reshape(2,2)
    xx=np.arange(2)
    axes[0].bar(xx-.18,values[:,0],width=.34,color='#2871b9',label='当夜输入：raw')
    axes[0].bar(xx+.18,values[:,1],width=.34,color='#cb493e',label='当夜输入：W3')
    for i in range(2):
        for j,offset in enumerate([-.18,.18]):axes[0].text(i+offset,values[i,j]+.035,f'{values[i,j]:.3f}',ha='center')
    axes[0].set_xticks(xx,['raw历史学模态','W3历史学模态']);axes[0].set_ylabel('模态核心 P95−P5（pixel）');axes[0].set_ylim(0,1.95)
    axes[0].set_title('换历史模型，结果明显变化\n当前是否W3不是本例主要分界',fontsize=12)
    axes[0].legend(fontsize=10);axes[0].grid(axis='y',alpha=.15);axes[0].set_axisbelow(True)
    h=report['historical_target_energy'];yy=np.arange(3)
    axes[1].bar(yy-.18,[v['raw_energy'] for v in h],width=.34,color='#77818d',label='历史W3输入能量')
    axes[1].bar(yy+.18,[v['residual_energy'] for v in h],width=.34,color='#cb493e',label='减预测后代理能量')
    for i,r in enumerate(h):
        for field,offset in [('raw_energy',-.18),('residual_energy',.18)]:axes[1].text(i+offset,r[field]+.009,f'{r[field]:.3f}',ha='center',fontsize=10)
    axes[1].set_xticks(yy,[r['night'][5:] for r in h]);axes[1].set_ylim(0,.48);axes[1].set_ylabel('相对各夜基线的二阶能量（pixel²）')
    axes[1].set_title('三夜合并收益不能替代逐夜检查\n用11/06冻结模型回看其三份训练统计',fontsize=12)
    axes[1].legend(fontsize=10);axes[1].grid(axis='y',alpha=.15);axes[1].set_axisbelow(True)
    fig.suptitle('YD1102：为何3夜历史仍会负优化\n右线780639298317｜11/06夜｜独立代数重建，非新上线方案',fontsize=15)
    fig.savefig(OUT/'yd_history_causality.png',dpi=180);plt.close(fig)
    # The exact page the user cited, now showing every marker during 23-07.
    line='left';dev='780637798298';night='2026-11-07'
    with np.load(BASE/f'data/{line}/{dev}/input.npz') as d:ts=d['timestamp'];names=d['names'];raw=d['x'];old=d['online_x']
    new=atlas.read(BASE/f'round2_waveform_10n/results/current_fade07/{line}/{dev}/output.bin')
    start=atlas.ms(night+' 23:00');end=atlas.ms('2026-11-08 07:00');mask=(ts>=start)&(ts<end);tt=ts[mask]
    m=pd.read_csv(ROOT/'reports/window_xj_point_nights.csv',dtype={'device':str})
    m=m[(m.profile=='current_fade07')&(m.line==line)&(m.device==dev)&(m.night==night)].set_index('marker')
    assert len(m)==34 and m.eligible.all() and m.pass_class.sum()==32
    folder=OUT/'用户案例34点';folder.mkdir(exist_ok=True);cards=[]
    fig,ax=plt.subplots(figsize=(14,4.4),layout='constrained')
    for name in sorted(names):
        j=list(names).index(name);r=m.loc[name];v=np.column_stack([raw[mask,j],old[mask,j],new['xy'][mask,0,j]])
        assert abs(atlas.span(v[:,2])-r.p2p)<1e-8
        ax.clear();px,pv=atlas.plot_input(tt,v);atlas.series(ax,px,pv);atlas.setup_axis(ax,start,end)
        status='在原幅度参考内' if r.pass_class else '略超原幅度参考'
        ax.set_title(f'左线 {dev} / {name}｜2026-11-07 23:00—11-08 07:00\n{status}：raw {atlas.span(v[:,0]):.3f} / calX {atlas.span(v[:,1]):.3f} / 新算法 {r.p2p:.3f} pixel；参考≤{r.limit:g}',fontsize=12)
        ax.set_xlabel('北京时间；三条曲线保留原采集时间和数值基准')
        if not fig.legends:fig.legend(*ax.get_legend_handles_labels(),loc='outside lower center',ncol=3,fontsize=10)
        file=f'用户案例34点/{name}.svg';fig.savefig(OUT/file)
        cards.append(f'<figure id="{name}"><figcaption><b>{name}</b> · {status} · 新算法范围 {r.p2p:.3f} pixel</figcaption><a href="{file}"><img loading="lazy" src="{file}" alt="{name}三曲线"></a></figure>')
    plt.close(fig)
    casehtml='23-07_左线798298_11-07.html'
    page=f'<nav><a href="index.html">返回本轮复核</a></nav><header><h1>你指出的左线798298 · 11月7日</h1><p>改看23:00—次日07:00，全部34点列出；32点在原参考范围内，ZD2101为2.075、ZD2301为2.109 pixel，属于轻微超参考值。标签只描述幅度，不代表波形整体失效。</p><p>灰色：数据库raw X；蓝色虚线：数据库calX；红色：Astra修后X（23—07输出与此前版本完全相同；07后切回raw）。XJ另看设备共同趋势及相对差，不因超过1 pixel自动判业务失败。</p></header>'+''.join(cards)
    (OUT/casehtml).write_text(atlas.document('23—07左线798298全部34点',page),encoding='utf8')
    descriptions={
      'yd_stage_decomposition.png':'YD1102逐阶段拆解：模态先放大，S2与S1略缓解。',
      'yd_history_causality.png':'历史模型交叉干预与分夜代理能量：3夜合并不等于每夜每点受保护。',
      'window_xj_left_780637798298_ZXJ4_2026-11-07.png':'用户指出的设备：ZXJ4修后范围0.650 pixel，相对普通点趋势差0.662 pixel。',
      'window_xj_left_780638327479_ZXJ6_2026-11-09.png':'大幅ZXJ6反例：按普通点中位趋势，不是全设备同向一起波动。',
      'exit_output_contract.png':'07点后只看原始：输出端结束修正段；基准切换断线显示，不再输出渐退斜坡。'}
    content='<header><h1>23—07波形复核与YD1102原因分析</h1><p>模态与滤波核心不改；新增07点结束修正的输出适配器。新窗口按原幅度参考描述为92.71%，XJ绝对幅度与相对设备变化分开解释。</p><nav><a href="../README.md">完整结论</a><a href="'+casehtml+'">你指出的设备：全部34点</a><a href="../reports/window_xj_review.md">窗口与XJ全量复核</a><a href="../reports/yd_stage_review.md">YD1102逐阶段证据</a><a href="../integration/README.md">07点结束修正接入说明</a></nav></header>'
    for file,desc in descriptions.items():content+=f'<figure><figcaption><h2>{desc}</h2></figcaption><a href="{file}"><img src="{file}" alt="{desc}"></a></figure>'
    content+='<section class="panel"><h2>退出输出已按业务确认更新</h2><p>23:00—07:00保留Astra修后X，07:00起发布raw X。后台核心继续处理历史；Y不变。221,720设备帧离线路由核验通过，23—07波形与旧输出完全相同。07点的数值差是观测段切换，不作为跨段物理峰谷；此接入件未部署，YD1102历史模态尚未修改。</p></section>'
    (OUT/'index.html').write_text(atlas.document('23—07复核与负优化原因',content),encoding='utf8')
    for p in OUT.glob('*.html'):
        for ref in re.findall(r'(?:src|href)="([^"]+)"',p.read_text(encoding='utf8')):
            if not ref.startswith('#'):assert (p.parent/ref).is_file(),ref
    archive=ROOT/'V54-Astra_23至07与负优化原因.zip'
    entries=[ROOT/'README.md']
    for directory in ['tools','reports','plots','integration']:
        entries.extend(p for p in (ROOT/directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts and '.mplconfig' not in p.parts and p.name!='delivery_verification.json')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in entries:z.write(p,'V54-Astra-23至07复核/'+str(p.relative_to(ROOT)).replace('\\','/'))
    with zipfile.ZipFile(archive) as z:assert z.testzip() is None
    result={'user_case_markers':34,'user_case_pass':32,'range_checks':34,'charts_index':str(OUT/'index.html'),'archive_sha256':sha(archive),'archive_bytes':archive.stat().st_size,'entries':len(entries),'local_links_verified':True}
    (ROOT/'reports/delivery_verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=True))

if __name__=='__main__':main()
