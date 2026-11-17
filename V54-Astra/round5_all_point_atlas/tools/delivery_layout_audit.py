"""Local document link checks and record of offline SVG visual inspection."""
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlsplit,unquote
import json,re,hashlib

ROOT=Path(__file__).resolve().parents[1]


class References(HTMLParser):
    def __init__(self):super().__init__();self.refs=[];self.ids=set()
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if 'id' in attrs:self.ids.add(attrs['id'])
        for key in ['href','src']:
            if key in attrs:self.refs.append(attrs[key])


def main():
    pages=list((ROOT/'plots').rglob('*.html'))+[ROOT/'算法框架.html']
    parsed={}
    for p in pages:
        h=References();h.feed(p.read_text(encoding='utf8'));parsed[p.resolve()]=h
    total=0;anchors=0
    for p,h in parsed.items():
        for ref in h.refs:
            url=urlsplit(ref)
            assert url.scheme not in ['http','https','javascript'],ref
            if url.scheme=='file':target=Path(unquote(url.path).lstrip('/')).resolve()
            else:target=(p.parent/unquote(url.path)).resolve() if url.path else p
            assert target.is_file(),(p,ref)
            total+=1
            if url.fragment and target.suffix=='.html':
                assert target in parsed and unquote(url.fragment) in parsed[target].ids,(p,ref)
                anchors+=1
    manifest=json.loads((ROOT/'reports/all_point_atlas_manifest_both.json').read_text(encoding='utf8'))
    previews=json.loads((ROOT/'reports/svg_preview_render.json').read_text(encoding='utf8'))
    for record in previews['records']:
        current=hashlib.sha256((ROOT/'plots'/record['source']).read_bytes()).hexdigest()
        assert current==record['sha256']
    result=dict(html_pages_checked=len(pages),local_references_checked=total,anchor_targets_checked=anchors,
        all_local_targets_exist=True,framework_present=True,network_references=0,
        visual_method='Four existing SVGs rendered directly offline using sharp, then inspected as PNG; no reconstructed plotting substitute',
        visually_checked_cases=previews['records'],
        visual_result='Chinese text, titles, shared axes, cross-midnight ticks, all three curves, missing-data placeholder and XJ descriptive label are readable; no clipping observed',
        browser_preview='Not completed: browser tool policy rejects file:// navigation. No workaround, alternate browser surface, or local web server was used.',
        limitation='HTML navigation targets and anchors verified structurally; HTML whole-page browser rendering was not inspected',
        csv_export_created=False)
    (ROOT/'reports/layout_and_link_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k!='visually_checked_cases'},ensure_ascii=True))


if __name__=='__main__':main()
