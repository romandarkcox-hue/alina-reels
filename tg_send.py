"""Отправка результатов в Telegram-бота @alinasokol_bot.

    py tg_send.py --chat-id                      # узнать chat_id (после /start в боте)
    py tg_send.py file1.png file2.mp4 --caption "Текст"

Токен — TELEGRAM_BOT_TOKEN, получатель — TELEGRAM_CHAT_ID (переменные окружения
или реестр Windows).
"""
import argparse
import json
import mimetypes
import os
import urllib.request
import uuid
from pathlib import Path


def env(name):
    val = os.environ.get(name)
    if not val and os.name == "nt":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                val = winreg.QueryValueEx(k, name)[0]
        except FileNotFoundError:
            pass
    return val


def call(method, fields=None, files=None):
    url = f"https://api.telegram.org/bot{env('TELEGRAM_BOT_TOKEN')}/{method}"
    if not files:
        data = json.dumps(fields or {}).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    else:
        boundary = uuid.uuid4().hex
        body = bytearray()
        for k, v in (fields or {}).items():
            body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
        for k, path in files:
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"; "
                     f"filename=\"{path.name}\"\r\nContent-Type: {mime}\r\n\r\n").encode()
            body += path.read_bytes() + b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        req = urllib.request.Request(url, data=bytes(body),
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("files", nargs="*")
    p.add_argument("--caption", default="")
    p.add_argument("--doc", action="store_true", help="отправить файлом (без сжатия и превью-плеера)")
    p.add_argument("--chat-id", action="store_true", help="показать chat_id из последних сообщений боту")
    a = p.parse_args()

    if a.chat_id:
        for u in call("getUpdates").get("result", []):
            m = u.get("message") or {}
            if m:
                print(m["chat"]["id"], m["from"].get("first_name"), m.get("text"))
        return

    chat = env("TELEGRAM_CHAT_ID")
    if not chat:
        raise SystemExit("Нет TELEGRAM_CHAT_ID")
    if a.caption and not a.files:
        call("sendMessage", {"chat_id": chat, "text": a.caption})
    for i, f in enumerate(map(Path, a.files)):
        cap = a.caption if i == 0 else ""
        ext = f.suffix.lower()
        # Картинки — документом, чтобы Telegram не сжимал.
        if a.doc:
            method, field = "sendDocument", "document"
        elif ext in (".mp4", ".mov"):
            method, field = "sendVideo", "video"
        elif ext in (".mp3", ".m4a", ".ogg", ".wav"):
            method, field = "sendAudio", "audio"
        else:
            method, field = "sendDocument", "document"
        call(method, {"chat_id": chat, "caption": cap}, [(field, f)])
        print("sent", f.name)


if __name__ == "__main__":
    main()
