import { randomBytes } from "node:crypto";

export const dynamic = "force-dynamic";

// This handoff receives only the short-lived code. Provider tokens and the
// PKCE verifier stay on the worker; no backend secrets are deployed to Vercel.
export async function GET() {
  const nonce = randomBytes(24).toString("base64");
  const html = `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Finish connecting Coinbase · Finney</title>
<style nonce="${nonce}">
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#10121a;color:#f0f1f8;font:16px/1.6 system-ui,sans-serif}main{max-width:640px;margin:clamp(48px,12vh,128px) auto;padding:24px}h1{font-size:30px;font-weight:550;letter-spacing:-.03em;line-height:1.25;margin:0 0 24px}p{margin:0 0 20px;color:#abb1c8}strong{color:#f0f1f8}button{min-height:44px;padding:12px 18px;border:0;border-radius:8px;background:#d7d2ff;color:#201d39;font:inherit;font-weight:600;cursor:pointer}button:disabled{opacity:.5;cursor:default}button:focus-visible,textarea:focus-visible,a:focus-visible{outline:2px solid #d7d2ff;outline-offset:4px}textarea{display:block;resize:vertical;width:100%;min-height:120px;margin:12px 0 20px;padding:12px;background:#171a24;color:#f0f1f8;border:1px solid #464d66;border-radius:8px;font:14px/1.5 monospace;overflow-wrap:anywhere}a{color:#d7d2ff;text-underline-offset:4px}#status{min-height:26px;margin-top:16px}label{display:block;margin-top:24px}[hidden]{display:none!important}footer{margin-top:32px;border-top:1px solid #2d3243;padding-top:20px;font-size:14px}
</style></head><body><main>
<h1 id="heading">Finish connecting Coinbase</h1>
<p id="explanation">Your wallet connection needs one final secure handoff to Finney. No payment has been requested.</p>
<section id="handoff" hidden>
<p>Copy the temporary callback below. Paste it into the connection helper’s <strong>hidden prompt</strong>, or save it in the <strong>password-manager field</strong> agreed with your setup helper. Complete this within ten minutes of starting the connection.</p>
<button id="copy" type="button">Copy secure callback</button>
<p id="status" role="status" aria-live="polite"></p>
<details><summary>Show callback for manual copying</summary><label for="callback">Temporary callback — keep private</label><textarea id="callback" readonly spellcheck="false" autocomplete="off" autocapitalize="off"></textarea></details>
<p>Keep this value out of chat. Finney will confirm the connection after the secure handoff is processed.</p>
</section>
<footer><a href="/" rel="noreferrer">Return to Finney</a></footer>
</main><script nonce="${nonce}">
(() => {
  const callback = window.location.href;
  const url = new URL(callback);
  history.replaceState(null, "", url.pathname);
  const params = url.searchParams;
  const allowed = new Set(["code", "state", "iss"]);
  const valid = !url.hash && !params.has("error") &&
    [...params.keys()].every(key => allowed.has(key) && params.getAll(key).length === 1) &&
    Boolean(params.get("code")) && (params.get("code") || "").length <= 8192 &&
    /^[A-Za-z0-9_-]{40,128}$/.test(params.get("state") || "") &&
    (!params.has("iss") || params.get("iss") === "https://wallet-mcp.coinbase.com") && callback.length <= 16384;
  if (!valid) {
    document.getElementById("heading").textContent = "Coinbase connection not completed";
    document.getElementById("explanation").textContent = "This link has no valid authorization callback. Ask your setup helper for a fresh Coinbase connection link.";
    return;
  }
  document.getElementById("handoff").hidden = false;
  document.getElementById("callback").value = callback;
  document.getElementById("copy").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(callback);
      document.getElementById("status").textContent = "Copied. Finish the secure handoff to connect your wallet.";
    } catch {
      document.querySelector("details").open = true;
      const field = document.getElementById("callback");
      field.focus(); field.select();
      document.getElementById("status").textContent = "Copy the selected callback, then finish the secure handoff.";
    }
  });
})();
</script></body></html>`;
  return new Response(html, {
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "private, no-store, max-age=0",
      Pragma: "no-cache",
      "Referrer-Policy": "no-referrer",
      "X-Content-Type-Options": "nosniff",
      "X-Frame-Options": "DENY",
      "X-Robots-Tag": "noindex, nofollow, noarchive",
      "Content-Security-Policy": `default-src 'none'; script-src 'nonce-${nonce}'; style-src 'nonce-${nonce}'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`,
    },
  });
}
