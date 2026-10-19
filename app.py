# برنامج تسيير الامتحانات المكتبي - تحويل Python كامل لطبقة Electron/Node مع واجهة HTML الأصلية
import os, sys, json, time, re, base64, hashlib, platform, subprocess, shutil, gzip, hmac, uuid, zlib
from pathlib import Path
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote
import sqlite3
import db as store
import guard_engine
ROOT=Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
PORT=18764
PUBLIC_KEY='''-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEA8T+IZCm2CGEPhhxms3xorBOZh2J1fWeZBRC/5modGYc=\n-----END PUBLIC KEY-----'''
APPDATA=Path(os.getenv('APPDATA') or Path.home()/'.config')
APP=APPDATA/'guard-app'; APP.mkdir(parents=True,exist_ok=True)
DBFILE=APP/'guard.db'; STAMP=APP/'guard-app-ts'; UPDATES=APP/'updates'; UPDATES.mkdir(exist_ok=True)
RENDERER_FILES={}; renderer_version='1.0.0'; shell_version='1.0.0'
# Migrate/copy the old Electron database only when the original Python DB doesn't exist.
if not DBFILE.exists():
    candidates=[APPDATA/'guard-app'/'guard.db', APPDATA/'برنامج الحراسة'/'guard.db', Path.home()/'.config'/'guard-app'/'guard.db']
    for candidate in candidates:
        if candidate.exists() and candidate.resolve()!=DBFILE.resolve():
            shutil.copy2(candidate,DBFILE); break

def b64u(b): return base64.urlsafe_b64encode(b).decode().rstrip('=')
def unb64u(s): return base64.urlsafe_b64decode(s+'='*((4-len(s)%4)%4))
def raw_machine_id():
    try:
        if sys.platform=='win32':
            out=subprocess.check_output(['reg','query',r'HKLM\SOFTWARE\Microsoft\Cryptography','/v','MachineGuid'],text=True,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            m=re.search(r'MachineGuid\s+REG_SZ\s+(\S+)',out,re.I)
            if m:return m.group(1)
        elif sys.platform=='darwin':
            out=subprocess.check_output(['ioreg','-rd1','-c','IOPlatformExpertDevice'],text=True,stderr=subprocess.DEVNULL); m=re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"',out)
            if m:return m.group(1)
        else:
            for p in ('/etc/machine-id','/var/lib/dbus/machine-id'):
                if Path(p).exists():return Path(p).read_text().strip()
    except Exception: pass
    macs=[]
    try:
        import psutil
        macs=sorted(a.address for arr in psutil.net_if_addrs().values() for a in arr if a.family==getattr(__import__('socket'),'AF_PACKET',-1) and a.address!='00:00:00:00:00:00')
    except Exception: pass
    return '|'.join([platform.node(),platform.processor() or '',macs[0] if macs else '',platform.system().lower(),platform.machine()])
def device_id():
    h=hashlib.sha256(('guard-app-device-v1|'+raw_machine_id()).encode()).hexdigest().upper()
    return 'DEV-'+'-'.join(h[i:i+4] for i in (0,4,8,12))
def verify_code(code):
    try:
        m=re.fullmatch(r'GRD1-([A-Za-z0-9_-]+)\.([A-Za-z0-9_-]+)',re.sub(r'\s+','',str(code or '')))
        if not m:return {'ok':False,'error':'صيغة الكود غير صحيحة'}
        payload,sig=unb64u(m.group(1)),unb64u(m.group(2))
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
        load_pem_public_key(PUBLIC_KEY.encode()).verify(sig,b'GRD1|'+payload)
        typ,dev,exp,issued=payload.decode().split('|')
        if typ not in ('T','F'):return {'ok':False,'error':'نوع الكود غير معروف'}
        if dev!=device_id():return {'ok':False,'error':'هذا الكود صادر لجهاز آخر'}
        if typ=='F':return {'ok':True,'state':'full','deviceId':dev,'type':'full'}
        end=int(datetime.strptime(exp,'%Y%m%d').replace(hour=23,minute=59,second=59).timestamp()*1000)
        now=int(time.time()*1000)
        if now>end:return {'ok':True,'state':'expired','deviceId':dev,'type':'trial','expiry':exp,'daysLeft':0}
        return {'ok':True,'state':'trial','deviceId':dev,'type':'trial','expiry':exp,'daysLeft':max(1,(end-now+86399999)//86400000)}
    except Exception:return {'ok':False,'error':'الكود غير صالح (التوقيع غير صحيح)'}
def lic_status(c):
    row=c.execute('SELECT code,last_seen FROM license WHERE id=1').fetchone(); now=int(time.time()*1000); last=max(int(row['last_seen'] or 0),read_stamp())
    if not row['code']:return {'state':'none','deviceId':device_id()}
    st=verify_code(row['code'])
    if not st.get('ok'):return {'state':'none','deviceId':device_id(),'error':st.get('error')}
    if last and now+36*3600*1000<last:return {'state':'clock','deviceId':device_id(),'type':st.get('type'),'error':'تم اكتشاف تعديل في تاريخ الجهاز. أعد ضبط التاريخ الصحيح.'}
    if st.get('state') not in ('expired','clock') and now>last:
        c.execute('UPDATE license SET last_seen=? WHERE id=1',(now,)); c.commit(); write_stamp(now)
    return st
def read_stamp():
    try:return int(STAMP.read_text().strip())
    except Exception:return 0
def write_stamp(ms):
    try:STAMP.write_text(str(ms),encoding='utf-8')
    except Exception:pass

def cmpver(a,b):
    def parts(v):return [int(x) for x in (str(v).split('.')+['0','0','0'])[:3]]
    return (parts(a)>parts(b))-(parts(a)<parts(b))
def safe_rel(p):
    if not isinstance(p,str) or not p or '\\' in p or '\x00' in p or p.startswith('/') or re.match(r'^[A-Za-z]:',p):return None
    q=Path(p)
    if '..' in q.parts or q.suffix.lower() not in {'.html','.js','.css','.json','.png','.jpg','.svg','.ico','.woff','.woff2','.ttf'}:return None
    return q.as_posix()
def verify_update(text):
    try:
        m=re.fullmatch(r'GUPD1-([A-Za-z0-9_-]+)\.([A-Za-z0-9_-]+)',str(text or '').strip())
        if not m:return {'ok':False,'error':'ملف التحديث غير صالح'}
        gz,sig=unb64u(m.group(1)),unb64u(m.group(2))
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
        load_pem_public_key(PUBLIC_KEY.encode()).verify(sig,b'GUPD1|'+gz)
        pkg=json.loads(gzip.decompress(gz).decode('utf-8'))
        if not re.fullmatch(r'\d+\.\d+\.\d+',pkg.get('version','')) or not isinstance(pkg.get('files'),list):return {'ok':False,'error':'بنية التحديث غير صحيحة'}
        files=[]; total=0
        for f in pkg['files']:
            rel=safe_rel(f.get('p'))
            if not rel:return {'ok':False,'error':'مسار غير مسموح داخل التحديث'}
            data=base64.b64decode(f.get('d','')); total+=len(data)
            if total>60*1024*1024:return {'ok':False,'error':'التحديث كبير جداً'}
            files.append((rel,data))
        if not any(p=='index.html' for p,d in files):return {'ok':False,'error':'التحديث لا يحتوي index.html'}
        return {'ok':True,'version':pkg['version'],'minShell':pkg.get('minShell','0.0.0'),'files':files}
    except Exception:return {'ok':False,'error':'ملف التحديث غير موقّع من المطور أو تالف'}
def load_bundled():
    """Renderer files embedded in the EXE (no editable files on disk). Falls back to renderer/ when run from source."""
    try:
        import _renderer_pack as pk
        raw=zlib.decompress(base64.b64decode(pk.BLOB))
        if hashlib.sha256(raw).hexdigest()!=pk.DIGEST:raise RuntimeError('تلف في ملفات الواجهة')
        return {k:base64.b64decode(v) for k,v in json.loads(raw)['files'].items()}
    except ImportError:
        d=ROOT/'renderer'
        return {p.relative_to(d).as_posix():p.read_bytes() for p in d.rglob('*') if p.is_file()}
def active_renderer():
    global RENDERER_FILES,renderer_version
    files=load_bundled(); bv=json.loads(files.get('version.json',b'{}').decode('utf-8')).get('version','1.0.0')
    current=UPDATES/'current.gupd'
    try:
        if current.exists():
            v=verify_update(current.read_text(encoding='utf-8'))
            if v.get('ok') and cmpver(v['version'],bv)>0 and cmpver(shell_version,v['minShell'])>=0:
                upd=dict(v['files']); upd['version.json']=json.dumps({'version':v['version']}).encode('utf-8')
                RENDERER_FILES,renderer_version=upd,v['version']; return
    except Exception:pass
    RENDERER_FILES,renderer_version=files,bv
active_renderer()
def install_update(text):
    v=verify_update(text)
    if not v.get('ok'):return v
    if cmpver(v['version'],renderer_version)<=0:return {'ok':False,'error':f"هذا التحديث ({v['version']}) ليس أحدث من النسخة الحالية ({renderer_version})"}
    if cmpver(shell_version,v['minShell'])<0:return {'ok':False,'error':f"يتطلب هذا التحديث تثبيت النسخة الكاملة {v['minShell']} أولاً"}
    UPDATES.mkdir(exist_ok=True)
    cur=UPDATES/'current.gupd'
    if cur.exists():shutil.copy2(cur,UPDATES/'previous.gupd')
    tmp=UPDATES/'current.gupd.tmp'; tmp.write_text(text.strip(),encoding='utf-8'); tmp.replace(cur)
    active_renderer(); return {'ok':True,'version':v['version']}

PRINT_HOOK=None   # يُضبط عند تشغيل النافذة: دالة تستقبل 'portrait' أو 'landscape' وتطلق الطباعة في خيط الواجهة
MIME={'.html':'text/html; charset=utf-8','.js':'application/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.json':'application/json; charset=utf-8','.svg':'image/svg+xml','.png':'image/png','.jpg':'image/jpeg','.ico':'image/x-icon','.woff2':'font/woff2','.woff':'font/woff','.ttf':'font/ttf'}
def ctype(name):return MIME.get(Path(name).suffix.lower(),'application/octet-stream')

# حقن طبقة التخزين (SQLite عبر الخادم المحلي) ودالة الطباعة في الواجهة
SHIM_JS=r'''<script>
(function(){
function req(path,body,headers){headers=headers||{};var x=new XMLHttpRequest();x.open(body===undefined?'GET':'POST','/api/'+path,false);x.setRequestHeader('Content-Type','application/json');for(var k in headers)x.setRequestHeader(k,headers[k]);x.send(body===undefined?null:JSON.stringify(body));if(x.status>=400)throw Error(x.responseText);return JSON.parse(x.responseText)}
var g={};
g.load=function(){return req('load').value};
g.save=function(v){return req('save',v)};
g.flush=function(){};
g.kvGet=function(k){return req('kvget',undefined,{'X-KV-Key':k}).value};
g.kvSet=function(k,v){return req('kvset',{k:k,v:v}).value};
g.kvRemove=function(k){return req('kvremove',{k:k}).value};
g.checkPassword=function(p){return req('checkpw',undefined,{'X-Password':encodeURIComponent(p)}).value};
g.setPassword=function(p){return req('setpw',{p:p}).value};
g.deviceId=function(){return req('device').value};
g.licStatus=function(){return req('licstatus')};
g.licActivate=function(c){return req('activate',{code:c})};
g.updInfo=function(){return req('updinfo')};
g.updPick=function(){return new Promise(function(resolve){var i=document.createElement('input');i.type='file';i.accept='.gupd';i.onchange=async function(){if(!i.files.length)return resolve({cancelled:true});try{var t=await i.files[0].text();resolve(req('install_update',{text:t}))}catch(e){resolve({ok:false,error:'تعذّر قراءة الملف'})}};i.click()})};
g.updRestart=function(){location.reload()};
window.guardDB=g;
/* window.print لا يعمل داخل QtWebEngine: نحوّل الطلب إلى التطبيق (نافذة الطباعة / معاينة PDF) */
window.print=function(){
  var s=document.getElementById('dynamicPrintStyle'),m=s&&/size:\s*A4\s+(landscape|portrait)/.exec(s.textContent||'');
  try{var x=new XMLHttpRequest();x.open('POST','/api/print',true);x.setRequestHeader('Content-Type','application/json');x.send(JSON.stringify({orientation:m?m[1]:'portrait'}))}catch(e){}
};
})();
</script>'''

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*a):pass
    def reply(self,obj,status=200):
        raw=json.dumps(obj,ensure_ascii=False).encode('utf-8'); self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Access-Control-Allow-Origin',f'http://127.0.0.1:{PORT}'); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def body(self):
        try:return json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))) or b'{}')
        except Exception:return {}
    def do_OPTIONS(self):self.send_response(204); self.send_header('Access-Control-Allow-Origin','*'); self.send_header('Access-Control-Allow-Headers','Content-Type,X-KV-Key,X-Password'); self.send_header('Access-Control-Allow-Methods','GET,POST,OPTIONS'); self.end_headers()
    def do_GET(self):
        p=urlparse(self.path).path
        if p.startswith('/api/'):
            c=store.connect(DBFILE)
            try:
                if p=='/api/load':self.reply({'value':json.dumps(store.load_all(c),ensure_ascii=False)})
                elif p=='/api/device':self.reply({'value':device_id()})
                elif p=='/api/licstatus':self.reply(lic_status(c))
                elif p=='/api/updinfo':self.reply({'version':renderer_version,'shell':shell_version})
                elif p=='/api/kvget':
                    k=self.headers.get('X-KV-Key',''); self.reply({'value':store.get_user(c) if k=='exam_local_user' else None})
                elif p=='/api/checkpw':self.reply({'value':store.check_password(c,unquote(self.headers.get('X-Password','')))})
                else:self.reply({'error':'غير معروف'},404)
            finally:c.close()
            return
        if p.startswith('/fonts/'):
            base=(ROOT/'fonts').resolve(); fp=(base/unquote(p[len('/fonts/'):])).resolve()
            if base in fp.parents and fp.is_file():
                self.send_bytes(fp.read_bytes(),ctype(fp.name),cache=True)
            else:self.send_error(404)
            return
        rel='index.html' if p in ('/','/index.html') else unquote(p.lstrip('/'))
        data=RENDERER_FILES.get(rel)
        if data is None:self.send_error(404);return
        if rel=='index.html':
            i=data.find(b'<head>')
            if i>=0:data=data[:i+6]+SHIM_JS.encode('utf-8')+data[i+6:]
        self.send_bytes(data,ctype(rel))
    def send_bytes(self,data,content_type,cache=False):
        self.send_response(200); self.send_header('Content-Type',content_type); self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','max-age=86400' if cache else 'no-store'); self.end_headers(); self.wfile.write(data)
    def do_POST(self):
        p=urlparse(self.path).path; body=self.body(); c=store.connect(DBFILE)
        try:
            if p=='/api/save':
                try:d=json.loads(body) if isinstance(body,str) else body; store.save_all(c,d); self.reply({'value':True})
                except Exception as e:self.reply({'error':'تعذر حفظ البيانات: '+str(e)},500)
            elif p=='/api/kvset':
                if body.get('k')=='exam_local_user':store.set_user(c,str(body.get('v') or 'admin'))
                self.reply({'value':True})
            elif p=='/api/kvremove':
                if body.get('k')=='exam_local_user':store.reset_account(c)
                self.reply({'value':True})
            elif p=='/api/setpw':store.set_password(c,str(body.get('p',''))); self.reply({'value':True})
            elif p=='/api/activate':
                code=re.sub(r'\s+','',str(body.get('code',''))); st=verify_code(code)
                if st.get('ok') and st.get('state') in ('trial','full'):
                    c.execute("UPDATE license SET device_id=?,code=?,activated=1,activation_code=?,activated_at=datetime('now') WHERE id=1",(device_id(),code,code));c.commit();self.reply({'ok':True,**lic_status(c)})
                else:self.reply({'ok':False,'error':st.get('error','انتهت صلاحية هذا الكود')})
            elif p=='/api/install_update':self.reply(install_update(str(body.get('text',''))))
            elif p=='/api/guard-solve':
                try:self.reply(guard_engine.solve_batch(body))
                except Exception as e:self.reply({'ok':False,'error':'خطأ في محرك التوليد Python: '+str(e)},500)
            elif p=='/api/print':
                o='landscape' if body.get('orientation')=='landscape' else 'portrait'
                if PRINT_HOOK:PRINT_HOOK(o); self.reply({'ok':True})
                else:self.reply({'ok':False,'error':'الطباعة غير متاحة'},503)
            else:self.reply({'error':'غير معروف'},404)
        finally:c.close()

TITLE='برنامج تسيير الامتحانات'
LOGFILE=APP/'guard.log'

def setup_logging():
    """البرنامج يعمل بلا نافذة أوامر: نسجل الأخطاء في ملف guard.log بدل ضياعها."""
    try:
        if LOGFILE.exists() and LOGFILE.stat().st_size>1_000_000:LOGFILE.write_text('',encoding='utf-8')
        f=open(LOGFILE,'a',encoding='utf-8',buffering=1)
        if sys.stdout is None:sys.stdout=f
        if sys.stderr is None:sys.stderr=f
        import traceback
        def hook(t,v,tb):
            f.write(datetime.now().isoformat()+' '+''.join(traceback.format_exception(t,v,tb))+'\n')
        sys.excepthook=hook
    except Exception:pass

def run_gui(server):
    from PySide6.QtWidgets import QApplication,QMessageBox,QFileDialog,QInputDialog
    from PySide6.QtCore import QUrl,Qt,QObject,Signal,Slot,QMarginsF,QStandardPaths
    from PySide6.QtGui import QIcon,QPageLayout,QPageSize,QDesktopServices
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile,QWebEngineDownloadRequest
    from PySide6.QtPrintSupport import QPrinter,QPrintDialog
    import tempfile
    global PRINT_HOOK

    try:
        if sys.platform=='win32':
            import ctypes;ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('GuardApp.ExamManager')
    except Exception:pass
    app=QApplication(sys.argv); app.setApplicationName(TITLE); app.setApplicationDisplayName(TITLE)
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    icon=None
    for name in ('icon.ico','icon.png'):
        ic=ROOT/'assets'/name
        if ic.exists():icon=QIcon(str(ic)); break
    if icon:app.setWindowIcon(icon)

    view=QWebEngineView(); view.setWindowTitle(TITLE)
    if icon:view.setWindowIcon(icon)

    def box(kind,text,buttons,default=None,escape=None):
        """نافذة رسائل عربية بعنوان البرنامج (بدل نوافذ المتصفح التي تُظهر 127.0.0.1)."""
        m=QMessageBox(view); m.setWindowTitle(TITLE); m.setIcon(kind); m.setText(text); m.setTextFormat(Qt.TextFormat.PlainText)
        m.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        if icon:m.setWindowIcon(icon)
        made={}
        for key,(label,role) in buttons.items():made[key]=m.addButton(label,role)
        if default:m.setDefaultButton(made[default])
        if escape:m.setEscapeButton(made[escape])
        m.exec()
        clicked=m.clickedButton()
        for key,b in made.items():
            if clicked is b:return key
        return escape

    AR=QMessageBox.ButtonRole
    class AppPage(QWebEnginePage):
        def javaScriptAlert(self,origin,msg):
            box(QMessageBox.Icon.Information,msg,{'ok':('موافق',AR.AcceptRole)},default='ok',escape='ok')
        def javaScriptConfirm(self,origin,msg):
            return box(QMessageBox.Icon.Question,msg,{'ok':('موافق',AR.AcceptRole),'cancel':('إلغاء',AR.RejectRole)},default='cancel',escape='cancel')=='ok'
        def javaScriptPrompt(self,origin,msg,default):
            text,ok=QInputDialog.getText(view,TITLE,msg,text=default)
            return (bool(ok),text)
        def javaScriptConsoleMessage(self,level,message,line,source):
            try:print(f'[js:{level}] {source}:{line} {message}')
            except Exception:pass

    profile=QWebEngineProfile.defaultProfile()
    profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.NoCache)
    page=AppPage(profile,view); view.setPage(page)

    # ---------- حفظ الملفات (النسخ الاحتياطي، القوالب...) ----------
    downloads=[]
    def open_folder(p):QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(p).parent)))
    def on_download(d):
        orig=d.downloadFileName() or 'ملف'
        docs=QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation) or str(Path.home())
        path,_=QFileDialog.getSaveFileName(view,'حفظ الملف',str(Path(docs)/orig))
        if not path:d.cancel();return
        p=Path(path)
        if not p.suffix and Path(orig).suffix:p=p.with_name(p.name+Path(orig).suffix)
        d.setDownloadDirectory(str(p.parent)); d.setDownloadFileName(p.name); d.accept(); downloads.append(d)
        def state(s):
            if s==QWebEngineDownloadRequest.DownloadState.DownloadCompleted:
                r=box(QMessageBox.Icon.Information,'تم حفظ الملف بنجاح:\n'+str(p),{'open':('فتح المجلد',AR.ActionRole),'ok':('موافق',AR.AcceptRole)},default='ok',escape='ok')
                if r=='open':open_folder(p)
            elif s in (QWebEngineDownloadRequest.DownloadState.DownloadInterrupted,):
                box(QMessageBox.Icon.Warning,'تعذّر حفظ الملف.',{'ok':('موافق',AR.AcceptRole)},default='ok',escape='ok')
        d.stateChanged.connect(state)
    profile.downloadRequested.connect(on_download)

    # ---------- الطباعة ----------
    printers=[]
    def layout_for(o):
        return QPageLayout(QPageSize(QPageSize.PageSizeId.A4),QPageLayout.Orientation.Landscape if o=='landscape' else QPageLayout.Orientation.Portrait,QMarginsF(0,0,0,0))
    def pdf_done(path,ok):
        if ok:QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        else:box(QMessageBox.Icon.Warning,'تعذّر إنشاء ملف PDF للمعاينة.',{'ok':('موافق',AR.AcceptRole)},default='ok',escape='ok')
    page.pdfPrintingFinished.connect(pdf_done)
    def do_print(o):
        r=box(QMessageBox.Icon.Question,'اختر طريقة الطباعة:',{
            'print':('🖨️ طباعة على الطابعة',AR.AcceptRole),
            'pdf':('📄 معاينة / حفظ PDF',AR.ActionRole),
            'cancel':('إلغاء',AR.RejectRole)},default='print',escape='cancel')
        if r=='print':
            pr=QPrinter(QPrinter.PrinterMode.HighResolution)
            pr.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
            pr.setPageOrientation(QPageLayout.Orientation.Landscape if o=='landscape' else QPageLayout.Orientation.Portrait)
            pr.setPageMargins(QMarginsF(0,0,0,0),QPageLayout.Unit.Millimeter)
            dlg=QPrintDialog(pr,view); dlg.setWindowTitle('طباعة')
            if dlg.exec():
                printers.append(pr)
                def finished(ok):
                    if not ok:box(QMessageBox.Icon.Warning,'تعذّرت الطباعة. جرّب خيار «معاينة / حفظ PDF».',{'ok':('موافق',AR.AcceptRole)},default='ok',escape='ok')
                    if pr in printers:printers.remove(pr)
                page.print(pr,finished)
        elif r=='pdf':
            tmp=Path(tempfile.gettempdir())/f'guard-print-{int(time.time())}.pdf'
            try:
                for old in Path(tempfile.gettempdir()).glob('guard-print-*.pdf'):
                    if time.time()-old.stat().st_mtime>86400:old.unlink(missing_ok=True)
            except Exception:pass
            page.printToPdf(str(tmp),layout_for(o))

    class Bridge(QObject):
        print_requested=Signal(str)
        def __init__(self):
            super().__init__(); self.print_requested.connect(self._run)
        @Slot(str)
        def _run(self,o):
            try:do_print(o)
            except Exception:
                import traceback;traceback.print_exc()
    bridge=Bridge()
    PRINT_HOOK=lambda o:bridge.print_requested.emit(o)

    view.resize(1280,800); view.load(QUrl(f'http://127.0.0.1:{PORT}/')); view.showMaximized()
    app.aboutToQuit.connect(server.shutdown)
    return app.exec()

def main():
    setup_logging()
    c=store.connect(DBFILE)
    # Save machine ID to the original schema and create a daily backup, keeping last seven.
    c.execute('UPDATE license SET device_id=? WHERE id=1',(device_id(),));c.commit();c.close()
    try:
        day=datetime.now().strftime('%Y-%m-%d'); backups=APP/'backups';backups.mkdir(exist_ok=True); dest=backups/f'guard-{day}.db'
        if DBFILE.exists() and not dest.exists():shutil.copy2(DBFILE,dest)
        for p in sorted(backups.glob('guard-*.db'),key=lambda x:x.name,reverse=True)[7:]:p.unlink(missing_ok=True)
    except Exception:pass
    try:
        server=ThreadingHTTPServer(('127.0.0.1',PORT),Handler)
    except OSError:
        # المنفذ مشغول: غالباً نسخة أخرى من البرنامج تعمل بالفعل
        try:
            from PySide6.QtWidgets import QApplication,QMessageBox
            app=QApplication(sys.argv); QMessageBox.warning(None,TITLE,'البرنامج يعمل بالفعل.\nإن لم تظهر نافذته فأغلق العملية GuardApp.exe من «مدير المهام» ثم أعد التشغيل.')
        except Exception:pass
        return
    import threading
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        import PySide6.QtWebEngineWidgets  # noqa: F401
    except ImportError:
        print('ثبّت المتطلبات: python -m pip install -r requirements.txt');print(f'الواجهة تعمل على http://127.0.0.1:{PORT}')
        try:input('اضغط Enter للخروج...')
        except Exception:pass
        server.shutdown();return
    sys.exit(run_gui(server))
if __name__=='__main__':main()
