import re

import requests


def list_models(url: str) -> list[str]:
    resp = requests.get(f"{url}/api/tags", timeout=5)
    resp.raise_for_status()
    return [m["name"] for m in resp.json().get("models", [])]


def ollama_chat(url: str, model: str, system: str, user: str, temperature: float) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {"temperature": temperature},
    }
    resp = requests.post(f"{url}/api/chat", json=payload, timeout=120)
    resp.raise_for_status()
    return resp.json()["message"]["content"].strip()


_TAG_RE = re.compile(r'^[a-z0-9][a-z0-9&/ -]*(,[a-z0-9][a-z0-9&/ -]*)+$')
_TOKEN_RE = re.compile(r'[a-z0-9]+(?:[&/ -][a-z0-9]+)*')

def parse_tags(raw: str) -> str:
    for line in raw.splitlines():
        line = line.strip()
        if _TAG_RE.match(line):
            return line
    tokens = _TOKEN_RE.findall(raw.lower())
    return ",".join(tokens[:12]) if tokens else "pop,vocal"


def validate_lyrics(text: str) -> str:
    if "[Chorus]" not in text and "[chorus]" not in text.lower():
        text = "[Verse]\n" + text
    return text.strip()
