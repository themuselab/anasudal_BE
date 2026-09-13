# -*- coding: utf-8 -*-
"""평가 질문 단건 임베딩 (재시도 포함)"""
import json, io, os, sys, time, subprocess, tempfile
BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
D = lambda *p: os.path.join(BASE, *p)
KEY = os.environ["GEMINI_KEY"]
MODEL = "models/gemini-embedding-2"
URL = "https://generativelanguage.googleapis.com/v1beta/%s:embedContent?key=%s" % (MODEL, KEY)
CACHE = D("data", "kb", "eval_query_vectors.json")

qs = json.load(io.open(D("data", "kb", "eval_questions.json"), encoding="utf-8"))
cache = json.load(io.open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}

for q in qs:
    t = q["question"]
    if t in cache:
        continue
    payload = {"model": MODEL, "content": {"parts": [{"text": t}]},
               "taskType": "RETRIEVAL_QUERY", "outputDimensionality": 768}
    fd, path = tempfile.mkstemp(suffix=".json"); os.close(fd)
    io.open(path, "w", encoding="utf-8").write(json.dumps(payload, ensure_ascii=False))
    for attempt in range(8):
        p = subprocess.run(["curl", "-s", "-m", "60", "-X", "POST", URL,
                            "-H", "Content-Type: application/json",
                            "--data-binary", "@" + path], capture_output=True)
        try:
            res = json.loads(p.stdout.decode("utf-8", "replace"))
        except Exception:
            res = {}
        if "embedding" in res:
            cache[t] = res["embedding"]["values"]
            break
        time.sleep(15)
    os.remove(path)
    io.open(CACHE, "w", encoding="utf-8").write(json.dumps(cache, ensure_ascii=False))
    print("  %s %s" % (q["id"], "OK" if t in cache else "FAIL"), flush=True)
    time.sleep(1.5)
print("질문 임베딩 %d/%d" % (len(cache), len(qs)))
