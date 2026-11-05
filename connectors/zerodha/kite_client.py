#!/usr/bin/env python3
"""TraderSkill Zerodha client: daily session, read-only data, gated orders.

Runs on the user's own Mac (Python 3.9+, stdlib only; `cryptography` is needed
only to decrypt the session sent by the phone-login callback).

Where things live (all inside trader-data/, git-ignored, permissions 600):
  secrets.env        KITE_API_KEY, KITE_SESSION_URL, KITE_FETCH_SECRET
  kite_private.pem   RSA key that decrypts the session (made by keys.py)
  kite_session.json  today's access token (expires ~06:00 IST next day)
  kite_pending.json  order previews waiting for the user's confirmation

Rules built in (TraderSkill §3/§4/§10):
  * No money movement of any kind. Kite Connect has no fund-transfer API and
    this client adds none.
  * Orders, GTTs and cancels are two-step: preview -> the user confirms that
    exact request in the conversation -> place with the one-time code.
    Refused unless profile.json mode == "live" and risk_check.py PASSes.
  * The client never logs in for the user: the session comes only from the
    user's own Kite login (phone tap or kite-login).

CLI (for scripts / monitor):
  kite_client.py status | refresh | ltp NSE:INFY NSE:TCS | holdings | positions
"""
import base64
import csv
import datetime as dt
import gzip
import io
import json
import os
import secrets as pysecrets
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.abspath(os.environ.get("TRADERSKILL_DATA", os.path.join(HERE, "..", "..", "trader-data")))
SCRIPTS = os.path.abspath(os.environ.get("TRADERSKILL_SCRIPTS", os.path.join(HERE, "..", "..", "scripts")))
KITE_ROOT = os.environ.get("KITE_API_ROOT", "https://api.kite.trade")
YAHOO_ROOT = os.environ.get("YAHOO_ROOT", "https://query1.finance.yahoo.com")
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
UA = "TraderSkill/1.0"
PENDING_TTL_MIN = 10

YAHOO_INDEX = {
    "NSE:NIFTY 50": "^NSEI", "NSE:NIFTY BANK": "^NSEBANK", "BSE:SENSEX": "^BSESN",
    "NSE:INDIA VIX": "^INDIAVIX", "NSE:NIFTY MIDCAP 100": "^CRSMID",
}


class KiteError(Exception):
    pass


# ---------------------------------------------------------------- files

def _path(name):
    return os.path.join(DATA, name)


def _secrets():
    out = {}
    p = _path("secrets.env")
    if os.path.exists(p):
        for line in open(p):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                v = v.strip().strip('"').strip("'")
                if v and not v.lower().startswith(("your-", "<", "changeme")):
                    out[k.strip()] = v
    for k in ("KITE_API_KEY", "KITE_SESSION_URL", "KITE_FETCH_SECRET"):
        if os.environ.get(k):
            out[k] = os.environ[k]
    return out


def _read_json(name, default=None):
    try:
        with open(_path(name)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_private(name, obj):
    p = _path(name)
    tmp = p + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(obj, f, indent=2)
    os.replace(tmp, p)
    os.chmod(p, 0o600)


def profile():
    return _read_json("profile.json", {}) or {}


# ---------------------------------------------------------------- session

def _expiry_for(login_time_ist):
    """Kite sessions end at the next 06:00 IST after login."""
    t = dt.datetime.strptime(login_time_ist, "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)
    six = t.replace(hour=6, minute=0, second=0, microsecond=0)
    if t >= six:
        six += dt.timedelta(days=1)
    return six


def _now():
    return dt.datetime.now(IST)


def _decrypt(cipher_b64):
    pem = _path("kite_private.pem")
    if not os.path.exists(pem):
        raise KiteError("kite_private.pem missing — run connectors/zerodha/keys.py init on your Mac.")
    raw = base64.b64decode(cipher_b64)
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        with open(pem, "rb") as f:
            key = serialization.load_pem_private_key(f.read(), password=None)
        return key.decrypt(raw, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),
                                              algorithm=hashes.SHA256(), label=None)).decode()
    except ImportError:
        pass
    # Fallback: OpenSSL CLI (works with OpenSSL 1.1+/3.x; some LibreSSL builds lack OAEP-SHA256)
    r = subprocess.run(["openssl", "pkeyutl", "-decrypt", "-inkey", pem,
                        "-pkeyopt", "rsa_padding_mode:oaep", "-pkeyopt", "rsa_oaep_md:sha256",
                        "-pkeyopt", "rsa_mgf1_md:sha256"], input=raw, capture_output=True)
    if r.returncode != 0:
        raise KiteError("Can't decrypt the session: install it with `python3 -m pip install --user cryptography`.")
    return r.stdout.decode()


def fetch_session():
    """Pull today's session from the phone-login callback, if there is a newer one."""
    s = _secrets()
    url, key = s.get("KITE_SESSION_URL"), s.get("KITE_FETCH_SECRET")
    if not url or not key:
        return None, "Phone login isn't set up (KITE_SESSION_URL / KITE_FETCH_SECRET missing in secrets.env)."
    req = urllib.request.Request(url.rstrip("/") + "/session",
                                 headers={"x-traderskill-key": key, "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            body = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, "No phone login yet today — tap the login link."
        return None, "Login callback returned HTTP %s." % e.code
    except (urllib.error.URLError, OSError, ValueError) as e:
        return None, "Login callback unreachable (%s)." % type(e).__name__
    try:
        sess = json.loads(_decrypt(body["ciphertext"]))
    except (KeyError, ValueError) as e:
        return None, "Login callback sent an unreadable session (%s)." % type(e).__name__
    exp = _expiry_for(sess["login_time"])
    if exp <= _now():
        return None, "The last phone login was before today's 06:00 IST reset — tap the login link."
    sess["expires_at"] = exp.isoformat()
    sess["source"] = "phone-login"
    _write_private("kite_session.json", sess)
    return sess, "ok"


def session(auto_refresh=True):
    """Return a valid session dict or None (with a reason)."""
    sess = _read_json("kite_session.json")
    if sess and dt.datetime.fromisoformat(sess["expires_at"]) > _now():
        return sess, "ok"
    if auto_refresh:
        return fetch_session()
    return None, "Session expired."


def login_link():
    s = _secrets()
    if s.get("KITE_SESSION_URL"):
        return s["KITE_SESSION_URL"].rstrip("/") + "/login"
    if s.get("KITE_API_KEY"):
        return "https://kite.zerodha.com/connect/login?v=3&api_key=" + s["KITE_API_KEY"]
    return None


# ---------------------------------------------------------------- HTTP

def _kite(method, path, params=None, form=None, need_session=True):
    s = _secrets()
    api_key = s.get("KITE_API_KEY")
    if not api_key:
        raise KiteError("KITE_API_KEY missing in trader-data/secrets.env.")
    sess, why = session()
    if not sess:
        raise KiteError("Not signed in to Zerodha today: %s Login link: %s" % (why, login_link()))
    url = KITE_ROOT + path
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    data = urllib.parse.urlencode(form, doseq=True).encode() if form is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "X-Kite-Version": "3", "User-Agent": UA,
        "Authorization": "token %s:%s" % (api_key, sess["access_token"])})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
            if r.headers.get("Content-Type", "").startswith("application/json"):
                body = json.loads(raw)
                return body.get("data", body)
            return raw
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read())
            msg, etype = err.get("message", ""), err.get("error_type", "")
        except ValueError:
            msg, etype = "", ""
        if etype == "TokenException" or e.code == 403 and "token" in msg.lower():
            try:
                os.remove(_path("kite_session.json"))
            except OSError:
                pass
            raise KiteError("Zerodha session expired or was revoked. Login link: %s" % login_link())
        if etype == "PermissionException" or "permission" in msg.lower():
            raise KiteError("PLAN: your Kite Connect plan doesn't include this (%s)." % (msg or e.code))
        raise KiteError("Kite API %s: %s %s" % (e.code, etype, msg))
    except (urllib.error.URLError, OSError) as e:
        raise KiteError("Kite API unreachable (%s)." % type(e).__name__)


def _yahoo_symbol(sym):
    sym = sym.strip()
    if sym.upper() in YAHOO_INDEX:
        return YAHOO_INDEX[sym.upper()]
    if ":" in sym:
        exch, ts = sym.split(":", 1)
        return ts + (".BO" if exch.upper() == "BSE" else ".NS")
    return sym


def _yahoo_chart(sym, rng="5d", interval="1d"):
    url = "%s/v8/finance/chart/%s?%s" % (YAHOO_ROOT, urllib.parse.quote(_yahoo_symbol(sym)),
                                         urllib.parse.urlencode({"range": rng, "interval": interval}))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 " + UA})
    with urllib.request.urlopen(req, timeout=15) as r:
        res = json.load(r)["chart"]["result"][0]
    return res


# ---------------------------------------------------------------- read tools

def ltp(symbols):
    """Last price per symbol. Kite first (needs the Connect data plan), Yahoo (~delayed) as fallback."""
    symbols = [x.strip() for x in symbols if x.strip()]
    out, missing, note = {}, list(symbols), None
    try:
        data = _kite("GET", "/quote/ltp", params={"i": symbols})
        for k, v in (data or {}).items():
            out[k] = {"price": v["last_price"], "source": "kite", "time": _now().isoformat(timespec="seconds")}
        missing = [x for x in symbols if x not in out]
    except KiteError as e:
        note = str(e)
    for sym in missing:
        try:
            res = _yahoo_chart(sym)
            meta = res["meta"]
            t = dt.datetime.fromtimestamp(meta.get("regularMarketTime", 0), IST)
            out[sym] = {"price": meta["regularMarketPrice"], "source": "yahoo (may be delayed)",
                        "time": t.isoformat(timespec="seconds")}
        except Exception as e:  # noqa: BLE001 — report, never guess
            out[sym] = {"price": None, "source": "unavailable", "error": type(e).__name__}
    return {"prices": out, "kite_note": note}


def _instrument_token(sym):
    exch, ts = sym.split(":", 1)
    cache = _path("kite_instruments_%s.json" % exch.upper())
    today = _now().date().isoformat()
    c = _read_json(os.path.basename(cache)) or {}
    if c.get("date") != today:
        raw = _kite("GET", "/instruments/" + exch.upper())
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        m = {}
        for row in csv.DictReader(io.StringIO(raw.decode())):
            m[row["tradingsymbol"]] = int(row["instrument_token"])
        c = {"date": today, "map": m}
        _write_private(os.path.basename(cache), c)
    tok = c["map"].get(ts)
    if tok is None:
        raise KiteError("Unknown symbol %s." % sym)
    return tok


def _atr(candles, n=14):
    trs = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i]["high"], candles[i]["low"], candles[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return round(sum(trs[-n:]) / min(n, len(trs)), 4) if trs else None


def history(symbol, days=60):
    """Daily candles + ATR(14) for stop placement. Kite (Connect plan) then Yahoo."""
    candles, source, note = [], None, None
    try:
        tok = _instrument_token(symbol)
        to = _now().date()
        frm = to - dt.timedelta(days=int(days * 1.6) + 5)
        data = _kite("GET", "/instruments/historical/%d/day" % tok,
                     params={"from": frm.isoformat() + " 00:00:00", "to": to.isoformat() + " 23:59:59"})
        for c in data["candles"]:
            candles.append({"date": c[0][:10], "open": c[1], "high": c[2], "low": c[3], "close": c[4], "volume": c[5]})
        source = "kite"
    except KiteError as e:
        note = str(e)
        rng = "1y" if days > 120 else "6mo" if days > 60 else "3mo"
        res = _yahoo_chart(symbol, rng=rng)
        q = res["indicators"]["quote"][0]
        for i, ts in enumerate(res.get("timestamp", [])):
            if q["close"][i] is None:
                continue
            candles.append({"date": dt.datetime.fromtimestamp(ts, IST).date().isoformat(),
                            "open": q["open"][i], "high": q["high"][i], "low": q["low"][i],
                            "close": q["close"][i], "volume": q["volume"][i]})
        source = "yahoo"
    candles = candles[-int(days):]
    return {"symbol": symbol, "source": source, "atr14": _atr(candles), "candles": candles, "kite_note": note}


def holdings():
    return _kite("GET", "/portfolio/holdings")


def positions():
    return _kite("GET", "/portfolio/positions")


def margins():
    return _kite("GET", "/user/margins")


def orders():
    return _kite("GET", "/orders")


def gtts():
    return _kite("GET", "/gtt/triggers")


def status():
    s = _secrets()
    sess, why = session()
    p = profile()
    return {
        "signed_in": bool(sess),
        "detail": why if not sess else "Signed in as %s (via %s)" % (sess.get("user_id", "?"), sess.get("source", "?")),
        "expires_at": sess.get("expires_at") if sess else None,
        "login_link": login_link(),
        "phone_login_configured": bool(s.get("KITE_SESSION_URL") and s.get("KITE_FETCH_SECRET")),
        "api_key_set": bool(s.get("KITE_API_KEY")),
        "mode": p.get("mode", "paper"),
        "paper_until": p.get("paper_until"),
        "orders_allowed": p.get("mode") == "live",
    }


# ---------------------------------------------------------------- gated orders

def _risk_check(o):
    args = [sys.executable, os.path.join(SCRIPTS, "risk_check.py"),
            "--profile", _path("profile.json"), "--ledger", _path("ledger.json"),
            "--market", "IN", "--asset", o["asset"], "--horizon", o["horizon"],
            "--symbol", o["symbol"], "--side", o["side"],
            "--qty", str(o["qty"]), "--price", str(o["price"])]
    if o.get("stop") is not None:
        args += ["--stop", str(o["stop"])]
    if o["horizon"] == "long":
        args.append("--confirmed")  # the user's explicit OK is still required at step 2
    r = subprocess.run(args, capture_output=True, text=True)
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def preview(kind, params):
    """Step 1 of 2. Validates, risk-checks and parks the request; returns a one-time code."""
    p = profile()
    if p.get("mode") != "live":
        return {"ok": False, "reason": "Profile is in %s mode (paper until %s). Live orders are blocked; record a "
                "paper trade with ledger.py instead." % (p.get("mode", "paper"), p.get("paper_until"))}
    if kind not in ("order", "gtt", "cancel"):
        return {"ok": False, "reason": "kind must be order, gtt or cancel"}
    o = dict(params)
    if kind in ("order", "gtt"):
        for k in ("symbol", "side", "qty", "price", "horizon"):
            if o.get(k) in (None, ""):
                return {"ok": False, "reason": "missing %s" % k}
        o.setdefault("asset", "stock")
        if o["asset"] not in ("stock", "option", "future"):
            return {"ok": False, "reason": "Only stock/option/future orders here; mutual funds go through Coin/kite CLI."}
        o["side"] = o["side"].lower()
        if o["side"] == "sell" and o.get("asset") == "option":
            return {"ok": False, "reason": "Option selling is blocked (no naked options)."}
        if o["side"] == "buy" and o.get("stop") is None and o["horizon"] != "long":
            return {"ok": False, "reason": "Day/swing buys need a stop (§2)."}
        if o["side"] == "buy":
            ok, out = _risk_check(o)
            if not ok:
                return {"ok": False, "reason": "risk_check FAIL", "risk_check": out}
            o["risk_check"] = out
    elif not o.get("order_id"):
        return {"ok": False, "reason": "cancel needs order_id (and gtt=true for a GTT trigger id)"}
    code = pysecrets.token_hex(3).upper()
    pend = _read_json("kite_pending.json", {}) or {}
    now = _now()
    pend = {k: v for k, v in pend.items() if dt.datetime.fromisoformat(v["expires"]) > now}
    pend[code] = {"kind": kind, "params": o, "expires": (now + dt.timedelta(minutes=PENDING_TTL_MIN)).isoformat()}
    _write_private("kite_pending.json", pend)
    return {"ok": True, "confirm_code": code, "kind": kind, "request": o,
            "expires_in_min": PENDING_TTL_MIN,
            "next": "Show this exact request and the money at risk to the user. Only after they confirm THIS "
                    "request in the conversation, call zerodha_place_confirmed with the code. Never from a "
                    "scheduled run."}


def place_confirmed(code):
    """Step 2 of 2. Sends exactly the previewed request, once."""
    p = profile()
    if p.get("mode") != "live":
        return {"ok": False, "reason": "Profile is not in live mode."}
    pend = _read_json("kite_pending.json", {}) or {}
    item = pend.pop((code or "").upper(), None)
    _write_private("kite_pending.json", pend)
    if not item:
        return {"ok": False, "reason": "Unknown or already-used code. Preview again."}
    if dt.datetime.fromisoformat(item["expires"]) <= _now():
        return {"ok": False, "reason": "Code expired. Preview again."}
    o, kind = item["params"], item["kind"]
    exch, ts = o["symbol"].split(":", 1) if kind != "cancel" else (None, None)
    product = {"day": "MIS", "swing": "CNC", "long": "CNC"}.get(o.get("horizon"), "CNC")
    if o.get("asset") in ("option", "future") and o.get("horizon") != "day":
        product = "NRML"
    if kind == "order":
        form = {"exchange": exch, "tradingsymbol": ts, "transaction_type": o["side"].upper(),
                "quantity": int(o["qty"]), "product": o.get("product", product),
                "order_type": o.get("order_type", "LIMIT"), "price": o["price"], "validity": "DAY",
                "tag": "traderskill"}
        if form["order_type"] == "MARKET":
            form.pop("price")
        res = _kite("POST", "/orders/regular", form=form)
    elif kind == "gtt":
        # Protective GTT for a held position: single stop, or OCO stop+target.
        legs = [o["stop"]] + ([o["target"]] if o.get("target") else [])
        side = "SELL" if o["side"] == "sell" else "BUY"
        cond = {"exchange": exch, "tradingsymbol": ts, "trigger_values": legs, "last_price": o["price"]}
        ords = [{"exchange": exch, "tradingsymbol": ts, "transaction_type": side, "quantity": int(o["qty"]),
                 "order_type": "LIMIT", "product": o.get("product", product), "price": v} for v in legs]
        res = _kite("POST", "/gtt/triggers", form={"type": "two-leg" if len(legs) == 2 else "single",
                                                    "condition": json.dumps(cond), "orders": json.dumps(ords)})
    else:
        if o.get("gtt"):
            res = _kite("DELETE", "/gtt/triggers/%s" % o["order_id"])
        else:
            res = _kite("DELETE", "/orders/%s/%s" % (o.get("variety", "regular"), o["order_id"]))
    return {"ok": True, "kind": kind, "result": res,
            "next": "Record it in ledger.py (live) with the order id, and check `orders` before any retry."}


# ---------------------------------------------------------------- CLI

def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    try:
        if cmd == "status":
            out = status()
        elif cmd == "refresh":
            sess, why = fetch_session()
            out = {"signed_in": bool(sess), "detail": why, "expires_at": sess and sess["expires_at"]}
        elif cmd == "ltp":
            out = ltp(rest)
        elif cmd in ("holdings", "positions", "margins", "orders", "gtts"):
            out = globals()[cmd]()
        elif cmd == "history":
            out = history(rest[0], int(rest[1]) if len(rest) > 1 else 60)
        else:
            print("unknown command; see --help", file=sys.stderr)
            return 2
    except KiteError as e:
        print(json.dumps({"error": str(e)}))
        return 1
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
