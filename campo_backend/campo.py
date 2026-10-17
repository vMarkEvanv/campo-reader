"""Web adapter for vMarkEvanv/campo-reader. Opt-in encrypted credentials and FAU session supports scheduled timetable and grade refresh."""
import hashlib
import getpass
import secrets
import json
import re
import os
from .credential_cipher import make_cipher, InvalidToken
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
import requests
from .console import ConsoleError
from .campo_source.core import Store, DataError, BERLIN, HOME, TIMETABLE, TRANSCRIPT, calendar_fingerprint, parse_calendar, validate_grades
from .campo_source import scripts
from . import campo_workspace as workspace
from . import campo_documents
from . import campo_courses
from . import campo_planner
from .browser import launch_browser

class SessionExpired(DataError):
    pass

class Campo:
    def __init__(self, root):
        self.root = Path(root) / 'data/campo'
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.cipher = make_cipher(self.root)
        self.public_user = getpass.getuser()
        self.csrf = secrets.token_urlsafe(32)
        self.lock = threading.RLock()
        self.jobs = {}
        self.slots = threading.BoundedSemaphore(1)

    def store(self, user):
        path = self.root / (hashlib.sha256(user.encode()).hexdigest() + '.sqlite3')
        store = Store(path)
        path.chmod(0o600)
        store.db.execute('CREATE TABLE IF NOT EXISTS web_settings (account_id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        store.db.commit()
        workspace.ensure(store)
        return store

    @staticmethod
    def preferences(store, account):
        row = store.db.execute('SELECT payload FROM web_settings WHERE account_id=?', (account,)).fetchone()
        result = {'enabled': True, 'interval_minutes': 10, 'subscription': '', 'session': '', 'reauth_required': False, 'last_attempt': 0}
        if row: result.update(json.loads(row[0]))
        return result

    @staticmethod
    def save_preferences(store, account, value):
        with store.db:
            store.db.execute('INSERT OR REPLACE INTO web_settings VALUES (?,?)', (account, json.dumps(value)))

    def remembered_credentials(self, settings):
        try:
            value=json.loads(self.cipher.decrypt(settings.get('credentials','').encode()).decode())
            if not isinstance(value.get('username'),str) or not value['username'] or not isinstance(value.get('password'),str) or not value['password']:return None
            return value
        except (InvalidToken,ValueError,TypeError,AttributeError):return None

    def settings_public(self, store, account, payload):
        settings = self.preferences(store, account)
        next_at = None
        ready = bool(settings['subscription'] and settings['session'] and not settings['reauth_required'])
        if settings['enabled'] and ready:
            next_at = max(time.time(), settings['last_attempt'] + settings['interval_minutes']*60)
        return {'enabled': settings['enabled'], 'interval_minutes': settings['interval_minutes'],
                'ready': ready, 'next_update_at': next_at,
                'credentials_saved': bool(self.remembered_credentials(settings)),
                'calendar_ready': bool(settings['subscription']),
                'grades_ready': bool(settings['session'] and not settings['reauth_required']),
                'reauth_required': settings['reauth_required'],
                'grades_updated_at': payload.get('grades_updated_at', payload.get('synced_at')),
                'calendar_updated_at': payload.get('calendar_updated_at', payload.get('synced_at'))}

    def worker(self, stop):
        while not stop.wait(15):
            try: self.tick()
            except Exception: pass  # No tokens, account labels or exceptions in logs.

    def tick(self):
        with self.lock:
            user = self.public_user
            store = self.store(user)
            try:
                for account, _ in store.list_accounts():
                    settings = self.preferences(store, account)
                    if not settings['enabled'] or not settings['subscription'] or not settings['session'] or settings['reauth_required']: continue
                    if time.time() < settings['last_attempt'] + settings['interval_minutes']*60: continue
                    if self.jobs.get((user, account), {}).get('running'): continue
                    if not self.slots.acquire(blocking=False): break
                    try:
                        url = self.cipher.decrypt(settings['subscription'].encode()).decode()
                        calendar_fingerprint(url)
                        self.restore_session(settings)
                    except (InvalidToken, DataError, ValueError):
                        self.slots.release()
                        settings.update(session='', reauth_required=True)
                        self.save_preferences(store, account, settings)
                        self.jobs[(user, account)] = {'running': False, 'message': '订阅凭证不可用，请登录并同步一次。'}
                        continue
                    try:
                        settings['last_attempt'] = time.time()
                        self.save_preferences(store, account, settings)
                        self.jobs[(user, account)] = {'running': True, 'message': '正在自动更新课表与成绩…'}
                        threading.Thread(target=self.sync, args=(user, account, None, None), daemon=True).start()
                    except Exception:
                        self.jobs.setdefault((user, account), {})['running'] = False
                        self.slots.release()
                        raise
            finally: store.close()

    def restore_session(self, settings):
        try:
            state = json.loads(self.cipher.decrypt(settings['session'].encode()).decode())
            if not isinstance(state, dict) or not isinstance(state.get('cookies'), list) or not isinstance(state.get('origins'), list):
                raise ValueError('Invalid session')
            for cookie in state['cookies']:
                domain = cookie.get('domain', '').lstrip('.')
                if not (domain == 'fau.de' or domain.endswith('.fau.de')):
                    raise ValueError('Invalid cookie origin')
            for origin in state['origins']:
                parts = urlsplit(origin.get('origin', ''))
                if parts.scheme != 'https' or not (parts.hostname == 'fau.de' or (parts.hostname or '').endswith('.fau.de')):
                    raise ValueError('Invalid storage origin')
            return state
        except (InvalidToken, ValueError, KeyError, TypeError, AttributeError):
            raise SessionExpired('登录会话不可用，请重新登录并同步。') from None

    @staticmethod
    def read_grades(page):
        if not page.evaluate(scripts.EXPAND_GRADES): raise DataError('找不到成绩展开入口。')
        deadline = time.monotonic() + 70
        last, stable_at, expansions = None, 0, 1
        while time.monotonic() < deadline:
            state = page.evaluate(scripts.STATE)
            if not state.get('logged_in'): raise SessionExpired('FAU 登录已过期，请重新登录并同步。')
            value = page.evaluate(scripts.GRADES)
            if value.get('ajax_error'): raise DataError('成绩展开失败，旧数据已保留。')
            if value.get('table_found') and value.get('columns_ok') and not value.get('ajax_pending') and value.get('quiet_ms',0) >= 600:
                if value.get('collapsed'):
                    if expansions >= 4: raise DataError('成绩未完全展开，旧数据已保留。')
                    page.evaluate(scripts.EXPAND_GRADES); expansions += 1
                elif value.get('rows') == last and time.monotonic()-stable_at >= .6:
                    return validate_grades(value)
                elif value.get('rows') != last:
                    last, stable_at = value.get('rows'), time.monotonic()
            page.wait_for_timeout(200)
        raise DataError('成绩读取超时或表格列不匹配，旧数据已保留。')

    def commit_sync(self, user, account, result, subscription, session, documents=(), credentials=None):
        # Commit one verified stage atomically, preserving every other stage.
        with self.lock:
            store = self.store(user)
            try:
                previous = store.read(account)
                if not result.get('identity') or not result.get('fingerprint') or (previous.get('fingerprint') and previous['fingerprint'] != result['fingerprint']):
                    raise DataError('当前 FAU 身份与本地账号不一致，旧数据已保留。')
                settings = self.preferences(store, account)
                if subscription is not None: settings['subscription'] = subscription
                if session is not None: settings.update(session=session, reauth_required=False, last_attempt=time.time())
                if credentials is not None:settings['credentials']=credentials
                result = dict(previous, **result)
                result['sync_revision'] = secrets.token_hex(12)
                with store.db:
                    for document in documents:
                        try: workspace.add_document(store, account, document['content'], document['title'], result.get('semester',''), document.get('category','other'), source='campo')
                        except ConsoleError:
                            result['documents_sync'] = {'checked_at':workspace.stamp(), 'message':'证明文件夹已满或文件不符合要求；原文件保留。'}
                    store.db.execute('UPDATE accounts SET payload=? WHERE id=?', (store._encode(result), account))
                    store.db.execute('INSERT OR REPLACE INTO web_settings VALUES (?,?)', (account,json.dumps(settings)))
                if (user,account) in self.jobs:
                    self.jobs[(user,account)]['data_revision'] = result['sync_revision']
            finally: store.close()

    def snapshot(self, user, account=None, lightweight=False):
        with self.lock:
            store = self.store(user)
            try:
                accounts = [{'id': key, 'label': label} for key, label in store.list_accounts()]
                if account and not any(x['id'] == account for x in accounts):
                    raise ConsoleError('账号不存在。', 404)
                if lightweight:return {'account':account,'job':dict(self.jobs.get((user,account),{}))}
                payload = store.read(account) if account else {}
                # Internal identity binding is never exposed as an API token.
                extra = workspace.snapshot(store, account, payload) if account else None
                payload.pop('fingerprint', None)
                payload.pop('study_planner', None)  # Internal catalog; UI uses resolved course credits.
                return {'accounts': accounts, 'account': account, 'data': payload, 'workspace': extra,
                        'job': dict(self.jobs.get((user, account), {})),
                        'settings': self.settings_public(store, account, payload) if account else None}
            finally:
                store.close()

    def document(self, user, account, key):
        with self.lock:
            store=self.store(user)
            try:
                try: store.read(account)
                except DataError: raise ConsoleError('账号不存在。',404) from None
                row=store.db.execute('SELECT title,content FROM documents WHERE id=? AND account_id=? AND deleted=0',(key,account)).fetchone()
                if not row:raise ConsoleError('证明文件不存在。',404)
                return row[0],bytes(row[1])
            finally:store.close()

    def action(self, user, payload):
        action, account = payload.get('action'), payload.get('id')
        with self.lock:
            store = self.store(user)
            try:
                if action == 'add':
                    if len(store.list_accounts()) >= 10:
                        raise ConsoleError('最多添加 10 个账号。')
                    label = payload.get('label')
                    if not isinstance(label, str): raise ConsoleError('请输入账号名称。')
                    account = store.add(label)
                else:
                    store.read(account)
                    if self.jobs.get((user, account), {}).get('running') and action in ('settings','delete','sync','refresh','documents-refresh','document-fetch','courses-refresh','planner-refresh','credentials-forget'):
                        raise ConsoleError('正在同步，请等待完成后再操作。', 409)
                    if action in ('courses-batch','course-save','plan-save','exam-save','exam-delete','document-upload','document-trash','document-restore','document-edit'):
                        workspace.mutate(store, account, payload)
                    elif action == 'settings':
                        minutes, enabled = payload.get('interval_minutes'), payload.get('enabled')
                        if type(minutes) is not int or not 1 <= minutes <= 1440 or type(enabled) is not bool:
                            raise ConsoleError('更新间隔需要 1–1440 分钟。')
                        settings = self.preferences(store, account)
                        settings.update(interval_minutes=minutes, enabled=enabled)
                        self.save_preferences(store, account, settings)
                    elif action == 'delete':
                        store.delete(account)
                        with store.db:
                            store.db.execute('DELETE FROM web_settings WHERE account_id=?', (account,))
                            for table in ('workspace','changes','documents'):
                                store.db.execute('DELETE FROM '+table+' WHERE account_id=?', (account,))
                        self.jobs.pop((user, account), None)
                        account = None
                    elif action == 'planner-refresh':
                        self.restore_session(self.preferences(store,account))
                        if not self.slots.acquire(blocking=False):raise ConsoleError('已有同步任务运行。',409)
                        self.jobs[(user,account)]={'running':True,'message':'正在读取 Study Planner 课程学分…'}
                        try:threading.Thread(target=self.sync_planner,args=(user,account),daemon=True).start()
                        except Exception:
                            self.jobs[(user,account)]['running']=False
                            self.slots.release()
                            raise
                    elif action == 'courses-refresh':
                        self.restore_session(self.preferences(store, account))
                        if not self.slots.acquire(blocking=False):raise ConsoleError('已有同步任务运行。',409)
                        self.jobs[(user,account)]={'running':True,'message':'正在读取课程报名…'}
                        try:threading.Thread(target=self.sync_courses,args=(user,account),daemon=True).start()
                        except Exception:
                            self.jobs[(user,account)]['running']=False
                            self.slots.release()
                            raise
                    elif action in ('documents-refresh','document-fetch'):
                        self.restore_session(self.preferences(store, account))
                        key=payload.get('document_key') if action=='document-fetch' else None
                        if key is not None and (not isinstance(key,str) or not re.fullmatch('[a-f0-9]{24}',key)):
                            raise ConsoleError('文档标识不正确。')
                        if not self.slots.acquire(blocking=False):raise ConsoleError('已有同步任务运行。',409)
                        self.jobs[(user,account)]={'running':True,'message':'正在读取 Campo Documents…'}
                        try:threading.Thread(target=self.sync_documents,args=(user,account,key,workspace.string(payload.get('term',''),80)),daemon=True).start()
                        except Exception:
                            self.jobs[(user,account)]['running']=False
                            self.slots.release()
                            raise
                    elif action == 'refresh':
                        self.restore_session(self.preferences(store, account))
                        if not self.slots.acquire(blocking=False):raise ConsoleError('已有同步任务运行。',409)
                        self.jobs[(user, account)] = {'running': True, 'message':'正在刷新课表、成绩和证明入口…'}
                        try: threading.Thread(target=self.sync,args=(user,account,None,None),daemon=True).start()
                        except Exception:
                            self.jobs[(user, account)]['running']=False
                            self.slots.release()
                            raise
                    elif action == 'credentials-forget':
                        settings=self.preferences(store,account);settings.pop('credentials',None)
                        self.save_preferences(store,account,settings)
                    elif action == 'sync':
                        remember=payload.get('remember_credentials',False)
                        use_saved=payload.get('use_saved_credentials',False)
                        if type(remember) is not bool or type(use_saved) is not bool:raise ConsoleError('账号保存选项不正确。')
                        username, password = payload.get('username'), payload.pop('password', None)
                        credentials=None
                        if use_saved:
                            saved=self.remembered_credentials(self.preferences(store,account))
                            if not saved:raise ConsoleError('没有可用的已保存账号，请重新输入。')
                            username,password=saved['username'],saved['password']
                        else:
                            credentials=''  # Unchecked means forget after successful sync.

                        if not isinstance(username, str) or not 0 < len(username.strip()) <= 128 or not isinstance(password, str) or not 0 < len(password) <= 1024:
                            raise ConsoleError('请输入 FAU 用户名和密码。')
                        if not self.slots.acquire(blocking=False):
                            raise ConsoleError('已有同步任务运行，请稍后重试。', 409)
                        if not use_saved and remember:
                            credentials=self.cipher.encrypt(json.dumps({'username':username.strip(),'password':password}).encode()).decode()
                        self.jobs[(user, account)] = {'running': True, 'message': '正在连接 Campo…'}
                        try:
                            threading.Thread(target=self.sync, args=(user, account, username.strip(), password, credentials), daemon=True).start()
                        except Exception:
                            self.jobs[(user, account)]['running'] = False
                            self.slots.release()
                            raise
                    else:
                        raise ConsoleError('不支持的操作。')
            except DataError as exc:
                raise ConsoleError(str(exc)) from None
            finally:
                store.close()
        return self.snapshot(user, account)

    def mark_expired(self,user,account):
        with self.lock:
            store=self.store(user)
            try:
                settings=self.preferences(store,account);settings.update(session='',reauth_required=True)
                self.save_preferences(store,account,settings)
            finally:store.close()

    def progress(self, user, account, message):
        with self.lock:
            self.jobs[(user, account)].update(message=message)

    def sync(self, user, account, username, password, credentials=None):
        browser = None
        start_time = time.monotonic()
        automatic = username is None
        try:
            storage_state = None
            if automatic:
                with self.lock:
                    store = self.store(user)
                    try: storage_state = self.restore_session(self.preferences(store, account))
                    finally: store.close()
            from .browser import sync_playwright
            with sync_playwright() as pw:
                browser = launch_browser(pw)
                context = browser.new_context(storage_state=storage_state) if storage_state is not None else browser.new_context()
                # Only official FAU HTTPS origins may receive requests or credentials.
                def guard(route):
                    if route.request.resource_type in ('image','font','media'):route.abort();return
                    p = urlsplit(route.request.url)
                    if p.scheme == 'https' and (p.hostname == 'fau.de' or (p.hostname or '').endswith('.fau.de')) and p.port in (None,443):
                        route.continue_()
                    else: route.abort()
                context.route('**/*', guard)
                page = context.new_page()
                page.set_default_timeout(25000)
                page.goto(HOME, wait_until='domcontentloaded')
                state = page.evaluate(scripts.STATE)
                if not state.get('logged_in'):
                    if automatic: raise SessionExpired('FAU 登录已过期，请重新登录并同步。')
                    form = page.evaluate(scripts.LOGIN_FORM)
                    if form.get('verification'):
                        raise DataError('FAU 要求额外验证，已停止自动登录。')
                    if not form.get('found'):
                        raise DataError('未找到 Campo 登录表单，页面适配需要更新。')
                    self.progress(user, account, '正在验证 FAU 账号…')
                    with page.expect_navigation(wait_until='domcontentloaded'):
                        if not page.evaluate(scripts.login_script(username, password)):
                            raise DataError('登录表单无法提交。')
                    password = None
                    state = page.evaluate(scripts.STATE)
                    if not state.get('logged_in'):
                        raise DataError('登录未成功，请核对密码；验证码或二次验证需在官方站点完成。')
                identity = state['identity']
                self.progress(user, account, '正在读取课表…')
                page.goto(TIMETABLE, wait_until='domcontentloaded')
                state = page.evaluate(scripts.STATE)
                if not state.get('logged_in'): raise SessionExpired('FAU 登录已过期，请重新登录并同步。')
                if state.get('identity') != identity:
                    raise DataError('登录身份无法确认，旧数据已保留。')
                semester = state.get('semester', '')
                if not page.evaluate(scripts.OPEN_CALENDAR): raise DataError('找不到课表导出入口。')
                deadline = time.monotonic() + 25
                url = ''
                while time.monotonic() < deadline:
                    url = page.evaluate(scripts.STATE).get('calendar_url')
                    if url: break
                    page.wait_for_timeout(200)
                fingerprint = calendar_fingerprint(url or '')
                with self.lock:
                    store = self.store(user)
                    try: previous = store.read(account)
                    finally: store.close()
                if previous.get('fingerprint') and previous['fingerprint'] != fingerprint:
                    raise DataError('此 FAU 身份与本地账号不一致，请另建账号。')
                binding = dict(identity=identity, fingerprint=fingerprint, semester=semester)
                subscription = self.cipher.encrypt(url.encode()).decode()
                saved_session = self.cipher.encrypt(json.dumps(context.storage_state()).encode()).decode()
                # Bind this verified identity before parallel stages; all later writes merge
                # against the latest committed payload rather than an old snapshot.
                self.commit_sync(user, account, binding, subscription, saved_session, credentials=credentials)
                completed, failed = [], []
                expired = False

                def verified_session():
                    current = page.evaluate(scripts.STATE)
                    if not current or not current.get('logged_in'):
                        raise SessionExpired('FAU 登录已过期，请重新登录后重试。')
                    if current.get('identity') != identity:
                        raise DataError('登录身份发生变化，已停止该项更新。')
                    return self.cipher.encrypt(json.dumps(context.storage_state()).encode()).decode()

                def publish(fields, name, session=None, documents=()):
                    now = datetime.now(BERLIN).isoformat()
                    self.commit_sync(user, account, dict(binding, synced_at=now, **fields), None, session, documents)
                    with self.lock:
                        completed.append(name)
                        self.jobs[(user,account)]['completed'] = list(completed)

                def fetch_calendar(calendar_url):
                    try:
                        data = self.calendar(calendar_url)
                        data['calendar_updated_at'] = datetime.now(BERLIN).isoformat()
                        publish(data, '课表')
                    except Exception:
                        with self.lock: failed.append('课表')

                def failure(name, exc):
                    nonlocal expired
                    failed.append(name)
                    if isinstance(exc, SessionExpired): expired = True

                with ThreadPoolExecutor(max_workers=1) as pool:
                    calendar = pool.submit(fetch_calendar, url)
                    url = ''
                    try:
                        self.progress(user, account, '正在读取成绩…')
                        page.goto(TRANSCRIPT, wait_until='domcontentloaded')
                        verified_session()
                        grades = self.read_grades(page)
                        session = verified_session()
                        publish(dict(grades=grades, grades_updated_at=datetime.now(BERLIN).isoformat()), '成绩', session)
                    except Exception as exc:
                        failure('成绩', exc)

                    timestamp = datetime.now(BERLIN).isoformat()
                    try:
                        self.progress(user, account, '正在读取课程报名…')
                        old_info = previous.get('courses_sync', {})
                        history = old_info.get('history_checked_at') or (old_info.get('checked_at','') if old_info.get('scope')=='all' else '')
                        recent = history[:10] == timestamp[:10]
                        rows, info = campo_courses.collect(page, identity, semester, current_only=recent)
                        if info.get('scope') == 'current':
                            terms = {campo_courses.term_key(t) for t in info['semesters']}
                            rows = [r for r in previous.get('courses',[]) if campo_courses.term_key(r.get('semester','')) not in terms] + rows
                            info['history_checked_at'] = history
                        else: info['history_checked_at'] = info['checked_at']
                        info.update(last_success_at=info['checked_at'],status='ok')
                        publish(dict(courses=rows, courses_sync=info), '课程报名', verified_session())
                    except Exception as exc:
                        failure('课程报名', exc)
                        info = dict(previous.get('courses_sync',{}), checked_at=workspace.stamp(), status='error', message='课程报名更新未完成，请重试。')
                        info['last_success_at'] = info.get('last_success_at') or previous.get('courses_sync',{}).get('checked_at')
                        self.commit_sync(user,account,dict(binding,courses_sync=info),None,None)

                    if previous.get('study_planner_sync',{}).get('status') == 'error' or previous.get('study_planner_sync',{}).get('checked_at','')[:10] != timestamp[:10]:
                        try:
                            self.progress(user,account,'正在更新学分…')
                            session = verified_session()
                            catalog = campo_planner.collect(context.storage_state(),identity)
                            publish(dict(study_planner=catalog,study_planner_sync={'checked_at':catalog['checked_at'],'status':'ok','message':'学分已更新'}), '学分', session)
                        except Exception as exc:
                            failure('学分', exc)
                            self.commit_sync(user,account,dict(binding,study_planner_sync=dict(previous.get('study_planner_sync',{}),checked_at=timestamp,status='error',message='学分更新未完成，请重试。')),None,None)

                    if previous.get('documents_sync',{}).get('status') == 'error' or previous.get('documents_sync',{}).get('checked_at','')[:10] != timestamp[:10]:
                        try:
                            self.progress(user,account,'正在更新证明文件…')
                            documents, info = campo_documents.collect(page,context,identity)
                            publish(dict(documents_sync=info), '证明', verified_session(), documents)
                        except Exception as exc:
                            failure('证明', exc)
                            info = dict(previous.get('documents_sync',{}),checked_at=timestamp,status='error',message='证明更新未完成，请重试。')
                            info['last_success_at'] = info.get('last_success_at') or previous.get('documents_sync',{}).get('checked_at')
                            self.commit_sync(user,account,dict(binding,documents_sync=info),None,None)
                    try: verified_session()
                    except SessionExpired: expired = True
                    except DataError: pass
                    # Only completion waits; each stage was already committed and visible.
                    calendar.result()
                if expired: self.mark_expired(user, account)
                self.commit_sync(user,account,dict(binding,sync_seconds=round(time.monotonic()-start_time,2)),None,None)
                updated = '、'.join(completed)
                missing = '、'.join(dict.fromkeys(failed))
                message = (updated+'已更新。' if updated else '') + (missing+'更新未完成，请重试。' if missing else '同步完成。')
                if expired: message += '登录已过期，请重新登录。'
                self.progress(user,account,message)
                browser.close(); browser = None
        except SessionExpired as exc:
            with self.lock:
                store = self.store(user)
                try:
                    settings = self.preferences(store, account)
                    settings.update(session='', reauth_required=True)
                    self.save_preferences(store, account, settings)
                finally: store.close()
            self.progress(user, account, str(exc) + ' 已更新的内容已保留。')
        except DataError as exc:
            self.progress(user, account, str(exc))
        except Exception:
            self.progress(user, account, '同步未完成，请检查网络后重试；已更新的内容已保留。')
        finally:
            password = None
            if browser:
                try: browser.close()
                except Exception: pass
            with self.lock: self.jobs[(user, account)]['running'] = False
            self.slots.release()

    def sync_planner(self,user,account):
        try:
            with self.lock:
                store=self.store(user)
                try:data=store.read(account);saved=self.restore_session(self.preferences(store,account))
                finally:store.close()
            catalog=campo_planner.collect(saved,data['identity'])
            with self.lock:
                store=self.store(user)
                try:
                    current=store.read(account)
                    if current.get('identity')!=data.get('identity'):raise DataError('账号身份发生变化，未保存学分。')
                    current.update(study_planner=catalog,study_planner_sync={'checked_at':catalog['checked_at'],'message':'Study Planner 学分已更新','status':'ok'})
                    with store.db:store.db.execute('UPDATE accounts SET payload=? WHERE id=?',(store._encode(current),account))
                finally:store.close()
            self.progress(user,account,'Study Planner 学分已更新；手动学分与分类保持原设置。')
        except DataError as exc:self.progress(user,account,str(exc))
        except Exception:self.progress(user,account,'Study Planner 读取未完成，原有学分与个人设置保留。')
        finally:
            with self.lock:self.jobs[(user,account)]['running']=False
            self.slots.release()

    def sync_courses(self,user,account):
        try:
            from .browser import sync_playwright
            with self.lock:
                store=self.store(user)
                try:data=store.read(account);saved=self.restore_session(self.preferences(store,account))
                finally:store.close()
            with sync_playwright() as pw:
                browser=launch_browser(pw)
                try:
                    context=browser.new_context(storage_state=saved)
                    def guard(route):
                        if route.request.resource_type in ('image','font','media'):route.abort();return
                        p=urlsplit(route.request.url)
                        if p.scheme=='https' and (p.hostname=='fau.de' or (p.hostname or '').endswith('.fau.de')) and p.port in (None,443):route.continue_()
                        else:route.abort()
                    context.route('**/*',guard)
                    page=context.new_page();page.set_default_timeout(25000)
                    courses,info=campo_courses.collect(page,data['identity'],data.get('semester',''))
                    info.update(history_checked_at=info['checked_at'],last_success_at=info['checked_at'],status='ok')
                    encrypted=self.cipher.encrypt(json.dumps(context.storage_state()).encode()).decode()
                    with self.lock:
                        store=self.store(user)
                        try:
                            current=store.read(account)
                            if current.get('identity')!=data.get('identity'):raise DataError('账号身份发生变化，未保存课程。')
                            current.update(courses=courses,courses_sync=info)
                            settings=self.preferences(store,account);settings['session']=encrypted
                            with store.db:
                                store.db.execute('UPDATE accounts SET payload=? WHERE id=?',(store._encode(current),account))
                                store.db.execute('INSERT OR REPLACE INTO web_settings VALUES (?,?)',(account,json.dumps(settings)))
                        finally:store.close()
                    self.progress(user,account,'课程报名已更新；考试意向和分组保持原设置。')
                finally:browser.close()
        except DataError as exc:
            if '登录已过期' in str(exc) or '登录会话不可用' in str(exc):self.mark_expired(user,account)
            self.progress(user,account,str(exc))
            if hasattr(exc,'schema'):
                with self.lock:self.jobs[(user,account)]['schema']=exc.schema
        except Exception:
            self.progress(user,account,'课程报名读取未完成，原有数据与个人选择保留。')
        finally:
            with self.lock:self.jobs[(user,account)]['running']=False
            self.slots.release()

    def sync_documents(self,user,account,key=None,term=""):
        try:
            from .browser import sync_playwright
            with self.lock:
                store=self.store(user)
                try:
                    data=store.read(account)
                    saved=self.restore_session(self.preferences(store,account))
                finally:store.close()
            expected=data.get('identity')
            if not expected:raise DataError('请先登录并同步课表与成绩。')
            with sync_playwright() as pw:
                browser=launch_browser(pw)
                try:
                    context=browser.new_context(storage_state=saved,accept_downloads=True)
                    def guard(route):
                        if route.request.resource_type in ('image','font','media'):route.abort();return
                        p=urlsplit(route.request.url)
                        if p.scheme=='https' and (p.hostname=='fau.de' or (p.hostname or '').endswith('.fau.de')) and p.port in (None,443):route.continue_()
                        else:route.abort()
                    context.route('**/*',guard)
                    page=context.new_page();page.set_default_timeout(25000)
                    documents,info=campo_documents.collect(page,context,expected,key,term)
                    encrypted=self.cipher.encrypt(json.dumps(context.storage_state()).encode()).decode()
                    with self.lock:
                        store=self.store(user)
                        try:
                            current=store.read(account)
                            if current.get('identity')!=expected:raise DataError('账号身份已变更，未保存文档。')
                            if 'terms' not in info and current.get('documents_sync',{}).get('terms'):
                                info['terms']=current['documents_sync']['terms']
                            current['documents_sync']=info
                            settings=self.preferences(store,account);settings['session']=encrypted
                            with store.db:
                                for doc in documents:
                                    workspace.add_document(store,account,doc['content'],doc['title'],doc.get('term') or current.get('semester',''),doc['category'],doc.get('language',''),source='campo')
                                store.db.execute('UPDATE accounts SET payload=? WHERE id=?',(store._encode(current),account))
                                store.db.execute('INSERT OR REPLACE INTO web_settings VALUES (?,?)',(account,json.dumps(settings)))
                        finally:store.close()
                    self.progress(user,account,info['message'])
                finally:browser.close()
        except DataError as exc:
            if '登录已过期' in str(exc) or '登录会话不可用' in str(exc):self.mark_expired(user,account)
            self.progress(user,account,str(exc))

        except ConsoleError as exc:
            self.progress(user,account,str(exc))
        except Exception:
            self.progress(user,account,'Documents 读取未完成；原有归档保留。请稍后重试。')
        finally:
            with self.lock:self.jobs[(user,account)]['running']=False
            self.slots.release()

    @staticmethod
    def calendar(url):
        calendar_fingerprint(url)
        with requests.get(url, timeout=(10,25), allow_redirects=False, stream=True) as response:
            if response.status_code != 200: raise DataError('Campo 日历下载失败。')
            data = bytearray(); deadline = time.monotonic()+45
            for chunk in response.iter_content(65536):
                if time.monotonic()>deadline or len(data)+len(chunk)>8_000_000: raise DataError('日历响应过大或超时。')
                data.extend(chunk)
        today = datetime.now(BERLIN).date()
        start, end = today-timedelta(days=180), today+timedelta(days=365)
        events = parse_calendar(bytes(data), start,end)
        if len(events)>20000: raise DataError('日历条目过多。')
        return {'events':events,'range_start':start.isoformat(),'range_end':end.isoformat()}
