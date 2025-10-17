from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

# --- Prefer the new SDK --------------------------------------------------------
try:
    from google import genai  # type: ignore
    _SDK = "new"
except Exception:  # pragma: no cover
    genai = None  # type: ignore
    _SDK = "missing"

# --- Fallback to the old SDK only if needed -----------------------------------
try:  # pragma: no cover
    import google.generativeai as old_genai  # type: ignore
except Exception:  # pragma: no cover
    old_genai = None  # type: ignore

# --- Project imports (kept as-is) ---------------------------------------------
from scripts.config_loader import GeneratorSettings
from scripts.utils.logger import setup_logger
from scripts.utils.sections import (
    find_best_match,
    iter_section_variants,
    section_present,
)
from scripts.utils.text import generate_slug


# ==============================================================================
# Types
# ==============================================================================

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


# ==============================================================================
# Main
# ==============================================================================

class ArticleGenerator:
    """Gemini 2.5で“自然で違和感のないnote向け本文”を生成するバージョン。

    改善点（従来比）:
      - 新SDK対応（`from google import genai`）。利用不可時は旧SDKに自動フォールバック。
      - モデル名をテキスト特化へ明示（`gemini-2.5-flash`）。
      - `_extract_text` をシンプル化（`inline_data` を UTF-8 デコードしようとしない）。
      - 生成後フィルタ（禁止表現・謝罪・AI自己言及・テンプレ臭の除去）。
      - リード文の必須化と長さチェック（100–200字）。
      - `dry_run` 時はダミー文を“書かない”方針（空を返し品質ゲートで弾く運用に適合）。
    """

    MODEL_TEXT = "gemini-2.5-flash"  # text-optimized, fast & cheap

    def __init__(self, settings: GeneratorSettings, api_key: Optional[str], dry_run: bool = False) -> None:
        self.settings = settings
        self.logger = setup_logger("article", settings.logs_dir)
        self.dry_run = dry_run
        self._client = None
        self._old_model = None

        if not dry_run and api_key:
            if _SDK == "new":
                self._client = genai.Client(api_key=api_key)
            elif old_genai is not None:
                old_genai.configure(api_key=api_key)
                self._old_model = old_genai.GenerativeModel(
                    model_name=f"models/{self.MODEL_TEXT}",
                    generation_config={
                        "temperature": 0.6,
                        "top_p": 0.9,
                        "max_output_tokens": 8192,
                    },
                )
            else:
                raise RuntimeError(
                    "Neither the new (`google.genai`) nor old (`google.generativeai`) SDK is available.\n"
                    "Install one of them: pip install google-genai  # or: pip install google-generativeai"
                )

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------

    def generate(self, keyword: str, memo: str, plan: dict) -> GeneratedArticle:
        prompt = self._build_prompt(keyword, memo, plan)

        if self.dry_run:
            # 品質ゲートと相性の良い挙動: 生成しない（空を返す）
            text = ""
        else:
            text = self._call_model(prompt)

        required_sections = list(self.settings.article.required_sections)
        text = self._ensure_sections_present(text, keyword, plan, required_sections)

        # リード文抽出（先頭~200字程度の1段落をリード扱い）
        lead, body = self._extract_lead(text)
        if lead and not (100 <= len(lead) <= 200):
            self.logger.info("Lead length out of range; len=%d (expected 100–200)", len(lead))

        body = self._enforce_length(body)
        body = self._ensure_balanced_fences(body)

        return GeneratedArticle(
            lead=lead,
            sections=self.settings.article.required_sections,
            references=self._extract_references(body),
            body_markdown=body,
        )

    # ---------------------------------------------------------------------
    # Model Call
    # ---------------------------------------------------------------------

    def _call_model(self, prompt: str) -> str:
        if self._client is not None:  # new SDK path
            resp = self._client.models.generate_content(
                model=self.MODEL_TEXT,
                contents=[{"role": "user", "parts": [{"text": prompt}]}],
                config={
                    "temperature": 0.65,
                    "top_p": 0.9,
                    "max_output_tokens": 8192,
                },
            )
            text = self._extract_text(resp)
        elif self._old_model is not None:  # old SDK path
            resp = self._old_model.generate_content([prompt])
            text = self._extract_text(resp)
        else:
            raise RuntimeError("No SDK client/model is available to generate content")

        text = self._post_filter(text)
        return text

    # ---------------------------------------------------------------------
    # Prompting
    # ---------------------------------------------------------------------

    def _build_prompt(self, keyword: str, memo: str, plan: dict) -> str:
        outline = plan.get("outline") if isinstance(plan, dict) else None
        summary = plan.get("summary") if isinstance(plan, dict) else None

        sections = "\n".join(f"- {item}" for item in (outline or []))
        tone = self.settings.article.tone
        target_chars = self.settings.article.target_chars

        antipatterns = (
            "以下の文言・行為は厳禁: 'この文章はAIが生成', 'ドライラン', 'ダミー', 'placeholder', 'テンプレ',"
            " 'まとめると', 'いかがでしたか', '筆者は思います', '必ず成功', '100%'."
        )

        return (
            "あなたは日本語で書くプロのSEOライターです。noteに最適化した自然な文体で、実務に役立つ内容を作成します。\n"
            f"キーワード: {keyword}\n"
            + (f"メモ:\n{memo}\n" if memo else "")
            + (f"構成案:\n{sections}\n" if sections else "")
            + (
                "制約:\n"
                f"- 全体は3000–5000字、目安は{target_chars}字。\n"
                "- リード文(100–200字) → H2見出し（必要に応じてH3/H4）。\n"
                "- 架空の体験や事実でない統計は禁止。一次情報や具体例を明記。\n"
                "- 画像のマークダウンは実画像が存在する場合のみ挿入する。\n"
                f"- 文体トーン: {tone}\n"
                f"- {antipatterns}\n"
            )
            + (
                "出力形式:\n"
                "- 冒頭にリード文(1段落)を置き、その後に本文を続ける。\n"
                "- '参考リンク' がある場合は末尾にH2で記載し、リンクは実在し内容が分かる説明を付ける。\n"
            )
        )

    # ---------------------------------------------------------------------
    # Post processing / Filters
    # ---------------------------------------------------------------------

    def _extract_text(self, response) -> str:
        """Extract plain text from both new/old SDK responses, ignoring binary parts."""
        # new SDK shape
        for attr in ("text",):
            if hasattr(response, attr) and getattr(response, attr):
                return getattr(response, attr)

        # generic candidates/parts walk
        texts: List[str] = []
        candidates = getattr(response, "candidates", []) or []
        if candidates:
            parts = getattr(candidates[0], "content", None)
            parts = getattr(parts, "parts", []) if parts else []
            for part in parts:
                t = getattr(part, "text", None)
                if t:
                    texts.append(t)
        return "".join(texts)

    _BAN_PATTERNS = [
        r"この(文章|文|コンテンツ).{0,10}AI(が|を).*生成",
        r"私はAI(です|モデル)",
        r"ドライラン|ダミー|placeholder|テンプレ",
        r"いかがでしたか",
        r"必ず成功|100%|絶対に",
        r"まとめると$",
    ]

    def _post_filter(self, text: str) -> str:
        if not text:
            return text
        # Kill banned phrases
        norm = unicodedata.normalize("NFKC", text)
        for pat in self._BAN_PATTERNS:
            norm = re.sub(pat, "", norm, flags=re.IGNORECASE | re.MULTILINE)
        # Normalize excessive blank lines
        norm = re.sub(r"\n{3,}", "\n\n", norm)
        return norm.strip()

    # ---------------------------------------------------------------------
    # Lead / References
    # ---------------------------------------------------------------------

    def _extract_lead(self, body: str) -> tuple[str, str]:
        if not body:
            return "", ""
        lines = body.lstrip().splitlines()
        if not lines:
            return "", body
        # 先頭段落(空行まで)をリードとして切り出す。ただし見出し(#や##)で始まる場合は除外。
        if lines[0].lstrip().startswith(("#", "##")):
            return "", body
        lead_lines = []
        rest_lines = []
        saw_blank = False
        for ln in lines:
            if not saw_blank and not ln.strip():
                saw_blank = True
                continue
            if not saw_blank:
                lead_lines.append(ln)
            else:
                rest_lines.append(ln)
        lead = "\n".join(lead_lines).strip()
        rest = "\n".join(rest_lines).lstrip()
        return lead, rest

    def _extract_references(self, body: str) -> List[str]:
        refs: List[str] = []
        if not body:
            return refs
        # 最後の『## 参考リンク』セクションからURLを収集
        m = re.search(r"##\s*参考リンク[\s\S]*$", body, flags=re.MULTILINE)
        if not m:
            return refs
        block = m.group(0)
        for url in re.findall(r"https?://\S+", block):
            refs.append(url.rstrip(").]、。,"))
        return refs

    # ---------------------------------------------------------------------
    # Length control & structure safety
    # ---------------------------------------------------------------------

    def _enforce_length(self, text: str) -> str:
        min_len = self.settings.article.min_chars
        max_len = self.settings.article.max_chars
        body = (text or "").strip()
        if not body:
            return body
        if len(body) <= max_len:
            if len(body) < min_len:
                self.logger.warning("Generated body shorter than minimum: %s chars", len(body))
            return body

        preface, sections = self._split_into_units(body)
        if not sections:
            return self._truncate_soft(body, max_len)

        current = self._compose_from_units(preface, sections)
        guard = 0
        while len(current) > max_len and guard < 50:
            guard += 1
            changed = False
            # 末尾セクションの末段落から徐々に削る
            for sec in reversed(sections):
                if not sec.paragraphs:
                    continue
                para = sec.paragraphs[-1]
                newp = self._truncate_soft(para, max(len(para) - (len(current) - max_len), 200))
                if newp != para:
                    sec.paragraphs[-1] = newp
                    current = self._compose_from_units(preface, sections)
                    changed = True
                    if len(current) <= max_len:
                        break
            if not changed:
                break

        if len(current) > max_len:
            current = self._truncate_soft(current, max_len)
            self.logger.warning("Fallback trimming applied; final length %s chars", len(current))
        return current

    def _truncate_soft(self, text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        cut = text[:limit]
        # できるだけ段落単位で切る
        idx = cut.rfind("\n\n")
        if idx >= limit // 2:
            return cut[:idx].rstrip()
        # 文末記号で切る
        for punct in ("。", "．", "！", "？", "!", "?"):
            p = cut.rfind(punct)
            if p >= limit // 2:
                return cut[: p + 1].rstrip()
        return cut.rstrip()

    def _ensure_balanced_fences(self, body: str) -> str:
        fence_count = body.count("```")
        if fence_count % 2 == 0:
            return body
        self.logger.warning("Unbalanced code fence detected; appending closing fence")
        return body.rstrip() + "\n```\n"

    # ---------------------------------------------------------------------
    # Section utils (kept compatible)
    # ---------------------------------------------------------------------

    def _section_keywords(self, section_name: str) -> List[str]:
        variants = [v for v in iter_section_variants(section_name) if v]
        if variants:
            return variants
        tokens = [section_name]
        if "・" in section_name:
            tokens.extend(section_name.split("・"))
        return tokens

    def _split_into_units(self, text: str) -> tuple[List[str], List[SectionBlock]]:
        lines = text.strip().splitlines()
        preface: List[str] = []
        sections: List[SectionBlock] = []
        current: Optional[SectionBlock] = None
        buf: List[str] = []

        def flush() -> None:
            nonlocal buf, current
            paragraph = "\n".join(buf).strip()
            buf = []
            if not paragraph:
                return
            if current is None:
                preface.append(paragraph)
            else:
                current.paragraphs.append(paragraph)

        for line in lines:
            stripped = line.lstrip()
            if stripped.startswith("##") and not stripped.startswith("###"):
                flush()
                heading_body = stripped[2:].lstrip()
                heading_text = f"## {heading_body}" if heading_body else "##"
                current = SectionBlock(heading=heading_text, paragraphs=[])
                sections.append(current)
                buf = []
                continue
            if stripped == "":
                flush()
                continue
            buf.append(line)
        flush()
        return preface, sections

    def _compose_from_units(self, preface: List[str], sections: List[SectionBlock]) -> str:
        parts: List[str] = []
        parts.extend(preface)
        for s in sections:
            parts.append(s.heading)
            parts.extend(s.paragraphs)
        return "\n\n".join(parts).strip()

    # ---------------------------------------------------------------------
    # Section presence & regeneration (compatible with your settings)
    # ---------------------------------------------------------------------

    def _ensure_sections_present(self, text: str, keyword: str, plan: dict, required_sections: List[str]) -> str:
        normalized_text = unicodedata.normalize("NFKC", text or "")
        missing = [s for s in required_sections if not section_present(normalized_text, s)]

        if missing:
            text, normalized_text, missing = self._attempt_canonicalize_sections(text, missing, required_sections)

        # 欠落時の再生成は、まず本文が空でない場合のみ実施（空なら上流で再試行）
        if missing and text and (self._client or self._old_model):
            text, normalized_text, missing = self._fill_missing_sections(text, normalized_text, missing, keyword, plan)

        if missing:
            self._persist_debug(text or "", keyword)
            raise ValueError(f"Missing required sections: {', '.join(missing)}")

        # リジェクトフレーズの検出（settings側の語彙に依存）
        if getattr(self.settings, "quality_gate", None) and self.settings.quality_gate.reject_phrases:
            for phrase in self.settings.quality_gate.reject_phrases:
                if not phrase:
                    continue
                if phrase in text or unicodedata.normalize("NFKC", phrase) in normalized_text:
                    raise ValueError("Contains rejected phrase")
        return text

    def _attempt_canonicalize_sections(self, text: str, missing: List[str], targets: List[str]):
        if not text:
            return text, unicodedata.normalize("NFKC", text or ""), missing
        preface, sections = self._split_into_units(text)
        remaining = list(range(len(sections)))
        matched: dict[str, int] = {}

        for name in targets:
            found = None
            for idx in remaining:
                heading_norm = unicodedata.normalize("NFKC", self._normalize_heading(sections[idx].heading))
                if find_best_match(heading_norm, [name]):
                    found = idx
                    break
            if found is None:
                keywords = self._section_keywords(name)
                for idx in remaining:
                    heading_norm = unicodedata.normalize("NFKC", self._normalize_heading(sections[idx].heading))
                    if all(k and k in heading_norm for k in keywords):
                        found = idx
                        break
            if found is not None:
                matched[name] = found
                remaining.remove(found)

        updated = False
        for name, idx in matched.items():
            normalized_heading = unicodedata.normalize("NFKC", self._normalize_heading(sections[idx].heading))
            target_norm = unicodedata.normalize("NFKC", name)
            if target_norm != normalized_heading:
                sections[idx].heading = f"## {name}"
                updated = True

        if updated:
            text = self._compose_from_units(preface, sections)

        normalized_text = unicodedata.normalize("NFKC", text or "")
        remaining_missing = [s for s in targets if not section_present(normalized_text, s)]
        return text, normalized_text, remaining_missing

    def _fill_missing_sections(self, text: str, normalized_text: str, missing: List[str], keyword: str, plan: dict):
        self.logger.info("Attempting regeneration for sections: %s", ", ".join(missing))
        updated = text
        for name in missing:
            addition = self._generate_section_addendum(name, updated, keyword, plan) or self._fallback_section_content(name, keyword, plan)
            if not addition:
                continue
            if f"## {name}" not in addition:
                addition = f"## {name}\n{addition.strip()}"
            updated = f"{updated.rstrip()}\n\n{addition.strip()}\n"

        normalized_text = unicodedata.normalize("NFKC", updated or "")
        remaining_missing = [s for s in self.settings.article.required_sections if not section_present(normalized_text, s)]
        if remaining_missing:
            self.logger.warning("Sections still missing after regeneration: %s", ", ".join(remaining_missing))
        return updated, normalized_text, remaining_missing

    def _generate_section_addendum(self, section_name: str, current_text: str, keyword: str, plan: dict) -> str:
        if not (self._client or self._old_model):
            return ""
        outline = plan.get("outline") if isinstance(plan, dict) else None
        summary = plan.get("summary") if isinstance(plan, dict) else ""
        parts = [
            "あなたはプロのSEOライターです。",
            f"対象キーワード: {keyword}",
        ]
        if summary:
            parts.append(f"記事の要約: {summary}")
        if outline:
            parts.append("記事の構成:\n" + "\n".join(f"- {i}" for i in outline))
        parts.append("既存本文を以下に示します。欠けている指定セクションだけを追記してください。")
        parts.append(current_text)

        if section_name == "参考リンク":
            instr = (
                "'## 参考リンク' の見出しを付け、信頼できる公開情報を日本語説明付きで3–5件、箇条書きで提示。"
                "ダミーURLは禁止。"
            )
        else:
            instr = (
                f"欠落セクションは '{section_name}'。H2見出しから開始し、具体例・統計・手順を200–400字で。"
                "テンプレ表現や一般論のみは禁止。読者の行動が変わる示唆を含める。"
            )

        parts.append(instr)
        parts.append("出力は指定セクションのみ。余計な前置き・後書きは不要。")
        prompt = "\n\n".join(parts)

        if self._client is not None:
            resp = self._client.models.generate_content(
                model=self.MODEL_TEXT,
                contents=[{"role": "user", "parts": [{"text": prompt}]}],
                config={"temperature": 0.6, "top_p": 0.9, "max_output_tokens": 1024},
            )
        else:
            resp = self._old_model.generate_content([prompt])  # type: ignore[union-attr]

        return (self._extract_text(resp) or "").strip()

    # ---------------------------------------------------------------------
    # Misc utilities
    # ---------------------------------------------------------------------

    def _persist_debug(self, text: str, keyword: str) -> None:
        try:
            debug_dir = self.settings.logs_dir / "debug"
            Path(debug_dir).mkdir(parents=True, exist_ok=True)
            timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
            slug = generate_slug(keyword or "article")
            path = debug_dir / f"{slug}-{timestamp}.md"
            path.write_text(text, encoding="utf-8")
            self.logger.error("Saved failing body to %s", path)
        except Exception:  # noqa: BLE001
            self.logger.exception("Failed to persist debug article body")

    def _normalize_heading(self, heading: str) -> str:
        return heading.lstrip("#").strip()

    def _default_section_placeholder(self, section: str) -> str:
        return (
            f"{section} セクションは生成結果から十分な情報が得られなかったため、"
            "テンプレートの補完テキストを追加しています。実運用時には見直してください。"
        )
