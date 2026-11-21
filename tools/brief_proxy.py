#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Local AI proxy for ATLAS one-line brief parsing.

The static HTML never holds an API key. Run this on the demo machine:

  python -I tools/brief_proxy.py --port 8790

Then set the script tag in src/index-atlas.html:

  <script src="brief.js" data-ai="http://127.0.0.1:8790/api/parse-brief"></script>

config.local.json (gitignored) needs:

  "ai": {
    "baseUrl": "https://api.deepseek.com/v1",
    "apiKey": "sk-...",
    "model": "deepseek-chat"
  }

Any OpenAI-compatible /chat/completions endpoint works. If the proxy is not
running or the key is missing, brief.js falls back to its offline rule parser.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
CFG = ROOT / "config.local.json"

SYSTEM_PROMPT = """你是户外媒体提案的 brief 参数解析器。只输出 JSON，不要解释、不要 Markdown。
把用户的一句话需求映射到下列字段；只输出文本中明确出现的字段，没出现就省略，不要猜。

字段与允许值：
- industryId: bank-insurance | private-hospital | food-beverage | health-supplement | theme-park
- budget: 数字，单位元，1000000–5000000
- weeks: 4 | 6
- windowId: kaimenhong（开门红/春节/Q1）| q2（春季/4-5月/Q2）| summer（暑期/7-8月）| midautumn（中秋国庆/9-10月）
- media: bus | metro | both
- radius: 1000 | 3000 | 5000（米）
- discount: 1 | 0.92

示例：
用户：银行 200 万，2027 开门红，陆家嘴 3km，地铁为主
输出：{"industryId":"bank-insurance","budget":2000000,"windowId":"kaimenhong","radius":3000,"media":"both"}

用户：医院 200 万 Q1 地铁出入口
输出：{"industryId":"private-hospital","budget":2000000,"windowId":"kaimenhong","media":"metro"}

用户：乐园 500 万 暑期 公交加地铁
输出：{"industryId":"theme-park","budget":5000000,"windowId":"summer","media":"both"}

用户：保健品 100 万 中秋 公交车身
输出：{"industryId":"health-supplement","budget":1000000,"windowId":"midautumn","media":"bus"}

不要输出价格、库存、触达等数字；这些由规则引擎计算。"""

EXPLAIN_PROMPT = """你是户外媒体公司的策略总监。下面是一份已经由规则引擎算好的方案 JSON。
请写一段 120–180 字的中文解释，回答三件事：
1) 为什么选这个锚点和半径；
2) 为什么地铁/公交是这个主次；
3) 为什么是这些线路/口。
只使用 JSON 里出现的信息；不要写任何金额、触达人次或新的数字；不要承诺效果；不要编客户、案例或媒体资源。
语气像在给客户当面讲，不要分点，不要 Markdown。只输出 JSON：{"explanation":"..."}"""


def load_ai_cfg():
    ai = {}
    if CFG.exists():
        try:
            cfg = json.loads(CFG.read_text(encoding="utf-8"))
            ai = cfg.get("ai") or {}
        except Exception:
            ai = {}
    if ai.get("baseUrl") and ai.get("apiKey") and ai.get("model"):
        return ai
    # Direct DeepSeek API key in the environment.
    ds_key = os.environ.get("DEEPSEEK_API_KEY")
    if ds_key:
        return {
            "baseUrl": "https://api.deepseek.com/v1",
            "apiKey": ds_key,
            "model": "deepseek-chat",
        }
    # Existing local LiteLLM DeepSeek gateway (see ~/.codex/deepseek-gateway).
    gw_key = os.environ.get("CODEX_DEEPSEEK_GATEWAY_KEY")
    if gw_key:
        return {
            "baseUrl": "http://127.0.0.1:4111/v1",
            "apiKey": gw_key,
            "model": "deepseek-v4-flash",
        }
    return None


def extract_json(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start:end + 1])
    raise ValueError("model did not return JSON")


def call_llm(ai, system, user, max_tokens=300, temperature=0):
    base = str(ai["baseUrl"]).rstrip("/")
    url = base if base.endswith("/chat/completions") else base + "/chat/completions"
    payload = {
        "model": ai["model"],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
    }
    req = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + str(ai["apiKey"]),
        },
        method="POST",
    )
    with urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
    return extract_json(content)


class Handler(BaseHTTPRequestHandler):
    server_version = "NewCloudBriefProxy/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("[brief-proxy] " + (fmt % args) + "\n")

    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(204, {})

    def do_GET(self):
        if self.path.rstrip("/") == "/health":
            self._send(200, {"ok": True, "configured": bool(load_ai_cfg())})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.rstrip("/")
        if path not in ("/api/parse-brief", "/api/explain"):
            self._send(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            body = json.loads(raw.decode("utf-8"))
            ai = load_ai_cfg()
            if not ai:
                self._send(501, {"error": "config.local.json 缺少 ai 配置，且环境变量无 DEEPSEEK_API_KEY"})
                return
            if path == "/api/parse-brief":
                text = str(body.get("text") or "").strip()
                if not text:
                    self._send(400, {"error": "text is required"})
                    return
                brief = call_llm(ai, SYSTEM_PROMPT, text, max_tokens=300, temperature=0)
                if isinstance(brief, dict) and set(brief.keys()) == {"brief"}:
                    brief = brief["brief"]
                self._send(200, {"brief": brief, "source": "llm"})
                return
            plan = body.get("plan")
            if not isinstance(plan, dict) or not plan:
                self._send(400, {"error": "plan is required"})
                return
            user = json.dumps(plan, ensure_ascii=False)
            result = call_llm(ai, EXPLAIN_PROMPT, user, max_tokens=500, temperature=0.2)
            explanation = ""
            if isinstance(result, dict):
                explanation = str(result.get("explanation") or "").strip()
            if not explanation:
                self._send(502, {"error": "model returned no explanation"})
                return
            self._send(200, {"explanation": explanation, "source": "llm"})
        except (HTTPError, URLError, TimeoutError) as exc:
            self._send(502, {"error": "LLM request failed: " + str(exc)})
        except Exception as exc:
            self._send(500, {"error": str(exc)})


def main():
    global CFG
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--config", default=str(CFG), help="path to config.local.json")
    args = ap.parse_args()
    CFG = Path(args.config)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ai = load_ai_cfg()
    print(f"brief proxy: http://{args.host}:{args.port}/api/parse-brief")
    print(f"explain proxy: http://{args.host}:{args.port}/api/explain")
    print("AI config:", "ok" if ai else "missing (offline rule parser will be used)")
    if ai:
        print("model:", ai.get("model"), "baseUrl:", ai.get("baseUrl"))
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
