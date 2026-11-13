#!/usr/bin/env python3
"""TJ·금영 노래방 인기곡을 모아 charts.json을 새로 만든다.

- 매달 GitHub Actions에서 실행된다 (.github/workflows/charts.yml). PC에서 직접 실행해도 된다.
- 목록마다 따로 가져오고, 못 가져온 목록은 지난 charts.json 내용을 그대로 둔다.
- 하나도 못 가져오면 오류로 끝난다 → Actions에 빨간 표시가 뜨고 charts.json은 그대로.
- 못 가져온 목록은 그 화면 모양을 debug 폴더에 남긴다 (목록.txt 요약 · 목록.html · 목록.jpg).
  실행할 때마다 debug 폴더를 비우고 새로 쓰므로, 다 성공하면 debug 폴더는 없어진다.
- 사이트 화면이 바뀌면 아래 SOURCES(주소·누를 탭 이름)나 줄 읽는 방법을 고쳐야 한다.
"""
import datetime
import json
import pathlib
import re
import shutil
import sys

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT / 'charts.json'
DEBUG = ROOT / 'debug'
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
SEARCH = {'tjjp'}  # 탭을 눌러도 목록이 안 바뀌면 '검색'·'조회' 단추도 눌러 보는 곳

# 화면에서 '곡 줄' 후보를 모은다. 줄마다 [보이는 글자, 그 글자를 감싼 class 이름들]을 순서대로.
# 1) 맨 안쪽 tr·li (표·목록)  2) 같은 모양의 자식이 8개 넘게 반복되는 곳 (div·ul 줄 등 표가 아닌 목록)
CANDS_JS = r"""() => {
  const SKIP = /^(SCRIPT|STYLE|NOSCRIPT|TEMPLATE|BUTTON|SELECT|OPTION|BR|IMG|SVG|INPUT|TEXTAREA)$/i;
  const hidden = (el) => {
    const cs = getComputedStyle(el);
    if (cs.display === 'contents') return false;
    if (cs.display === 'none' || cs.visibility === 'hidden' || el.getClientRects().length === 0) return true;
    return cs.overflow.includes('hidden') && el.offsetHeight <= 1;  // 접힌 가사 · 화면 읽기 전용 글자
  };
  const cls = (el) => (typeof el.className === 'string' ? el.className.trim().replace(/\s+/g, ' ') : '');
  // '..'로 잘려 보이는 글자: 줄 안의 속성(title 등)이나 숨은 글자에서 같은 말로 시작하는 더 긴 글자를 찾는다
  const CUT = /(\.\.|…)$/;
  const norm = (v) => (typeof v === 'string' ? v.replace(/\s+/g, ' ').trim() : '');
  const full = (el, row, t) => {
    const pre = t.replace(/(\.+|…)$/, '').trim();
    if (pre.length < 2) return null;
    const ok = (v) => { v = norm(v); return v.startsWith(pre) && v.length > pre.length + 1 && !CUT.test(v) ? v : null; };
    for (let e = el; e && e !== row.parentElement; e = e.parentElement) {
      for (const a of ['title', 'data-title', 'data-original-title', 'aria-label', 'alt']) {
        const v = ok(e.getAttribute(a));
        if (v) return v;
      }
    }
    for (const e of [row, ...row.querySelectorAll('*')]) {
      for (const a of e.getAttributeNames()) {
        let v = e.getAttribute(a);
        try { v = decodeURIComponent(v); } catch (x) { /* 그대로 */ }
        if (ok(v)) return ok(v);
      }
    }
    const tw = document.createTreeWalker(row, NodeFilter.SHOW_TEXT);
    for (let n = tw.nextNode(); n; n = tw.nextNode()) {
      if (ok(n.textContent)) return ok(n.textContent);
    }
    return null;
  };
  const tokens = (row) => {
    const out = [];
    const walk = (n, hint) => {
      for (const c of n.childNodes) {
        if (out.length >= 80) return;
        if (c.nodeType === 3) {
          const t = c.textContent.replace(/\s+/g, ' ').trim();
          const f = t && CUT.test(t) ? full(n, row, t) : null;
          if (f) out.push([f.slice(0, 200), hint + '>@full']);  // @full: 전체 제목을 찾음 (세기용 표시)
          else if (t) out.push([t.slice(0, 200), hint]);
        } else if (c.nodeType === 1 && !SKIP.test(c.tagName) && !hidden(c)) {
          walk(c, hint + '>' + cls(c));
        }
      }
    };
    walk(row, '');
    return out;
  };
  const path = (el) => {
    const p = [];
    for (let e = el; e && e !== document.body && p.length < 4; e = e.parentElement) {
      const c = cls(e).split(' ').filter(Boolean).slice(0, 2).join('.');
      p.unshift(e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + (c ? '.' + c : ''));
    }
    return p.join(' > ');
  };
  const cands = [];
  const leaf = [...document.querySelectorAll('tr, li, [role=row]')]
    .filter(el => !el.querySelector('tr, li, [role=row]') && !hidden(el))
    .slice(0, 400).map(tokens).filter(t => t.length >= 2);
  if (leaf.length) cands.push({where: '맨 안쪽 tr·li', rows: leaf});
  const STATE = /^(on|active|selected|current|first|last|odd|even|clear|clearfix)$/i;
  for (const el of document.querySelectorAll('body *')) {
    const kids = [...el.children].filter(k => !SKIP.test(k.tagName));
    if (kids.length < 8) continue;
    const groups = new Map();
    for (const k of kids) {
      const sig = k.tagName.toLowerCase() + cls(k).split(' ').filter(c => c && !STATE.test(c)).sort().map(c => '.' + c).join('');
      if (!groups.has(sig)) groups.set(sig, []);
      groups.get(sig).push(k);
    }
    const [sig, g] = [...groups].sort((a, b) => b[1].length - a[1].length)[0];
    if (g.length < 8) continue;
    const rows = g.filter(k => !hidden(k)).slice(0, 210).map(tokens).filter(t => t.length >= 2);
    if (rows.length >= 5) cands.push({where: path(el) + ' > ' + sig + ' ×' + g.length, rows});
  }
  return cands;
}"""

NUM = re.compile(r'^\d{1,6}$')
DATE = re.compile(r'^\d{4}[.\-/]\d{1,2}([.\-/]\d{1,2})?$')
JUNK = {'닫기', '가사', '가사보기', 'MV', 'MR', 'NEW', 'HOT', 'LTS', 'PICK', '+'}  # 제목·가수 옆의 표시·단추 글자
TITLE_HINT = re.compile(r'(^|[\s_>-])(tit|title|subject)', re.I)  # class 이름: popular_chart_tit, song-title …
ARTIST_HINT = re.compile(r'(^|[\s_>-])(sng|singer|artist|art)([\s_>-]|$)', re.I)  # …_sng, singer, mo-art …


CUT_TAIL = re.compile(r'(?<!\.)\.\.$')  # 사이트가 긴 제목 끝을 잘라 붙인 '..' (세 점 '...'은 원래 제목일 수 있어 그대로)


def fix_cut(title):
    """전체 제목을 못 찾은 '..' 제목: '..'을 떼고, 닫히지 않은 괄호부터 뒤를 버린다.
    예) 'Tears (ドラマ..' → 'Tears', 'うさぎラップ(…ver.) ("ちいかわ..' → 'うさぎラップ(…ver.)'"""
    t = CUT_TAIL.sub('', title).rstrip()
    pairs, opened = {')': '(', '）': '（', ']': '[', '」': '「', '』': '『'}, []
    for k, ch in enumerate(t):
        if ch in pairs.values():
            opened.append((ch, k))
        elif ch in pairs and opened and opened[-1][0] == pairs[ch]:
            opened.pop()
    if opened:
        t = t[:opened[0][1]]
    t = t.rstrip(' -,/:·~"\'')
    return t or CUT_TAIL.sub('', title).rstrip()


def parse_rows(rows, stats=None):
    """줄들 [[글자, class 이름들], ...] → [[번호, 제목, 가수], ...].
    곡 번호: 100보다 큰 3~6자리 숫자 중 첫째 (앞의 순위·등락 숫자는 100 이하).
    제목·가수: class 이름(tit·title / sng·singer·artist)으로 먼저 고르고, 없으면 번호 다음 글자 순서대로.
    stats를 주면 잘린 제목 수를 센다 (full: 전체 제목 찾음, cut: 뒷부분 정리)."""
    out, seen = [], set()
    for toks in rows:
        toks = [(t, h) for t, h in toks if t not in JUNK]
        i = next((k for k, (t, _) in enumerate(toks) if NUM.match(t) and len(t) >= 3 and int(t) > 100), None)
        if i is None:
            continue
        rest = [(t, h) for t, h in toks[i + 1:] if not DATE.match(t) and len(t) <= 120]
        title = next((t for t, h in rest if TITLE_HINT.search(h) and not ARTIST_HINT.search(h)), None)
        if title is None:
            title = next((t for t, _ in rest if not NUM.match(t)), None)
        if not title:
            continue
        artist = next((t for t, h in rest if ARTIST_HINT.search(h) and t != title and len(t) <= 60), None)
        if artist is None:
            after = [t for t, _ in rest][[t for t, _ in rest].index(title) + 1:]
            artist = next((t for t in after if t != title and len(t) <= 60 and not NUM.match(t)), '')
        n = int(toks[i][0])
        if n in seen:
            continue
        seen.add(n)
        if stats is not None and len(out) < 100 and any(t == title and '@full' in h for t, h in rest):
            stats['full'] += 1
        if CUT_TAIL.search(title):
            title = fix_cut(title)
            if stats is not None and len(out) < 100:
                stats['cut'] += 1
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


def click_tab(page, names, log):
    for name in names:
        loc = page.get_by_text(name, exact=True)
        if loc.count():
            log.append('탭 누름: %s (같은 글자 %d개 중 첫째) %s' % (name, loc.count(), loc.first.evaluate('e => e.outerHTML.slice(0, 200)')))
            loc.first.click(timeout=8000)
            page.wait_for_load_state('networkidle', timeout=20000)
            page.wait_for_timeout(1500)
            return name
    raise RuntimeError('탭을 못 찾음: ' + ', '.join(names))


def click_search(page, log):
    """탭만 눌러서는 목록이 안 바뀌는 곳을 위해 '검색'·'조회' 단추를 누른다. 머리글(header·nav)의 검색은 건너뛴다."""
    for name in ('검색', '조회'):
        loc = page.get_by_role('button', name=name, exact=True).or_(page.get_by_text(name, exact=True))
        for k in range(min(loc.count(), 10)):
            el = loc.nth(k)
            if el.is_visible() and not el.evaluate("e => !!e.closest('header, nav, #header, .header, .gnb')"):
                log.append('단추 누름: %s %s' % (name, el.evaluate('e => e.outerHTML.slice(0, 200)')))
                el.click(timeout=8000)
                page.wait_for_load_state('networkidle', timeout=20000)
                page.wait_for_timeout(1500)
                return True
    log.append('누를 검색·조회 단추가 없어요')
    return False


def same_as(rows, others):
    """앞 20곡 번호가 이번에 모은 다른 목록과 똑같으면 그 목록 이름 (탭이 안 바뀐 것)"""
    head = [x[0] for x in rows[:20]]
    return next((k for k, v in others.items() if len(head) >= 10 and [x[0] for x in v[:20]] == head), None)


def read_page(page, caught, log):
    """먼저 사이트가 받아 온 JSON에서, 없으면 화면 글자에서 곡 줄을 읽는다 → (곡 줄, 읽은 곳)"""
    got, via = [], ''
    for r in caught:
        if r.request.resource_type not in ('xhr', 'fetch') and 'json' not in (r.headers.get('content-type') or ''):
            continue
        try:
            body = r.text()
        except Exception as e:
            log.append('  응답 %s %s → 내용을 못 읽음 (%s)' % (r.request.method, r.url[:150], str(e).splitlines()[0][:80]))
            continue
        j = []
        if body.lstrip()[:1] in ('{', '['):  # content-type이 json이 아니어도 JSON이면 읽는다
            try:
                j = parse_json(json.loads(body))
            except Exception:
                pass
        log.append('  응답 %s %s [%s, %s, %d자] → 곡 %d줄' % (r.request.method, r.url[:150], r.status, r.headers.get('content-type', ''), len(body), len(j)))
        if r.request.post_data:
            log.append('    보낸 값: ' + r.request.post_data[:300])
        log.append('    앞부분: ' + re.sub(r'\s+', ' ', body[:300]))
        if len(j) > len(got):
            got, via = j, 'JSON ' + r.url.split('?')[0][-60:]
    if len(got) >= 10:
        return got, via
    best, scored, win = [], [], None
    for c in page.evaluate(CANDS_JS):
        p = parse_rows(c['rows'])
        scored.append((len(p), c))
        if len(p) > len(best):
            best, via, win = p, '화면 ' + c['where'][-80:], c
    if win:
        stats = {'full': 0, 'cut': 0}
        parse_rows(win['rows'], stats)
        if stats['full'] or stats['cut']:
            via += ' · 잘린 제목: 전체 찾음 %d, 뒤 정리 %d' % (stats['full'], stats['cut'])
    scored.sort(key=lambda x: (-x[0], -len(x[1]['rows'])))
    log.append('  화면 줄 묶음 후보 %d개 (곡이 많이 읽힌 순, 앞 8개)' % len(scored))
    for k, (n, c) in enumerate(scored[:8], 1):
        log.append('  [%d] %s · %d줄 → 곡 %d줄' % (k, c['where'], len(c['rows']), n))
        for row in c['rows'][:3]:
            log.append('      | ' + ' | '.join(t[:40] + ('{%s}' % h.strip('>')[-40:] if h.strip('>') else '') for t, h in row[:14]))
    return best, via


def collect(page, lid, urls, tabs, others, log):
    rows, vias = [], []
    need = MIN_ROWS.get(lid, 20)
    for url in urls:
        caught = []
        handler = lambda r, c=caught: c.append(r)  # Playwright는 내장 함수(caught.append)를 바로 못 받는다
        page.on('response', handler)
        try:
            log.append('== 주소: ' + url)
            page.goto(url, wait_until='networkidle', timeout=45000)
            page.wait_for_timeout(1500)
            if tabs:
                caught.clear()
                click_tab(page, tabs, log)
            log.append('지금 주소: %s · 제목: %s' % (page.url, page.title()))
            got, via = read_page(page, caught, log)
            if lid in SEARCH and (len(got) < need or same_as(got, others)):
                log.append('목록이 안 바뀐 것 같아 검색 단추를 눌러 봐요 (%d곡, 같은 목록: %s)' % (len(got), same_as(got, others)))
                caught.clear()
                if click_search(page, log):
                    got, via = read_page(page, caught, log)
        finally:
            page.remove_listener('response', handler)
        rows += [x for x in got if x[0] not in {y[0] for y in rows}]
        vias.append(via)
    if len(rows) < need:
        raise RuntimeError('%d곡만 읽혔어요 (최소 %d곡)' % (len(rows), need))
    same = same_as(rows, others)
    if same:
        raise RuntimeError('%s 목록과 똑같아요 — 탭이 안 바뀐 것 같아요' % same)
    return rows[:100], ' / '.join(dict.fromkeys(v for v in vias if v))


def save_debug(page, lid, err, log):
    """못 가져온 목록의 화면 모양을 debug 폴더에 남긴다 (요약 txt · html · 화면 jpg)"""
    DEBUG.mkdir(exist_ok=True)
    head = ['목록: ' + lid, '이유: ' + str(err).splitlines()[0][:300],
            '시각: ' + datetime.datetime.now(KST).strftime('%Y-%m-%d %H:%M KST'), '']
    (DEBUG / (lid + '.txt')).write_text('\n'.join(head + log) + '\n', encoding='utf-8')
    for name, save in ((lid + '.html', lambda p: p.write_text(page.content(), encoding='utf-8')),
                       (lid + '.jpg', lambda p: page.screenshot(path=str(p), full_page=True, type='jpeg', quality=50))):
        try:
            save(DEBUG / name)
        except Exception as e:
            with (DEBUG / (lid + '.txt')).open('a', encoding='utf-8') as f:
                f.write('%s 저장 실패: %s\n' % (name, str(e).splitlines()[0][:150]))


def main():
    old = json.loads(OUT.read_text(encoding='utf-8')) if OUT.exists() else {'lists': []}
    old_lists = {l['id']: l for l in old.get('lists', [])}
    new_rows, report = {}, []
    shutil.rmtree(DEBUG, ignore_errors=True)  # 지난번 실패 기록은 지우고 이번 것만 남긴다
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        page = br.new_context(locale='ko-KR', timezone_id='Asia/Seoul', viewport={'width': 1366, 'height': 900},
                              user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36').new_page()
        for lid, urls, tabs in SOURCES:
            log = []
            try:
                new_rows[lid], via = collect(page, lid, urls, tabs, new_rows, log)
                report.append('%-9s 성공 %3d곡  1위 %s  (%s)' % (lid, len(new_rows[lid]), new_rows[lid][0][1], via))
            except Exception as e:
                report.append('%-9s 실패 — %s (지난 목록 그대로)' % (lid, str(e).splitlines()[0][:150]))
                try:
                    save_debug(page, lid, e, log)
                    report.append('          화면 모양 저장: debug/%s.txt · .html · .jpg' % lid)
                except Exception as e2:
                    report.append('          화면 모양 저장 실패: %s' % str(e2).splitlines()[0][:150])
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
