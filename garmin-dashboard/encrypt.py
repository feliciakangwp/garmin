"""Lock dashboard.html behind a password for publishing: writes site/index.html.

The dashboard is encrypted with AES-256-GCM (key from PBKDF2-SHA256), and the page
decrypts it in the browser once you type the password. Nothing readable is published.

    DASHBOARD_PASSWORD=... python3 encrypt.py      (needs: pip install cryptography)
"""
import base64
import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

HERE = Path(__file__).resolve().parent
ITERATIONS = 600_000

password = os.environ.get("DASHBOARD_PASSWORD", "")
if len(password) < 8:
    sys.exit("DASHBOARD_PASSWORD is missing or shorter than 8 characters; refusing to publish.")

html = (HERE / "dashboard.html").read_bytes()
salt, iv = os.urandom(16), os.urandom(12)
key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITERATIONS).derive(password.encode())
cipher = AESGCM(key).encrypt(iv, html, None)
b64 = lambda b: base64.b64encode(b).decode()

page = (HERE / "lock.html").read_text(encoding="utf-8")
page = (page.replace("__SALT__", b64(salt)).replace("__IV__", b64(iv))
            .replace("__ITER__", str(ITERATIONS)).replace("__DATA__", b64(cipher)))
out = HERE / "site"
out.mkdir(exist_ok=True)
(out / "index.html").write_text(page, encoding="utf-8")
print(f"Wrote {out / 'index.html'} (encrypted)")
