# anime.xlsx / Main1 → ani-rate 取り込み用 JSON
import openpyxl, json, sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

SRC = r".\anime.xlsx"
OUTDIR = r".\_import"
os.makedirs(OUTDIR, exist_ok=True)

wb = openpyxl.load_workbook(SRC, read_only=True, data_only=True)
rows = list(wb['Main1'].iter_rows(values_only=True))
wb.close()

EP0 = 9  # J列 = 1話。n話 = index 8+n

works, skipped = [], []
for r in rows[1:]:
    if len(r) < 3 or r[2] in (None, ''):
        continue
    seq   = r[0] if isinstance(r[0], (int, float)) else None
    score = r[1] if isinstance(r[1], (int, float)) else None
    title = str(r[2]).strip()
    year  = None
    if len(r) > 4 and isinstance(r[4], (int, float)) and 1990 <= r[4] <= 2100:
        year = int(r[4])
    eps = []
    for i in range(EP0, len(r)):
        v = r[i]
        if isinstance(v, (int, float)):
            eps.append({"no": i - 8, "score": float(v)})
    if seq is None:
        skipped.append(title); continue
    works.append({
        "seq": int(seq), "title": title,
        "score": float(score) if score is not None else None,
        "year": year, "epScores": eps, "source": "import"
    })

works.sort(key=lambda w: -w["seq"])

# 年アンカー間を縦方向のみ補間（アンカー外は不明のまま null）
anchors = sorted([(w["seq"], w["year"]) for w in works if w["year"]], reverse=True)
print("年アンカー:", anchors)
for w in works:
    if w["year"] is not None:
        continue
    for i, (s, y) in enumerate(anchors):
        if w["seq"] >= s:
            w["year"] = y if i == 0 or w["seq"] < anchors[i-1][0] else w["year"]
            break
    else:
        w["year"] = None
# 最上位アンカーより上は最新年扱い
if anchors:
    top_seq, top_year = anchors[0]
    for w in works:
        if w["seq"] > top_seq and w["year"] is None:
            w["year"] = top_year

out = {"version": 1, "source": "anime.xlsx / Main1", "works": works}
dst = os.path.join(OUTDIR, "anime_import.json")
with open(dst, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

ys = {}
for w in works: ys[w["year"]] = ys.get(w["year"], 0) + 1
sc = [w["score"] for w in works if w["score"] is not None]
print(f"\n出力: {dst}  ({os.path.getsize(dst):,} bytes)")
print(f"作品数={len(works)} / 点数あり={len(sc)} / 話ごと点数あり={sum(1 for w in works if w['epScores'])}")
print(f"点数 min={min(sc)} max={max(sc)} 平均={sum(sc)/len(sc):.2f}")
print("年の内訳:", sorted(ys.items(), key=lambda x: (x[0] is None, x[0])))
print("点数なし:", [w['title'] for w in works if w['score'] is None])
print("連番なしで除外:", skipped)
print("\n先頭5件:", [(w['seq'], w['title'], w['score'], w['year']) for w in works[:5]])
print("末尾3件:", [(w['seq'], w['title'], w['score'], w['year']) for w in works[-3:]])
