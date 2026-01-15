from langdetect import LangDetectException, detect


LANG_NAME_MAP = {
    "en": "English",
    "zh": "中文",
    "ja": "日本語",
    "ko": "한국어",
    "fr": "Français",
    "de": "Deutsch",
    "es": "Español",
    "pt": "Português",
    "it": "Italiano",
    "ru": "Русский",
    "ar": "العربية",
    "hi": "हिन्दी",
    "id": "Bahasa Indonesia",
    "th": "ไทย",
    "vi": "Tiếng Việt",
    "tr": "Türkçe",
    "nl": "Nederlands",
    "pl": "Polski",
    "sv": "Svenska",
}


def normalize_lang(lang_code: str | None) -> str:
    if not lang_code or not str(lang_code).strip():
        return "en"

    code = str(lang_code).strip().lower()
    if code in {"zh-cn", "zh-tw", "zh-hans", "zh-hant"}:
        return "zh"
    return code


def detect_lang(text: str) -> str:
    """Detect language code from text; fallback to English on failure."""
    try:
        code = detect(text or "")
    except LangDetectException:
        return "en"

    return normalize_lang(code)


def language_name(lang_code: str) -> str:
    """Return readable language name for a code."""
    return LANG_NAME_MAP.get(normalize_lang(lang_code), "English")
