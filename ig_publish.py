"""Публикация рилсов в Instagram @sokolova.aalina (запускается на серверах GitHub).

    python ig_publish.py check              # ключ и лимит публикаций
    python ig_publish.py list               # очередь
    python ig_publish.py next               # опубликовать следующий ролик (если сегодня ещё не было)
    python ig_publish.py next --dry-run     # показать, что выйдет, ничего не выкладывая
    python ig_publish.py next --force       # выложить, даже если сегодня уже был рилс

Очередь — queue.json: [{"video": "videos/...mp4", "caption": "captions/...txt", "published": null}, ...].
Ключ — IG_PAGE_TOKEN (бессрочный ключ страницы Alina Sokolova). Публикуем ТОЛЬКО в аккаунт Алины.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
QUEUE = ROOT / "queue.json"
API = "https://graph.facebook.com/v21.0"
IG_USER = "17841480762700707"  # @sokolova.aalina — только сюда
MSK = timezone(timedelta(hours=3))  # Москва, без перехода на летнее время


def env(name):
    val = os.environ.get(name)
    if not val and os.name == "nt":
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            val = winreg.QueryValueEx(k, name)[0]
    return val


def call(method, path, params=None, data=None, headers=None, url=None):
    params = dict(params or {})
    if not url:
        params["access_token"] = env("IG_PAGE_TOKEN")
        url = f"{API}/{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Instagram API {e.code}: {e.read().decode(errors='replace')}")


def now():
    return datetime.now(MSK)


def tg(text):
    subprocess.run([sys.executable, str(ROOT / "tg_send.py"), "--caption", text], cwd=ROOT)


def load_queue():
    return json.loads(QUEUE.read_text(encoding="utf-8"))


def save_queue(q):
    QUEUE.write_text(json.dumps(q, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def check():
    me = call("GET", IG_USER, {"fields": "username,followers_count,media_count"})
    lim = call("GET", f"{IG_USER}/content_publishing_limit", {"fields": "quota_usage,config"})
    print(json.dumps({"account": me, "limit": lim.get("data")}, ensure_ascii=False, indent=1))
    if me.get("username") != "sokolova.aalina":
        raise SystemExit("Ключ смотрит не на аккаунт Алины — стоп.")


def publish(video: Path, caption: str):
    # 1. контейнер рилса с прямой загрузкой файла (13,8 МБ проверено 13.11 — берёт без ужатия)
    c = call("POST", f"{IG_USER}/media", {
        "media_type": "REELS", "upload_type": "resumable",
        "caption": caption, "share_to_feed": "true"})
    cid, upload_url = c["id"], c["uri"]
    # 2. загрузка видео
    data = video.read_bytes()
    r = call("POST", None, url=upload_url, data=data, headers={
        "Authorization": f"OAuth {env('IG_PAGE_TOKEN')}",
        "offset": "0", "file_size": str(len(data))})
    if not r.get("success"):
        raise SystemExit(f"Загрузка не удалась: {r}")
    # 3. ждём обработки
    for _ in range(60):
        st = call("GET", cid, {"fields": "status_code,status"})
        if st.get("status_code") == "FINISHED":
            break
        if st.get("status_code") in ("ERROR", "EXPIRED"):
            raise SystemExit(f"Instagram не принял видео: {st}")
        time.sleep(10)
    else:
        raise SystemExit("Instagram слишком долго обрабатывает видео")
    # 4. публикация
    pub = call("POST", f"{IG_USER}/media_publish", {"creation_id": cid})
    media = call("GET", pub["id"], {"fields": "permalink"})
    return pub["id"], media.get("permalink")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["check", "next", "list"])
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true", help="выложить, даже если сегодня уже был рилс")
    a = p.parse_args()

    if a.cmd == "check":
        check()
        return
    q = load_queue()
    if a.cmd == "list":
        for i, it in enumerate(q, 1):
            print(i, "✓ " + it["published"] if it.get("published") else "…", it["video"])
        return

    today = now().strftime("%Y-%m-%d")
    if not a.force and any((it.get("published") or "").startswith(today) for it in q):
        print(f"Сегодня ({today}) рилс уже вышел — выходим")
        return
    item = next((it for it in q if not it.get("published")), None)
    if not item:
        print("Очередь пуста")
        if not a.dry_run:
            tg("Instagram Алины: очередь рилсов пуста, пришлите новые ролики 🙂")
        return
    video, caption = ROOT / item["video"], (ROOT / item["caption"]).read_text(encoding="utf-8").strip()
    if a.dry_run:
        print(f"Будет опубликовано: {video.name} ({video.stat().st_size / 2**20:.1f} МБ)\n---\n{caption}")
        return
    check()
    print(f"Публикую {video.name}", flush=True)
    mid, link = publish(video, caption)
    item["published"] = now().strftime("%Y-%m-%d %H:%M")
    item["media_id"], item["permalink"] = mid, link
    save_queue(q)
    left = sum(1 for it in q if not it.get("published"))
    print(f"Опубликовано: {link} (в очереди ещё {left})")
    tg(f"✅ Instagram: опубликован рилс {video.stem}\n{link}\nВ очереди ещё: {left}")


if __name__ == "__main__":
    main()
