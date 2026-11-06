import os,tempfile,time,io,json,sqlite3,zipfile
os.environ['MCQ_DATA_DIR']=tempfile.mkdtemp(prefix='mcq-test-')
from fastapi.testclient import TestClient
from PIL import Image
from backend import main as m
from backend.engine import words_to_rows,segment,fill_question
H={'X-MCQ-Request':'1'}

def client():
    c=TestClient(m.app);assert c.post('/api/session',json={},headers=H).status_code==200;return c

def test_export_is_real_apkg_and_private():
    c=client();p=c.post('/api/demo',headers=H).json();pid=p['id'];q=p['questions'][0]
    assert c.post(f'/api/projects/{pid}/export',headers=H).status_code==400
    q['choices']=['<script>alert(1)</script>']+[f'선지 {i}' for i in range(2,11)];q['answers']=[1,6,9];q['reviewed']=True
    r=c.put(f'/api/projects/{pid}',headers=H,json={'revision':p['revision'],'deck':p['deck'],'questions':[q]});assert r.status_code==200,r.text
    stale=c.put(f'/api/projects/{pid}',headers=H,json={'revision':0,'deck':p['deck'],'questions':[q]});assert stale.status_code==409
    other=client();assert other.get(f'/api/projects/{pid}').status_code==404
    assert other.get(f'/api/projects/{pid}/questions/{q["id"]}/image').status_code==404
    assert c.post(f'/api/projects/{pid}/export').status_code==403
    exported=c.post(f'/api/projects/{pid}/export',headers=H);assert exported.status_code==200,exported.text
    with zipfile.ZipFile(io.BytesIO(exported.content)) as z:
        assert z.testzip() is None
        media=json.loads(z.read('media'));assert len(media)==2
        path=m.ROOT/'verify.anki2';path.write_bytes(z.read('collection.anki2'))
        with sqlite3.connect(path) as db:
            fields=db.execute('SELECT flds FROM notes').fetchone()[0].split('\x1f')
            assert fields[1]=='1,6,9' and fields[2]=='복수 정답'
            assert fields[6]=='&lt;script&gt;alert(1)&lt;/script&gt;' and fields[15]=='선지 10'
            models=json.loads(db.execute('SELECT models FROM col').fetchone()[0]);model=next(iter(models.values()))
            assert '{{C10}}' in model['tmpls'][0]['qfmt']
    assert c.delete(f'/api/projects/{pid}',headers=H).status_code==200
    assert c.get(f'/api/projects/{pid}').status_code==404

def test_upload_split_merge_and_validation():
    c=client();buf=io.BytesIO();Image.new('RGB',(800,1000),'white').save(buf,format='PNG')
    r=c.post('/api/projects',headers=H,files={'file':('test.png',buf.getvalue(),'image/png')},data={'deck':'Test','auto':'false'});assert r.status_code==200,r.text
    p=r.json()
    for _ in range(100):
        p=c.get('/api/projects/'+p['id']).json()
        if p['status']=='ready':break
        time.sleep(.05)
    assert len(p['pages'])==1
    q=p['questions'][0];r=c.post(f'/api/projects/{p["id"]}/questions/{q["id"]}/split',headers=H,json={'fraction':.4});assert r.status_code==200
    p=r.json();assert len(p['questions'])==2
    assert p['questions'][0]['parts'][0]['y1']==.4
    r=c.post(f'/api/projects/{p["id"]}/questions/{p["questions"][0]["id"]}/merge',headers=H);assert r.status_code==200
    p=r.json();assert len(p['questions'])==1 and len(p['questions'][0]['parts'])==2
    p['questions'][0]['answers']=[99]
    r=c.put('/api/projects/'+p['id'],headers=H,json={'revision':p['revision'],'deck':p['deck'],'questions':p['questions']});assert r.status_code==422
    assert c.post('/api/projects/'+p['id']+'/ocr',headers=H,json={'consent':True}).status_code==400

def test_auth_gate_cannot_be_bypassed(monkeypatch):
    monkeypatch.setenv('MCQ_ACCESS_CODE','test-access')
    c=TestClient(m.app);assert c.post('/api/session',headers=H,json={}).status_code==403
    c.cookies.set('mcq_session','a'*64)
    assert c.get('/api/projects').status_code==401
    assert c.post('/api/session',headers=H,json={'code':'test-access'}).status_code==200
    assert c.get('/api/projects').status_code==200

def test_cross_page_segmentation_and_clova_contract(monkeypatch):
    def w(text,y,x=30):return dict(text=text,x=x,y=y,w=400,h=20,score=.99)
    pages=[dict(index=i,width=800,height=1000,file=f'page-{i}.png') for i in range(2)]
    project={'pages':pages}
    layouts=[[w('1. 첫 번째 문제입니다',40),w('1) 첫째 선지',600),w('2) 둘째 선지',650)], [w('3) 셋째 선지',40),w('2. 두 번째 문제입니다',300),w('1) A',600),w('2) B',650)]]
    qs=segment(project,layouts);assert len(qs)==2 and len(qs[0]['parts'])==2 and qs[0]['number']=='1'
    for page in pages:Image.new('RGB',(800,1000),'white').save(m.ROOT/page['file'])
    fill_question(project,qs[0],layouts,m.ROOT)
    assert qs[0]['choices']==['첫째 선지','둘째 선지','셋째 선지'],qs[0]
    monkeypatch.setenv('CLOVA_OCR_URL','https://example.apigw.ntruss.com/general');monkeypatch.setenv('CLOVA_OCR_SECRET','test-only')
    class Fake:
        def __init__(self,**kw):pass
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def post(self,url,headers,json):
            assert headers['X-OCR-SECRET']=='test-only' and json['version']=='V2' and json['lang']=='ko'
            assert json['images'][0]['data'] and json['images'][0]['format']=='png'
            class R:
                status_code=200
                def json(self):return {'images':[{'inferResult':'SUCCESS','fields':[{'inferText':'한글 English','inferConfidence':.95,'boundingPoly':{'vertices':[{'x':2,'y':4},{'x':100,'y':4},{'x':100,'y':24},{'x':2,'y':24}]}}]}]}
            return R()
    monkeypatch.setattr(m.httpx,'Client',Fake)
    words=m.ocr_page(m.ROOT/'page-0.png');assert words[0]['text']=='한글 English' and words[0]['h']==20

def test_multipage_pdf_render_and_join():
    c=client();buf=io.BytesIO()
    Image.new('RGB',(600,800),'white').save(buf,format='PDF',save_all=True,append_images=[Image.new('RGB',(600,800),'white')])
    r=c.post('/api/projects',headers=H,files={'file':('two-pages.pdf',buf.getvalue(),'application/pdf')},data={'auto':'false'})
    assert r.status_code==200,r.text
    pid=r.json()['id']
    for _ in range(200):
        p=c.get('/api/projects/'+pid).json()
        if p['status'] not in ('processing','ocr'):break
        time.sleep(.05)
    assert p['status']=='ready' and len(p['pages'])==2,p
    qid=p['questions'][0]['id']
    r=c.post(f'/api/projects/{pid}/questions/{qid}/merge',headers=H)
    assert r.status_code==200
    assert [s['page'] for s in r.json()['questions'][0]['parts']]==[0,1]
    qid=r.json()['questions'][0]['id']
    im=c.get(f'/api/projects/{pid}/questions/{qid}/image')
    assert im.status_code==200
    with Image.open(io.BytesIO(im.content)) as img:assert img.height>img.width*2
