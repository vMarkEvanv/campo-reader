import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from campo_backend.campo import Campo
from campo_backend.console import ConsoleError

class CredentialsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.c=Campo(Path(self.tmp.name));self.u='alice'
        self.a=self.c.action(self.u,{'action':'add','label':'A'})['account']
        self.data={'identity':'Alice','fingerprint':'alice','events':[],'grades':[]}
        s=self.c.store(self.u);s.save(self.a,self.data);s.close()
    def prefs(self):
        s=self.c.store(self.u)
        try:return self.c.preferences(s,self.a)
        finally:s.close()
    def remember(self):
        token=self.c.cipher.encrypt(json.dumps({'username':'test-user','password':'test-password'}).encode()).decode()
        self.c.commit_sync(self.u,self.a,self.data,'subscription','session',credentials=token)
        return token
    def test_opt_in_encrypted_not_exposed(self):
        with patch('campo_backend.campo.threading.Thread') as thread:
            result=self.c.action(self.u,{'id':self.a,'action':'sync','username':'test-user','password':'test-password','remember_credentials':True})
        args=thread.call_args.kwargs['args'];token=args[-1]
        self.assertNotIn('test-password',token)
        self.assertFalse(result['settings']['credentials_saved']) # Not saved before validation.
        self.assertNotIn('test-password',json.dumps(result))
        self.c.commit_sync(self.u,self.a,self.data,'subscription','session',credentials=token)
        self.assertEqual(self.c.remembered_credentials(self.prefs())['password'],'test-password')
        result=self.c.snapshot(self.u,self.a)
        self.assertTrue(result['settings']['credentials_saved'])
        self.assertNotIn(token,json.dumps(result));self.assertNotIn('test-password',json.dumps(result))
    def test_reuse_without_password_input(self):
        self.remember()
        with patch('campo_backend.campo.threading.Thread') as thread:
            self.c.action(self.u,{'id':self.a,'action':'sync','use_saved_credentials':True})
        self.assertEqual(thread.call_args.kwargs['args'][2:4],('test-user','test-password'))
    def test_forget_preserves_existing_session(self):
        self.remember()
        result=self.c.action(self.u,{'id':self.a,'action':'credentials-forget'})
        self.assertFalse(result['settings']['credentials_saved'])
        self.assertEqual(self.prefs()['session'],'session')
        self.assertNotIn('credentials',self.prefs())
    def test_missing_saved_and_invalid_flags(self):
        with self.assertRaises(ConsoleError):self.c.action(self.u,{'id':self.a,'action':'sync','use_saved_credentials':True})
        with self.assertRaises(ConsoleError):self.c.action(self.u,{'id':self.a,'action':'sync','remember_credentials':'yes'})
    def test_default_does_not_save_and_success_can_forget(self):
        self.remember()
        with patch('campo_backend.campo.threading.Thread') as thread:
            self.c.action(self.u,{'id':self.a,'action':'sync','username':'test-user','password':'test-password'})
        self.assertEqual(thread.call_args.kwargs['args'][-1],'')
        self.c.commit_sync(self.u,self.a,self.data,'subscription','session',credentials='')
        self.assertFalse(self.c.snapshot(self.u,self.a)['settings']['credentials_saved'])
