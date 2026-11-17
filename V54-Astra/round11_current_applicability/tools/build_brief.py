from pathlib import Path
from datetime import datetime,timedelta,timezone
import html,json,struct
import numpy as np

ROOT=Path(__file__).resolve().parents[1];BASE=ROOT.parent;OUT=ROOT/'reports';TZ=timezone(timedelta(hours=8))
COLORS=['#64748b','#15803d','#d97706','#be123c']
def ms(s):return int(datetime.fromisoformat(s).replace(tzinfo=TZ).timestamp()*1000)
def panel(parts,x,y,w,h,title,t,series,labels,lo,ylim=None):
    vals=np.concatenate([a[np.isfinite(a)] for a in series]);mn,mx=(float(vals.min()),float(vals.max())) if ylim is None else ylim
    span=max(mx-mn,.05);mn-=span*.07;mx+=span*.07
    left=x+68;right=x+w-22;top=y+66;bottom=y+h-45
    parts.append(f'<text x="{x+12}" y="{y+24}" font-size="18" font-weight="600">{html.escape(title)}</text>')
    for k,label in enumerate(labels):
        xx=x+16+k*138;parts.append(f'<line x1="{xx}" x2="{xx+24}" y1="{y+45}" y2="{y+45}" stroke="{COLORS[k]}" stroke-width="2"/><text x="{xx+29}" y="{y+49}" font-size="12">{html.escape(label)}</text>')
    for k in range(5):
        v=mn+(mx-mn)*k/4;py=bottom-(bottom-top)*k/4
        parts.append(f'<line x1="{left}" x2="{right}" y1="{py}" y2="{py}" stroke="#e2e8f0"/><text x="{left-9}" y="{py+4}" text-anchor="end" font-size="11">{v:.2f}</text>')
    for k in range(9):
        xx=left+(right-left)*k/8;parts.append(f'<text x="{xx}" y="{bottom+21}" text-anchor="middle" font-size="11">{(23+k)%24:02}:00</text>')
    for j,a in enumerate(series):
        runs=[];run=[]
        for i,(tt,v) in enumerate(zip(t,a)):
            if not np.isfinite(v) or (i and tt-t[i-1]>180000):
                if run:runs.append(run);run=[]
            if np.isfinite(v):run.append(f'{left+(int(tt)-lo)/28800000*(right-left):.2f},{bottom-(float(v)-mn)/(mx-mn)*(bottom-top):.2f}')
        if run:runs.append(run)
        for r in runs:parts.append(f'<polyline points="{" ".join(r)}" stroke="{COLORS[j]}" stroke-width="1.4" fill="none"/>')
    parts.append(f'<text x="{left}" y="{bottom+39}" font-size="11" fill="#64748b">相对同一 raw 基准 / pixel；原时间戳，无平移</text>')
def main():
    parts=['<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="810" viewBox="0 0 1200 810">','<rect width="1200" height="810" fill="white"/>','<g font-family="Microsoft YaHei, Noto Sans CJK SC, sans-serif" fill="#172033">',
           '<text x="28" y="35" font-size="24" font-weight="700">历史更多，结果并不单向变好</text>',
           '<text x="28" y="61" font-size="14" fill="#475569">3 / 5 / 7 夜均只用目标夜之前的历史；以下为模态核心，未叠加 S2 / S1。</text>']
    for k,(dev,night,name,title) in enumerate([
        ('780638349768','2026-11-14','ZD4404','平稳点被放大：左 349768 · ZD4404 · 11/14'),
        ('780638327479','2026-11-12','ZXJ6','原失败点有改善：左 327479 · ZXJ6 · 11/12')]):
        with np.load(OUT/f'history_length_arrays_left_{dev}.npz') as z:
            key=night.replace('-','_');t=z[key+'_timestamp'];j=list(z['names']).index(name);raw=z[key+'_raw'][:,j]
            lo=ms(night+'T23:00');ref=float(np.nanmedian(raw[(t>=lo-3600000)&(t<lo)]));take=(t>=lo)&(t<lo+28800000)
            curves=[raw[take]-ref]+[z[key+f'_modal_h{n}'][take,j]-ref for n in [3,5,7]]
            panel(parts,18,80+k*354,1164,350,title,t[take],curves,['raw','3 夜','5 夜','7 夜'],lo)
    parts+=['</g></svg>'];(OUT/'history_length_focus.svg').write_text(''.join(parts),encoding='utf8')
    audit=json.loads((OUT/'reference_guard_field_audit.json').read_text(encoding='utf8'))
    summary=audit['summary']['ordinary_J'];quiet=audit['summary']['quiet_ordinary_J']
    rows=''.join(f'<tr><td>{n}</td><td>{passed} / 3130</td><td>{p95}</td></tr>' for n,passed,p95 in [('3夜',1924,'2.357'),('5夜',1921,'2.407'),('7夜',1922,'2.372')])
    body=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>历史适用性与过修保护｜R11</title><style>body{{font:16px/1.8 "Microsoft YaHei",sans-serif;color:#172033;background:#f4f6f8;margin:0}}main{{max-width:1060px;margin:auto;padding:34px}}section{{background:white;padding:24px;margin:20px 0;border-radius:8px}}h1{{font-size:28px}}h2{{font-size:21px}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #dbe2ea;padding:8px;text-align:left}}strong{{color:#14532d}}.reject{{color:#9f1239}}a{{color:#1d4ed8}}img{{width:100%}}code{{font-size:14px}}</style><main>
    <h1>历史适用性：先防错误扣除，再考虑更多历史</h1><p>离线分析 · 2026-11-17 · 所有结果留在 V54-Astra / round11_current_applicability</p>
    <section><h2>本轮结论</h2><p><strong>暂保留最近3个合格夜；增加至5/7夜不能替代当日适用性判断。</strong> 本轮试验的“J活动小就缩小总补偿”未通过，已否决，未接入交付源码或状态包。</p><p>当前历史保存跨测点关系，并不按时间重播历史波形。真正风险是今天的其他点变化、有效点集合或参考状态，被旧关系错误投影到目标点。</p></section>
    <section><h2>更多历史：同一组12设备、6夜对照</h2><p>11/10–15，23–07；3130个合格点夜。三种长度均重新生成模态及gain，只用此前历史。以下仅是模态核心，不能与完整链通过数直接相加。</p><table><tr><th>历史长度</th><th>范围≤1 pixel</th><th>范围P95 / pixel</th></tr>{rows}</table><p>左349768 / ZD4404 / 11-14：raw范围0.985，3夜0.152，5夜1.460，7夜1.479。原327479 / ZXJ6失败点随更多历史改善，但其他点存在退步。</p><img src="reports/history_length_focus.svg" alt="更多历史的改善与退步实例"><p><a href="reports/history_length_summary.md">完整中文报告与统计口径</a></p></section>
    <section><h2>平稳夜与保护试验</h2><p>完整10夜普通/J有效4851点夜，其中raw范围≤1的121点夜，现有完整链没有范围放大。没有覆盖“前三夜均强、第四夜整台静止”的真实案例，不能据此宣称该情景已验证。</p><p class="reject">否决候选：只用J活动强弱缩放既有总补偿。普通/J按普通≤2、J≤1范围统计，从{summary['base']['role_pass']}降到{summary['shadow']['role_pass']} / {summary['eligible']}；新增{summary['new_role_failure']}个范围失败。XJ另列描述，不当静止基准，也不据绝对范围直接判业务失败。</p><p>原因可直接解释：输出 = raw − gain × 补偿；即使raw不动，gain改变也会造成 −补偿 × gain变化 的额外坐标变化。渐变只把跳变换成斜坡。实测327479 / ZXJ6 / 11-08最大相邻变化0.577→6.603 pixel。</p><p><a href="reports/quiet_inventory.md">固定平稳样本</a> · <a href="reports/reference_activity_guard_verdict.md">保护候选否决报告</a> · <a href="reports/reference_activity_guard_tests.json">构造测试与反例</a></p></section>
    <section><h2>真实历史后的已知真值测试</h2><p>冻结327479真实11/09–11三夜模型，第四夜22–07所有54点均恒定：模态预测补偿、输出误差、新生范围均为0。历史本身不会播放旧波形。保留前一段W3缓存的独立边界测试出现约0.002854 pixel变化，不能与理想恒定用例混淆。</p><p>再只给普通点真实+1 pixel阶跃、J及其他点保持不动：ZD4703保留0.89954；按历史最大自投影选出的ZD3204保留0.63956，同时静止ZXJ6出现最高0.92847 pixel假响应。这直接暴露目标变化被跨点旧关系传播的问题。仅Python模态核心，未经过原生全链；该对抗点不是全设备发生率估计。</p><p><a href="reports/synthetic_constant_core.md">合成构造、真值及完整结果</a></p></section>
    <section><h2>下一版应实现的逻辑契约</h2><ol><li>历史只提供候选空间关系。当夜扰动幅度由当夜观测估计，不继承过去“大波动就强补”的力度。</li><li>用独立J检查历史预测的当前残差、方向、参考之间一致性及可观测性。普通点与XJ的自身拟合不能单独授权扣除它们的变化。</li><li>只允许参考有证据支持的补偿增量。关系失配时停止增加不可信补偿，保留已接受值并显示失配状态；不能突然把全部补偿归零。冻结可能保留旧偏置，必须可见。</li><li>J不足或某模态在J上不可辨时明确“无充分证据”。当前12台中5台无J，不能声称此方案覆盖它们；也不把XJ假定不动补位。</li><li>3夜维持当前默认；可另保留7夜用于历史稳定性诊断和后续独立验证，不自动混入、不按本夜结果挑最佳模型。历史更替、重启与07切原始数据均需单列测试。</li></ol><p>这是待实现并验证的方向，尚未证明可以解决327479的关系失配。参考驱动的模型估计、后级S2/S1、保护切换和状态恢复需要一起验证；不新增运维逐点旋钮。</p></section>
    <section><h2>验证边界</h2><p>历史长度重建的72个设备夜与冻结原生3夜模态核对，最大差5.11×10⁻¹⁰ pixel。J活动候选只叠加于冻结原生输出，不能替代完整链事件注入。新DLL未执行；未改数据库、已导出CSV或交付cpp/h/状态包。</p><p>合成真实阶跃、扰动与位移相消、参考故障、保护切换均必须独立验收。范围更小或能量更低不是物理准确性证明。<a href="reports/guard_design_review.md">详细设计与否决条件</a></p></section></main></html>'''
    (ROOT/'index.html').write_text(body,encoding='utf8')
    print('BRIEF_READY',ROOT/'index.html')
if __name__=='__main__':main()
