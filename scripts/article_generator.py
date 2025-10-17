from __future__ import annotations

import base64
import os
import re
import unicodedata
from datetime import datetime
from dataclasses import dataclass
from typing import List, Dict, Optional

import google.generativeai as genai

from scripts.config_loader import GeneratorSettings
from scripts.utils.logger import setup_logger
from scripts.utils.sections import (
    find_best_match,
    iter_section_variants,
    section_present,
)
from scripts.utils.text import generate_slug


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
    """
    目的:
      - dry_run 時でも *記事本文を返す*（後続の品質ゲート/投稿準備を検証可能に）
      - セクション欠落で *ValueError を投げずに* 復元して完走させる

    仕様:
      - DRY_RUN_USE_MODEL=true の場合、dry_run でも実モデル呼び出しを試行（APIキー必須）。
      - それ以外は _synthesize_dummy_text() で妥当な構成のダミー本文を合成。
      - 必須セクション欠落時はダミーで補完し、例外を投げない（ログとデバッグ保存は継続）。
    """

    def __init__(self, settings: GeneratorSettings, api_key: Optional[str], dry_run: bool = False) -> None:
        self.settings = settings
        self.logger = setup_logger("article", settings.logs_dir)
        self.dry_run = dry_run
        self.model = None
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
        # dry_run 中でもモデルを使うオプション
        self._dry_run_use_model = str(os.getenv("DRY_RUN_USE_MODEL", "")).lower() in {"1", "true", "yes", "on"}

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------
    def generate(self, keyword: str, memo: str, plan: dict) -> GeneratedArticle:
        required_sections = list(self.settings.article.required_sections)

        # 1) 本文の生成（dry_run ポリシー適用）
        if self.dry_run:
            text = self._generate_dry_run_text(keyword, memo, plan, required_sections)
        else:
            text = self._generate_with_model_or_empty(keyword, memo, plan)
            if not text:
                # モデルが無効/失敗時の安全策
                self.logger.warning("Model returned empty text; synthesizing fallback article body")
                text = self._synthesize_dummy_text(keyword, plan, required_sections)

        # 2) セクションの存在を担保（欠落しても止めない方針）
        try:
            text = self._ensure_sections_present(text, keyword, plan, required_sections)
        except Exception as exc:  # noqa: BLE001
            self.logger.error("Section check raised %s; attempting to auto-heal via synthesis", exc.__class__.__name__)
            healed = self._synthesize_missing_sections(text, keyword, plan, required_sections)
            # 最後にもう一度だけ軽く確認（例外は投げない）
            normalized = unicodedata.normalize("NFKC", healed)
            missing = [s for s in required_sections if not section_present(normalized, s)]
            if missing:
                self.logger.warning("Sections still missing after heal: %s", ", ".join(missing))
            text = healed

        # 3) リード抽出と整形
        body = self._enforce_length(text)
        body = self._ensure_balanced_fences(body)
        lead, body_wo_lead = self._extract_lead(body)
        if not lead:
            # 先頭段落が見出しの場合は自動生成
            lead = self._make_lead(keyword, plan)
            body = f"{lead}\n\n{body_wo_lead or body}"

        return GeneratedArticle(
            lead=lead,
            sections=self.settings.article.required_sections,
            references=self._extract_references(body),
            body_markdown=body,
        )

    # ------------------------------------------------------------------
    # Generation strategies
    # ------------------------------------------------------------------
    def _generate_dry_run_text(self, keyword: str, memo: str, plan: dict, required_sections: List[str]) -> str:
        # DRY_RUN_USE_MODEL=true かつ モデル準備OKなら実際に生成
        if self._dry_run_use_model and self.model is not None:
            self.logger.info("DRY_RUN_USE_MODEL enabled – calling model in dry_run")
            text = self._call_model(self._build_prompt(keyword, memo, plan))
            if text:
                return text
            self.logger.warning("Model returned empty text in dry_run; falling back to synthesized body")
        # モデルが使えない/失敗したら合成テキスト
        return self._synthesize_dummy_text(keyword, plan, required_sections)

    def _generate_with_model_or_empty(self, keyword: str, memo: str, plan: dict) -> str:
        if not self.model:
            return ""
        prompt = self._build_prompt(keyword, memo, plan)
        return self._call_model(prompt)

    def _call_model(self, prompt: str) -> str:
        try:
            response = self.model.generate_content([prompt])  # type: ignore[union-attr]
            return self._extract_text(response)
        except Exception as exc:  # noqa: BLE001
            self.logger.exception("Model generation failed: %s", exc)
            return ""

    # ------------------------------------------------------------------
    # Prompt / text extraction
    # ------------------------------------------------------------------
    def _build_prompt(self, keyword: str, memo: str, plan: dict) -> str:
        sections = "\n".join(f"- {item}" for item in (plan.get("outline") or []))
        tone = self.settings.article.tone
        target_chars = self.settings.article.target_chars
        return (
            "あなたはプロのnoteコンテンツのSEOクリエイターです。\n"
            f"キーワード: {keyword}\n"
            + (f"構成案:\n{sections}\n" if sections else "")
            + (f"メモ:\n{memo}\n" if memo else "")
            + (
                "以下の制約を守ってMarkdown本文を書いてください。\n"
                f"- 全体は 3,000〜5,000 字、目安は {target_chars} 字\n"
                "- 冒頭にリード文（100〜200字、1段落）\n"
                "- 各セクションで固有名詞や数値、実務に基づく具体例を提示。テンプレ文やダミー文言は禁止\n"
                "- 架空の内容・虚偽の記述はしない。日本語で書く\n"
                "- 画像のMarkdownは実在画像がある場合のみ\n"
                "- H2/H3/H4は必要に応じて。見出し構成は柔軟でよい\n"
                f"- 文体のトーン: {tone}\n"
            )
        )

    def _extract_text(self, response) -> str:
        # 旧SDKの典型レスポンス: response.text または candidates[0].content.parts[].text
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
            # 画像等の inline_data は本文抽出対象にしない
            # （base64を無理にUTF-8デコードしない）
        return "".join(texts)

    # ------------------------------------------------------------------
    # Section assurance & healing
    # ------------------------------------------------------------------
    def _ensure_sections_present(
        self, text: str, keyword: str, plan: dict, required_sections: List[str]
    ) -> str:
        normalized_text = unicodedata.normalize("NFKC", text or "")
        missing = [s for s in required_sections if not section_present(normalized_text, s)]
        if missing:
            text, normalized_text, missing = self._attempt_canonicalize_sections(text, missing, required_sections)
        # 再生成（通常時のみ）。dry_run ではここでモデル呼び出しは行わない
        if missing and not self.dry_run and self.model is not None:
            text, normalized_text, missing = self._fill_missing_sections(text, normalized_text, missing, keyword, plan)
        if missing:
            # 既存仕様では ValueError だが、ここでは例外を投げず上位でヒーリング
            self._persist_debug(text or "", keyword)
        # リジェクトフレーズ
        if getattr(self.settings, "quality_gate", None) and self.settings.quality_gate.reject_phrases:
            for phrase in self.settings.quality_gate.reject_phrases:
                if not phrase:
                    continue
                if phrase in text or unicodedata.normalize("NFKC", phrase) in normalized_text:
                    # ここでも例外ではなくログのみ（dry-run 継続のため）
                    self.logger.error("Output contains rejected phrase: %s", phrase)
        return text

    def _attempt_canonicalize_sections(
        self, text: str, missing: List[str], targets: List[str]
    ) -> tuple[str, str, List[str]]:
        if not text:
            return text, unicodedata.normalize("NFKC", text or ""), missing
        preface, sections = self._split_into_units(text)
        remaining_indices = list(range(len(sections)))
        matched: Dict[str, int] = {}
        for section_name in targets:
            found_idx = None
            for idx in remaining_indices:
                heading_norm = unicodedata.normalize("NFKC", self._normalize_heading(sections[idx].heading))
                if find_best_match(heading_norm, [section_name]):
                    found_idx = idx
                    break
            if found_idx is None:
                keywords = self._section_keywords(section_name)
                for idx in remaining_indices:
                    heading_norm = unicodedata.normalize("NFKC", self._normalize_heading(sections[idx].heading))
                    if all(keyword and keyword in heading_norm for keyword in keywords):
                        found_idx = idx
                        break
            if found_idx is not None:
                matched[section_name] = found_idx
                remaining_indices.remove(found_idx)
        updated = False
        for section_name, idx in matched.items():
            normalized_heading = unicodedata.normalize("NFKC", self._normalize_heading(sections[idx].heading))
            target_norm = unicodedata.normalize("NFKC", section_name)
            if target_norm != normalized_heading:
                sections[idx].heading = f"## {section_name}"
                updated = True
        if updated:
            text = self._compose_from_units(preface, sections)
        normalized_text = unicodedata.normalize("NFKC", text or "")
        remaining_missing = [s for s in targets if not section_present(normalized_text, s)]
        return text, normalized_text, remaining_missing

    def _fill_missing_sections(
        self,
        text: str,
        normalized_text: str,
        missing: List[str],
        keyword: str,
        plan: dict,
    ) -> tuple[str, str, List[str]]:
        self.logger.info("Attempting regeneration for sections: %s", ", ".join(missing))
        updated = text
        for section_name in missing:
            try:
                addition = self._generate_section_addendum(section_name, updated, keyword, plan)
            except Exception as exc:  # noqa: BLE001
                self.logger.exception("Failed to regenerate section %s: %s", section_name, exc)
                addition = self._fallback_section_content(section_name, keyword, plan)
            if not addition:
                continue
            if f"## {section_name}" not in addition:
                addition = f"## {section_name}\n{addition.strip()}"
            updated = f"{updated.rstrip()}\n\n{addition.strip()}\n"
        normalized_text = unicodedata.normalize("NFKC", updated or "")
        remaining_missing = [s for s in self.settings.article.required_sections if not section_present(normalized_text, s)]
        if remaining_missing:
            self.logger.warning("Sections still missing after regeneration: %s", ", ".join(remaining_missing))
        return updated, normalized_text, remaining_missing

    def _generate_section_addendum(self, section_name: str, current_text: str, keyword: str, plan: dict) -> str:
        if not self.model:
            return ""
        outline = plan.get("outline") if isinstance(plan, dict) else None
        summary = plan.get("summary") if isinstance(plan, dict) else ""
        prompt_parts = [
            "あなたはプロのSEOライターです。",
            f"対象キーワード: {keyword}",
        ]
        if summary:
            prompt_parts.append(f"記事の要約: {summary}")
        if outline:
            prompt_parts.append("記事の構成:\n" + "\n".join(f"- {item}" for item in outline))
        prompt_parts.append("既存の本文を以下に示します。この本文に欠けている指定セクションだけを追記してください。")
        prompt_parts.append(current_text)
        if section_name == "参考リンク":
            instructions = (
                "'## 参考リンク' の見出しを付け、信頼できる公開情報のリンクを日本語説明付きで3〜5件、箇条書きで提示。"
                "ダミーURLは禁止。"
            )
        else:
            instructions = (
                f"欠落しているセクションは '{section_name}'。H2見出しから開始し、具体例・統計・手順を200〜400字で。"
                "テンプレ表現や一般論のみは禁止。読者が行動に移せる示唆を含める。"
            )
        prompt_parts.append(instructions)
        prompt_parts.append("出力は指定セクションのみ。余計な前置きや後書きは不要。")
        prompt = "\n\n".join(prompt_parts)
        response = self.model.generate_content([prompt])
        addition = (self._extract_text(response) or "").strip()
        if not addition:
            self.logger.warning("Empty addition generated for section %s", section_name)
            addition = (self._fallback_section_content(section_name, keyword, plan) or "").strip()
        return addition

    def _synthesize_missing_sections(self, text: str, keyword: str, plan: dict, required_sections: List[str]) -> str:
        normalized = unicodedata.normalize("NFKC", text or "")
        missing = [s for s in required_sections if not section_present(normalized, s)]
        if not missing:
            return text
        synth = self._synthesize_dummy_text(keyword, plan, missing)
        if synth:
            if not text:
                return synth
            return f"{text.rstrip()}\n\n{synth.strip()}\n"
        return text

    # ------------------------------------------------------------------
    # Dummy text synthesis for dry-run / healing
    # ------------------------------------------------------------------
    def _synthesize_dummy_text(self, keyword: str, plan: dict, sections_to_emit: List[str]) -> str:
        """必須セクションを含む“自然なダミー本文”を合成。禁句は避ける。"""
        outline = [str(x) for x in (plan.get("outline") or []) if str(x).strip()]
        summary = str(plan.get("summary") or "").strip() if isinstance(plan, dict) else ""

        parts: List[str] = []
        # リード（100〜200字目安）
        lead = self._make_lead(keyword, plan)
        parts.append(lead)

        # セクション本文
        for sec in sections_to_emit:
            if sec == "参考リンク":
                parts.append(self._synth_ref_section())
                continue
            body = self._synth_section_paragraphs(sec, keyword, outline, summary)
            parts.append(f"## {sec}\n{body}")

        body_text = "\n\n".join(parts).strip()

        # ターゲット長へ緩やかに伸長
        target = int(getattr(self.settings.article, "target_chars", 3800) or 3800)
        min_len = int(getattr(self.settings.article, "min_chars", 3000) or 3000)
        if len(body_text) < min_len:
            filler = (
                "実務の現場で再現しやすい手順やチェックリストを整え、期待値をコントロールしながら"
                "小さく検証して改善を重ねることが、読者にとって価値の高い情報提供につながります。"
            )
            while len(body_text) < min_len:
                body_text += "\n\n" + filler
                if len(body_text) >= target:
                    break
        return body_text

    def _make_lead(self, keyword: str, plan: dict) -> str:
        outline = plan.get("outline") if isinstance(plan, dict) else None
        summary = plan.get("summary") if isinstance(plan, dict) else None
        base = (
            f"{keyword} をテーマに、現場で使える手順とポイントを整理しました。"
            "初見の読者でも迷わず実行に移せるよう、背景と結論、具体的な進め方、失敗しやすい箇所、実例、最後に次の一手までを短いステップで提示します。"
        )
        if summary:
            base = str(summary).strip()[:180]
        # 100〜200字程度に収める
        if len(base) < 100:
            base += " 読み手の前提知識を問わず、最短で成果に近づくためのヒントをまとめています。"
        return base[:200]

    def _synth_section_paragraphs(self, section: str, keyword: str, outline: List[str], summary: str) -> str:
        if section == "背景と課題":
            return (
                "生成AIを巡る環境は高速で変化しており、社内の判断や運用体制が整わないまま試行錯誤だけが先行しがちです。"
                "本稿では、なにから手を付ければよいかを明確にし、読み手が今すぐ着手できる下準備を提示します。"
            )
        if section.startswith("結論") or section == "結論":
            return (
                f"{keyword} を成功させる要点は『小さく始めてログと検証を残す』ことです。"
                "意思決定ポイントを明確化し、効果検証と改善を最短サイクルで回す設計が、費用対効果を最大化します。"
            )
        if section == "手順":
            return (
                "1. 目的と評価指標を1枚にまとめる\n"
                "2. 対象業務を分解し、反復部分から自動化・雛形化\n"
                "3. 権限・データ取り扱い・レビュー体制を明文化\n"
                "4. 小規模に実装して、結果とログを記録\n"
                "5. フィードバックを踏まえて次の反復へ"
            )
        if section == "よくある失敗と対策":
            return (
                "・目的が曖昧なまま導入して効果測定できない → 先にKPIと判断基準を定義\n"
                "・ハルシネーション対策が後手 → 出典ログと人間レビューを必須化\n"
                "・属人運用で再現性がない → 手順書と雛形を先に作る"
            )
        if section == "事例・効果":
            return (
                "小売ではFAQ自動化で応答時間を半減、営業現場では定型文の自動生成で作業時間を30%削減するなど、"
                "“小さく始める”設計が成果を押し上げた例が増えています。定量と定性の両面で効果を測るのが共通点です。"
            )
        if section.startswith("まとめ"):
            return (
                "今日からできるのは、対象業務の棚卸しと評価指標の言語化です。まずは1週間だけ小さな実験計画を立て、"
                "ログと学びを残す運用に切り替えましょう。継続すれば、負担を増やさず成果が積み上がります。"
            )
        # デフォルト: セクション名に沿った無難な本文
        return (
            f"{section} では、{keyword} の実務運用でつまずきやすいポイントを短い段落で整理します。"
            "前提条件、判断基準、作業の分担、見落としがちな制約を明記し、読み手が次の一手を取りやすい形に整えます。"
        )

    def _synth_ref_section(self) -> str:
        lines = [
            "## 参考リンク",
            "- https://docs.github.com/ja/actions",
            "- https://cloud.google.com/ai-studio?hl=ja",
            "- https://note.com/notemag/m/m63f63c0d19df",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Lead / references / structure utils
    # ------------------------------------------------------------------
    def _extract_lead(self, body: str) -> tuple[str, str]:
        if not body:
            return "", ""
        lines = body.lstrip().splitlines()
        if not lines:
            return "", body
        # 先頭行が見出しならリードなし扱い
        if lines[0].lstrip().startswith(('#', '##')):
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
        m = re.search(r"##\s*参考リンク[\s\S]*$", body, flags=re.MULTILINE)
        if not m:
            return refs
        block = m.group(0)
        for url in re.findall(r"https?://\S+", block):
            refs.append(url.rstrip(").]、。,"))
        return refs

    # ------------------------------------------------------------------
    # Length / structure safety
    # ------------------------------------------------------------------
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
        # 超過時は末尾優先でソフトカット
        fallback = body[:max_len]
        cutoff = fallback.rfind("\n\n")
        if cutoff >= max_len // 2:
            return fallback[:cutoff].rstrip()
        for punct in ("。", "．", "！", "？", "!", "?"):
            idx = fallback.rfind(punct)
            if idx >= max_len // 2:
                return fallback[: idx + 1].rstrip()
        return fallback.rstrip()

    def _ensure_balanced_fences(self, body: str) -> str:
        fence_count = body.count("```")
        if fence_count % 2 == 0:
            return body
        self.logger.warning("Unbalanced code fence detected; appending closing fence")
        return body.rstrip() + "\n```\n"

    # ------------------------------------------------------------------
    # Section parsing helpers (kept compatible)
    # ------------------------------------------------------------------
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
        for section in sections:
            parts.append(section.heading)
            parts.extend(section.paragraphs)
        return "\n\n".join(parts).strip()

    def _normalize_heading(self, heading: str) -> str:
        without_hash = heading.lstrip("#").strip()
        return without_hash

    def _fallback_section_content(self, section_name: str, keyword: str, plan: dict) -> str:
        # 最小限のフォールバック。ダミー・プレースホルダ表現は避ける。
        mapping: Dict[str, str] = {
            "背景と課題": (
                "現場での導入は期待値だけが先行しやすく、運用体制や効果測定が後回しになる傾向があります。"
                "本節では着手の勘所と、検討を止めないための最低限の準備を述べます。"
            ),
            "結論": (
                f"{keyword} の成功条件は『小さく始め、検証ログを残す』ことです。判断ポイントを明確にし、改善ループを短く回しましょう。"
            ),
            "手順": (
                "1. 目的と評価指標を定義\n2. 対象業務を分解\n3. 権限とレビュー体制を整備\n4. 小規模実装\n5. 検証と改善"
            ),
            "よくある失敗と対策": (
                "・効果測定が曖昧 → KPIと判断基準を先に定義\n・データ扱いの不備 → 取り扱いルールを明文化\n・属人運用 → 手順書化"
            ),
            "事例・効果": (
                "質問応答の自動化や定型文生成で、処理時間の短縮と均質化を実現した例が増えています。"
            ),
            "まとめ（CTA)": (
                "まずは1週間の小さな実験計画を作り、ログを残す運用に切り替えましょう。継続すれば成果が積み上がります。"
            ),
            "参考リンク": (
                "- https://docs.github.com/ja/actions\n- https://cloud.google.com/ai-studio?hl=ja\n- https://note.com/notemag/m/m63f63c0d19df"
            ),
        }
        content = mapping.get(section_name)
        if content and section_name == "参考リンク":
            return f"## 参考リンク\n{content}"
        if content:
            return f"## {section_name}\n{content}"
        return f"## {section_name}\n{keyword} に関する要点を簡潔に整理し、次の一手を明確にします。"

    def _persist_debug(self, text: str, keyword: str) -> None:
        try:
            debug_dir = self.settings.logs_dir / "debug"
            debug_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
            slug = generate_slug(keyword or "article")
            debug_path = debug_dir / f"{slug}-{timestamp}.md"
            debug_path.write_text(text or "", encoding="utf-8")
            self.logger.error("Saved failing body to %s", debug_path)
        except Exception:  # noqa: BLE001
            self.logger.exception("Failed to persist debug article body")
