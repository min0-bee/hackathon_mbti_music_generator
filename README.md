# 🎶 MBTI Song Generator (Streamlit Demo)

MBTI + 키워드 + 한 줄 메모 → 한국어 가사 생성 → (모의) 음악 재생까지 한 번에 보여주는 해커톤용 MVP입니다.

## 📦 설치
```bash
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 🔑 OpenAI 키 (선택)
- 실제 가사 생성을 위해 OpenAI를 사용하려면 환경변수 설정:
```bash
export OPENAI_API_KEY="sk-..."   # Windows(PowerShell): setx OPENAI_API_KEY "sk-..."
```
- 키가 없으면 **오프라인 데모 모드**로 동작하며, 템플릿 기반 가사를 생성합니다.

## ▶️ 실행
```bash
streamlit run app.py
```

## 🧩 구조
- `app.py` : Streamlit UI + 프롬프트 템플릿 + OpenAI 연동(옵션) + 모의 음악(사인파)
- `requirements.txt` : 최소 의존성
- `README.md` : 문서

## 🎛️ 커스터마이즈
- `MBTI_STYLE_MAP` 에서 MBTI 별 장르/템포를 조정하세요.
- `make_prompt()` 의 프롬프트를 팀 분위기에 맞게 수정하세요.
- 실제 음악 생성 API(Suno/Stable Audio 등)를 호출하고 싶다면,
  - `wav_bytes = generate_sine_music_bytes(...)` 부분을 API 호출로 바꾸고, 반환된 URL/바이너리를 `st.audio()`에 넣으세요.

## ⚠️ 주의
- 이 버전의 음악은 **모의 생성(사인파)**입니다. 해커톤에서 빠르게 동작 시연하기 위한 용도입니다.
- 가사 내용은 개인 비하/혐오 표현 없이, MBTI를 절대화하지 않는 톤을 권장합니다.
