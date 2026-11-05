#!/usr/bin/env python3
"""TraderSkill Zerodha connector — a local MCP server (stdio, stdlib only).

Registered in the Claude desktop app by install.command. Cowork sessions linked
to this Mac see its tools as  mcp__remote-devices__zerodha__<tool>.

Read tools work whenever today's session exists (phone tap or kite login).
Order tools are two-step and blocked unless profile.json mode == "live".
There are no tools that move money — by design.
"""
import json
import sys
import traceback

import kite_client as kc

PROTOCOL = "2025-06-18"

SYM = {"type": "string", "description": "Kite symbol, e.g. NSE:INFY, BSE:SENSEX, NSE:NIFTY 50"}
ORDER_PROPS = {
    "symbol": SYM,
    "side": {"type": "string", "enum": ["buy", "sell"]},
    "qty": {"type": "integer", "minimum": 1},
    "price": {"type": "number", "description": "Limit price (or current price for MARKET / GTT reference)"},
    "stop": {"type": "number", "description": "Stop price (required for day/swing buys; GTT stop leg)"},
    "target": {"type": "number", "description": "Optional target (GTT OCO second leg)"},
    "horizon": {"type": "string", "enum": ["day", "swing", "long"]},
    "asset": {"type": "string", "enum": ["stock", "option", "future"], "default": "stock"},
    "order_type": {"type": "string", "enum": ["LIMIT", "MARKET"], "default": "LIMIT"},
}

TOOLS = [
    {"name": "zerodha_status",
     "description": "Zerodha session state: signed in?, expiry (~06:00 IST), the one-tap login link, mode "
                    "(paper/live). Call first. If not signed in, give the user the login link.",
     "inputSchema": {"type": "object", "properties": {}}, "annotations": {"readOnlyHint": True}},
    {"name": "zerodha_refresh_session",
     "description": "Fetch today's session from the phone-login callback right now (after the user tapped the link).",
     "inputSchema": {"type": "object", "properties": {}}, "annotations": {"readOnlyHint": True}},
    {"name": "zerodha_ltp",
     "description": "Last traded price for Indian symbols. Uses Kite (needs the Connect data plan), otherwise "
                    "Yahoo Finance (may be delayed). Each price says its source and time — never guess.",
     "inputSchema": {"type": "object", "properties": {"symbols": {"type": "array", "items": SYM, "minItems": 1}},
                     "required": ["symbols"]}, "annotations": {"readOnlyHint": True}},
    {"name": "zerodha_history",
     "description": "Daily candles plus ATR(14) for stop placement and backtests.",
     "inputSchema": {"type": "object", "properties": {"symbol": SYM,
                                                      "days": {"type": "integer", "default": 60, "maximum": 2500}},
                     "required": ["symbol"]}, "annotations": {"readOnlyHint": True}},
    {"name": "zerodha_holdings", "description": "Delivery holdings (read-only).",
     "inputSchema": {"type": "object", "properties": {}}, "annotations": {"readOnlyHint": True}},
    {"name": "zerodha_positions", "description": "Open day/net positions (read-only).",
     "inputSchema": {"type": "object", "properties": {}}, "annotations": {"readOnlyHint": True}},
    {"name": "zerodha_margins", "description": "Available cash and margins (read-only). Never move money.",
     "inputSchema": {"type": "object", "properties": {}}, "annotations": {"readOnlyHint": True}},
    {"name": "zerodha_orders", "description": "Today's orders and their status (read-only).",
     "inputSchema": {"type": "object", "properties": {}}, "annotations": {"readOnlyHint": True}},
    {"name": "zerodha_gtts", "description": "Active GTT triggers (read-only).",
     "inputSchema": {"type": "object", "properties": {}}, "annotations": {"readOnlyHint": True}},
    {"name": "zerodha_preview_order",
     "description": "STEP 1 of 2 for a LIVE order, GTT stop, or cancel. Refused unless profile mode is live; runs "
                    "TraderSkill risk_check. Returns a one-time confirm_code (10 min). Show the exact request "
                    "to the user and get their explicit OK for it. Never call from a scheduled run.",
     "inputSchema": {"type": "object", "properties": dict(
         kind={"type": "string", "enum": ["order", "gtt", "cancel"]},
         order_id={"type": "string", "description": "cancel only"},
         gtt={"type": "boolean", "description": "cancel only: order_id is a GTT trigger id"},
         **ORDER_PROPS), "required": ["kind"]},
     "annotations": {"readOnlyHint": False, "destructiveHint": False}},
    {"name": "zerodha_place_confirmed",
     "description": "STEP 2 of 2: send exactly the previewed request, once. Only after the user confirmed that "
                    "specific request in this conversation. Needs a static IP whitelisted in Kite for orders.",
     "inputSchema": {"type": "object", "properties": {"confirm_code": {"type": "string"}},
                     "required": ["confirm_code"]},
     "annotations": {"readOnlyHint": False, "destructiveHint": True}},
]


def call(name, a):
    if name == "zerodha_status":
        return kc.status()
    if name == "zerodha_refresh_session":
        sess, why = kc.fetch_session()
        return {"signed_in": bool(sess), "detail": why, "expires_at": sess and sess["expires_at"],
                "login_link": kc.login_link()}
    if name == "zerodha_ltp":
        return kc.ltp(a.get("symbols") or [])
    if name == "zerodha_history":
        return kc.history(a["symbol"], int(a.get("days", 60)))
    if name in ("zerodha_holdings", "zerodha_positions", "zerodha_margins", "zerodha_orders", "zerodha_gtts"):
        return getattr(kc, name.split("_", 1)[1])()
    if name == "zerodha_preview_order":
        a = dict(a)
        return kc.preview(a.pop("kind"), a)
    if name == "zerodha_place_confirmed":
        return kc.place_confirmed(a.get("confirm_code"))
    raise ValueError("unknown tool " + name)


def reply(id_, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": id_}
    if error:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg, default=str) + "\n")
    sys.stdout.flush()


def handle(req):
    method, id_ = req.get("method"), req.get("id")
    if id_ is None:  # notification
        return
    if method == "initialize":
        ver = (req.get("params") or {}).get("protocolVersion") or PROTOCOL
        reply(id_, {"protocolVersion": ver, "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "zerodha", "title": "TraderSkill Zerodha", "version": "1.0.0"},
                    "instructions": "TraderSkill rules apply: paper by default, risk_check before orders, user "
                                    "confirms each live order, never move money, never log in for the user."})
    elif method == "ping":
        reply(id_, {})
    elif method == "tools/list":
        reply(id_, {"tools": TOOLS})
    elif method == "tools/call":
        p = req.get("params") or {}
        try:
            out = call(p.get("name"), p.get("arguments") or {})
            reply(id_, {"content": [{"type": "text", "text": json.dumps(out, indent=2, default=str)}],
                        "isError": False})
        except kc.KiteError as e:
            reply(id_, {"content": [{"type": "text", "text": str(e)}], "isError": True})
        except Exception as e:  # noqa: BLE001
            traceback.print_exc(file=sys.stderr)
            reply(id_, {"content": [{"type": "text", "text": "%s: %s" % (type(e).__name__, e)}], "isError": True})
    elif method in ("resources/list", "prompts/list"):
        reply(id_, {method.split("/")[0]: []})
    else:
        reply(id_, error={"code": -32601, "message": "Method not found: %s" % method})


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            reply(None, error={"code": -32700, "message": "Parse error"})
            continue
        for r in (req if isinstance(req, list) else [req]):
            handle(r)


if __name__ == "__main__":
    main()
