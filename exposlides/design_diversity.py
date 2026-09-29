"""Попарная проверка композиций: номера образцов не считаются различием."""

from itertools import combinations

from exposlides.design_models import DeckPlan, TemplateProfile
from exposlides.template_layout import composition_key


def variant_diversity(profile: TemplateProfile, variants: list[DeckPlan]) -> dict:
    """Каждая пара колод различается хотя бы одним слайдом, включая обложку."""
    patterns = {pattern.source_slide_index: composition_key(pattern) for pattern in profile.patterns}

    def signature(slide):
        return (patterns[slide.source_slide_index], tuple(sorted(
            (block.kind, tuple(round(v / 12700) for v in block.box.model_dump().values()),
             block.style.font, round(block.style.size, 1), block.text, tuple(block.items))
            for block in slide.blocks if block.kind != "page_number"
        )))

    pairs = []
    for left, right in combinations(variants, 2):
        if [s.story_slide_id for s in left.slides] != [s.story_slide_id for s in right.slides]:
            raise ValueError("Варианты должны содержать одну и ту же историю")
        slides = list(zip(left.slides, right.slides, strict=True))
        different = sum(signature(a) != signature(b) for a, b in slides)
        pairs.append({"left": left.variant_id, "right": right.variant_id,
                      "different": different, "compared": len(slides),
                      "sufficient": different > 0})
    return {"rule": "pairwise_distinct_decks", "common_cover_allowed": True,
            "sufficient": len(variants) == 3 and all(p["sufficient"] for p in pairs),
            "pairs": pairs}
