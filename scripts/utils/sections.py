from __future__ import annotations

import unicodedata
from typing import Dict, Iterable, List, Sequence


SECTION_ALIASES: Dict[str, Sequence[str]] = {
    "背景と課題": ("背景と課題", "背景", "課題"),
    "結論（先出し）": ("結論（先出し）", "結論", "結論まとめ"),
    "手順": ("手順", "ステップ", "実行手順"),
    "よくある失敗と対策": ("よくある失敗と対策", "失敗と対策", "失敗例", "注意点"),
    "事例・効果": ("事例・効果", "事例", "成功事例", "効果"),
    "まとめ（CTA)": ("まとめ（CTA)", "まとめ", "次のアクション", "CTA"),
    "参考リンク": ("参考リンク", "参考資料", "リソース"),
}


def normalize(text: str | None) -> str:
    return unicodedata.normalize("NFKC", text or "")


def iter_section_variants(section: str) -> Iterable[str]:
    yield section
    aliases = SECTION_ALIASES.get(section, ())
    for alias in aliases:
        yield alias


def section_present(body: str, section: str) -> bool:
    normalized_body = normalize(body)
    for variant in iter_section_variants(section):
        normalized_variant = normalize(variant)
        if not normalized_variant:
            continue
        if normalized_variant in normalized_body:
            return True
        heading_variant = normalize(f"## {variant}")
        if heading_variant in normalized_body:
            return True
    return False


def find_best_match(heading: str, candidates: Sequence[str]) -> str | None:
    normalized_heading = normalize(heading)
    for canonical in candidates:
        for alias in iter_section_variants(canonical):
            if normalize(alias) in normalized_heading:
                return canonical
    return None


def canonicalize_outline(outline: Sequence[str]) -> List[str]:
    canonical: List[str] = []
    for heading in outline:
        match = find_best_match(heading, SECTION_ALIASES.keys())
        canonical.append(match or heading)
    return canonical
