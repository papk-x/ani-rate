# anime.xlsx / Main1 → ani-rate 取り込み用 JSON
#
# 出力先はリポジトリの外（htmlフォルダには置かない）。既定は xlsx と同じ場所の _import/。
#   python tools/xlsx_to_json.py [xlsxのパス] [出力ディレクトリ]
import openpyxl, json, sys, io, os, re, datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

SRC = sys.argv[1] if len(sys.argv) > 1 else \
    r".\anime.xlsx"
OUTDIR = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(SRC), "_import")
SHEET = 'Main1'

EP0 = 9            # J列 = 1話。n話 = 列インデックス 8+n
EP_MAX_COL = 44    # これ以降はスタジオ名などの別用途
THIS_YEAR = datetime.date.today().year

# 列: A=連番 B=点数 C=タイトル D=状態 E=クール F=話数 G=別採点 H=備考
COL_SEQ, COL_SCORE, COL_TITLE, COL_STATE, COL_COUR, COL_EPCOUNT, COL_ALT, COL_MEMO = 0, 1, 2, 3, 4, 5, 6, 7

STATE_MAP = {'途': 'dropped', '未': 'watching', '完': 'done'}
COUR_MONTH = {1: '1月期', 2: '4月期', 3: '7月期', 4: '10月期'}


def cell_str(v):
    """1234.0 のような float を '1234' に寄せた文字列にする"""
    if v is None:
        return ''
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v).strip()


def parse_cour(raw):
    """E列を解釈する。

    2024 / 2025 / 2026 … 視聴年そのもの（xlsx 上の数少ない明示アンカー）
    211 / 204 …           放送クール。YY + 期(1〜4)。211 = 2021年1月期
    12 / 22 …             放送年のみ（2012 / 2022）
    16M / M / O / SP …    メディア種別。数字が付くものは放送年も取れる
    """
    s = cell_str(raw)
    if not s:
        return {}
    out = {'courRaw': s}

    m = re.fullmatch(r'(\d*)\s*(M|MO|O|SP|s|r|ｒ)', s, re.IGNORECASE)
    if m:
        num, kind = m.group(1), m.group(2).upper()
        out['media'] = {'M': 'movie', 'MO': 'movie', 'O': 'ova', 'SP': 'sp'}.get(kind, 'tv')
        if kind in ('S', 'R', 'Ｒ'):
            out['media'] = 'tv'
        if num:
            y = int(num)
            if y <= 99:
                y += 2000 if y <= THIS_YEAR % 100 + 1 else 1900
            out['airYear'] = y
        return out

    if not re.fullmatch(r'\d+', s):
        return out
    n = int(s)
    out['media'] = 'tv'
    if 1990 <= n <= 2100:                    # 4桁 = 視聴年の明示
        out['watchYear'] = n
        return out
    if 100 <= n <= 999:                      # 3桁 = YY + 期
        yy, q = n // 10, n % 10
        if 1 <= q <= 4 and yy <= THIS_YEAR % 100 + 1:
            out['airYear'] = 2000 + yy
            out['airCour'] = q
            return out
        out.pop('media', None)               # 解釈できない3桁（502 など）は捨てる
        return out
    if 0 <= n <= 99:                         # 2桁 = 放送年のみ
        out['airYear'] = 2000 + n if n <= THIS_YEAR % 100 + 1 else 1900 + n
        return out
    return out


# ---------------------------------------------------------------- 読み込み
wb = openpyxl.load_workbook(SRC, read_only=True, data_only=True)
rows = list(wb[SHEET].iter_rows(values_only=True))
wb.close()

works, skipped = [], []
for r in rows[1:]:
    if len(r) <= COL_TITLE or r[COL_TITLE] in (None, ''):
        continue
    title = str(r[COL_TITLE]).strip()
    seq = r[COL_SEQ] if isinstance(r[COL_SEQ], (int, float)) else None
    if seq is None:
        skipped.append(title)
        continue
    score = r[COL_SCORE] if isinstance(r[COL_SCORE], (int, float)) else None

    def get(i):
        return r[i] if len(r) > i else None

    cour = parse_cour(get(COL_COUR))
    state = STATE_MAP.get(cell_str(get(COL_STATE)))
    epCount = get(COL_EPCOUNT) if isinstance(get(COL_EPCOUNT), (int, float)) else None
    alt = get(COL_ALT) if isinstance(get(COL_ALT), (int, float)) else None
    memo = cell_str(get(COL_MEMO))

    eps = []
    for i in range(EP0, min(len(r), EP_MAX_COL)):
        v = r[i]
        if isinstance(v, (int, float)):
            eps.append({"no": i - 8, "score": float(v)})

    works.append({
        "seq": int(seq),
        "title": title,
        "score": float(score) if score is not None else None,
        "status": state or ('done' if score is not None else 'watching'),
        "year": cour.get('watchYear'),
        "yearEst": False,
        "airYear": cour.get('airYear'),
        "airCour": cour.get('airCour'),
        "airDate": None,
        "media": cour.get('media'),
        "courRaw": cour.get('courRaw'),
        "epCount": int(epCount) if epCount is not None else None,
        "altScore": float(alt) if alt is not None else None,
        "note": memo,
        "epScores": eps,
        "source": "import",
    })

works.sort(key=lambda w: -w["seq"])

# ---------------------------------------------------------------- 視聴年の推定
# 連番は視聴順そのものなので、視聴年は連番に対して単調に増えるはず。
# 手掛かりは2種類ある。
#   強い手掛かり … E列に直接入っている視聴年（2024 / 2025 / 2026）
#   弱い手掛かり … 放送クール。TVアニメはほぼ放送と同時に見ているので放送年≒視聴年
# ただし劇場版・OVA・旧作は後から見ているため、単調性を壊すものはアンカーから外す。
STRONG = 2

cands = []
for w in works:                      # works は新しい順。古い順に並べ直して扱う
    if w["year"] is not None:
        cands.append((w["seq"], w["year"], STRONG, w))
    elif w["airYear"] is not None and w["media"] == 'tv':
        cands.append((w["seq"], w["airYear"], 1, w))
cands.sort(key=lambda t: t[0])       # 連番の昇順 = 視聴順

# 単調非減少になる最大重みの部分列を選ぶ（後追い視聴の外れ値をここで捨てる）
best = [0] * len(cands)
prev = [-1] * len(cands)
for i in range(len(cands)):
    best[i] = cands[i][2]
    for j in range(i):
        if cands[j][1] <= cands[i][1] and best[j] + cands[i][2] > best[i]:
            best[i] = best[j] + cands[i][2]
            prev[i] = j
anchors = []
if cands:
    i = max(range(len(cands)), key=lambda k: best[k])
    while i >= 0:
        anchors.append((cands[i][0], cands[i][1]))
        i = prev[i]
    anchors.reverse()
dropped_anchors = [(c[0], c[1], c[3]["title"]) for c in cands
                   if (c[0], c[1]) not in set(anchors)]

# アンカー間を連番で線形補間する。アンカーより古い側は外挿しない（過去は視聴ペースが違うため）
by_seq = sorted(works, key=lambda w: w["seq"])
if anchors:
    lo_seq, lo_year = anchors[0]
    hi_seq, hi_year = anchors[-1]
    for w in by_seq:
        if w["year"] is not None:
            continue
        s = w["seq"]
        if s < lo_seq:
            continue                                  # 推定できない
        if s >= hi_seq:
            w["year"], w["yearEst"] = hi_year, True
            continue
        for (s0, y0), (s1, y1) in zip(anchors, anchors[1:]):
            if s0 <= s < s1:
                if y0 == y1:
                    w["year"], w["yearEst"] = y0, True
                else:
                    t = (s - s0) / (s1 - s0)
                    w["year"] = int(round(y0 + (y1 - y0) * t))
                    w["yearEst"] = True
                break

out = {
    "version": 2,
    "source": "anime.xlsx / Main1",
    "generatedAt": datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
    "works": works,
}
os.makedirs(OUTDIR, exist_ok=True)
dst = os.path.join(OUTDIR, "anime_import.json")
with open(dst, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

# ---------------------------------------------------------------- 確認用の出力
ys = {}
for w in works:
    ys[w["year"]] = ys.get(w["year"], 0) + 1
sc = [w["score"] for w in works if w["score"] is not None]
st = {}
for w in works:
    st[w["status"]] = st.get(w["status"], 0) + 1

print(f"入力: {SRC}")
print(f"出力: {dst}  ({os.path.getsize(dst):,} bytes)")
print(f"作品数={len(works)} / 点数あり={len(sc)} / 話ごと点数あり={sum(1 for w in works if w['epScores'])}")
print(f"点数 min={min(sc)} max={max(sc)} 平均={sum(sc)/len(sc):.2f}")
print("状態:", sorted(st.items()))
print(f"年アンカー {len(anchors)}件:", anchors[:6], '...', anchors[-6:])
print(f"単調性を壊すため除外したアンカー {len(dropped_anchors)}件:",
      [(s, y, t[:16]) for s, y, t in dropped_anchors[:10]])
print("年の内訳:", sorted(ys.items(), key=lambda x: (x[0] is None, x[0])))
print(f"うち推定={sum(1 for w in works if w['yearEst'])} / 確定={sum(1 for w in works if w['year'] and not w['yearEst'])} / 不明={ys.get(None,0)}")
print("メディア:", sorted({w['media'] or '-' : 0 for w in works}.keys()),
      {k: sum(1 for w in works if w['media'] == k) for k in ('tv', 'movie', 'ova', 'sp')})
dup = {}
for w in works:
    dup.setdefault(w["title"], []).append(w["seq"])
dup = {t: s for t, s in dup.items() if len(s) > 1}
print(f"完全同名 {len(dup)}タイトル / {sum(len(s) for s in dup.values())}件:",
      [(t[:22], s) for t, s in dup.items()])
print("  ※ 同名でも連番が違えば別の記録として全部取り込む（アプリ側は連番で重複判定する）")
print("点数なし:", [w['title'] for w in works if w['score'] is None])
print("連番なしで除外:", skipped)
print("先頭5件:", [(w['seq'], w['title'], w['score'], w['year'], w['yearEst']) for w in works[:5]])
