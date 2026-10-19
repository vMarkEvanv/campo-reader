"""Platform encryption: AndroidKeyStore on phones, existing Fernet on desktop."""
import os
import sys
if hasattr(sys,'getandroidapilevel'):
    class InvalidToken(ValueError):pass
    class AndroidCipher:
        def encrypt(self,value):
            from java import jclass
            return str(jclass('io.github.vmarkevanv.camporeader.CampoApplication').instance.seal(value.decode('utf-8'))).encode('ascii')
        def decrypt(self,value):
            from java import jclass
            try:return str(jclass('io.github.vmarkevanv.camporeader.CampoApplication').instance.unseal(value.decode('ascii'))).encode('utf-8')
            except Exception:raise InvalidToken('本机凭证不可用，请重新登录。') from None
    def make_cipher(root):return AndroidCipher()
else:
    from cryptography.fernet import Fernet,InvalidToken
    def make_cipher(root):
        key=root/'calendar.key'
        if not key.exists():
            try:
                fd=os.open(key,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,'wb') as stream:stream.write(Fernet.generate_key())
            except FileExistsError:pass
        key.chmod(0o600)
        return Fernet(key.read_bytes())
