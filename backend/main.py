import asyncio, base64, hashlib, hmac, io, json, os, re, secrets, shutil, sqlite3, threading, time
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse
import httpx
from fastapi import FastAPI, Request, Response, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator
from .engine import render, uid, new_question, part, segment, fill_question, compose, split_parts, make_apkg

ROOT=Path(os.getenv('MCQ_DATA_DIR','./data')).resolve();ROOT.mkdir(parents=True,exist_ok=True)
DB=ROOT/'mcq.sqlite';LOCK=threading.RLock();POOL=ThreadPoolExecutor(max_workers=2);SLOTS=threading.BoundedSemaphore(6)
RENDER_LOCK=threading.Lock() # PDFium must not render concurrently in separate threads.
TTL=24*3600
SECRET_FILE=ROOT/'session-secret'
if not SECRET_FILE.exists():
    try:
        with SECRET_FILE.open('x') as f:f.write(secrets.token_hex(32))
    except FileExistsError:pass
SESSION_SECRET=SECRET_FILE.read_text().strip().encode()
def signed(token):return token+'.'+hmac.new(SESSION_SECRET,token.encode(),'sha256').hexdigest()
def valid_token(value):
    return bool(re.fullmatch(r'[a-f0-9]{64}\.[a-f0-9]{64}',value) and hmac.compare_digest(value,signed(value.split('.')[0])))

def connect():
    db=sqlite3.connect(DB,timeout=20);db.execute('PRAGMA journal_mode=WAL');return db
with connect() as db:
    db.execute('CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,owner TEXT,updated REAL,state TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS quota(day TEXT PRIMARY KEY,used INTEGER)')

def read(pid,owner=None):
    with connect() as db:r=db.execute('SELECT owner,state FROM projects WHERE id=?',(pid,)).fetchone()
    if not r or (owner is not None and not hmac.compare_digest(r[0],owner)):raise HTTPException(404,'작업을 찾을 수 없습니다. 24시간이 지나 삭제되었거나 다른 브라우저에서 만든 작업입니다.')
    return json.loads(r[1])

def write(p,owner=None):
    with connect() as db:
        if owner:db.execute('INSERT INTO projects VALUES(?,?,?,?)',(p['id'],owner,time.time(),json.dumps(p,ensure_ascii=False)))
        else:db.execute('UPDATE projects SET updated=?,state=? WHERE id=?',(time.time(),json.dumps(p,ensure_ascii=False),p['id']))

def purge():
    with LOCK,connect() as db:
        rows=db.execute('SELECT id FROM projects WHERE updated<?',(time.time()-TTL,)).fetchall()
        for (pid,) in rows:shutil.rmtree(ROOT/pid,ignore_errors=True)
        db.execute('DELETE FROM projects WHERE updated<?',(time.time()-TTL,))
    # Upload failures can leave directories without a database record.
    with connect() as db:known={r[0] for r in db.execute('SELECT id FROM projects')}
    for folder in ROOT.iterdir():
        if folder.is_dir() and re.fullmatch(r'[0-9a-f]{32}',folder.name) and folder.name not in known and folder.stat().st_mtime<time.time()-TTL:shutil.rmtree(folder,ignore_errors=True)

@asynccontextmanager
async def lifespan(app):
    purge()
    with connect() as db:states=[json.loads(r[0]) for r in db.execute('SELECT state FROM projects')]
    for p in states:
        if p['status'] in ('processing','ocr'):
            p.update(status='error',message='서버가 재시작되어 처리가 중단됐습니다. 파일을 다시 올려주세요.');write(p)
    async def clean():
        while True:
            await asyncio.sleep(600);await asyncio.to_thread(purge)
    task=asyncio.create_task(clean());yield;task.cancel()
app=FastAPI(title='MCQ',lifespan=lifespan)

@app.middleware('http')
async def guard(request,call_next):
    if request.url.path.startswith('/api/') and request.method in ('POST','PUT','DELETE') and request.headers.get('x-mcq-request')!='1':
        return Response(status_code=403,content='Same-origin request required')
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff';response.headers['Referrer-Policy']='same-origin'
    if request.url.path.startswith('/api/'):response.headers['Cache-Control']='no-store'
    return response

def owner(request):
    token=request.cookies.get('mcq_session','')
    if not valid_token(token):raise HTTPException(401,'새로고침 후 다시 시작하세요.')
    return hashlib.sha256(token.encode()).hexdigest()

def credentials():return os.getenv('CLOVA_OCR_URL','').strip(),os.getenv('CLOVA_OCR_SECRET','').strip()

@app.get('/api/config')
def config():
    url,key=credentials();return {'ocr_ready':bool(url and key),'access_required':bool(os.getenv('MCQ_ACCESS_CODE')),'max_pages':50,'max_mb':30,'retention_hours':24}

class Session(BaseModel):code:str=Field(default='',max_length=200)
@app.post('/api/session')
def session(data:Session,request:Request,response:Response):
    required=os.getenv('MCQ_ACCESS_CODE','')
    if required and not hmac.compare_digest(data.code,required):raise HTTPException(403,'접속 코드를 확인하세요.')
    token=request.cookies.get('mcq_session')
    if not token or not valid_token(token):token=signed(secrets.token_hex(32))
    response.set_cookie('mcq_session',token,httponly=True,samesite='strict',secure=os.getenv('COOKIE_SECURE','false').lower()=='true',max_age=TTL)
    return {'ok':True}

@app.get('/api/projects')
def listing(request:Request):
    who=owner(request)
    with connect() as db:rows=db.execute('SELECT state FROM projects WHERE owner=? ORDER BY updated DESC',(who,)).fetchall()
    return [dict(id=p['id'],deck=p['deck'],status=p['status']) for p in map(lambda r:json.loads(r[0]),rows)]

@app.get('/api/projects/{pid}')
def get_project(pid:str,request:Request):return read(pid,owner(request))

def quota():
    with LOCK,connect() as db:
        day=time.strftime('%Y-%m-%d',time.gmtime());db.execute('INSERT OR IGNORE INTO quota VALUES(?,0)',(day,))
        used=db.execute('SELECT used FROM quota WHERE day=?',(day,)).fetchone()[0]
        if used>=int(os.getenv('OCR_DAILY_LIMIT','200')):raise ValueError('오늘의 서버 OCR 호출 한도에 도달했습니다. 수동 편집을 이용하세요.')
        db.execute('UPDATE quota SET used=used+1 WHERE day=?',(day,))

def ocr_page(path):
    url,key=credentials();parsed=urlparse(url)
    if not url or not key:raise ValueError('CLOVA OCR API가 아직 연결되지 않았습니다.')
    if parsed.scheme!='https' or not parsed.hostname or not parsed.hostname.endswith('.apigw.ntruss.com'):raise ValueError('CLOVA OCR Invoke URL 설정을 확인하세요.')
    quota()
    payload={'version':'V2','requestId':uid(),'timestamp':int(time.time()*1000),'lang':'ko','images':[{'format':'png','name':'exam','data':base64.b64encode(path.read_bytes()).decode()}]}
    try:
        with httpx.Client(timeout=60,follow_redirects=False) as client:r=client.post(url,headers={'X-OCR-SECRET':key},json=payload)
        if r.status_code!=200:raise ValueError(f'CLOVA OCR 호출 실패 (HTTP {r.status_code}). 서버 API 설정과 이용 한도를 확인하세요.')
        data=r.json()['images'][0]
        if data['inferResult']!='SUCCESS':raise ValueError('CLOVA OCR가 이미지를 인식하지 못했습니다.')
        words=[]
        for field in data.get('fields',[]):
            points=field['boundingPoly']['vertices'];xs=[p['x'] for p in points];ys=[p['y'] for p in points]
            words.append(dict(text=field['inferText'],score=field.get('inferConfidence',0),x=min(xs),y=min(ys),w=max(xs)-min(xs),h=max(ys)-min(ys)))
        return words
    except (httpx.HTTPError,KeyError,TypeError) as exc:raise ValueError('OCR 통신 또는 응답 형식 오류입니다. 잠시 후 다시 시도하세요.') from None

def run_ocr(pid):
    p=read(pid);directory=ROOT/pid;layouts=[]
    for i,page in enumerate(p['pages']):
        cache=directory/f'ocr-{i}.json'
        if cache.exists():words=json.loads(cache.read_text())
        else:
            words=ocr_page(directory/page['file']);cache.write_text(json.dumps(words,ensure_ascii=False))
        layouts.append(words);p.update(progress=round((i+1)/len(p['pages'])*90),message=f"문자 인식 · {i+1}/{len(p['pages'])}페이지");write(p)
    questions=segment(p,layouts)
    if len(questions)>300:raise ValueError('한 작업에 최대 300문제를 지원합니다.')
    for q in questions:fill_question(p,q,layouts,directory)
    p.update(questions=questions,status='ready',progress=100,message='자동 인식 완료. 원본과 대조하여 검토하세요.',revision=p['revision']+1);write(p)

def job(pid,source=None,auto=False):
    try:
        p=read(pid)
        if source:
            with RENDER_LOCK:p['pages']=render(source,ROOT/pid)
            p['questions']=[new_question([part(i)],i+1) for i in range(len(p['pages']))]
            p.update(status='ocr' if auto else 'ready',progress=20 if auto else 100,message='문자 인식 중' if auto else '수동 편집 모드 · 문제 영역과 선지를 직접 입력하세요.',revision=p['revision']+1);write(p)
            source.unlink(missing_ok=True)
        if auto:run_ocr(pid)
    except Exception as exc:
        p=read(pid);p.update(status='ready' if p['pages'] else 'error',message=str(exc) if isinstance(exc,ValueError) else '파일 처리에 실패했습니다. PDF 또는 이미지 형식을 확인하세요.',progress=100,revision=p['revision']+1);write(p)
    finally:SLOTS.release()

@app.post('/api/projects')
async def upload(request:Request,file:UploadFile=File(...),deck:str=Form('나의 MCQ 덱'),auto:bool=Form(False),consent:bool=Form(False)):
    who=owner(request)
    if len(deck)>100:raise HTTPException(400,'덱 이름은 100자 이하로 입력하세요.')
    if auto and (not consent or not all(credentials())):raise HTTPException(400,'OCR 연결과 외부 전송 동의를 확인하세요.')
    suffix=Path(file.filename or '').suffix.lower()
    if suffix not in ('.pdf','.png','.jpg','.jpeg'):raise HTTPException(400,'PDF, PNG, JPG 파일을 선택하세요.')
    with LOCK,connect() as db:
        count=db.execute('SELECT COUNT(*) FROM projects WHERE owner=?',(who,)).fetchone()[0]
        total=db.execute('SELECT COUNT(*) FROM projects').fetchone()[0]
        if count>=5 or total>=100:raise HTTPException(429,'작업 보관 한도입니다. 이전 작업을 삭제하고 다시 시도하세요.')
    if not SLOTS.acquire(False):raise HTTPException(429,'현재 처리 중인 작업이 많습니다. 잠시 후 다시 시도하세요.')
    pid=uid();directory=ROOT/pid;directory.mkdir();source=directory/('upload'+suffix)
    try:
        size=0
        with source.open('wb') as output:
            while chunk:=await file.read(1024*1024):
                size+=len(chunk)
                if size>30*1024*1024:raise HTTPException(413,'파일은 최대 30MB까지 업로드할 수 있습니다.')
                output.write(chunk)
        p=dict(id=pid,deck=deck.strip() or '나의 MCQ 덱',filename=(file.filename or 'exam')[:200],status='processing',progress=0,message='파일을 분석하고 있습니다.',pages=[],questions=[],revision=0)
        write(p,who);POOL.submit(job,pid,source,auto);return p
    except Exception:
        shutil.rmtree(directory,ignore_errors=True);SLOTS.release();raise
    finally:await file.close()

class Part(BaseModel):
    page:int=Field(ge=0,le=49)
    y0:float=Field(ge=0,lt=1);y1:float=Field(gt=0,le=1)
    x0:float=Field(ge=0,lt=1);x1:float=Field(gt=0,le=1)
    @model_validator(mode='after')
    def valid(self):
        if self.y1-self.y0<.005 or self.x1-self.x0<.01:raise ValueError('영역이 너무 작습니다.')
        return self
class Question(BaseModel):
    id:str=Field(pattern=r'^[a-f0-9]{32}$');number:str=Field(max_length=40)
    parts:list[Part]=Field(min_length=1,max_length=20)
    cut:float=Field(gt=0,lt=1)
    choices:list[str]=Field(min_length=2,max_length=10)
    answers:list[int]=Field(max_length=10)
    included:bool=True;reviewed:bool=False
    warnings:list[str]=Field(default_factory=list,max_length=30);source:str='manual'
    @model_validator(mode='after')
    def valid(self):
        if any(len(c)>10000 for c in self.choices):raise ValueError('선지 길이 제한을 초과했습니다.')
        if len(set(self.answers))!=len(self.answers) or any(i<0 or i>=len(self.choices) for i in self.answers):raise ValueError('정답 번호 오류')
        if self.reviewed and (not self.answers or any(not c.strip() for c in self.choices)):raise ValueError('선지와 정답을 먼저 입력하세요.')
        return self
class Save(BaseModel):
    revision:int;deck:str=Field(min_length=1,max_length=100);questions:list[Question]=Field(max_length=300)

def editable(p):
    if p['status'] not in ('ready','error'):raise HTTPException(409,'처리가 끝난 후 수정하세요.')

@app.put('/api/projects/{pid}')
def save(pid:str,data:Save,request:Request):
    with LOCK:
        p=read(pid,owner(request));editable(p)
        if p['revision']!=data.revision:raise HTTPException(409,'다른 화면에서 작업이 바뀌었습니다. 새로고침하세요.')
        qs=[q.model_dump() for q in data.questions]
        if len({q['id'] for q in qs})!=len(qs):raise HTTPException(400,'중복 문제 ID')
        for q in qs:
            if any(v['page']>=len(p['pages']) for v in q['parts']):raise HTTPException(400,'페이지 번호 오류')
        p.update(deck=data.deck,questions=qs,revision=p['revision']+1);write(p);return p

class OCR(BaseModel):consent:bool=False
@app.post('/api/projects/{pid}/ocr')
def rerun(pid:str,data:OCR,request:Request):
    with LOCK:
        p=read(pid,owner(request));editable(p)
        if not data.consent or not all(credentials()):raise HTTPException(400,'OCR 연결과 외부 전송 동의를 확인하세요.')
        if not p['pages']:raise HTTPException(400,'처리할 페이지가 없습니다.')
        if not SLOTS.acquire(False):raise HTTPException(429,'잠시 후 다시 시도하세요.')
        p.update(status='ocr',progress=0,message='OCR 실행 중',revision=p['revision']+1);write(p);POOL.submit(job,pid,None,True);return p

@app.get('/api/projects/{pid}/pages/{index}')
def page_image(pid:str,index:int,request:Request):
    p=read(pid,owner(request))
    if not 0<=index<len(p['pages']):raise HTTPException(404)
    return FileResponse(ROOT/pid/p['pages'][index]['file'],media_type='image/png')

@app.get('/api/projects/{pid}/questions/{qid}/image')
def question_image(pid:str,qid:str,request:Request):
    p=read(pid,owner(request));q=next((q for q in p['questions'] if q['id']==qid),None)
    if not q:raise HTTPException(404)
    try:im=compose(p,q,ROOT/pid)
    except ValueError as exc:raise HTTPException(400,str(exc))
    buf=io.BytesIO();im.save(buf,format='PNG');return Response(buf.getvalue(),media_type='image/png')

class Split(BaseModel):fraction:float=Field(gt=.01,lt=.99)
@app.post('/api/projects/{pid}/questions/{qid}/split')
def split(pid:str,qid:str,data:Split,request:Request):
    with LOCK:
        p=read(pid,owner(request));editable(p);i=next((i for i,q in enumerate(p['questions']) if q['id']==qid),None)
        if i is None:raise HTTPException(404)
        if len(p['questions'])>=300:raise HTTPException(400,'문제 수 제한')
        q=p['questions'][i];a,b=split_parts(p,q,data.fraction)
        p['questions'][i:i+1]=[new_question(a,q['number']),new_question(b,q['number']+'-2')];p['revision']+=1;write(p);return p

@app.post('/api/projects/{pid}/questions/{qid}/merge')
def merge(pid:str,qid:str,request:Request):
    with LOCK:
        p=read(pid,owner(request));editable(p);i=next((i for i,q in enumerate(p['questions']) if q['id']==qid),None)
        if i is None or i+1>=len(p['questions']):raise HTTPException(400,'합칠 다음 문제가 없습니다.')
        a,b=p['questions'][i:i+2];parts=a['parts']+b['parts']
        if len(parts)>20:raise HTTPException(400,'연결 가능한 영역은 최대 20개입니다.')
        p['questions'][i:i+2]=[new_question(parts,a['number'])];p['revision']+=1;write(p);return p

@app.post('/api/projects/{pid}/export')
def export(pid:str,request:Request):
    with LOCK:
        p=read(pid,owner(request));editable(p);target=ROOT/pid/'deck.apkg'
        try:make_apkg(p,ROOT/pid,target)
        except ValueError as exc:raise HTTPException(400,str(exc))
        return Response(target.read_bytes(),media_type='application/octet-stream',headers={'Content-Disposition':'attachment; filename="MCQ.apkg"'})

@app.delete('/api/projects/{pid}')
def delete(pid:str,request:Request):
    with LOCK:
        p=read(pid,owner(request));editable(p)
        with connect() as db:db.execute('DELETE FROM projects WHERE id=?',(pid,))
        shutil.rmtree(ROOT/pid,ignore_errors=True)
    return {'ok':True}

@app.post('/api/demo')
def demo(request:Request):
    from PIL import Image,ImageDraw,ImageFont
    who=owner(request)
    with LOCK,connect() as db:
        if db.execute('SELECT COUNT(*) FROM projects WHERE owner=?',(who,)).fetchone()[0]>=5 or db.execute('SELECT COUNT(*) FROM projects').fetchone()[0]>=100:raise HTTPException(429,'이전 작업을 삭제한 후 다시 시도하세요.')
        pid=uid();directory=ROOT/pid;directory.mkdir()
        im=Image.new('RGB',(1000,750),'white');draw=ImageDraw.Draw(im);font=ImageFont.load_default(size=27)
        lines=[(60,55,'MCQ / SAMPLE EXAM',(80,110,95)),(60,145,'1. Which action helps you remember what you learn?',(20,40,30)),(60,350,'1) Read the same page without a break',(40,50,45)),(60,420,'2) Practice active recall at spaced intervals',(30,100,170)),(60,490,'3) Skip every difficult question',(40,50,45))]
        for x,y,text,color in lines:draw.text((x,y),text,font=font,fill=color)
        im.save(directory/'page-0.png');q=new_question([part(0)],1);q.update(cut=.4,choices=['Read the same page without a break','Practice active recall at spaced intervals','Skip every difficult question'],answers=[1],warnings=['샘플입니다. 원본을 확인하고 검토 완료를 눌러보세요.'],source='sample')
        p=dict(id=pid,deck='MCQ · 첫 번째 학습 덱',filename='MCQ_sample.png',status='ready',progress=100,message='샘플 작업입니다. 실제 편집과 Anki 다운로드를 체험할 수 있습니다.',pages=[dict(index=0,width=1000,height=750,file='page-0.png')],questions=[q],revision=0)
        write(p,who);return p

STATIC=Path(os.getenv('MCQ_STATIC_DIR',str(Path(__file__).parent.parent/'frontend'/'dist')))
if STATIC.exists():app.mount('/',StaticFiles(directory=STATIC,html=True),name='frontend')
