#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
doubao_proxy_server.py
本地代理：解决浏览器 CORS 限制，并把豆包调用放到本地进程里执行。
"""
import os, json, re, argparse
from flask import Flask, request, jsonify, make_response
from openai import OpenAI

app = Flask(__name__)

def client_for(key: str):
    return OpenAI(base_url="https://ark.cn-beijing.volces.com/api/v3", api_key=key)

@app.after_request
def add_cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    return resp

@app.route("/doubao", methods=["POST", "OPTIONS"])
def doubao():
    if request.method == "OPTIONS":
        return make_response("", 204)

    data = request.get_json(force=True, silent=False) or {}
    model = data.get("model", "doubao-seed-1-8-251228")
    api_key = data.get("api_key") or os.getenv("DOUBAO_API_KEY", "")
    schema = data.get("schema", "")
    payload = data.get("payload", "")

    if not api_key:
        return jsonify({"error": "missing api_key"}), 400

    c = client_for(api_key)
    resp = c.responses.create(
        model=model,
        input=[{
            "role": "user",
            "content": [
                {"type": "input_text", "text": schema},
                {"type": "input_text", "text": payload}
            ]
        }]
    )

    text = getattr(resp, "output_text", "")
    m = re.search(r"\{[\s\S]*\}\s*$", text)
    if not m:
        return jsonify({"error": "model did not return json", "raw": text[:500]}), 502
    return jsonify(json.loads(m.group(0)))

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8787)
    args = ap.parse_args()
    app.run(host=args.host, port=args.port, debug=False)
