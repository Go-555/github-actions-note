from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from typing import List

import google.generativeai as genai

from scripts.config_loader import GeneratorSettings
from scripts.utils.logger import setup_logger


@dataclass
class GeneratedArticle:
    lead: str
    sections: List[str]
    references: List[str]
    body_markdown: str


@dataclass
class SectionBlock:
    heading: str
    paragraphs: List[str]


class ArticleGenerator:
    def __init__(self, settings: GeneratorSettings, api_key: str, dry_run: bool = False) -> None:
        self.settings = settings
        self.logger = setup_logger("article", settings.logs_dir)
        self.dry_run = dry_run
        if not dry_run and api_key:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel(
                model_name="models/gemini-2.5-flash",
                generation_config={
                    "temperature": 0.65,
                    "top_p": 0.9,
                    "max_output_tokens": 8192,
                },
            )
        else:
            self.model = None

    def generate(self, keyword: str, memo: str, plan: dict) -> GeneratedArticle:
        prompt = self._build_prompt(keyword, memo, plan)
        if self.dry_run:
            text = self._dummy_body(keyword, plan)
        else:
            response = self.model.generate_content([prompt])
            text = self._extract_text(response)
        self.logger.info("Generated article body for '%s'", keyword)
        body = self._enforce_length(text)
        return GeneratedArticle(
            lead="",
            sections=self.settings.article.required_sections,
            references=[],
            body_markdown=body,
        )

    def _build_prompt(self, keyword: str, memo: str, plan: dict) -> str:
        sections = "\n".join(f"- {item}" for item in plan["outline"])
        return (
            "あなたはプロのSEOライターです。\n"
            f"キーワード: {keyword}\n"
            f"構成案:\n{sections}\n"
            f"メモ:\n{memo or 'なし'}\n"
            "以下の制約を守ってMarkdown本文を書いてください。\n"
            "- 全体の文字数は 3,000〜5,000 字に収める\n"
            "- リード文（100～200字）を先頭に書く\n"
            "- 背景と課題, 結論（先出し）, 手順, よくある失敗と対策, 事例・効果, まとめ（CTA), 参考リンク の順に H2 見出しを配置する\n"
            "- 必要に応じて H3/H4 を使い、読者に実務で役立つ洞察を提供する\n"
            "- 誇大表現や根拠のない断定は避け、一次情報や具体例を挙げる\n"
            "- 参考リンクは文末のリストで提示する\n"
            "- 画像を差し込みたい箇所には '![代替テキスト](./assets/placeholder.jpg)' の形式で記載する（後で差し替える）\n"
            "- 日本語で書く\n"
        )

    def _dummy_body(self, keyword: str, plan: dict) -> str:
        sections = self.settings.article.required_sections
        lines = [f"# {keyword} の最新戦略", "", "リード文: このコンテンツは自動生成のドライランです。実運用では Gemini がここに実際の本文を生成します。", ""]
        filler = (
            "このセクションはドライラン用のダミー本文です。実運用ではここに最新情報、統計データ、"
            "実務で役立つノウハウが詳細に書き込まれます。テンプレートの長さを担保するために、"
            "ダミーテキストを複数段落にわたって繰り返し追加しています。"
        )
        filler_paragraphs = "\n\n".join([filler for _ in range(5)])
        for section in sections:
            lines.append(f"## {section}")
            lines.append(filler_paragraphs)
            lines.append("")
        lines.append("## 参考リンク")
        lines.append("- https://example.com")
        return "\n".join(lines)

    def _extract_text(self, response) -> str:
        if getattr(response, "text", None):
            return response.text
        candidates = getattr(response, "candidates", [])
        if not candidates:
            return ""
        parts = getattr(candidates[0].content, "parts", [])
        texts: List[str] = []
        for part in parts:
            value = getattr(part, "text", None)
            if value:
                texts.append(value)
                continue
            inline = getattr(part, "inline_data", None)
            if inline and getattr(inline, "data", None):
                try:
                    texts.append(base64.b64decode(inline.data).decode("utf-8"))
                    continue
                except Exception:  # noqa: BLE001
                    pass
            as_dict = getattr(part, "as_dict", None)
            if callable(as_dict):
                try:
                    dict_value = as_dict()
                    if isinstance(dict_value, dict):
                        text_value = dict_value.get("text")
                        if text_value:
                            texts.append(text_value)
                except Exception:  # noqa: BLE001
                    continue
        return "".join(texts)

    def _enforce_length(self, text: str) -> str:
        min_len = self.settings.article.min_chars
        max_len = self.settings.article.max_chars
        body = text.strip()
        if not body:
            return body
        if len(body) <= max_len:
            if len(body) < min_len:
                self.logger.warning("Generated body shorter than minimum: %s chars", len(body))
            return body

        preface, sections = self._split_into_units(body)
        if not sections:
            trimmed = self._trim_paragraph_to(body, max_len)
            if len(trimmed) < min_len:
                self.logger.warning("Body length after trimming (%s) below minimum %s", len(trimmed), min_len)
            return trimmed

        current = self._compose_from_units(preface, sections)

        while len(current) > max_len:
            removed = False
            for section in reversed(sections):
                if len(section.paragraphs) <= 1:
                    continue
                removed_para = section.paragraphs.pop()
                candidate = self._compose_from_units(preface, sections)
                if len(candidate) >= min_len:
                    current = candidate
                    removed = True
                    break
                section.paragraphs.append(removed_para)
            if not removed and len(preface) > 1:
                removed_preface = preface.pop()
                candidate = self._compose_from_units(preface, sections)
                if len(candidate) >= min_len:
                    current = candidate
                    removed = True
                else:
                    preface.append(removed_preface)
            if not removed:
                break

        guard = 0
        while len(current) > max_len and guard < 100:
            guard += 1
            trimmed = False
            excess = len(current) - max_len
            section_min = self._section_min_length()
            for section in reversed(sections):
                if not section.paragraphs:
                    continue
                paragraph = section.paragraphs[-1]
                paragraph_len = len(paragraph)
                reduce_cap = max(paragraph_len - section_min, 0)
                if reduce_cap <= 0:
                    continue
                reduce_by = min(excess, reduce_cap)
                target_len = max(paragraph_len - reduce_by, section_min)
                if target_len >= paragraph_len:
                    continue
                new_paragraph = self._trim_paragraph_to(paragraph, target_len)
                if new_paragraph == paragraph:
                    continue
                section.paragraphs[-1] = new_paragraph
                current = self._compose_from_units(preface, sections)
                trimmed = True
                break
            if trimmed:
                continue
            if preface:
                paragraph = preface[-1]
                paragraph_len = len(paragraph)
                lead_min = self._lead_min_length()
                reduce_cap = max(paragraph_len - lead_min, 0)
                if reduce_cap > 0:
                    reduce_by = min(len(current) - max_len, reduce_cap)
                    target_len = max(paragraph_len - reduce_by, lead_min)
                    if target_len < paragraph_len:
                        new_paragraph = self._trim_paragraph_to(paragraph, target_len)
                        if new_paragraph != paragraph:
                            preface[-1] = new_paragraph
                            current = self._compose_from_units(preface, sections)
                            continue
            break

        if len(current) > max_len:
            fallback = current[:max_len]
            cutoff = fallback.rfind("\n\n")
            if cutoff >= min_len:
                current = fallback[:cutoff].rstrip()
            else:
                current = fallback.rstrip()
            self.logger.warning("Fallback trimming applied; final length %s chars", len(current))

        if len(current) < min_len:
            self.logger.warning("Body length after trimming (%s) below minimum %s", len(current), min_len)

        return current

    def _split_into_units(self, text: str) -> tuple[List[str], List[SectionBlock]]:
        lines = text.strip().splitlines()
        preface: List[str] = []
        sections: List[SectionBlock] = []
        current_section: SectionBlock | None = None
        buffer: List[str] = []

        def flush_buffer() -> None:
            nonlocal buffer, current_section
            paragraph = "\n".join(buffer).strip()
            buffer = []
            if not paragraph:
                return
            if current_section is None:
                preface.append(paragraph)
            else:
                current_section.paragraphs.append(paragraph)

        for line in lines:
            if line.startswith("## "):
                flush_buffer()
                current_section = SectionBlock(heading=line.strip(), paragraphs=[])
                sections.append(current_section)
                continue
            if line.strip() == "":
                flush_buffer()
                continue
            buffer.append(line)

        flush_buffer()
        return preface, sections

    def _compose_from_units(self, preface: List[str], sections: List[SectionBlock]) -> str:
        parts: List[str] = []
        parts.extend(preface)
        for section in sections:
            parts.append(section.heading)
            parts.extend(section.paragraphs)
        return "\n\n".join(parts).strip()

    def _trim_paragraph_to(self, paragraph: str, target_len: int) -> str:
        text = paragraph.strip()
        if not text:
            return text
        if target_len <= 0:
            return ""
        if len(text) <= target_len:
            return text
        if self._is_bullet_block(text):
            trimmed_lines: List[str] = []
            total = 0
            for line in text.splitlines():
                if not line.strip():
                    if trimmed_lines:
                        trimmed_lines.append(line)
                    continue
                line_len = len(line)
                if trimmed_lines and total + line_len > target_len:
                    break
                trimmed_lines.append(line)
                total += line_len
                if total >= target_len:
                    break
            return "\n".join(trimmed_lines).strip()
        sentences = self._split_sentences(text)
        if not sentences:
            return self._truncate_text(text, target_len)
        trimmed_sentences: List[str] = []
        total = 0
        for idx, sentence in enumerate(sentences):
            sentence = sentence.strip()
            if not sentence:
                continue
            trimmed_sentences.append(sentence)
            total += len(sentence)
            if total >= target_len and idx != 0:
                break
        candidate = "".join(trimmed_sentences).strip()
        if not candidate:
            candidate = sentences[0].strip()
        if len(candidate) > target_len:
            candidate = self._truncate_text(candidate, target_len)
        return candidate

    def _split_sentences(self, text: str) -> List[str]:
        sentences = re.split(r"(?<=[。．？！!?])\s+", text)
        return [sentence for sentence in sentences if sentence.strip()]

    def _is_bullet_block(self, text: str) -> bool:
        lines = [line for line in text.splitlines() if line.strip()]
        if not lines:
            return False
        for line in lines:
            stripped = line.lstrip()
            if stripped.startswith(('-', '*', '+', '・')):
                continue
            if re.match(r"\d+\.\s", stripped):
                continue
            return False
        return True

    def _truncate_text(self, text: str, limit: int) -> str:
        if limit <= 0:
            return ""
        if len(text) <= limit:
            return text
        truncated = text[:limit]
        for punct in ("。", "．", "！", "？", "!", "?"):
            idx = truncated.rfind(punct)
            if idx != -1 and idx >= limit // 2:
                return truncated[: idx + 1]
        comma_idx = truncated.rfind("、")
        if comma_idx != -1 and comma_idx >= limit // 2:
            return truncated[:comma_idx].rstrip("、")
        return truncated.rstrip()

    def _section_min_length(self) -> int:
        section_count = max(len(self.settings.article.required_sections), 1)
        calculated = self.settings.article.min_chars // (section_count * 2)
        return max(180, calculated)

    def _lead_min_length(self) -> int:
        return max(self.settings.article.lead_min_chars, 80)
