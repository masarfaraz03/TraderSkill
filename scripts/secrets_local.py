#!/usr/bin/env python3
"""Local-only secrets helper. Real values live in trader-data/secrets.env (git-ignored).

  secrets_local.py init  [--data trader-data]   create secrets.env from the example (if missing)
  secrets_local.py check [--data trader-data]   show which keys are set (values masked)
  secrets_local.py audit [--repo .]             fail if anything secret/personal is tracked by git

From Python:  from secrets_local import load; load("trader-data")   # sets os.environ, prints nothing
Never print, log, commit or paste secret values.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLE = os.path.join(HERE, "..", "assets", "secrets.example.env")
DUMMY = re.compile(r"^(your-|you@example|<|changeme|$)", re.I)


def parse(path):
    out = {}
    if not os.path.exists(path):
        return out
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def load(data="trader-data"):
    vals = parse(os.path.join(data, "secrets.env"))
    for k, v in vals.items():
        if v and not DUMMY.match(v):
            os.environ.setdefault(k, v)
    return sorted(k for k, v in vals.items() if v and not DUMMY.match(v))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", choices=["init", "check", "audit"])
    p.add_argument("--data", default="trader-data")
    p.add_argument("--repo", default=".")
    a = p.parse_args()
    dst = os.path.join(a.data, "secrets.env")
    if a.cmd == "init":
        os.makedirs(a.data, exist_ok=True)
        if os.path.exists(dst):
            print(f"{dst} already exists — not touched.")
        else:
            shutil.copy(EXAMPLE, dst)
            os.chmod(dst, 0o600)
            print(f"Created {dst} (permissions 600). Fill in real values in your own editor.")
    elif a.cmd == "check":
        vals = parse(dst)
        if not vals:
            print(f"No {dst}. Run: secrets_local.py init")
            return
        for k, v in vals.items():
            state = "not set" if (not v or DUMMY.match(v)) else f"set ({v[:2]}…{len(v)} chars)"
            print(f"{k:24} {state}")
    else:
        try:
            files = subprocess.check_output(["git", "-C", a.repo, "ls-files"], text=True).split()
        except Exception as e:
            sys.exit(f"git not available: {e}")
        bad = [f for f in files if f.startswith("trader-data/") or re.search(r"(^|/)(secrets?|\.env)(\.|$)", f)
               and "example" not in f]
        pat = re.compile(r"(api[_-]?key|secret|token|password)\s*[=:]\s*['\"]?(?!your-|you@|<)[A-Za-z0-9_\-]{16,}", re.I)
        email = re.compile(r"[A-Za-z0-9._%+-]+@(?!example\.|users\.noreply)[A-Za-z0-9.-]+\.[a-z]{2,}", re.I)
        hits = []
        for f in files:
            fp = os.path.join(a.repo, f)
            if not os.path.isfile(fp) or f.startswith("addons/"):
                continue
            try:
                t = open(fp, errors="ignore").read()
            except Exception:
                continue
            if pat.search(t):
                hits.append(f"{f}: looks like a real secret")
            for m in email.findall(t):
                hits.append(f"{f}: email address {m}")
        for b in bad:
            hits.append(f"{b}: private file is tracked by git")
        if hits:
            print("AUDIT FAILED:\n  " + "\n  ".join(sorted(set(hits))))
            sys.exit(2)
        print("AUDIT OK: no secrets, personal emails or private files tracked.")


if __name__ == "__main__":
    main()
