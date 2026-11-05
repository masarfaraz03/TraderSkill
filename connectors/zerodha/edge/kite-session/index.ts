// TraderSkill — one-tap Zerodha login callback (Supabase Edge Function "kite-session").
//
//   GET /kite-session/login     -> redirects to Zerodha's own login page (you sign in + 2FA there)
//   GET /kite-session/callback  -> Zerodha redirects here with request_token; we exchange it for the
//                                  day's access token, ENCRYPT it with your Mac's public key, store
//                                  only the ciphertext, and show "Connected".
//   GET /kite-session/session   -> your Mac fetches the ciphertext (header x-traderskill-key).
//
// Never stores your password/2FA (Zerodha handles those). The plaintext token is never stored here;
// only your Mac's private key can decrypt it. Secrets KITE_API_KEY / KITE_API_SECRET are entered by
// you in the Supabase dashboard. Deploy with verify_jwt = false (Zerodha's redirect has no JWT).
import { createClient } from "npm:@supabase/supabase-js@2";
import { FETCH_SECRET_SHA256, PUBLIC_KEY_PEM } from "./config.ts";

const API_KEY = Deno.env.get("KITE_API_KEY") ?? "";
const API_SECRET = Deno.env.get("KITE_API_SECRET") ?? "";
const db = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);

const enc = new TextEncoder();
const hex = (b: ArrayBuffer) => [...new Uint8Array(b)].map((x) => x.toString(16).padStart(2, "0")).join("");
const sha256 = async (s: string) => hex(await crypto.subtle.digest("SHA-256", enc.encode(s)));

function page(title: string, body: string, status = 200) {
  const html = `<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<title>${title}</title><body style="font:17px -apple-system,system-ui,sans-serif;max-width:30em;margin:3em auto;padding:0 1em;line-height:1.5">
<h2>${title}</h2><p>${body}</p></body>`;
  return new Response(html, { status, headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } });
}

async function encryptForMac(plain: string): Promise<string> {
  const b64 = PUBLIC_KEY_PEM.replace(/-----[^-]+-----/g, "").replace(/\s+/g, "");
  const der = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  const key = await crypto.subtle.importKey("spki", der, { name: "RSA-OAEP", hash: "SHA-256" }, false, ["encrypt"]);
  const ct = await crypto.subtle.encrypt({ name: "RSA-OAEP" }, key, enc.encode(plain));
  return btoa(String.fromCharCode(...new Uint8Array(ct)));
}

function safeEqual(a: string, b: string) {
  if (a.length !== b.length) return false;
  let r = 0;
  for (let i = 0; i < a.length; i++) r |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return r === 0;
}

Deno.serve(async (req) => {
  const url = new URL(req.url);
  const route = url.pathname.replace(/\/+$/, "").split("/").pop();

  if (route === "login") {
    if (!API_KEY) return page("Not set up yet", "KITE_API_KEY secret is missing in Supabase.", 500);
    return Response.redirect(`https://kite.zerodha.com/connect/login?v=3&api_key=${encodeURIComponent(API_KEY)}`, 302);
  }

  if (route === "callback") {
    const token = url.searchParams.get("request_token");
    if (url.searchParams.get("status") !== "success" || !token) {
      return page("Login not completed", "Zerodha didn't confirm the login. Open the link again.", 400);
    }
    if (!API_KEY || !API_SECRET) return page("Not set up yet", "Kite secrets are missing in Supabase.", 500);
    const checksum = await sha256(API_KEY + token + API_SECRET);
    const r = await fetch("https://api.kite.trade/session/token", {
      method: "POST",
      headers: { "X-Kite-Version": "3", "content-type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ api_key: API_KEY, request_token: token, checksum }),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok || !j?.data?.access_token) {
      return page("Zerodha refused the login", `(${j?.error_type ?? r.status}) Open the link and try again.`, 502);
    }
    const d = j.data;
    const ciphertext = await encryptForMac(JSON.stringify({
      access_token: d.access_token, user_id: d.user_id, login_time: d.login_time,
    }));
    const { error } = await db.from("kite_session").upsert({ id: 1, ciphertext, login_time: d.login_time, updated_at: new Date().toISOString() });
    if (error) return page("Couldn't save the session", "Storage error — try again in a minute.", 500);
    return page("✅ Zerodha connected for today", `Signed in as ${d.user_id}. TraderSkill on your Mac picks it up automatically. You can close this tab.`);
  }

  if (route === "session") {
    const key = req.headers.get("x-traderskill-key") ?? "";
    if (!safeEqual(await sha256(key), FETCH_SECRET_SHA256)) return new Response("forbidden", { status: 403 });
    const { data, error } = await db.from("kite_session").select("ciphertext, login_time, updated_at").eq("id", 1).maybeSingle();
    if (error) return new Response("storage error", { status: 500 });
    if (!data) return new Response("no session", { status: 404 });
    return new Response(JSON.stringify(data), { headers: { "content-type": "application/json", "cache-control": "no-store" } });
  }

  return new Response("not found", { status: 404 });
});
