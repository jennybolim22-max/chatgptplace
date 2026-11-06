"""Image processing and conservative, single-column exam segmentation."""
import re, uuid, html, hashlib
from pathlib import Path
from PIL import Image, ImageOps
import pypdfium2 as pdfium
import genanki
Image.MAX_IMAGE_PIXELS = 30_000_000

def uid(): return uuid.uuid4().hex

def render(source, directory):
    pages=[]
    def save(im):
        if im.width*im.height>30_000_000: raise ValueError('이미지 해상도가 너무 큽니다.')
        im=ImageOps.exif_transpose(im).convert('RGB');im.thumbnail((1800,2600))
        name=f'page-{len(pages)}.png';im.save(directory/name)
        pages.append(dict(index=len(pages),width=im.width,height=im.height,file=name))
    if source.suffix.lower()=='.pdf':
        with pdfium.PdfDocument(source) as doc:
            if not 1<=len(doc)<=50:raise ValueError('PDF는 1~50페이지를 지원합니다.')
            for page in doc:
                scale=min(2.5,1800/page.get_width(),2600/page.get_height())
                bitmap=page.render(scale=scale)
                try:save(bitmap.to_pil())
                finally:bitmap.close();page.close()
    else:
        with Image.open(source) as im:save(im)
    return pages

def part(page,y0=0,y1=1):return dict(page=page,y0=y0,y1=y1,x0=0.,x1=1.)

def compose(project,q,directory):
    pieces=[]
    for p in q['parts']:
        page=project['pages'][p['page']]
        with Image.open(directory/page['file']) as im:
            box=(int(p['x0']*im.width),int(p['y0']*im.height),int(p['x1']*im.width),int(p['y1']*im.height))
            if box[2]<=box[0] or box[3]<=box[1]:raise ValueError('이미지 영역이 비어 있습니다.')
            pieces.append(im.crop(box).convert('RGB'))
    width=max(im.width for im in pieces);height=sum(im.height for im in pieces)
    if width*height>35_000_000:raise ValueError('한 문제에 연결된 이미지가 너무 큽니다. 문제를 나누세요.')
    out=Image.new('RGB',(width,height),'white');y=0
    for im in pieces:out.paste(im,(0,y));y+=im.height
    return out

def new_question(parts,number):
    return dict(id=uid(),number=str(number),parts=parts,cut=.55,choices=['']*5,answers=[],included=True,reviewed=False,warnings=['원본과 선지를 확인하세요.'],source='manual')

def words_to_rows(words):
    rows=[]
    for w in sorted(words,key=lambda w:(w['y']+w['h']/2,w['x'])):
        center=w['y']+w['h']/2
        match=next((r for r in rows if abs(r['cy']-center)<max(3,min(r['h'],w['h'])*.5)),None)
        if match is None:rows.append({'cy':center,'h':w['h'],'words':[w]})
        else:match['words'].append(w)
    out=[]
    for r in rows:
        ws=sorted(r['words'],key=lambda w:w['x']);out.append(dict(text=' '.join(w['text'] for w in ws),x=min(w['x'] for w in ws),y=min(w['y'] for w in ws),bottom=max(w['y']+w['h'] for w in ws),score=min(w['score'] for w in ws),words=ws))
    return sorted(out,key=lambda r:r['y'])

QNUM=re.compile(r'^\s*(\d{1,3})(?:[.．]\s*|\s+(?=[가-힣A-Za-z]))')
OPT=re.compile(r'^\s*(?:\(?([1-9]|10)\s*[)）]|([①②③④⑤⑥⑦⑧⑨⑩]))\s*')

def opt(text):
    m=OPT.match(text)
    if not m:return None
    return int(m[1]) if m[1] else ord(m[2])-0x2460+1

def segment(project,layouts):
    anchors=[]
    for i,(page,words) in enumerate(zip(project['pages'],layouts)):
        for row in words_to_rows(words):
            m=QNUM.match(row['text'])
            # Period-only single digit labels can be choices. Avoid treating
            # them as a new question without following question text.
            if m and row['x']<page['width']*.22 and len(row['text'][m.end():].strip())>3:
                anchors.append((i,max(0,(row['y']-5)/page['height']),m[1]))
    if not anchors:return [new_question([part(i)],i+1) for i in range(len(project['pages']))]
    questions=[]
    if anchors[0][0]>0:
        for i in range(anchors[0][0]):questions.append(new_question([part(i)],'?'))
    # Include leading material on the first anchored page instead of dropping it.
    if anchors[0][1]>.18:questions.append(new_question([part(anchors[0][0],0,anchors[0][1])],'?'))
    for j,(p,y,n) in enumerate(anchors):
        endp,endy,_=anchors[j+1] if j+1<len(anchors) else (len(project['pages'])-1,1,'')
        parts=[part(i,y if i==p else 0,endy if i==endp else 1) for i in range(p,endp+1)]
        parts=[v for v in parts if v['y1']-v['y0']>.002]
        questions.append(new_question(parts,n))
    return questions

def fill_question(project,q,layouts,directory):
    words=[];offset=0;total=0
    for p in q['parts']:
        page=project['pages'][p['page']];w,h=page['width'],page['height'];top=int(p['y0']*h);bottom=int(p['y1']*h)
        for word in layouts[p['page']]:
            if top<=word['y']+word['h']/2<bottom and p['x0']*w<=word['x']<p['x1']*w:
                words.append(dict(word,x=word['x']-int(p['x0']*w),y=word['y']-top+offset))
        offset+=bottom-top
    total=offset
    rows=words_to_rows(words);anchors=[(r,opt(r['text'])) for r in rows if opt(r['text']) and r['x']<project['pages'][q['parts'][0]['page']]['width']*.25]
    nums=[n for _,n in anchors]
    if not 2<=len(nums)<=10 or nums!=list(range(1,len(nums)+1)):
        q['warnings']=['선지 번호를 확정하지 못했습니다. 선지 수와 경계를 직접 확인하세요.'];return
    q['cut']=max(.001,(anchors[0][0]['y']-4)/total);q['choices']=[];q['answers']=[];q['warnings']=[];q['source']='clova';q['reviewed']=False
    im=compose(project,q,directory)
    for i,(row,n) in enumerate(anchors):
        bottom=anchors[i+1][0]['y'] if i+1<len(anchors) else total
        group=[r for r in rows if row['y']<=r['y']<bottom and not re.search(r'출\s*제\s*자',r['text'])]
        text='\n'.join(r['text'] for r in group);text=OPT.sub('',text,count=1).strip();q['choices'].append(text)
        if not text or any(r['score']<.9 for r in group):q['warnings'].append(f'{i+1}번 선지 확인 필요')
        if re.search(r'[\u3400-\u9fffㄱ-ㅎㅏ-ㅣ]',text):q['warnings'].append(f'{i+1}번 한자·낱자 확인 필요')
        crop=im.crop((0,max(0,int(row['y'])),im.width,min(im.height,int(bottom))))
        pixels=list(crop.getdata());ink=sum(min(c)<190 for c in pixels);blue=sum(b>90 and b-r>35 and b>g*1.1 for r,g,b in pixels)
        if blue>=15 and blue/max(1,ink)>.12:q['answers'].append(i)
    if not q['answers']:q['warnings'].append('정답을 지정하세요.')

def split_parts(project,q,fraction):
    sizes=[int((p['y1']-p['y0'])*project['pages'][p['page']]['height']) for p in q['parts']]
    target=sum(sizes)*fraction;a=[];b=[];offset=0
    for p,size in zip(q['parts'],sizes):
        if target>=offset+size:a.append(dict(p))
        elif target<=offset:b.append(dict(p))
        else:
            y=p['y0']+(p['y1']-p['y0'])*(target-offset)/size
            a.append(dict(p,y1=y));b.append(dict(p,y0=y))
        offset+=size
    if not a or not b:raise ValueError('양쪽에 이미지가 남도록 분할 위치를 선택하세요.')
    return a,b

def make_apkg(project,directory,target):
    esc=lambda x:html.escape(x,quote=True).replace('\n','<br>')
    options=''.join('{{#C'+str(i)+'}}<button type="button" class="choice" data-i="'+str(i-1)+'"><b>'+str(i)+'</b><span>{{C'+str(i)+'}}</span></button>{{/C'+str(i)+'}}' for i in range(1,11))
    front='<div class="question">{{Question}}</div><div class="hint">{{Mode}}</div><div id="choices">'+options+'</div><div id="key" hidden>{{Key}}</div>'
    script='''<script>(function(){let key='mcq:'+document.getElementById('key').textContent;let picked=[];let items=[...document.querySelectorAll('.choice')];try{picked=JSON.parse(sessionStorage.getItem(key)||'[]')}catch(e){}function paint(){items.forEach(e=>e.classList.toggle('picked',picked.includes(+e.dataset.i)))}paint();items.forEach(e=>e.onclick=()=>{if(document.getElementById('answers'))return;let i=+e.dataset.i;if(document.querySelector('.hint').textContent.includes('단일'))picked=[i];else picked=picked.includes(i)?picked.filter(x=>x!==i):[...picked,i];paint();try{sessionStorage.setItem(key,JSON.stringify(picked))}catch(e){}})})();</script>'''
    back='''{{FrontSide}}<hr id="answer"><div id="answers" hidden>{{Answers}}</div><p id="summary"></p><small>{{Source}}</small><details><summary>원본 확인</summary>{{Original}}</details><script>(function(){let a=document.getElementById('answers').textContent.split(',').map(Number);document.querySelectorAll('.choice').forEach(e=>{e.onclick=null;e.classList.toggle('correct',a.includes(+e.dataset.i));e.classList.toggle('wrong',!a.includes(+e.dataset.i)&&e.classList.contains('picked'))});document.getElementById('summary').textContent='정답: '+a.map(x=>x+1).join(', ')+'번';try{sessionStorage.removeItem('mcq:'+document.getElementById('key').textContent)}catch(e){}})();</script>'''
    model=genanki.Model(1843092711,'MCQ Web · 객관식 2–10 v1',fields=[{'name':n} for n in ['Question','Answers','Mode','Key','Original','Source']+[f'C{i}' for i in range(1,11)]],templates=[{'name':'객관식','qfmt':front+script,'afmt':back}],css='.card{font:18px/1.7 Arial,sans-serif;text-align:left;max-width:900px;margin:auto;padding:20px}img{max-width:100%;height:auto}.choice{display:flex;gap:16px;width:100%;text-align:left;font:inherit;color:inherit;padding:12px;border:1px solid #aaa;border-radius:10px;margin:8px 0;background:transparent}.picked{border-color:#287b66;background:#287b6620}.correct{background:#287b6630;border:2px solid #287b66}.wrong{border-color:#c44;background:#c442222}.hint,small{font-size:13px;opacity:.7}')
    deckid=int(hashlib.sha256(project['id'].encode()).hexdigest()[:8],16)>>1;deck=genanki.Deck(deckid,project['deck']);media=[]
    for q in project['questions']:
        if not q['included']:continue
        if not q['reviewed'] or not q['answers'] or any(not c.strip() for c in q['choices']):raise ValueError('내보낼 모든 문제의 선지·정답을 확인하고 검토 완료를 선택하세요.')
        im=compose(project,q,directory);cut=int(im.height*q['cut'])
        if not 1<=cut<im.height:raise ValueError('앞면 경계를 확인하세요.')
        frontfile=directory/f"mcq-{project['id']}-{q['id']}-front.png";original=directory/f"mcq-{project['id']}-{q['id']}-original.png"
        im.crop((0,0,im.width,cut)).save(frontfile);im.save(original);media.extend([str(frontfile),str(original)])
        fields=[f'<img src="{frontfile.name}">',','.join(map(str,q['answers'])),'단일 정답' if len(q['answers'])==1 else '복수 정답',q['id'],f'<img src="{original.name}">',esc(project['filename']+' · '+q['number'])]+[esc(c) for c in q['choices']]+['']*(10-len(q['choices']))
        deck.add_note(genanki.Note(model=model,fields=fields,guid=genanki.guid_for(project['id'],q['id']),tags=['MCQ']))
    if not deck.notes:raise ValueError('내보낼 문제를 선택하세요.')
    package=genanki.Package(deck);package.media_files=media;package.write_to_file(str(target))
