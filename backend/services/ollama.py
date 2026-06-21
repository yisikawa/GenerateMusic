import re

import requests


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


def parse_tags(raw: str) -> str:
    for line in raw.splitlines():
        line = line.strip()
        if re.match(r'^[a-z_]+(,[a-z_]+)+$', line):
            return line
    tokens = re.findall(r'[a-z_]+', raw.lower())
    return ",".join(tokens[:12]) if tokens else "pop,vocal"


def validate_lyrics(text: str) -> str:
    if "[Chorus]" not in text and "[chorus]" not in text.lower():
        text = "[Verse]\n" + text
    return text.strip()
