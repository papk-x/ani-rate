# _import/anime_import.json の「年が無い作品」に AniList から放送年を入れて、
# 差分だけの取り込み用 JSON を書き出す。
#
#   python tools/fill_years.py [入力JSON] [出力JSON]
#
# 元の anime_import.json は書き換えない。出力は既定で _import/anime_years.json。
# アプリの「インポート」で読ませると、**空いている項目だけ**が埋まる（点数やメモは上書きしない）。
import json, sys, io, os, re, time, unicodedata, urllib.request, urllib.error, datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 入力の場所は端末ごとに違う。公開リポジトリなので実際のパスは書かない。
#   1. 引数    python tools/fill_years.py "D:\path\_import\anime_import.json"
#   2. 環境変数 ANI_IMPORT
#   3. 既定     カレントディレクトリの _import/anime_import.json
SRC = sys.argv[1] if len(sys.argv) > 1 else (
    os.environ.get("ANI_IMPORT") or os.path.join("_import", "anime_import.json"))
DST = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
    os.path.dirname(os.path.abspath(SRC)), "anime_years.json")

API = 'https://graphql.anilist.co'
HDR = {'Content-Type': 'application/json', 'Accept': 'application/json',
       'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36'}
BATCH = 20          # エイリアスで1リクエストにまとめる件数
WAIT = 2.5          # AniList のレート制限は30リクエスト/分

# AniList の検索と綴りが合わず、どう崩しても当たらないものを手で埋める表。
# 作品名は個人の視聴履歴そのものなので、公開リポジトリには置かず
# 入力と同じフォルダの manual_years.json（gitignore対象）から読む。
#   { "作品名": 2015, ... }
MANUAL = {}

FMT = {'TV': 'tv', 'TV_SHORT': 'tv', 'ONA': 'tv', 'MOVIE': 'movie', 'OVA': 'ova', 'SPECIAL': 'sp'}


def strip_season(t):
    """括弧の中・第N期・シーズン表記を落とす"""
    t = unicodedata.normalize('NFKC', str(t or ''))
    t = re.sub(r'[（(\[][^）)\]]*[）)\]]', ' ', t)
    t = re.sub(r'第?\s*\d+\s*期', ' ', t)
    t = re.sub(r'\d+\s*(st|nd|rd|th)?\s*シーズン', ' ', t, flags=re.I)
    t = re.sub(r'(ファースト|セカンド|サード)シーズン', ' ', t)
    t = re.sub(r'Season\s*\d+', ' ', t, flags=re.I)
    return re.sub(r'\s+', ' ', t).strip()


# 崩し方は4段階まで。これ以上崩すと別作品に当たる
# （「映画 ふたりはプリキュア」が「映画 バクテン!!」になった）ので、先頭の語だけでは引かない
TRIES = [
    lambda t: t,
    strip_season,
    lambda t: strip_season(t).replace('・', ''),
    lambda t: re.sub(r'[・\s]', '', strip_season(t)),
]


def ask(queries):
    """検索語のリストを1リクエストで引く。Media を直接引くと1件でも
    見つからない時に 404 で全部落ちるため、Page で包む"""
    decl = ','.join(f'$s{k}:String' for k in range(len(queries)))
    body = ' '.join(
        f'a{k}:Page(perPage:1){{media(search:$s{k},type:ANIME,sort:SEARCH_MATCH){{'
        f'title{{native}} startDate{{year month day}} format episodes}}}}'
        for k in range(len(queries)))
    payload = {'query': f'query({decl}){{{body}}}',
               'variables': {f's{k}': q for k, q in enumerate(queries)}}
    for _ in range(3):
        try:
            r = urllib.request.urlopen(urllib.request.Request(
                API, data=json.dumps(payload).encode(), headers=HDR), timeout=45)
            return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(25)
                continue
            return json.loads(e.read().decode())
    return {}


# ---------------------------------------------------------------- 読み込み
src = json.load(open(SRC, encoding='utf-8'))
works = src['works']

man_path = os.path.join(os.path.dirname(os.path.abspath(SRC)), 'manual_years.json')
if os.path.exists(man_path):
    MANUAL.update(json.load(open(man_path, encoding='utf-8')))
    print(f'手入力の年: {man_path} から {len(MANUAL)} 件')
targets = [w for w in works if w.get('year') is None]
print(f'入力: {SRC}')
print(f'全 {len(works)} 件 / 年が無い {len(targets)} 件')

found = {}      # seq -> AniList の1件
for p, fn in enumerate(TRIES):
    rest = [w for w in targets if w['seq'] not in found and w['title'] not in MANUAL]
    if p:
        rest = [w for w in rest
                if len(fn(w['title'])) >= 2
                and all(g(w['title']) != fn(w['title']) for g in TRIES[:p])]
    if not rest:
        continue
    print(f'  {p+1}周目（{"そのまま" if p==0 else "表記を崩す"}）… {len(rest)} 件')
    for i in range(0, len(rest), BATCH):
        part = rest[i:i + BATCH]
        j = ask([fn(w['title']) for w in part])
        for k, w in enumerate(part):
            media = (((j.get('data') or {}).get(f'a{k}') or {}).get('media') or [None])[0]
            if media and (media.get('startDate') or {}).get('year'):
                found[w['seq']] = (media, p)
        time.sleep(WAIT)

# ---------------------------------------------------------------- 差分を作る
patch = []
for w in targets:
    row = {'seq': w['seq'], 'title': w['title'], 'yearEst': True}
    if w['title'] in MANUAL:
        row['year'] = MANUAL[w['title']]
        row['src'] = 'manual'
    elif w['seq'] in found:
        m, p = found[w['seq']]
        d = m['startDate']
        row['year'] = d['year']
        row['airYear'] = d['year']
        if d.get('month'):
            row['airCour'] = (d['month'] - 1) // 3 + 1
            if d.get('day'):
                row['airDate'] = f"{d['year']}-{d['month']:02d}-{d['day']:02d}"
        if m.get('format'):
            row['media'] = FMT.get(m['format'], 'tv')
        if m.get('episodes'):
            row['epCount'] = m['episodes']
        row['src'] = 'anilist' if p == 0 else 'anilist-alt'
    else:
        continue
    patch.append(row)

out = {
    'version': 2,
    'source': 'AniList / 放送年の補完',
    'mode': 'merge',        # 空いている項目だけ埋める。既存の値は上書きしない
    'generatedAt': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
    'works': patch,
}
with open(DST, 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False, separators=(',', ':'))

miss = [w for w in targets if w['seq'] not in found and w['title'] not in MANUAL]
by = {}
for r in patch:
    by[r['src']] = by.get(r['src'], 0) + 1
print(f'\n出力: {DST}  ({os.path.getsize(DST):,} bytes)')
print(f'年を入れた {len(patch)} 件  内訳: {sorted(by.items())}')
print(f'まだ年が無い {len(miss)} 件: {[w["title"][:24] for w in miss]}')
print('\nアプリの 設定 → インポート でこの JSON を読ませてください。')
print('既存の作品は空いている項目だけが埋まり、点数・メモ・話ごとの記録は上書きされません。')
