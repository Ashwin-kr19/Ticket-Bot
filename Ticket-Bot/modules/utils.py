import json
from deep_translator import GoogleTranslator

def load_api_keys():
    try:
        with open('api_keys.json', 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading API keys: {e}")
        return {}

def translate_text(text, dest_lang):
    try:
        translated = GoogleTranslator(source='auto', target=dest_lang).translate(text)
        return translated
    except Exception as e:
        return f"Error translating text: {str(e)}"

LANGUAGES = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "hi": "Hindi",
    "id": "Indonesian",
    "ms": "Malay",
    "tl": "Tagalog",
    "vi": "Vietnamese",
    "th": "Thai",
    "my": "Burmese",
    "km": "Khmer",
    "lo": "Lao",
    "fil": "Filipino",
    "tet": "Tetum",
}