# -*- coding: utf-8 -*-
"""Gemini 임베딩으로 KB 청크 벡터화 (batchEmbedContents, 이어받기 지원)
사용: GEMINI_KEY=<키> python scripts/embed_gemini.py [배치수]
"""
import json, io, os, sys, time, subprocess, tempfile

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
D = lambda *p: os.path.join(BASE, *p)
KEY = os.environ.get("GEMINI_KEY", "").strip()
if not KEY:
    sys.exit("GEMINI_KEY 필요")

MODEL = "models/gemini-embedding-2"
URL = ("https://generativelanguage.googleapis.com/v1beta/%s:batchEmbedContents?key=%s" % (MODEL, KEY))
BATCH = 50
DIM = 768                      # 저장·계산 비용을 줄이기 위해 축소 차원 사용
MAX_BATCHES = int(sys.argv[1]) if len(sys.argv) > 1 else 10 ** 9

OUT = D("data", "kb", "kb_vectors.jsonl")

docs = [json.loads(l) for l in io.open(D("data", "kb", "kb_chunks.jsonl"), encoding="utf-8")]
done = set()
if os.path.exists(OUT):
    for l in io.open(OUT, encoding="utf-8"):
        try:
            done.add(json.loads(l)["id"])
        except Exception:
            pass
todo = [d for d in docs if d["id"] not in done]
print("전체 %d / 완료 %d / 남은 %d" % (len(docs), len(done), len(todo)), flush=True)


def post(payload):
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    io.open(path, "w", encoding="utf-8").write(json.dumps(payload, ensure_ascii=False))
    try:
        p = subprocess.run(["curl", "-s", "-m", "120", "-X", "POST", URL,
                            "-H", "Content-Type: application/json",
                            "--data-binary", "@" + path], capture_output=True)
        return json.loads(p.stdout.decode("utf-8", "replace"))
    except Exception as e:
        return {"error": {"message": str(e)}}
    finally:
        os.remove(path)


fp = io.open(OUT, "a", encoding="utf-8")
ok = err = 0
for bi in range(0, min(len(todo), MAX_BATCHES * BATCH), BATCH):
    chunk = todo[bi:bi + BATCH]
    payload = {"requests": [{
        "model": MODEL,
        "content": {"parts": [{"text": d["text"][:2000]}]},
        "taskType": "RETRIEVAL_DOCUMENT",
        "outputDimensionality": DIM,
    } for d in chunk]}
    embs = None
    for attempt in range(6):
        res = post(payload)
        embs = res.get("embeddings")
        if embs and len(embs) == len(chunk):
            break
        code = (res.get("error") or {}).get("code")
        wait = 20 if code == 429 else 5
        print("  재시도 %d/6 @%d (code=%s, %ds 대기)" % (attempt + 1, bi, code, wait), flush=True)
        embs = None
        time.sleep(wait)
    if not embs:
        err += 1
        continue
    for d, e in zip(chunk, embs):
        fp.write(json.dumps({"id": d["id"], "v": e["values"]}, ensure_ascii=False) + "\n")
    ok += len(chunk)
    fp.flush()
    if (bi // BATCH) % 5 == 0:
        print("  %d/%d 완료" % (ok, len(todo)), flush=True)
    time.sleep(2.0)
fp.close()
print("DONE 임베딩 %d건 추가 (실패 배치 %d)" % (ok, err))
