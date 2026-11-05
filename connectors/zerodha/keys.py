#!/usr/bin/env python3
"""Make the keys for one-tap phone login (run once on your Mac; safe to re-run with --force).

  keys.py init [--force]      create kite_private.pem + KITE_FETCH_SECRET, write the PUBLIC parts
                              to trader-data/kite_edge_config.json for deploying the callback
  keys.py set-url <url>       store the callback URL as KITE_SESSION_URL in secrets.env

Prints nothing secret. The private key and fetch secret never leave trader-data/.
"""
import hashlib
import json
import os
import re
import secrets
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.abspath(os.environ.get("TRADERSKILL_DATA", os.path.join(HERE, "..", "..", "trader-data")))
ENV = os.path.join(DATA, "secrets.env")


def set_secret(name, value):
    lines = open(ENV).read().splitlines() if os.path.exists(ENV) else []
    pat = re.compile(r"^\s*%s\s*=" % re.escape(name))
    out, done = [], False
    for ln in lines:
        if pat.match(ln):
            out.append("%s=%s" % (name, value))
            done = True
        else:
            out.append(ln)
    if not done:
        out.append("%s=%s" % (name, value))
    fd = os.open(ENV + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(out) + "\n")
    os.replace(ENV + ".tmp", ENV)
    os.chmod(ENV, 0o600)


def has_secret(name):
    if not os.path.exists(ENV):
        return False
    for ln in open(ENV):
        if ln.strip().startswith(name + "="):
            v = ln.split("=", 1)[1].strip()
            return bool(v) and not v.startswith("your-")
    return False


def init(force):
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
    except ImportError:
        sys.exit("Needs the cryptography package: python3 -m pip install --user cryptography")
    os.makedirs(DATA, exist_ok=True)
    pem = os.path.join(DATA, "kite_private.pem")
    if os.path.exists(pem) and not force:
        print("kite_private.pem already exists (use --force to replace; you'd then redeploy the callback).")
    else:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        fd = os.open(pem, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption()))
        print("Created trader-data/kite_private.pem (permissions 600).")
    with open(pem, "rb") as f:
        key = serialization.load_pem_private_key(f.read(), password=None)
    pub = key.public_key().public_bytes(serialization.Encoding.PEM,
                                        serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    if force or not has_secret("KITE_FETCH_SECRET"):
        set_secret("KITE_FETCH_SECRET", secrets.token_hex(32))
        print("Stored a new KITE_FETCH_SECRET in trader-data/secrets.env.")
    if not has_secret("KITE_API_KEY"):
        set_secret("KITE_API_KEY", "your-kite-api-key")
    fetch = [ln.split("=", 1)[1].strip() for ln in open(ENV) if ln.startswith("KITE_FETCH_SECRET=")][0]
    cfg = {"public_key_pem": pub, "fetch_secret_sha256": hashlib.sha256(fetch.encode()).hexdigest()}
    cfg_path = os.path.join(DATA, "kite_edge_config.json")
    with open(cfg_path, "w") as f:
        json.dump(cfg, f, indent=2)
    print("Wrote public deploy values to trader-data/kite_edge_config.json (public key + secret hash only).")


def main(a):
    if not a or a[0] in ("-h", "--help"):
        print(__doc__)
    elif a[0] == "init":
        init("--force" in a)
    elif a[0] == "set-url" and len(a) == 2:
        set_secret("KITE_SESSION_URL", a[1].rstrip("/"))
        print("KITE_SESSION_URL saved.")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
