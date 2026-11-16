"""Загрузка рилсов Алины на YouTube (Shorts).
Ключи: YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN — из переменных окружения или .env.

  py -I yt_publish.py check                       — проверить доступ к каналу
  py -I yt_publish.py file VIDEO CAPTION [--privacy public|private|unlisted]
  py -I yt_publish.py next [--dry-run]            — первый рилс очереди, который ещё не на YouTube
  py -I yt_publish.py today [--dry-run]           — рилс, вышедший сегодня в Instagram (если его ещё нет на YouTube)
  py -I yt_publish.py status VIDEO_ID             — статус загруженного ролика
"""
import argparse, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
QUEUE = HERE / "queue.json"
MSK = timezone(timedelta(hours=3))
CATEGORY = "27"  # Образование


def env(name):
    v = os.environ.get(name)
    if not v and (HERE / ".env").exists():
        for line in (HERE / ".env").read_text(encoding="utf-8").splitlines():
            if line.startswith(name + "="):
                v = line.split("=", 1)[1].strip()
    if not v:
        sys.exit(f"Нет ключа {name}")
    return v


def http(url, data=None, headers=None, method=None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            body = r.read()
            return r.status, dict(r.headers), (json.loads(body) if body else {})
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"YouTube API {e.code}: {e.read().decode('utf-8', 'replace')[:800]}")


def access_token():
    data = urllib.parse.urlencode({"client_id": env("YT_CLIENT_ID"), "client_secret": env("YT_CLIENT_SECRET"),
                                   "refresh_token": env("YT_REFRESH_TOKEN"),
                                   "grant_type": "refresh_token"}).encode()
    return http("https://oauth2.googleapis.com/token", data)[2]["access_token"]


def make_meta(caption: str, privacy: str):
    lines = [l.strip() for l in caption.strip().splitlines()]
    title = re.sub(r"[<>]", "", lines[0])
    tag = " #shorts"
    title = (title[:100 - len(tag)].rstrip() + tag)
    tags = [t.lstrip("#") for t in re.findall(r"#\w+", caption)]
    return {
        "snippet": {"title": title, "description": caption.strip()[:4900], "tags": tags,
                    "categoryId": CATEGORY, "defaultLanguage": "ru", "defaultAudioLanguage": "ru"},
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False,
                   "containsSyntheticMedia": True, "embeddable": True},
    }


def upload(video: Path, caption: str, privacy="public"):
    tok = access_token()
    meta = json.dumps(make_meta(caption, privacy)).encode()
    size = video.stat().st_size
    _, h, _ = http("https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
                   meta, {"Authorization": "Bearer " + tok, "Content-Type": "application/json; charset=UTF-8",
                          "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)})
    loc = h.get("Location") or h.get("location")
    for attempt in range(1, 4):
        try:
            _, _, res = http(loc, video.read_bytes(), {"Authorization": "Bearer " + tok, "Content-Type": "video/mp4"},
                             method="PUT")
            return res
        except RuntimeError as e:
            print(f"Попытка {attempt}/3 не удалась: {e}", flush=True)
            time.sleep(20)
    raise RuntimeError("Загрузка не прошла")


def status(vid):
    tok = access_token()
    _, _, r = http(f"https://www.googleapis.com/youtube/v3/videos?part=status,snippet,processingDetails&id={vid}",
                   headers={"Authorization": "Bearer " + tok})
    return r.get("items", [{}])[0]


def tg(text):
    try:
        import subprocess
        subprocess.run([sys.executable, str(HERE / "tg_send.py"), "--caption", text], timeout=60)
    except Exception:
        pass


def main():
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["check", "file", "next", "today", "status"])
    p.add_argument("args", nargs="*")
    p.add_argument("--privacy", default="public", choices=["public", "private", "unlisted"])
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()

    if a.cmd == "check":
        tok = access_token()
        _, _, r = http("https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics&mine=true",
                       headers={"Authorization": "Bearer " + tok})
        print(json.dumps(r.get("items", []), ensure_ascii=False, indent=1)[:1500])
        return
    if a.cmd == "status":
        print(json.dumps(status(a.args[0]), ensure_ascii=False, indent=1))
        return
    if a.cmd == "file":
        video, cap = HERE / a.args[0], HERE / a.args[1]
        caption = cap.read_text(encoding="utf-8")
        if a.dry_run:
            print(json.dumps(make_meta(caption, a.privacy), ensure_ascii=False, indent=1)); return
        res = upload(video, caption, a.privacy)
        print("Загружено:", f"https://youtube.com/shorts/{res['id']}", "| доступ:", res["status"]["privacyStatus"])
        return

    q = json.loads(QUEUE.read_text(encoding="utf-8"))
    if a.cmd == "today":
        today = datetime.now(MSK).strftime("%Y-%m-%d")
        item = next((i for i in q if (i.get("published") or "").startswith(today) and not i.get("yt_id")), None)
        if not item:
            print(f"YouTube: на сегодня ({today}) загружать нечего"); return
    else:
        item = next((i for i in q if not i.get("yt_id")), None)
        if not item:
            print("В очереди нет рилсов для YouTube"); return
    caption = (HERE / item["caption"]).read_text(encoding="utf-8")
    print("YouTube:", item["video"])
    if a.dry_run:
        print(json.dumps(make_meta(caption, a.privacy), ensure_ascii=False, indent=1)); return
    try:
        res = upload(HERE / item["video"], caption, a.privacy)
    except Exception as e:
        tg(f"⚠️ YouTube Алины: загрузка не прошла ({item['video']}): {e}"[:900])
        raise
    item["yt_id"] = res["id"]
    item["yt_published"] = datetime.now(MSK).strftime("%Y-%m-%d %H:%M")
    item["yt_url"] = f"https://youtube.com/shorts/{res['id']}"
    QUEUE.write_text(json.dumps(q, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("Загружено:", item["yt_url"], "| доступ:", res["status"]["privacyStatus"])


if __name__ == "__main__":
    main()
