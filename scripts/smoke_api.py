"""배포 후 스모크 테스트: 화면 흐름 순서대로 API를 호출한다. 사용: python scripts/smoke_api.py [base_url]
흐름: 칩 회전 → 세션(지역 없음) → 아이 설명 → "추천해줘"(지역 묻기) → 지역 실어 추천 → 피드백(학습 표본)"""
import sys, json, time, httpx
B = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
A = B + "/v1"
out = []
def log(t, r, keys=None):
    try: body = r.json()
    except Exception: body = r.text
    env_ok = isinstance(body, dict) and "success" in body
    payload = (body.get("data") if body.get("success") else body.get("error")) if env_ok else body
    shown = {k: payload.get(k) for k in keys} if keys and isinstance(payload, dict) else payload
    tag = "" if env_ok else " (봉투 없음!)"
    out.append(f"[{r.status_code}]{tag} {t}\n{json.dumps(shown, ensure_ascii=False)[:900]}\n")
    return payload if isinstance(payload, (dict, list)) else {}
c = httpx.Client(timeout=90)
def ask(payload):
    """Gemini 무료 키 분당 한도 보호: 생성 호출 사이 간격"""
    time.sleep(5)
    return c.post(f"{A}/chat/ask", json=payload)
log("GET /health", c.get(f"{B}/health"))
log("GET regions/sido", c.get(f"{A}/regions/sido"))
regs = log("GET regions?sido=서울특별시", c.get(f"{A}/regions", params={"sido": "서울특별시"}))
inst = log("GET institutions?sido=서울특별시&size=2", c.get(f"{A}/institutions", params={"sido": "서울특별시", "size": 2}))
if inst.get("items"): log(f"GET institutions/{inst['items'][0]['biz_no']}", c.get(f"{A}/institutions/{inst['items'][0]['biz_no']}"))
sets = [tuple(p["prompt_id"] for p in c.get(f"{A}/chat/prompts").json()["data"]) for _ in range(3)]
out.append(f"[---] chat/prompts ×3 회전: {sets}  (서로 다름={len(set(sets)) == 3})\n")

s = log("POST sessions (지역 없음)", c.post(f"{A}/sessions", json={}))
sid = s["session_id"]
q = "30개월인데 아직 두 단어 문장을 못 만들고 이름 불러도 잘 안 쳐다봐요"
t0 = time.time(); a = log("POST chat/ask (아이 설명)", ask({"session_id": sid, "message": q}))
out.append(f"  소요 {time.time()-t0:.1f}s · intent={a.get('intent')} ask_region={a.get('ask_region')} highlights={a.get('highlights')}\n")
t0 = time.time(); ask({"session_id": sid, "message": q})
out.append(f"  같은 질문 재호출 {time.time()-t0:.1f}s (임베딩 캐시)\n")
aid = a.get("answer_id")
if aid:
    log(f"GET chat/answers/{aid}/evidence", c.get(f"{A}/chat/answers/{aid}/evidence"), ["answer_id"])
    p = log("POST chat/ask '네, 기관 추천해주세요' → pick_region 기대", ask({"session_id": sid, "message": "네, 기관 추천해주세요"}), ["intent", "ask_region", "recommend_for", "text"])
    rid = next((r["region_id"] for r in regs if r["sigungu"] == "노원구"), regs[0]["region_id"])
    rec = log(f"POST chat/recommend (region_id={rid})", c.post(f"{A}/chat/recommend", json={"session_id": sid, "answer_id": p.get("recommend_for") or aid, "region_id": rid}), ["intro", "scope_sido"])
    log("GET sessions (지역 저장됨?)", c.get(f"{A}/sessions/{sid}"))
    log("POST chat/ask '기관 추천해줘' → recommend 기대", ask({"session_id": sid, "message": "기관 추천해줘"}), ["intent", "recommend_for", "text"])
    log("POST feedback 👍", c.post(f"{A}/feedback", json={"answer_id": aid, "rating": "up"}))
    log("POST feedback 👎+UNCLEAR", c.post(f"{A}/feedback", json={"answer_id": aid, "rating": "down", "reason_code": "UNCLEAR"}))
    log("POST feedback 👎 사유없음 → 400 FEEDBACK_REASON_REQUIRED", c.post(f"{A}/feedback", json={"answer_id": aid, "rating": "down"}), ["code", "message"])
    log("POST feedback 잘못된 사유 → 400 INVALID_REASON_CODE", c.post(f"{A}/feedback", json={"answer_id": aid, "rating": "down", "reason_code": "X"}), ["code", "details"])
    log("POST chat/ask 형식 오류 → 400 VALIDATION_ERROR", ask({"session_id": "nope"}), ["code", "details"])
    log("GET sessions 없는 세션 → 404 SESSION_NOT_FOUND", c.get(f"{A}/sessions/00000000-0000-0000-0000-000000000000"), ["code"])
    log("GET 없는 라우트 → 404 NOT_FOUND", c.get(f"{A}/nothing"), ["code"])
f = log("POST sessions (fresh)", c.post(f"{A}/sessions", json={}))
log("POST chat/ask '근처 기관 추천해줘' (설명 없음) → need_context", ask({"session_id": f["session_id"], "message": "근처 기관 추천해줘"}), ["intent", "text"])
d = log("POST chat/ask 진단 요구 → diagnosis", ask({"session_id": sid, "message": "우리 아이 자폐인지 아닌지 진단해주세요"}), ["intent", "fallback_tier", "answer_id"])
if d.get("answer_id"):
    log("POST chat/recommend (진단 응답으로) → 409 ANSWER_NOT_GROUNDED", c.post(f"{A}/chat/recommend", json={"session_id": sid, "answer_id": d["answer_id"]}), ["code"])
log("POST chat/ask 범위 밖 → out_of_scope", ask({"session_id": sid, "message": "오늘 저녁 메뉴 추천해줘"}), ["intent", "fallback_tier", "evidence_count"])
open("data/raw/smoke_api.txt", "w", encoding="utf-8").write("\n".join(out))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
print("\n".join(out))
