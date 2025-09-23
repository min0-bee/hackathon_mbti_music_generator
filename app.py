# -*- coding: utf-8 -*-
import os
from io import BytesIO
import wave
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import streamlit as st
import gspread
from datetime import datetime
import urllib.parse as _u
from textwrap import dedent
import requests, time, json



# OpenAI (가사 생성 옵션)
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except Exception:
    OPENAI_AVAILABLE = False



# 세션 상태 초기화
if "lyrics" not in st.session_state:
    st.session_state["lyrics"] = ""
if "played" not in st.session_state:
    st.session_state["played"] = False
if "start_time" not in st.session_state:   # 페이지 뷰 시작 시간
    st.session_state["start_time"] = datetime.now()
if "button_clicks" not in st.session_state:
    st.session_state["button_clicks"] = 0
if "visit_count" not in st.session_state:
    st.session_state["visit_count"] = 1
else:
    st.session_state["visit_count"] += 1
if "sharing" not in st.session_state:
    st.session_state["sharing"] = False

# 세션 시간대 계산 (제출/공유 공통 사용)
hour = datetime.now().hour
if 6 <= hour < 12:
    session_time = "morning"
elif 12 <= hour < 18:
    session_time = "afternoon"
elif 18 <= hour < 24:
    session_time = "evening"
else:
    session_time = "night"

# -----------------------------
# 기본 설정
# -----------------------------
st.set_page_config(page_title="MBTI Song Generator", page_icon="🎶", layout="centered")
st.title("MBTI Song Generator 🎶")

MBTI_OPTIONS = [
    "INTJ","INTP","ENTJ","ENTP",
    "INFJ","INFP","ENFJ","ENFP",
    "ISTJ","ISFJ","ESTJ","ESFJ",
    "ISTP","ISFP","ESTP","ESFP",
]

MBTI_STYLE_MAP = {
    "INFP": {"genre": "lofi ballad", "tempo": 70},
    "INFJ": {"genre": "warm ballad", "tempo": 72},
    "ENFP": {"genre": "bright pop", "tempo": 112},
    "ENTP": {"genre": "indie pop", "tempo": 118},
    "INTJ": {"genre": "minimal electronic", "tempo": 90},
    "INTP": {"genre": "ambient electronic", "tempo": 85},
    "ENTJ": {"genre": "cinematic pop", "tempo": 110},
    "ENFJ": {"genre": "soft pop", "tempo": 100},
    "ISTJ": {"genre": "acoustic folk", "tempo": 85},
    "ISFJ": {"genre": "piano ballad", "tempo": 78},
    "ESTJ": {"genre": "rock pop", "tempo": 120},
    "ESFJ": {"genre": "city pop", "tempo": 108},
    "ISTP": {"genre": "chill hop", "tempo": 88},
    "ISFP": {"genre": "dream pop", "tempo": 95},
    "ESTP": {"genre": "electro pop", "tempo": 122},
    "ESFP": {"genre": "dance pop", "tempo": 125},
}

def mbti_style(mbti: str):
    return MBTI_STYLE_MAP.get(mbti, {"genre": "pop", "tempo": 100})

# -----------------------------
# Google Sheets 연결
# -----------------------------
HEADERS = [
  "timestamp","user_id","mbti","keywords","joy","energy","personal_line",
  "satisfaction","mbti_match","played","lyrics_lines","lyrics",
  # --- new: burnout light + post satisfaction ---
  "bo_exhaust","bo_cynicism","bo_burden","bo_anger","bo_fatigue","bo_sleep",  
  "burnout_score","burnout_level",              # 합계, 'low/moderate/high'
  "would_return", "page_view_time","button_clicks","revisit","sharing","session_time"                          # 0~10, TRUE/FALSE
]


@st.cache_resource
def connect_gsheet(sheet_name: str):
    # 1) secrets 필수 체크
    if "gcp_service_account" not in st.secrets:
        raise RuntimeError(
            "gcp_service_account 시크릿이 없습니다. Streamlit Cloud > Settings > Secrets 에 서비스 계정 JSON을 TOML로 넣어주세요."
        )

    # 2) gspread + google-auth로 연결
    try:
        gc = gspread.service_account_from_dict(dict(st.secrets["gcp_service_account"]))
        sh = gc.open(sheet_name)
        return sh.sheet1
    except Exception as e:
        # 앱이 통째로 죽지 않도록 메시지 표기
        st.error(f"Google Sheets 연결 실패: {e}")
        raise


SHEET_NAME = "mbti_song_data"  # 너의 구글시트 이름
sheet = connect_gsheet(SHEET_NAME)

def append_row_to_sheet(sheet, payload: dict):
    """Google Sheet에 한 행 추가. HEADERS 순서와 1:1 매칭"""
    row = [
        # 1~12
        datetime.now().isoformat(),
        payload.get("user_id",""),
        payload["mbti"],
        ",".join(payload["keywords"]),
        payload["joy"],
        payload["energy"],
        payload["personal_line"],
        payload["satisfaction"],
        payload["mbti_match"],
        payload["played"],
        payload["lyrics_lines"],
        payload["lyrics"],

        # 13~20 (번아웃 관련)
        payload["bo_exhaust"],
        payload["bo_cynicism"],
        payload["bo_burden"],
        payload["bo_anger"],
        payload["bo_fatigue"],
        payload["bo_sleep"],
        payload["burnout_score"],
        payload["burnout_level"],

        # 21 (would_return)
        payload["would_return"],

        # 22~27 (신규 6개 지표: 필수!)
        payload["page_view_time"],
        payload["button_clicks"],
        payload["revisit"],
        payload["sharing"],
        payload["session_time"],
    ]
    sheet.append_row(row, value_input_option="USER_ENTERED")


# -----------------------------
# share
# -----------------------------


def render_share_ui(user_id: str):
    share_url = build_share_link(user_id)
    st.session_state["sharing"] = True  # 로그용 플래그

    st.success("추천 링크가 준비됐어요. 복사해서 친구에게 보내보세요!")
    st.text_input("추천 링크", value=share_url, disabled=True)

    # Copy / WebShare (모바일) 둘 다 지원하는 작은 위젯
    html = f"""
    <div style="display:flex;gap:8px;align-items:center;">
      <button id="copyBtn">📋 링크 복사</button>
      <button id="shareBtn">🔗 시스템 공유</button>
      <span id="msg" style="margin-left:8px;color:gray;"></span>
    </div>
    <script>
      const url = {share_url!r};
      const msg = document.getElementById('msg');
      document.getElementById('copyBtn').onclick = async () => {{
        try {{
          await navigator.clipboard.writeText(url);
          msg.textContent = "복사됨!";
        }} catch (e) {{
          msg.textContent = "복사 실패… (수동 복사 이용)";
        }}
      }};
      const shareBtn = document.getElementById('shareBtn');
      if (!navigator.share) {{
        shareBtn.style.display = 'none';
      }} else {{
        shareBtn.onclick = async () => {{
          try {{
            await navigator.share({{ title: "MBTI Song Generator", url }});
          }} catch (e) {{}}
        }};
      }}
    </script>
    """
    st.components.v1.html(html, height=60)


def build_share_link(user_id: str = "") -> str:
    # 배포 주소 (끝 슬래시는 제거)
    base = "https://hackathonmbtimusicgenerator.streamlit.app"
    ref = (user_id or "anon").strip()
    return f"{base}?ref={_u.quote(ref)}"


# -----------------------------
# 번아웃 점수
# -----------------------------
def burnout_level(score: int, max_score: int):
    # 6문항 × 1~5점 = 6~30점
    if max_score == 30:
        if score >= 20:
            return "high"
        elif score >= 10:
            return "moderate"
        else:
            return "low"
    # fallback (기타 문항 수일 때)
    pct = score / max_score
    if pct >= 0.75:
        return "high"
    elif pct >= 0.5:
        return "moderate"
    return "low"

def burnout_feedback(level: str) -> str:
    if level == "high":
        return "🌧️ 비 : 많이 지쳐 계시네요. 🛑 지금은 잠시 멈추고 쉼이 필요합니다. 음악을 같이 들어볼까요?"
    elif level == "moderate":
        return "🌫️ 안개 : 나쁘지 않습니다. 하지만 번아웃의 신호가 보입니다. ⚖️ 잠깐의 휴식과 전환이 도움이 될 거예요."
    else:  # low
        return "☀️ 맑음 : 컨디션이 비교적 안정적이시네요. 🌿 음악으로 지금의 에너지를 더 채워보세요!"


# -----------------------------
# LLM 프롬프트/폴백
# -----------------------------

def get_openai_api_key() -> str:
    # 1) Streamlit secrets 우선
    try:
        key = st.secrets["openai"]["api_key"]
        if key:
            return key.strip()
    except Exception:
        pass
    # 2) 환경변수 fallback
    return os.environ.get("OPENAI_API_KEY", "").strip()



def make_prompt(mbti, keywords, personal_line, joy, energy):
    style = mbti_style(mbti)
    tpl = f"""
Context: 당신은 퍼스널 작사가입니다.

Task: 아래 조건을 바탕으로 한 **완성된 노래 가사**를 작성해주세요.
- MBTI: {mbti} 사용자의 MBTI에 어울리는 가사여야함.
- 분위기/장르: {style['genre']} / BPM: {style['tempo']}
- 포함할 키워드: {', '.join(keywords) if keywords else '없음'}.
- 사용자 입력 기분: {personal_line if personal_line.strip() else '없음'}. 가사에 사용자의 입력 기분이 반영되어야함.
- 감정 강도: 기쁨 {joy}%, 에너지 {energy}%
- 금지: 공격적/혐오/차별 표현 금지, 특정인 실명 언급 금지

형식:
1. 노래 제목 (예: "'{mbti}를 위한 선선한 여름밤의 사유'")
2. (Verse 1) … 가사 …
3. (Chorus) … 가사 …
4. (Verse 2) … 가사 …
5. (Bridge) … 가사 …
6. (Outro) … 가사 …

마지막에 "가사를 생성한 이유:"라는 문단을 두 줄로 작성해주세요.

Output: 위 형식을 반드시 따라 작성해주세요.
"""
    return tpl.strip()


def fallback_lyrics(mbti, keywords, personal_line, joy, energy):
    k = ", ".join(keywords) if keywords else "오늘"
    memo = personal_line or "마음을 적어봤어"
    lines = [
        f"겉은 차갑지만 속은 조용히 데워지는 {mbti}의 밤",
        f"{k}이라는 단어가 창가에서 흩날려",
        f"말없이 걷지만 발끝엔 작은 리듬",
        f"너를 떠올리면 심장 박동이 맞춰져",
        f"기쁨 {joy}% 에너지 {energy}%의 온도계가 흔들려도",
        f"나는 끝내 손을 뻗어 불을 켜고",
        f"{memo}라는 메모를 가슴 주머니에 넣어",
        f"내일의 내가 오늘의 나를 안아주길"
    ]
    return "\n".join(lines)

def call_openai(prompt: str):
    if not OPENAI_AVAILABLE:
        raise RuntimeError("OpenAI SDK not available")
    api_key = get_openai_api_key()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set (secrets 또는 env)")
    client = OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.8,
        top_p=0.9,
    )
    return resp.choices[0].message.content.strip()


# -----------------------------
# suno api 음악 생성
# -----------------------------
def get_suno_api_key() -> str:
    try:
        return st.secrets["suno"]["api_key"].strip()
    except Exception:
        return os.environ.get("SUNO_API_KEY", "").strip()
    

import re
from textwrap import dedent

def _extract_title_and_body(lyrics_text: str) -> tuple[str, str]:
    """
    네 LLM 출력 형식(1. 제목 / 2~6. 섹션)에서 제목과 본문만 뽑아 Suno에 넣기 좋게 정리.
    """
    title = "Untitled"
    body  = lyrics_text.strip()

    # 1) "1. 노래 제목" 라인 찾기 (여러 패턴 방어적으로)
    m = re.search(r"^\s*1\.\s*(?:노래\s*제목|Title)\s*[:：]?\s*(.+)$", lyrics_text, flags=re.M|re.I)
    if m:
        title = m.group(1).strip().strip('"').strip("「」'“”")
    else:
        # 첫 줄이 제목처럼 보이면 사용
        first = lyrics_text.strip().splitlines()[0]
        if 3 <= len(first) <= 60:
            title = first.strip().strip('"').strip("「」'“”")

    # 2) "가사를 생성한 이유:" 이하 삭제 (Suno엔 불필요)
    body = re.split(r"\n\s*가사를\s*생성한\s*이유\s*:\s*", body, flags=re.I)[0].strip()

    # 3) 번호/헤더 제거(선택) + 섹션 헤더는 유지
    #   - Verse/Chorus/Bridge/Outro 라벨은 남겨두면 보컬/구성 힌트가 됨
    #   - "2. (Verse 1) ..." → "(Verse 1) ..." 로만 정리
    body = re.sub(r"^\s*\d+\.\s*", "", body, flags=re.M)
    return title or "Untitled", body

def _mbti_audio_hints(mbti: str) -> dict:
    style = mbti_style(mbti)
    # 각 MBTI에 약간의 악기/무드 태그 추가 (원하면 자유롭게 가감)
    add = {
        "INFP":  {"instruments": ["soft piano","warm pad","vinyl hiss"], "mood": ["intimate","nostalgic"]},
        "INFJ":  {"instruments": ["piano","strings"], "mood": ["warm","reflective"]},
        "ENFP":  {"instruments": ["acoustic guitar","shaker"], "mood": ["bright","uplifting"]},
        "ENTP":  {"instruments": ["clean electric guitar","synth lead"], "mood": ["playful","energetic"]},
        "INTJ":  {"instruments": ["minimal synth","sub bass"], "mood": ["focused","cinematic"]},
        "INTP":  {"instruments": ["ambient pad","plucks"], "mood": ["airy","thoughtful"]},
        "ENTJ":  {"instruments": ["cinematic drums","piano"], "mood": ["confident","grand"]},
        "ENFJ":  {"instruments": ["soft keys","light percussion"], "mood": ["gentle","hopeful"]},
        "ISTJ":  {"instruments": ["acoustic guitar","upright bass"], "mood": ["steady","calm"]},
        "ISFJ":  {"instruments": ["piano","strings"], "mood": ["comforting","warm"]},
        "ESTJ":  {"instruments": ["rock drums","electric bass"], "mood": ["driving","bold"]},
        "ESFJ":  {"instruments": ["city-pop keys","funk bass"], "mood": ["groovy","friendly"]},
        "ISTP":  {"instruments": ["lofi kit","bass"], "mood": ["chill","cool"]},
        "ISFP":  {"instruments": ["dreamy synth","reverb guitar"], "mood": ["tender","dreamy"]},
        "ESTP":  {"instruments": ["edm drums","synth bass"], "mood": ["energetic","fun"]},
        "ESFP":  {"instruments": ["dance kit","plucky synth"], "mood": ["party","vivid"]},
    }.get(mbti, {"instruments": ["piano","pad"], "mood": ["balanced"]})

    return {
        "genre": style["genre"],
        "bpm": style["tempo"],
        "instruments": add["instruments"],
        "mood": add["mood"],
    }

def _build_suno_prompt(
    lyrics_text: str,
    mbti: str,
    keywords: list[str] | None = None,
    joy: int = 50,
    energy: int = 50
) -> tuple[str, str]:

    """
    Suno로 보낼 'prompt' 문자열과 'title'을 구성해서 반환.
    (Suno API payload의 prompt/title에 그대로 넣으면 됨)
    """
    title, body = _extract_title_and_body(lyrics_text)
    hints = _mbti_audio_hints(mbti)
    kwords = ", ".join(keywords or []) or "none"

    prompt = dedent(f"""
    [Song Title]
    {title}

    [Target Style]
    Genre: {hints['genre']}
    BPM: {hints['bpm']}
    Instruments: {", ".join(hints['instruments'])}
    Mood: {", ".join(hints['mood'])}
    Keywords: {kwords}
    Joy: {joy}%, Energy: {energy}%

    [Structure]
    Keep sections in singing flow (Verse/Chorus/Bridge/Outro).
    Keep melody and harmony cohesive with the lyrics mood and BPM.
    Simple, memorable topline; avoid excessive runs.

    [Vocal]
    Pop/indie-friendly lead vocal; natural phrasing; light reverb.
    Korean lyrics; clear diction; avoid explicit content.

    [Mixing]
    Balanced mix; vocal forward but not harsh; gentle compression; soft limiter.

    [Lyrics]
    {body}
    """).strip()

    return prompt, title


def generate_music_with_suno(lyrics: str, mbti: str, title: str = "") -> dict:
    """
    Suno API로 곡 생성 → taskId 폴링 → 재생 가능한 URL 반환.
    return 예시: {"stream_url": "...", "audio_url": "...", "cover": "..."}
    """
    api_key = get_suno_api_key()
    if not api_key:
        raise RuntimeError("SUNO_API_KEY 가 설정되어 있지 않습니다. secrets.toml의 [suno].api_key 를 확인하세요.")

    headers = {"Authorization": f"Bearer {api_key}"}
    prompt = _build_suno_prompt(lyrics, mbti)
    payload = {
        "model": "V4_5", 
        # 최소 파라미터 (문서 기준)
        "prompt": prompt,
        "title": title or f"{mbti} Song",
        # 태그에는 장르 위주로
        "tags": mbti_style(mbti)["genre"],
        # 커스텀 모드(가사/스타일 반영용)와 보컬 포함 기본값
        "customMode": True,
        "instrumental": False,
        "callBackUrl": "https://example.com/callback"  # 더미 URL


    }

    # 1) 생성 요청
    r = requests.post("https://api.sunoapi.org/api/v1/generate", headers=headers, json=payload, timeout=30)
    r.raise_for_status()
    j = r.json()
    if j.get("code") != 200 or "data" not in j or "taskId" not in j["data"]:
        raise RuntimeError(f"Suno generate 응답 비정상: {j}")
    task_id = j["data"]["taskId"]

    # 2) 상태 폴링 (스트리밍 URL이 보통 더 빨리 준비됨)
    stream_url, audio_url, cover = None, None, None
    for _ in range(40):  # 최대 약 2분 폴링(2s * 60)
        time.sleep(2)
        q = requests.get(
            "https://api.sunoapi.org/api/v1/generate/record-info",
            headers=headers,
            params={"taskId": task_id},
            timeout=20
        )
        if q.status_code != 200:
            continue
        info = q.json()
        data = (info or {}).get("data", {})
        status = data.get("status", "")
        resp = (data.get("response") or {})
        items = (resp.get("sunoData") or [])  # 여러 트랙이 올 수 있음

        # URL 추출
        for it in items:
            stream_url = stream_url or it.get("streamAudioUrl")
            audio_url = audio_url or it.get("audioUrl")
            cover      = cover or it.get("imageUrl")

        if status in ("FIRST_SUCCESS", "SUCCESS") and (stream_url or audio_url):
            break
        if status in ("CREATE_TASK_FAILED", "GENERATE_AUDIO_FAILED", "SENSITIVE_WORD_ERROR"):
            raise RuntimeError(f"Suno 작업 실패: status={status}, info={info}")

    if not (stream_url or audio_url):
        raise TimeoutError("Suno API가 제시간에 트랙 URL을 반환하지 못했습니다.")

    return {"stream_url": stream_url, "audio_url": audio_url, "cover": cover}



# -----------------------------
# (모의) 음악 생성: 사인파
# -----------------------------
def generate_sine_music_bytes(duration_sec=8, sample_rate=22050, base_freq=440.0, tremolo=0.25):
    t = np.linspace(0, duration_sec, int(sample_rate * duration_sec), endpoint=False)
    glide = np.linspace(0, 1, t.size)
    freq = base_freq * (1 + 0.02 * glide)
    wave_arr = np.sin(2 * np.pi * freq * t) * (0.6 + tremolo * np.sin(2 * np.pi * 3 * t))
    wave_arr = (wave_arr / np.max(np.abs(wave_arr)) * 32767).astype(np.int16)
    buf = BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(wave_arr.tobytes())
    return buf.getvalue()

def mbti_to_freq(mbti: str):
    base = {
        "INFP": 392.0, "INFJ": 415.3, "ENFP": 523.3, "ENTP": 493.9,
        "INTJ": 349.2, "INTP": 329.6, "ENTJ": 440.0, "ENFJ": 466.2,
        "ISTJ": 293.7, "ISFJ": 311.1, "ESTJ": 587.3, "ESFJ": 554.4,
        "ISTP": 261.6, "ISFP": 277.2, "ESTP": 659.3, "ESFP": 622.3,
    }
    return base.get(mbti, 440.0)

# -----------------------------
# 세션 상태
# -----------------------------
if "lyrics" not in st.session_state:
    st.session_state["lyrics"] = ""
if "played" not in st.session_state:
    st.session_state["played"] = False

# -----------------------------
# 사이드바
# -----------------------------
with st.sidebar:
    st.markdown("### ⚙️ Settings")
    st.caption("OpenAI 키가 없으면 템플릿 가사로 폴백합니다.")
    mode = st.radio("모드 선택", ["가사 생성", "대시보드"])
    st.markdown("---")
    st.markdown("**데이터 수집 항목**")
    st.write("- MBTI/키워드/joy/energy/메모")
    st.write("- 만족도/MBTI 매칭/재생 클릭 여부")
    st.write("- 가사 줄 수/가사 텍스트")

# -----------------------------
# 본문: 두 모드
# -----------------------------

if mode == "가사 생성":


    col1, col2 = st.columns(2)
    with col1:
        mbti = st.selectbox("MBTI 선택", MBTI_OPTIONS, index=4)
    with col2:
        style = mbti_style(mbti)
        st.write(f"**자동 장르 제안:** {style['genre']} / **BPM 느낌:** {style['tempo']}")

    keyword_options = [
        # 기존 키워드
        "봄","여름밤","가을","겨울","창가","외로움","설렘","도전","퇴근길","봄비","새벽","바다",
        
        # 계절/풍경 관련
        "첫눈","단풍길","안개","별빛","노을","장마",
        
        # 시간/장소 관련
        "골목길","광주","지하철역","카페","밤하늘","캠핑장","내 방",
        
        # 감정/상태 관련
        "그리움","설원","추억","기다림","위로","자유","슬픔","행복",
        
        # 분위기/상징 관련
        "촛불","낙엽","파도","바람","흔적"
    ]
    keywords = st.multiselect("키워드 선택 (최대 3개 권장)", keyword_options)
    personal_line = st.text_input("오늘의 기분/한 줄 메모", placeholder="예) 친구들이랑 바닷가에 가서 행복한 시간을 보냈어.")

    c3, c4 = st.columns(2)
    with c3:
        joy = st.slider("기쁨(%)", 0, 100, 60)
    with c4:
        energy = st.slider("에너지(%)", 0, 100, 50)

    with st.expander("🧪 가벼운 번아웃 체크 (1분)", expanded=True):
        st.caption("참고: 의료 진단이 아닌 일상 컨디션 체크입니다.")
        options = [1, 2, 3, 4, 5]

        bo_exhaust   = st.radio("요즘 정서적 피로를 자주 느낀다", options, index=0, horizontal=True)
        bo_cynic     = st.radio("일/사람에 냉소적이거나 거리감이 느껴진다", options, index=0, horizontal=True)
        bo_burden    = st.radio("일하는 것에 심적 부담과 자신의 한계를 느낀다.", options, index=0, horizontal=True)
        bo_anger     = st.radio("이전에는 그냥 넘어가던 일에도 화를 참을 수 없다.", options, index=0, horizontal=True)
        bo_fatigue   = st.radio("만성피로, 감기나 두통, 요통, 소화불량이 늘었다.", options, index=0, horizontal=True)
        bo_sleep     = st.radio("충분한 시간의 잠을 자도 계속 피곤함을 느낀다.", options, index=0, horizontal=True)

        bo_answers = [bo_exhaust, bo_cynic, bo_burden, bo_anger, bo_fatigue, bo_sleep]
        bo_score = int(sum(bo_answers))
        bo_level = burnout_level(bo_score, max_score=5 * len(bo_answers))

        


    # 가사 생성
    if st.button("🎤 가사 생성하기", type="primary"):
        st.session_state["button_clicks"] += 1
        prompt = make_prompt(mbti, keywords, personal_line, joy, energy)
        use_openai = OPENAI_AVAILABLE and bool(get_openai_api_key())
        with st.spinner("가사를 빚는 중..."):
            try:
                if use_openai:
                    lyrics = call_openai(prompt)
                else:
                    lyrics = fallback_lyrics(mbti, keywords, personal_line, joy, energy)
            except Exception as e:
                st.warning(f"OpenAI 호출 실패: {e}\n→ 오프라인 데모 가사로 대체합니다.")
                lyrics = fallback_lyrics(mbti, keywords, personal_line, joy, energy)
        st.session_state["lyrics"] = lyrics
        st.session_state["played"] = False  # 새 가사 생성 시 재생 상태 초기화

    # 결과 영역
    if st.session_state["lyrics"]:
        st.subheader("컨디션 지수")
        st.info(burnout_feedback(bo_level))
        st.subheader("가사")
        st.text_area("생성된 가사", st.session_state["lyrics"], height=220)

        # st.subheader("Music (Demo)")
        # if not st.session_state["played"]:
        #     if st.button("▶️ 음악 재생"):
        #         st.session_state["button_clicks"] += 1
        #         st.session_state["played"] = True
        #         st.rerun()
        # else:
        #     wav_bytes = generate_sine_music_bytes(duration_sec=8, base_freq=mbti_to_freq(mbti), tremolo=0.25)
        #     st.audio(wav_bytes, format="audio/wav")
        #     st.caption("※ 재생 버튼 클릭이 데이터로 기록됩니다.")
        st.subheader("Music (Suno AI)")
        if not st.session_state.get("played"):
            if st.button("▶️ 음악 생성 & 재생", type="primary"):
                st.session_state["button_clicks"] += 1
                with st.spinner("Suno AI로 음악 생성 중... (스트리밍 준비까지 ~40초 예상)"):
                    try:
                        out = generate_music_with_suno(
                            lyrics=st.session_state["lyrics"],
                            mbti=mbti,
                            title=f"{mbti} - {mbti_style(mbti)['genre']}"
                        )
                        # 스트리밍이 먼저면 그걸 재생, 없으면 mp3
                        st.session_state["audio_url"] = out.get("stream_url") or out.get("audio_url")
                        st.session_state["cover_url"] = out.get("cover")
                        st.session_state["played"] = True
                        st.rerun()
                    except Exception as e:
                        st.error(f"Suno API 실패: {e}")
        else:
            # 준비된 URL 재생
            if url := st.session_state.get("audio_url"):
                st.audio(url)
                if st.session_state.get("cover_url"):
                    st.image(st.session_state["cover_url"], caption="Cover Art", use_container_width=True)
                st.caption("※ Suno AI가 생성한 음악입니다.")
                # 생성 다운로드
                # 🔽 MP3 다운로드 버튼 (audio_url로 바로 바이트 받아서 내려줌)
                try:
                    if "audio_bytes" not in st.session_state:
                        r = requests.get(url, timeout=120)
                        r.raise_for_status()
                        st.session_state["audio_bytes"] = r.content
                    fname = f"{st.session_state.get('song_title','MBTI_Song')}.mp3".replace("/", "_")
                    st.download_button("💾 MP3 다운로드",
                                    data=st.session_state["audio_bytes"],
                                    file_name=fname,
                                    mime="audio/mpeg")
                except Exception:
                    # 아직 mp3가 준비 전이거나 네트워크 이슈면 링크라도 제공
                    st.link_button("🔗 새 탭에서 열기", url)

            else:
                st.warning("아직 음악 URL이 없습니다.")


        # 피드백 수집
        user_id     = st.text_input("닉네임(선택)", value="")
        mbti_match  = st.checkbox("내 MBTI랑 잘 맞았어요")
        # 만족도/재방문 의향
        # nps = st.slider("추천 의향 (0~10)", 0, 10, 7)
        would_return = st.checkbox("다시 이용하고 싶어요")
        st.subheader("음악이 나와 어울리나요?")
        satisfaction = st.slider("만족도 (1~5)", 1, 5, 3)  # ← 범위 1~5로 통일

        # 번아웃 점수/레벨 (6문항 합산)
        bo_score = int(bo_exhaust + bo_cynic + bo_burden + bo_anger + bo_fatigue + bo_sleep)
        bo_level = burnout_level(bo_score, max_score=5 * 6)  # ← 6문항 × 5점 만점



        if st.button("📨 제출(데이터 저장)"):
            page_view_time = (datetime.now() - st.session_state["start_time"]).seconds
            payload = {
                "user_id": user_id.strip(),
                "mbti": mbti,
                "keywords": keywords,
                "joy": int(joy),
                "energy": int(energy),
                "personal_line": personal_line.strip(),
                "satisfaction": int(satisfaction),
                "mbti_match": bool(mbti_match),
                "played": bool(st.session_state["played"]),
                "lyrics_lines": len(st.session_state["lyrics"].splitlines()),
                "lyrics": st.session_state["lyrics"],
                # --- burnout 추가 ---
                "bo_exhaust": int(bo_exhaust),
                "bo_cynicism": int(bo_cynic),
                "bo_burden": int(bo_burden),
                "bo_anger": int(bo_anger),
                "bo_fatigue": int(bo_fatigue),
                "bo_sleep": int(bo_sleep),
                "burnout_score": bo_score,
                "burnout_level": bo_level,
                # --- 만족도 추가 ---
                # "nps": int(nps),
                "would_return": bool(would_return),
                "page_view_time": page_view_time,
                "button_clicks": st.session_state["button_clicks"],
                "revisit": st.session_state["visit_count"] > 1,
                "sharing": st.session_state["sharing"],
                "session_time": session_time
            }
            try:
                append_row_to_sheet(sheet, payload)
                st.success("제출 완료! Google Sheets에 저장되었습니다.")
                st.session_state["played"] = False
            except Exception as e:
                st.error(f"저장 실패: {e}")

        if st.button("🔗 공유하기"):
            st.session_state["sharing"] = True
            payload = {
                "user_id": user_id.strip(),
                "mbti": mbti,
                "keywords": keywords,
                "joy": int(joy),
                "energy": int(energy),
                "personal_line": personal_line.strip(),
                "satisfaction": int(satisfaction),
                "mbti_match": bool(mbti_match),
                "played": bool(st.session_state["played"]),
                "lyrics_lines": len(st.session_state["lyrics"].splitlines()),
                "lyrics": st.session_state["lyrics"],
                "bo_exhaust": int(bo_exhaust),
                "bo_cynicism": int(bo_cynic),
                "bo_burden": int(bo_burden),
                "bo_anger": int(bo_anger),
                "bo_fatigue": int(bo_fatigue),
                "bo_sleep": int(bo_sleep),
                "burnout_score": bo_score,
                "burnout_level": bo_level,
                "would_return": bool(would_return),
                "page_view_time": (datetime.now() - st.session_state["start_time"]).seconds,
                "button_clicks": st.session_state["button_clicks"],
                "revisit": st.session_state["visit_count"] > 1,
                "sharing": True,
                "session_time": session_time
            }

            append_row_to_sheet(sheet, payload)
            render_share_ui(user_id)



    # with st.expander("프롬프트 보기", expanded=False):
    #     # 마지막 프롬프트 미리보기 (생성 이전엔 예시 표시)
    #     preview = make_prompt(mbti, keywords, personal_line, joy, energy)
    #     st.code(preview, language="markdown")

elif mode == "대시보드":
    st.header("Dashboard (Live from Google Sheets)")
    try:
        records = sheet.get_all_records()  # expected_headers 제거
        if not records:
            st.info("아직 데이터가 없습니다.")
        else:
            df = pd.DataFrame(records)

            # 숫자형 변환
            num_cols = [
                "joy","energy","satisfaction","lyrics_lines",
                "bo_exhaust","bo_cynicism","bo_burden","bo_anger","bo_fatigue","bo_sleep",
                "burnout_score","page_view_time","button_clicks"
            ]
            for col in num_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")


            # --- 불안정도(번아웃 강도) 계산 & 시각화 --------------------
            # burnout_score가 있으면 사용, 없으면 개별 문항 합산으로 보정
            MAX_SCORE = 30  # 6문항 × 5점
            MIN_SCORE = 6   # 6문항 × 1점
            bo_cols = ["bo_exhaust","bo_cynicism","bo_burden","bo_anger","bo_fatigue","bo_sleep"]

            # 숫자형 변환(추가)
            if "burnout_score" in df.columns:
                df["burnout_score"] = pd.to_numeric(df["burnout_score"], errors="coerce")
            for c in bo_cols:
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors="coerce")

            # 보정 계산: burnout_score가 없거나 전부 NaN이면 개별 문항 합산
            if "burnout_score" not in df.columns or df["burnout_score"].isna().all():
                if set(bo_cols).issubset(df.columns):
                    df["burnout_score"] = df[bo_cols].sum(axis=1)

            if "burnout_score" in df.columns and df["burnout_score"].notna().any():
                # anxiety_pct 산출 (0~100)
                df["anxiety_pct"] = (
                    ((df["burnout_score"] - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)) * 100
                ).clip(0, 100)

                st.subheader("불안정도(Anxiety Index)")
                avg_anx = float(df["anxiety_pct"].mean())
                st.metric("평균 불안정도", f"{avg_anx:.1f}%")
                st.progress(int(round(avg_anx)))

                # MBTI별 번아웃 수준 분포 (파이 차트: 평균 번아웃 점수 비율)
                st.subheader("MBTI별 번아웃 수준 분포")
                if "mbti" in df.columns:
                    burnout_by_mbti = (
                        df.dropna(subset=["burnout_score"])
                        .groupby("mbti")["burnout_score"]
                        .mean()
                        .sort_values()
                    )
                    if not burnout_by_mbti.empty:
                        # 팔레트 색상 생성 (예: Set3)
                        colors = cm.Set3(np.linspace(0, 1, len(burnout_by_mbti)))

                        fig, ax = plt.subplots()
                        ax.pie(
                            burnout_by_mbti.values,
                            labels=burnout_by_mbti.index,
                            autopct="%1.1f%%",
                            startangle=90,
                            counterclock=False,
                            colors=colors
                        )
                        st.pyplot(fig)
                    else:
                        st.caption("MBTI별 번아웃 평균을 계산할 데이터가 부족합니다.")
                else:
                    st.caption("MBTI 컬럼이 없어 MBTI별 분포를 표시할 수 없습니다.")

                # MBTI별 평균 불안정도 (막대 차트)
                if "mbti" in df.columns:
                    st.caption("MBTI별 평균 불안정도")
                    mbti_avg = (
                        df.dropna(subset=["anxiety_pct"])
                        .groupby("mbti")["anxiety_pct"]
                        .mean()
                        .sort_values(ascending=False)
                    )
                    if not mbti_avg.empty:
                        st.bar_chart(mbti_avg)
                    else:
                        st.caption("불안정도 평균을 계산할 데이터가 부족합니다.")
            else:
                st.caption("불안정도 데이터를 계산할 수 없습니다.")
            # ------------------------------------------------------------

            st.subheader("MBTI별 평균 만족도 (Average Satisfaction)")
            st.bar_chart(df.groupby("mbti")["satisfaction"].mean())

            st.subheader("MBTI별 키워드 비율 (Keyword Ratio)")
            if "keywords" in df.columns:
                kw_dummies = df["keywords"].str.get_dummies(sep=",")
                kw_by_mbti = pd.concat([df["mbti"], kw_dummies], axis=1).groupby("mbti").sum()
                st.dataframe(kw_by_mbti)

            st.subheader("Joy vs Energy (by MBTI)")
            st.scatter_chart(df, x="joy", y="energy", color="mbti")

            c1, c2 = st.columns(2)
            with c1:
                st.subheader("재생 클릭률 (Played rate)")
                played_rate = (df["played"].astype(str).str.lower().isin(["true","1"])).mean()
                st.write(f"{played_rate*100:.1f}%")
            with c2:
                st.subheader("MBTI 매칭 비율 (Matched rate)")
                match_rate = (df["mbti_match"].astype(str).str.lower().isin(["true","1"])).mean()
                st.write(f"{match_rate*100:.1f}%")
            
            st.subheader("최근 데이터 (Latest rows)")
            st.dataframe(df.tail())
    except Exception as e:
        st.error(f"대시보드를 불러오지 못했어요: {e}")


# # (선택) 통신 테스트
# with st.expander("🔧 Google Sheets 통신 테스트", expanded=False):
#     if st.button("테스트 행 추가"):
#         try:
#             append_row_to_sheet(sheet, {
#                 "user_id": "test",
#                 "mbti": "TEST",
#                 "keywords": ["ping"],
#                 "joy": 1, "energy": 2,
#                 "personal_line": "health check",
#                 "satisfaction": 3,
#                 "mbti_match": True,
#                 "played": True,
#                 "lyrics_lines": 1,
#                 "lyrics": "test line"
#             })
#             st.success("OK! 시트에 테스트 행이 추가됐어요.")
#         except Exception as e:
#             st.error(f"시트 연결 실패: {e}")