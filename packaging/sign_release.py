"""Sign release assets in GitHub Actions; secret never enters source or artifacts."""
import base64
import os
from pathlib import Path
import sys
import tempfile
from publish_update import publish
from version import VERSION

def main():
 root=Path(__file__).resolve().parents[1]
 raw=base64.b64decode(os.environ.pop('UPDATE_SIGNING_KEY'),validate=True)
 with tempfile.TemporaryDirectory(prefix='campo-sign-') as tmp:
  key=Path(tmp)/'signing.key';key.write_bytes(raw);key.chmod(0o600)
  publish(root/'release/CampoReader-Setup-Windows-x64.exe',VERSION,(root/'packaging/release-notes.md').read_text('utf-8'),root/'release',key,root/'update-public-key.txt')
 print('Signed release manifest with the existing update key')
if __name__=='__main__':main()
