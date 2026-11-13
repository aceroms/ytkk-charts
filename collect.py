#!/usr/bin/env python3
"""TJ·금영 노래방 인기곡을 모아 charts.json을 새로 만든다.

- 매달 GitHub Actions에서 실행된다 (.github/workflows/charts.yml). PC에서 직접 실행해도 된다.
- 목록마다 따로 가져오고, 못 가져온 목록은 지난 charts.json 내용을 그대로 둔다.
- 하나도 못 가져오면 오류로 끝난다 → Actions에 빨간 표시가 뜨고 charts.json은 그대로.
- 사이트 화면이 바뀌면 아래 SOURCES(주소·누를 탭 이름)나 줄 읽는 방법을 고쳐야 한다.
"""
import datetime
import json
import pathlib
import re
import sys

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT / 'charts.json'
KST = datetime.timezone(datetime.timedelta(hours=9))

# TV 노래모음에 보일 모양. rows(곡 목록)는 가져와서 채운다
META = {
    'ky100': dict(title='금영 인기 TOP 100', kw='금영 인기', big='100', src='금영', sub='금영 월간 인기곡', c=['#c93f27', '#fff4ef'], br='KY'),
    'tj100': dict(title='TJ 인기 TOP 100', kw='TJ 인기', big='100', src='TJ', sub='TJ미디어 인기 차트', c=['#f2b544', '#2a1a05'], br='TJ'),
    'kyjp': dict(title='금영 일본곡 인기', kw='일본곡', big='J-POP', src='금영', sub='금영 장르별 인기곡', c=['#f1d9df', '#2a0f18'], br='KY'),
    'tjjp': dict(title='TJ J-POP 인기', kw='TJ\nJ-POP', big='JP', src='TJ', sub='TJ미디어 JPOP 인기 차트', c=['#7cc0ec', '#0f2433'], br='TJ'),
    'kyballad': dict(title='금영 발라드 인기', kw='발라드', big='발라드', src='금영', sub='금영 장르별 인기곡', c=['#3a6f8f', '#f6f1e8'], br='KY'),
    'kytrot': dict(title='금영 트로트 인기', kw='트로트', big='트로트', src='금영', sub='금영 성인가요 인기곡', c=['#2f7d5c', '#effaf4'], br='KY'),
    'kydance': dict(title='금영 댄스 인기', kw='댄스', big='댄스', src='금영', sub='금영 장르별 인기곡', c=['#2f4fbf', '#f3f0ff'], br='KY'),
}
# 가져올 곳: (목록, 주소, 누를 탭 이름 후보). 탭 이름은 화면에 보이는 글자 그대로
SOURCES = [
    ('ky100', ['https://kysing.kr/popular/?period=m&range=1', 'https://kysing.kr/popular/?period=m&range=2'], None),
    ('tj100', ['https://www.tjmedia.com/chart/top100'], None),
    ('tjjp', ['https://www.tjmedia.com/chart/top100'], ['JPOP', 'J-POP']),
    ('kyjp', ['https://kysing.kr/genre-polular/'], ['일본곡', 'J-POP', 'JPOP', '일본']),
    ('kyballad', ['https://kysing.kr/genre-polular/'], ['발라드']),
    ('kytrot', ['https://kysing.kr/genre-polular/'], ['트로트', '성인가요']),
    ('kydance', ['https://kysing.kr/genre-polular/'], ['댄스']),
]
MIN_ROWS = {'ky100': 60, 'tj100': 60}  # 이보다 적게 읽히면 실패로 본다 (나머지는 20곡)
ORDER = ['ky100', 'tj100', 'kyjp', 'tjjp', 'kyballad', 'kytrot', 'kydance']  # 지난 파일에만 있는 목록은 뒤에 그대로

# 화면의 줄(tr·li 등)마다 보이는 글자 조각을 순서대로 모은다
ROWS_JS = r"""() => {
  const out = [];
  const els = document.querySelectorAll('tr, li, [role=row]');
  for (const el of els) {
    if (el.querySelector('tr, li, [role=row]')) continue;
    const toks = [];
    const walk = (n) => {
      for (const c of n.childNodes) {
        if (c.nodeType === 3) { const t = c.textContent.replace(/\s+/g, ' ').trim(); if (t) toks.push(t); }
        else if (c.nodeType === 1 && !/^(SCRIPT|STYLE|BUTTON|SELECT|OPTION)$/.test(c.tagName)) {
          const cs = getComputedStyle(c);
          if (cs.display !== 'none' && cs.visibility !== 'hidden') walk(c);
        }
      }
    };
    walk(el);
    if (toks.length >= 3 && toks.length <= 40) out.push(toks);
  }
  return out;
}"""

NUM = re.compile(r'^\d{1,6}$')
DATE = re.compile(r'^\d{4}[.\-/]\d{1,2}([.\-/]\d{1,2})?$')


def parse_rows(rows):
    """[글자 조각, ...] 줄들 → [[번호, 제목, 가수], ...]. 순위(앞의 작은 숫자) 다음의 3~6자리가 곡 번호."""
    out, seen = [], set()
    for toks in rows:
        nums = [i for i, t in enumerate(toks) if NUM.match(t)]
        if not nums:
            continue
        i = nums[0]
        if len(nums) > 1 and int(toks[nums[0]]) <= 100 and len(toks[nums[1]]) >= 3 and nums[1] <= nums[0] + 2:
            i = nums[1]  # 첫 숫자는 순위
        if len(toks[i]) < 3:
            continue
        rest = [t for t in toks[i + 1:] if not NUM.match(t) and not DATE.match(t) and len(t) <= 120]
        if not rest:
            continue
        title = rest[0]
        artist = next((t for t in rest[1:] if t != title and len(t) <= 60), '')
        n = int(toks[i])
        if n in seen:
            continue
        seen.add(n)
        out.append([n, title, artist])
    return out[:100]


def parse_json(obj):
    """TJ 사이트가 받아 오는 JSON에서 곡 줄 찾기 (pro·indexTitle·indexSong 같은 이름)"""
    best = []

    def pick(d, names, test):
        for k in names:
            if k in d and test(d[k]):
                return d[k]
        return None

    def walk(o, depth=0):
        nonlocal best
        if depth > 8:
            return
        if isinstance(o, list) and len(o) >= 10 and all(isinstance(x, dict) for x in o[:10]):
            got = []
            for d in o:
                n = pick(d, ['pro', 'songNo', 'song_no', 'no', 'number', 'songNum'], lambda v: str(v).isdigit() and 3 <= len(str(v)) <= 6)
                t = pick(d, ['indexTitle', 'title', 'songTitle', 'song_title', 'subject'], lambda v: isinstance(v, str) and v.strip())
                a = pick(d, ['indexSong', 'singer', 'artist', 'artistName', 'singerName'], lambda v: isinstance(v, str))
                if n is not None and t:
                    got.append([int(n), t.strip(), (a or '').strip()])
            if len(got) >= len(o) * 0.8 and len(got) > len(best):
                best = got
        if isinstance(o, dict):
            for v in o.values():
                walk(v, depth + 1)
        elif isinstance(o, list):
            for v in o[:200]:
                walk(v, depth + 1)

    walk(obj)
    return best[:100]


def click_tab(page, names):
    for name in names:
        loc = page.get_by_text(name, exact=True)
        if loc.count():
            loc.first.click(timeout=8000)
            page.wait_for_load_state('networkidle', timeout=20000)
            page.wait_for_timeout(1500)
            return name
    raise RuntimeError('탭을 못 찾음: ' + ', '.join(names))


def collect(page, lid, urls, tabs):
    rows = []
    for url in urls:
        caught = []
        handler = lambda r: caught.append(r)
        page.on('response', handler)
        try:
            page.goto(url, wait_until='networkidle', timeout=45000)
            page.wait_for_timeout(1500)
            if tabs:
                caught.clear()
                click_tab(page, tabs)
        finally:
            page.remove_listener('response', handler)
        got = []
        for r in caught:  # 먼저 사이트가 받아 온 JSON에서
            try:
                if 'json' in (r.headers.get('content-type') or ''):
                    j = parse_json(r.json())
                    if len(j) > len(got):
                        got = j
            except Exception:
                pass
        if len(got) < 10:  # 없으면 화면 글자에서
            got = parse_rows(page.evaluate(ROWS_JS))
        rows += [x for x in got if x[0] not in {y[0] for y in rows}]
    need = MIN_ROWS.get(lid, 20)
    if len(rows) < need:
        raise RuntimeError('%d곡만 읽혔어요 (최소 %d곡)' % (len(rows), need))
    return rows[:100]


def main():
    old = json.loads(OUT.read_text(encoding='utf-8')) if OUT.exists() else {'lists': []}
    old_lists = {l['id']: l for l in old.get('lists', [])}
    new_rows, report = {}, []
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        page = br.new_context(locale='ko-KR', timezone_id='Asia/Seoul', viewport={'width': 1366, 'height': 900},
                              user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36').new_page()
        for lid, urls, tabs in SOURCES:
            try:
                new_rows[lid] = collect(page, lid, urls, tabs)
                report.append('%-9s 성공 %3d곡  1위 %s' % (lid, len(new_rows[lid]), new_rows[lid][0][1]))
            except Exception as e:
                report.append('%-9s 실패 — %s (지난 목록 그대로)' % (lid, str(e).splitlines()[0][:150]))
        br.close()
    print('\n'.join(report))
    if not new_rows:
        print('하나도 못 가져왔어요. 사이트가 막았거나 화면이 바뀌었을 수 있어요.', file=sys.stderr)
        sys.exit(1)
    lists = []
    for lid in ORDER:
        if lid in new_rows:
            lists.append(dict(id=lid, **META[lid], rows=new_rows[lid]))
        elif lid in old_lists:
            lists.append(old_lists[lid])
    lists += [l for i, l in old_lists.items() if i not in ORDER]  # 예: tj2025 (해마다 한 번 나오는 목록)
    lists = lists[:12]
    changed = [l['id'] for l in lists if l != old_lists.get(l['id'])]
    if not changed and len(lists) == len(old_lists):
        print('바뀐 목록이 없어요')
        return
    now = datetime.datetime.now(KST)
    out = {'version': now.strftime('%Y-%m-%d'), 'label': '%d월 %d일' % (now.month, now.day),
           'note': '자동 수집 · 바뀐 목록: ' + ', '.join(changed), 'lists': lists}
    if out['version'] <= old.get('version', ''):
        print('오늘 이미 만든 목록이 있어요 (version %s)' % old.get('version'))
        out['version'] = old['version']
    txt = json.dumps(out, ensure_ascii=False, indent=1)
    txt = re.sub(r'\[\n\s+(\d+),\n\s+("(?:[^"\\]|\\.)*"),\n\s+("(?:[^"\\]|\\.)*")\n\s+\]', r'[\1, \2, \3]', txt)
    txt = re.sub(r'\[\n\s+("#[0-9a-fA-F]{6}"),\n\s+("#[0-9a-fA-F]{6}")\n\s+\]', r'[\1, \2]', txt)
    OUT.write_text(txt + '\n', encoding='utf-8')
    print('charts.json 저장: %s · 바뀐 목록 %s' % (out['version'], ', '.join(changed)))


if __name__ == '__main__':
    main()
