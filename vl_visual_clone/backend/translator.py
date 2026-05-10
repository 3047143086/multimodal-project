from typing import Iterable


class Translator:
    def __init__(self, enabled: bool, source_lang: str, target_lang: str):
        self.enabled = enabled
        self.source_lang = source_lang
        self.target_lang = target_lang

    def translate_text(self, text: str) -> str:
        text = (text or "").strip()
        if not text:
            return ""
        if not self.enabled or self.source_lang == self.target_lang:
            return text
        # Placeholder strategy: keep source text when no MT backend is configured.
        # This preserves visual layout pipeline while leaving translation hook pluggable.
        return text

    def translate_many(self, texts: Iterable[str]) -> list[str]:
        return [self.translate_text(t) for t in texts]
