"""The adapter follows Campo's current JSF component ids, not flow execution keys."""

STATE = r"""
(() => {
 const avatar = document.querySelector('[id$="avatarInfobox:open"]');
 let identity = (avatar?.getAttribute('title') || avatar?.getAttribute('data-title') || avatar?.getAttribute('aria-label') || '').trim();
 identity = identity.replace(/^(My profile|Mein Profil)\s*:\s*/i, '').split(/\s+(Student|Studierende|Studierender|Friedrich-Alexander)/i)[0].trim();
 const timeout = document.getElementById('sessionTimeoutLoginForm');
 const timeoutVisible = !!timeout && !!(timeout.offsetWidth || timeout.offsetHeight || timeout.getClientRects().length);
 const termRoot = document.querySelector('[id$="anzeigeoptionen:changeTerm"]');
 const selectedOption = termRoot?.querySelector('select')?.selectedOptions?.[0];
 const termLabel = termRoot?.querySelector('.ui-selectonemenu-label');
 const semester = (selectedOption?.textContent || termLabel?.textContent || '').replace(/\s+/g,' ').trim();
 return {logged_in: !!document.querySelector('[id$="logoutLink"]') && !!identity && !timeoutVisible,
 identity, title: document.getElementById('hisinoneTitle')?.innerText || '',
 timetable: !!document.getElementById('plan'), transcript: !!document.getElementById('examsReadonly'),
 calendar_url: document.querySelector('[id$="ical:cal_add"]')?.value || '',
 semester};
})()
"""

LOGIN_FORM = r"""
(() => {
 const forms = Array.from(document.forms).filter(f => {
  const u = new URL(f.action,location.href);
  return u.protocol==='https:' && u.hostname==='www.campo.fau.de' && u.pathname==='/qisserver/rds' &&
   u.searchParams.get('category')==='auth.login' && f.querySelector('input[name="asdf"]') && f.querySelector('input[name="fdsa"]');
 });
 const verification = Array.from(document.querySelectorAll('input')).some(e => /otp|totp|captcha|verification/i.test(e.name+' '+e.id));
 return {found:forms.length>0,verification};
})()
"""

def login_script(username: str, password: str) -> str:
    import json
    # Credentials are passed only to an exact official Campo form, never printed.
    credentials = json.dumps({"username":username,"password":password}, ensure_ascii=True)
    return r"""
(() => {
 const credentials = CREDENTIALS;
 const form = Array.from(document.forms).find(f => {
  const u=new URL(f.action,location.href);
  return u.protocol==='https:' && u.hostname==='www.campo.fau.de' && u.pathname==='/qisserver/rds' &&
   u.searchParams.get('category')==='auth.login' && f.querySelector('input[name="asdf"]') && f.querySelector('input[name="fdsa"]');
 });
 if(!form || location.protocol!=='https:' || location.hostname!=='www.campo.fau.de')return false;
 const user=form.querySelector('input[name="asdf"]'), pass=form.querySelector('input[name="fdsa"]');
 user.value=credentials.username;pass.value=credentials.password;
 for(const el of [user,pass]) {el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));}
 setTimeout(() => HTMLFormElement.prototype.submit.call(form), 0);
 return true;
})()
""".replace("CREDENTIALS", credentials)

OPEN_CALENDAR = r"""
(() => { const b = document.querySelector('[id$="ical:showPopup"]'); if(!b) return false; b.click(); return true; })()
"""

EXPAND_GRADES = r"""
(() => {
 const b=document.querySelector('[id$="tree:expandAll2"]');if(!b)return false;
 if(!window.__campoReaderGradeWatch){
  const watch={pending:0,lastMutation:performance.now(),error:false};
  window.__campoReaderGradeWatch=watch;
  const ajax=window.jsf?.ajax || window.faces?.ajax;
  if(ajax?.addOnEvent){
   ajax.addOnEvent(event => {
    if(event.status==='begin')watch.pending++;
    if(event.status==='success'){watch.pending=Math.max(0,watch.pending-1);watch.lastMutation=performance.now();}
   });
   ajax.addOnError?.(() => {watch.pending=0;watch.error=true;});
  }
  const root=document.getElementById('examsReadonly');
  if(root){watch.observer=new MutationObserver(() => {watch.lastMutation=performance.now();});watch.observer.observe(root,{subtree:true,childList:true,characterData:true});}
 }
 const watch=window.__campoReaderGradeWatch;
 if(watch.pending)return 'pending';
 watch.lastMutation=performance.now();watch.error=false;b.click();return true;
})()
"""

GRADES = r"""
(() => {
 const root = document.getElementById('examsReadonly:overviewAsTreeReadonly:collapsiblePanel');
 const table = root?.querySelector('table.treeTableWithIcons');
 if (!table) return {table_found:false};
 const clean = el => (el?.innerText || '').replace(/\s+/g, ' ').trim();
 const rows = Array.from(table.rows);
 const header = rows.find(r => Array.from(r.cells).some(c => c.tagName === 'TH'));
 if (!header) return {table_found:true,columns_ok:false};
 let width = 0;
 const headers = Array.from(header.cells).map(c => {const h={text:clean(c).toLowerCase(),start:width,width:c.colSpan||1};width+=h.width;return h;});
 const aliases = {
  name:['degree','abschluss','bezeichnung','abschluss / fach'],number:['number','nummer'],
  grade:['grade','note'],status:['status'],credits:['ects credits','ects-punkte','ects','ects credits/points'],
  attempt:['attempt','versuch'],released:['grade release date','datum der notenfreigabe','notenfreigabedatum'],
  annotation:['annotation','vermerk']
 };
 const columns={};
 for(const [key,names] of Object.entries(aliases)){const h=headers.find(h=>names.includes(h.text));if(h)columns[key]=h;}
 const degree=headers.find(h=>h.width>1);
 if (degree) columns.name=degree;
 if (!['name','grade','status','credits','number'].every(k=>columns[k])) return {table_found:true,columns_ok:false};
 let program='';
 const records=[];
 for(const row of rows){
  if(row===header || !row.cells.length)continue;
  const cells=[];
  for(const cell of Array.from(row.cells)) for(let i=0;i<(cell.colSpan||1);i++)cells.push(cell);
  const read = key => {
   const h=columns[key]; if(!h)return '';
   if(key==='name'){
    const unique=[...new Set(cells.slice(h.start,h.start+h.width))];
    return unique.map(c=>clean(c.querySelector('[id$=":defaulttext"]'))||clean(c)).filter(Boolean).join(' ');
   }
   return clean(cells[h.start]);
  };
  const name=read('name'); if(!name)continue;
  const nameCells=[...new Set(cells.slice(columns.name.start,columns.name.start+columns.name.width))];
  const icon=nameCells.flatMap(c=>Array.from(c.querySelectorAll('img'))).find(img=>!/^Endknoten/i.test(img.alt||''));
  const alt=(icon?.alt||'').toLowerCase(), src=(icon?.getAttribute('src')||'').toLowerCase();
  let kind='group';
  if(alt==='module'||alt==='modul'||/\/module?\./.test(src))kind='module';
  else if(alt==='examination'||alt==='prüfung'||/exam|medal/.test(src))kind='exam';
  else if(alt.includes('regulations')||alt.includes('ordnung')||/\/book\./.test(src))kind='program';
  if(kind==='program')program=name;
  const record={name,kind,program,level:clean(row.cells[0])};
  for(const key of ['number','grade','status','credits','attempt','released','annotation'])record[key]=read(key);
  records.push(record);
 }
 const watch=window.__campoReaderGradeWatch;
 return {table_found:true,columns_ok:true,rows:records,
 ajax_pending:(watch?.pending||0)>0,ajax_error:watch?.error||false,
 quiet_ms:watch?performance.now()-watch.lastMutation:0,
 collapsed: table.querySelectorAll('button[aria-expanded="false"]').length};
})()
"""
