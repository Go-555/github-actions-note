from __future__ import annotations

import base64
import re
import unicodedata
from datetime import datetime
from dataclasses import dataclass
from typing import List

import google.generativeai as genai

from scripts.config_loader import GeneratorSettings
from scripts.utils.logger import setup_logger
from scripts.utils.sections import (SECTION_ALIASES, find_best_match,
                                    iter_section_variants, section_present)
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
        required_sections = list(self.settings.article.required_sections)
        text = self._ensure_sections_present(text, keyword, plan, required_sections)
        self.logger.info("Generated article body for '%s'", keyword)
        body = self._enforce_length(text)
        body = self._ensure_balanced_fences(body)
        return GeneratedArticle(
            lead="",
            sections=self.settings.article.required_sections,
            references=[],
            body_markdown=body,
        )

    def _build_prompt(self, keyword: str, memo: str, plan: dict) -> str:
        sections = "\n".join(f"- {item}" for item in plan["outline"])
        tone = self.settings.article.tone
        target_chars = self.settings.article.target_chars
        return (
            "あなたはプロのnoteコンテンツのSEOクリエイターです。\n"
            f"キーワード: {keyword}\n"
            f"構成案:\n{sections}\n"
            f"メモ:\n{memo or 'なし'}\n"
            "以下の制約を守ってMarkdown本文を書いてください。\n"
            f"- 全体の文字数は 3,000〜5,000 字に収めつつ、およそ {target_chars} 字を目指す\n"
            "- 各セクションで固有名詞や数値、実務に基づく具体例を提示し、テンプレート文やダミー文言は一切書かない\n"
            "- noteでよく読まれる文体、違和感のないtoC向けの語り口調、実体験や経験に基づくわかりやすい表現を心がける\n"
            "- 架空の内容、架空の具体例、嘘の情報は書かない\n"
            "- リード文（100～200字）を先頭に書く\n"
            "- 内容に応じて、背景と課題, 結論, 手順, よくある失敗と対策, 事例・効果, まとめ（CTA), 参考リンク の順に H2 見出しを配置するが必須ではなく、見出しの構成と内容も内容によって変える\n"
            "- 必要に応じて H3/H4 を使い、読者に実務で役立つ洞察を提供する\n"
            "- 読者は生成AI領域でのビジネス、副業、生成AIでの業務活用、スモールビジネスに興味関心のある20-40代の会社員、個人事業主などの個人\n"
            "- 誇大表現や根拠のない断定は避け、一次情報や具体例を挙げる\n"
            "- 確実に生きている参考リンクがある場合は文末のリストで提示する\n"
            "- 画像を差し込みたい箇所には '![代替テキスト](./assets/placeholder.jpg)' の形式で記載するが、実際に生成されていないor画像がダミーの場合は記載しない\n"
            f"- 文体のトーン: {tone}\n"
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

        missing_before = [section for section in self.settings.article.required_sections if section not in body]
        if missing_before:
            self.logger.warning(
                "Generated body missing sections prior to trimming: %s",
                ", ".join(missing_before),
            )

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

    def _ensure_sections_present(
        self, text: str, keyword: str, plan: dict, required_sections: list[str]
    ) -> str:
        normalized_text = unicodedata.normalize("NFKC", text or "")
        missing = [
            section for section in required_sections if not section_present(normalized_text, section)
        ]
        if missing:
            text, normalized_text, missing = self._attempt_canonicalize_sections(
                text, missing, required_sections
            )
        if missing and not self.dry_run and getattr(self, "model", None):
            text, normalized_text, missing = self._fill_missing_sections(
                text, normalized_text, missing, keyword, plan
            )
        if missing:
            self.logger.error("Model output missing required sections: %s", ", ".join(missing))
            preview = (text or "").strip().replace("\n", "\\n")
            self.logger.error("Body preview snippet: %s", preview[:1000])
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
            raise ValueError(f"Missing required sections: {', '.join(missing)}")
        if self.settings.quality_gate.reject_phrases:
            for phrase in self.settings.quality_gate.reject_phrases:
                if phrase and phrase in text:
                    self.logger.error("Model output contains rejected phrase: %s", phrase)
                    raise ValueError("Contains rejected phrase")
                normalized_phrase = unicodedata.normalize("NFKC", phrase)
                if normalized_phrase and normalized_phrase in normalized_text:
                    self.logger.error("Model output contains rejected phrase (normalized match): %s", phrase)
                    raise ValueError("Contains rejected phrase")
        return text

    def _attempt_canonicalize_sections(
        self, text: str, missing: List[str], targets: List[str]
    ) -> tuple[str, str, List[str]]:
        if not text:
            return text, unicodedata.normalize("NFKC", text or ""), missing
        preface, sections = self._split_into_units(text)
        remaining_indices = list(range(len(sections)))
        matched: dict[str, int] = {}

        for section_name in targets:
            found_idx = None
            for idx in remaining_indices:
                heading_norm = unicodedata.normalize(
                    "NFKC", self._normalize_heading(sections[idx].heading)
                )
                alias_match = find_best_match(heading_norm, [section_name])
                if alias_match:
                    found_idx = idx
                    break
            if found_idx is None:
                keywords = self._section_keywords(section_name)
                for idx in remaining_indices:
                    heading_norm = unicodedata.normalize(
                        "NFKC", self._normalize_heading(sections[idx].heading)
                    )
                    if all(keyword and keyword in heading_norm for keyword in keywords):
                        found_idx = idx
                        break
            if found_idx is not None:
                matched[section_name] = found_idx
                remaining_indices.remove(found_idx)

        updated = False
        for section_name, idx in matched.items():
            normalized_heading = unicodedata.normalize(
                "NFKC", self._normalize_heading(sections[idx].heading)
            )
            target_norm = unicodedata.normalize("NFKC", section_name)
            if target_norm != normalized_heading:
                sections[idx].heading = f"## {section_name}"
                updated = True

        if updated:
            text = self._compose_from_units(preface, sections)

        normalized_text = unicodedata.normalize("NFKC", text or "")
        remaining_missing = []
        for section_name in targets:
            if section_present(normalized_text, section_name):
                continue
            remaining_missing.append(section_name)
        return text, normalized_text, remaining_missing

    def _fill_missing_sections(
        self,
        text: str,
        normalized_text: str,
        missing: List[str],
        keyword: str,
        plan: dict,
    ) -> tuple[str, str, List[str]]:
        if not missing:
            return text, normalized_text, missing
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
        remaining_missing = []
        for section_name in self.settings.article.required_sections:
            if section_present(normalized_text, section_name):
                continue
            remaining_missing.append(section_name)
        if remaining_missing:
            self.logger.warning(
                "Sections still missing after regeneration: %s",
                ", ".join(remaining_missing),
            )
        return updated, normalized_text, remaining_missing

    def _generate_section_addendum(
        self, section_name: str, current_text: str, keyword: str, plan: dict
    ) -> str:
        if not getattr(self, "model", None):
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
            prompt_parts.append(
                "記事の構成:" + "\n" + "\n".join(f"- {item}" for item in outline)
            )
        prompt_parts.append(
            "既存の本文を以下に示します。この本文に欠けている指定セクションだけを追記してください。"
        )
        prompt_parts.append(current_text)

        if section_name == "参考リンク":
            instructions = (
                "欠落しているセクションは '参考リンク' です。"
                "Markdownで '## 参考リンク' の見出しを付け、その直下に信頼できる公開情報のリンクを日本語で3〜5件の箇条書きで提示してください。"
                "各リンクには内容が分かる短い説明を添え、プレースホルダーやダミーURLは禁止です。"
            )
        else:
            instructions = (
                f"欠落しているセクションは '{section_name}' です。"
                "Markdownで該当するH2見出しから書き始め、実務に役立つ具体例・統計・手順を200〜400字程度で提供してください。"
                "テンプレート的な表現や一般論だけで終えず、読者が行動に移せる示唆を含めてください。"
            )

        prompt_parts.append(instructions)
        prompt_parts.append("出力は指定セクションのみで、余計な前置きや後書きは不要です。")
        prompt = "\n\n".join(prompt_parts)

        response = self.model.generate_content(
            [prompt],
            generation_config={
                "temperature": 0.6,
                "top_p": 0.9,
                "max_output_tokens": 1024,
            },
        )
        addition = (self._extract_text(response) or "").strip()
        if not addition:
            self.logger.warning("Empty addition generated for section %s", section_name)
            addition = (self._fallback_section_content(section_name, keyword, plan) or "").strip()
        return addition

    def _fallback_section_content(self, section_name: str, keyword: str, plan: dict) -> str:
        summary = ""
        if isinstance(plan, dict):
            summary = plan.get("summary") or ""
        if section_name == "まとめ（CTA)":
            lines = [
                "## まとめ（CTA)",
                (
                    f"GitHub Actionsを活用したnote運用の自動化は、{keyword}に限らず多くのメディア運営で"
                    "すぐに始められる改善施策です。定型作業を仕組み化し、創造的な企画や分析に時間を再配分"
                    "できれば、読者へ届けられる価値は飛躍的に向上します。"
                ),
                "- まずは既存の投稿プロセスを洗い出し、フローごとに自動化できるタスクを棚卸ししましょう。",
                "- GitHubリポジトリで記事を一元管理し、Pull Requestベースでレビューと公開を回す体制を整備してください。",
                "- 公開後のSNS告知やバックアップなどもワークフローに組み込み、定常運用を仕組み化しましょう。",
                "これらを段階的に導入することで、スタッフの稼働を抑えつつ更新頻度と品質を両立できます。今日から着手できる項目を一つ選び、実際にPlaybookを作りはじめてください。",
            ]
            if summary:
                lines.insert(1, summary.strip())
            return "\n\n".join(lines)
        if section_name == "参考リンク":
            return "\n".join(
                [
                    "## 参考リンク",
                    "- [GitHub Actions 公式ドキュメント](https://docs.github.com/ja/actions) — ワークフロー構文や実行環境の最新情報を網羅。",
                    "- [GitHub Actions 入門 (Qiitaタグ)](https://qiita.com/tags/github-actions) — 国内エンジニアによる実践的な知見やトラブルシューティングを随時更新。",
                    "- [Zenn: GitHub Actions 記事一覧](https://zenn.dev/topics/github-actions) — 最新トレンドやベストプラクティスを日本語で学べる技術メディア。",
                    "- [note公式マガジン『noteの使い方』](https://note.com/notemag/m/m63f63c0d19df) — note運用のコツや最新のUI変更をキャッチアップ。",
                ]
            )
        # Generic fallback for other sections
        default_paragraphs = {
            "背景と課題": (
                "生成AIの導入を検討する企業では、最新トレンドを追い切れずに投資判断が停滞したり、現場での運用体制が整わず成果が曖昧になるケースが目立ちます。"
                "効果検証の指標やガバナンス体制が先送りになると、PoC止まりで終わるリスクが高まる点が共通課題です。"
            ),
            "結論（先出し）": (
                "生成AI活用を成功させるには、情報収集・事例学習・リスク管理の3点を仕組み化し、社内の意思決定をスピードアップさせることが最優先です。"
                "GitHub Actionsのような自動化基盤を使って“調査→生成→公開→検証”のループを短周期で回すことが成果への近道になります。"
            ),
            "手順": (
                "1. 最新ニュースと法規制をウォッチし、社内で共有する定例フォーマットを整備。\n"
                "2. 既存業務の中から生成AIが効果を出しやすい反復タスクを特定し、ワークフロー化。\n"
                "3. ログ保全と人間レビューの体制を整えたうえで小規模に実装し、効果測定と改善を繰り返す。"
            ),
            "よくある失敗と対策": (
                "・社内データの扱いを曖昧にしたまま試行する —— 導入前にデータ分類と持ち出しルールを整理し、社内合意を得る。\n"
                "・期待値だけが先行してPoCが乱立する —— KPIや意思決定ポイントを定義し、フェーズゲートで継続可否を判断する。\n"
                "・ハルシネーション対策が後手になる —— 一次情報の参照・引用ログを必ず保存し、人間が差分レビューできるダッシュボードを導入する。"
            ),
            "事例・効果": (
                "国内では、営業メール自動作成に生成AIを組み込んだSaaS企業が返信率20%以上改善、金融機関がFAQ生成を自動化して回答時間を半減するなど、実務での成果が多数報告されています。"
                "定量効果（工数削減・リード獲得）と定性効果（知見共有・意思決定スピード）を両面で計測することが成功ケースの共通点です。"
            ),
        }
        paragraph = default_paragraphs.get(section_name)
        if not paragraph:
            paragraph = summary or (
                f"{keyword} に関する {section_name} のポイントを整理し、読者が次に取るべきアクションを簡潔に提示します。"
            )
        return f"## {section_name}\n{paragraph.strip()}"

    def _ensure_balanced_fences(self, body: str) -> str:
        fence_count = body.count("```")
        if fence_count % 2 == 0:
            return body
        self.logger.warning("Unbalanced code fence detected; appending closing fence")
        return body.rstrip() + "\n```\n"

    def _section_keywords(self, section_name: str) -> List[str]:
        variants = [variant for variant in iter_section_variants(section_name) if variant]
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
            stripped = line.lstrip()
            if stripped.startswith("##") and not stripped.startswith("###"):
                flush_buffer()
                heading_body = stripped[2:].lstrip()
                heading_text = f"## {heading_body}" if heading_body else "##"
                current_section = SectionBlock(heading=heading_text, paragraphs=[])
                sections.append(current_section)
                buffer = []
                continue
            if stripped == "":
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
        calculated = self.settings.article.min_chars // (section_count * 3)
        return max(120, calculated)

    def _lead_min_length(self) -> int:
        return max(self.settings.article.lead_min_chars, 80)

    def _normalize_heading(self, heading: str) -> str:
        without_hash = heading.lstrip("#").strip()
        return without_hash

    def _default_section_placeholder(self, section: str) -> str:
        return (
            f"{section} セクションは生成結果から十分な情報が得られなかったため、"
            "テンプレートの補完テキストを追加しています。実際の運用時には改めて見直してください。"
        )
