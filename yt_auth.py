"""Однократный вход в YouTube: открывает браузер, получает постоянный ключ (refresh token)
и дописывает YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN в .env (не в git).
Запуск: py -I yt_auth.py  (YT_CLIENT_ID и YT_CLIENT_SECRET уже должны быть в .env)"""
import http.server, json, secrets, sys, threading, urllib.parse, urllib.request, webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENV = HERE / ".env"
SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"


def read_env():
    d = {}
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                d[k.strip()] = v.strip()
    return d


def set_env(key, value):
    lines = ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []
    lines = [l for l in lines if not l.startswith(key + "=")] + [f"{key}={value}"]
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    env = read_env()
    cid, csec = env.get("YT_CLIENT_ID"), env.get("YT_CLIENT_SECRET")
    if not cid or not csec:
        sys.exit("В .env нет YT_CLIENT_ID / YT_CLIENT_SECRET")
    state = secrets.token_urlsafe(16)
    result = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "code" in q or "error" in q:
                result.update({k: v[0] for k, v in q.items()})
                ok = "code" in q and q.get("state", [""])[0] == state
                msg = "Готово! Окно можно закрыть." if ok else "Ошибка входа: " + q.get("error", ["?"])[0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(f"<h2 style='font-family:sans-serif'>{msg}</h2>".encode())
                threading.Thread(target=srv.shutdown).start()
            else:
                self.send_response(404); self.end_headers()

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    redirect = f"http://127.0.0.1:{srv.server_port}"
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": cid, "redirect_uri": redirect, "response_type": "code", "scope": SCOPES,
        "access_type": "offline", "prompt": "consent", "state": state})
    print("Открываю браузер. Если не открылся — откройте ссылку вручную:\n" + url, flush=True)
    webbrowser.open(url)
    srv.serve_forever()

    if result.get("state") != state or "code" not in result:
        sys.exit("Вход не удался: " + json.dumps(result, ensure_ascii=False))
    data = urllib.parse.urlencode({"code": result["code"], "client_id": cid, "client_secret": csec,
                                   "redirect_uri": redirect, "grant_type": "authorization_code"}).encode()
    tok = json.load(urllib.request.urlopen("https://oauth2.googleapis.com/token", data))
    if "refresh_token" not in tok:
        sys.exit("Google не выдал постоянный ключ: " + json.dumps(tok)[:300])
    set_env("YT_REFRESH_TOKEN", tok["refresh_token"])

    req = urllib.request.Request("https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics&mine=true",
                                 headers={"Authorization": "Bearer " + tok["access_token"]})
    ch = json.load(urllib.request.urlopen(req)).get("items", [])
    for c in ch:
        print("Канал:", c["snippet"]["title"], "| id", c["id"], "| подписчиков",
              c["statistics"].get("subscriberCount"))
        set_env("YT_CHANNEL_ID", c["id"])
    if not ch:
        print("ВНИМАНИЕ: у выбранного аккаунта нет канала — войдите под аккаунтом канала.")
    print("Ключ сохранён в .env")


if __name__ == "__main__":
    main()
