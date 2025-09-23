# -*- coding: utf-8 -*-
import os
from io import BytesIO
import wave
import numpy as np
import pandas as pd
import streamlit as st
import gspread
from datetime import datetime

# Google Auth (secrets 우선, 없으면 json 파일 사용)
USE_SECRETS = False
try:
    from google.oauth2.service_account import Credentials  # secrets 방식
    if "gcp_service_account" in st.secrets:
        USE_SECRETS = True
except Exception:
    USE_SECRETS = False

# oauth2client (json 파일 방식)
try:
    from oauth2client.service_account import ServiceAccountCredentials
    OAUTH2CLIENT_AVAILABLE = True
except Exception:
    OAUTH2CLIENT_AVAILABLE = False

# OpenAI (가사 생성 옵션)
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except Exception:
    OPENAI_AVAILABLE = False

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
HEADERS = ["timestamp","user_id","mbti","keywords","joy","energy","personal_line",
           "satisfaction","mbti_match","played","lyrics_lines","lyrics"]

@st.cache_resource
def connect_gsheet(sheet_name: str):
    """secrets.toml이 있으면 google-auth, 없으면 json 파일(oauth2client) 사용."""
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    # 1. Streamlit secrets 사용
    if hasattr(st, "secrets") and "gcp_service_account" in st.secrets:
        creds = Credentials.from_service_account_info(
            dict(st.secrets["gcp_service_account"]), scopes=scopes
        )
        client = gspread.authorize(creds)

    # 2. 로컬 json 키 사용 (python app.py 같은 경우)
    else:
        if not OAUTH2CLIENT_AVAILABLE:
            raise RuntimeError("oauth2client가 설치되지 않았어요. pip install oauth2client 또는 secrets 설정을 사용하세요.")
        json_path = "gcp_service_key.json"
        if not os.path.exists(json_path):
            raise FileNotFoundError("gcp_service_key.json 파일을 찾을 수 없습니다 (앱 폴더에 두세요).")
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(json_path, scope)
        client = gspread.authorize(creds)

    sheet = client.open(sheet_name).sheet1
    # 헤더 보장
    values = sheet.get_all_values()
    if not values:
        sheet.append_row(HEADERS, value_input_option="USER_ENTERED")
    return sheet



SHEET_NAME = "mbti_song_data"  # 너의 구글시트 이름
sheet = connect_gsheet(SHEET_NAME)

def append_row_to_sheet(sheet, payload: dict):
    """Google Sheet에 한 행 추가."""
    row = [
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
    ]
    sheet.append_row(row, value_input_option="USER_ENTERED")

# -----------------------------
# LLM 프롬프트/폴백
# -----------------------------
def make_prompt(mbti, keywords, personal_line, joy, energy):
    style = mbti_style(mbti)
    tpl = f"""
Context: 당신은 한국어 가사 작사가입니다.
Task: 다음 조건을 충족하는 8줄의 한국어 가사를 작성하세요.
- MBTI: {mbti}
- 핵심특징(요약): 사용자는 "{mbti}"이며, 일반적으로 알려진 {mbti} 성향을 가사에 부드럽게 녹여 표현합니다.
- 분위기/장르: {style['genre']}, 서정적, {style['tempo']} BPM 느낌
- 포함할 키워드: {', '.join(keywords) if keywords else '없음'}
- 사용자 한 줄 메모: {personal_line if personal_line.strip() else '없음'}
- 감정 강도: 기쁨 {joy}%, 에너지 {energy}%
- 라임 수준: 보통
- 시점: 2인칭(너) 또는 1인칭 혼용 가능
- 금지: 공격적/혐오/차별 표현 금지, 특정인 실명 언급 금지
Output: 가사만 출력 (설명/해설 없이)
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
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")
    client = OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.8,
        top_p=0.9,
    )
    return resp.choices[0].message.content.strip()

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

    keyword_options = ["겨울","여름밤","창가","외로움","설렘","도전","퇴근길","봄비","새벽","바다"]
    keywords = st.multiselect("키워드 선택 (최대 3개 권장)", keyword_options)
    personal_line = st.text_input("오늘의 기분/한 줄 메모", placeholder="예) 친구들이랑 바닷가에서 웃었어")

    c3, c4 = st.columns(2)
    with c3:
        joy = st.slider("기쁨(%)", 0, 100, 60)
    with c4:
        energy = st.slider("에너지(%)", 0, 100, 50)

    # 가사 생성
    if st.button("🎤 가사 생성하기", type="primary"):
        prompt = make_prompt(mbti, keywords, personal_line, joy, energy)
        use_openai = OPENAI_AVAILABLE and bool(os.environ.get("OPENAI_API_KEY","").strip())
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
        st.subheader("가사")
        st.text_area("생성된 가사", st.session_state["lyrics"], height=220)

        st.subheader("Music (Demo)")
        if not st.session_state["played"]:
            if st.button("▶️ 음악 재생"):
                st.session_state["played"] = True
                st.rerun()
        else:
            wav_bytes = generate_sine_music_bytes(duration_sec=8, base_freq=mbti_to_freq(mbti), tremolo=0.25)
            st.audio(wav_bytes, format="audio/wav")
            st.caption("※ 재생 버튼 클릭이 데이터로 기록됩니다.")

        # 피드백 수집
        mbti_match = st.checkbox("내 MBTI랑 잘 맞았어요")
        satisfaction = st.slider("만족도 (1~5)", 1, 5, 3)
        user_id = st.text_input("닉네임/학번 (선택)", value="")

        if st.button("📨 제출(데이터 저장)"):
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
            }
            try:
                append_row_to_sheet(sheet, payload)
                st.success("제출 완료! Google Sheets에 저장되었습니다.")
                # 다음 사용자를 위해 재생 상태만 초기화(가사는 남겨둠)
                st.session_state["played"] = False
            except Exception as e:
                st.error(f"저장 실패: {e}")

    with st.expander("프롬프트 보기", expanded=False):
        # 마지막 프롬프트 미리보기 (생성 이전엔 예시 표시)
        preview = make_prompt(mbti, keywords, personal_line, joy, energy)
        st.code(preview, language="markdown")

elif mode == "대시보드":
    st.header("Dashboard (Live from Google Sheets)")
    try:
        records = sheet.get_all_records()
        if not records:
            st.info("아직 데이터가 없습니다.")
        else:
            df = pd.DataFrame(records)

            # 숫자형 변환
            for col in ["joy","energy","satisfaction","lyrics_lines"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")

            st.subheader("최근 데이터 (Latest rows)")
            st.dataframe(df.tail())

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
