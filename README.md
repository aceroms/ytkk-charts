# ytkk-charts

프로젝터의 **YouTube 노래방** 앱이 받아 가는 TJ·금영 노래방 인기곡 목록입니다 (개인 사용).

- 매달 4일 오전 10시쯤 GitHub Actions가 `collect.py`로 TJ·금영 사이트의 인기곡을 모아 `charts.json`을 새로 만듭니다.
- TV는 일주일에 한 번 `https://raw.githubusercontent.com/aceroms/ytkk-charts/main/charts.json`을 확인하고, 새 목록이면 "받을까요?"라고 물어봅니다.
- 목록 하나를 못 가져오면 그 목록은 지난 내용을 그대로 둡니다. 하나도 못 가져오면 Actions가 실패(빨간 표시)로 끝나고 `charts.json`은 바뀌지 않습니다.

## 처음 한 번 (핸드폰으로도 돼요)

1. github.com 오른쪽 위 `+` → **New repository**
   - Repository name: `ytkk-charts`
   - **Public** (TV가 키 없이 받으려면 공개여야 해요. 곡 번호·제목·가수만 들어 있어요)
   - Create repository
2. 저장소 화면에서 **uploading an existing file** → `charts.json`, `collect.py`, `README.md` 올리기 → Commit changes
3. **Add file → Create new file**
   - 파일 이름 칸에 `.github/workflows/charts.yml` 그대로 입력 (슬래시를 넣으면 폴더가 만들어져요)
   - `charts.yml` 내용을 붙여 넣고 Commit changes
4. **Actions** 탭 → (처음이면 사용 허락 버튼) → 왼쪽 **인기곡 모으기** → **Run workflow**
   - 초록색 ✓: 성공. 실행 기록의 `TJ·금영 인기곡 모으기` 단계에서 목록마다 "성공 100곡 / 실패 — 이유"를 볼 수 있어요
   - 빨간색 ✗: 아래 '안 될 때' 참고
5. TV: 노래방 → 설정 → **인기곡 지금 확인** → "새 인기곡 목록이 있어요" → 받기

## 파일

| 파일 | 내용 |
|---|---|
| `charts.json` | TV가 받는 목록. 처음 파일은 앱에 들어 있던 11월 12일 목록과 같아요 (그래서 TV가 묻지 않아요) |
| `collect.py` | 모으는 프로그램 (Python + Playwright). 위쪽 `SOURCES`에 주소와 누를 탭 이름이 있어요 |
| `.github/workflows/charts.yml` | 매달 자동 실행 설정 |
| `debug/` | 못 가져온 목록의 화면 모양 (목록.txt 요약 · .html · .jpg). 다 성공하면 없어져요 |

## charts.json 모양

```json
{
  "version": "2026-12-04",
  "label": "12월 4일",
  "lists": [
    { "id": "ky100", "title": "금영 인기 TOP 100", "kw": "금영 인기", "big": "100", "src": "금영",
      "sub": "금영 월간 인기곡", "c": ["#c93f27", "#fff4ef"], "br": "KY",
      "rows": [[55791, "나는 반딧불", "황가람"]] }
  ]
}
```

TV는 받기 전에 모양을 검사해요: version은 `YYYY-MM-DD`, 목록 1~12개, 목록마다 곡 5~200개, `br`은 `TJ`/`KY`, `src`는 `TJ`/`금영`, 색은 `#rrggbb` 두 개. 하나라도 어긋나면 받지 않고 지금 목록을 그대로 써요.

## 안 될 때

- **사이트가 GitHub 서버를 막는 경우**: 곡 목록을 모으는 다른 저장소(kirin765/norebang-data)도 가끔 이런 일이 있어 PC에서 모은다고 해요. 그럴 때는 Windows PC에서:
  ```
  pip install "playwright>=1.50"
  python -m playwright install chromium
  python collect.py
  ```
  만들어진 `charts.json`을 저장소에 다시 올리면(Upload files) 돼요.
- **'실패 — 탭을 못 찾음'**: 사이트의 탭 이름이 바뀐 거예요. `collect.py`의 `SOURCES`에서 이름을 화면에 보이는 글자로 고쳐요.
- **'○곡만 읽혔어요'·'○○ 목록과 똑같아요'**: 사이트 화면 모양이 바뀌었거나 탭이 안 눌린 거예요. 저장소의 `debug/목록.txt`(예: `debug/kyjp.txt`)에 그 화면에서 읽은 줄들이 남아 있어요. AI에게 그 파일을 보여 주고 `collect.py`를 고쳐 달라고 하세요.
- 공개 저장소에 60일 동안 아무 변화가 없으면 GitHub이 예약 실행을 멈출 수 있어요. 메일이 오면 Actions 탭에서 다시 켜 주세요.
