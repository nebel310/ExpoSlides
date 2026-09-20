import re

FACT_TOKEN_PATTERN = re.compile(r"(?<!\w)\d+(?:[.,]\d+)?[ \t]*%?")
WORD_PATTERN = re.compile(r"[a-zа-яё]{4,}", re.IGNORECASE)
STOP_WORDS = {
    "будет",
    "были",
    "было",
    "года",
    "году",
    "данных",
    "который",
    "между",
    "после",
    "перед",
    "также",
    "этого",
    "этот",
}
CLAIM_MARKER_PATTERNS = (
    re.compile(r"\b(?:вдвое|втрое|вчетверо)\b", re.IGNORECASE),
    re.compile(r"\bв\s+\d+(?:[.,]\d+)?\s+раз(?:а)?\b", re.IGNORECASE),
    re.compile(r"\bна\s+\d+(?:[.,]\d+)?\s*%", re.IGNORECASE),
)


def extract_fact_tokens(text: str) -> set[str]:
    return {
        match.group(0).replace(" ", "").replace(",", ".")
        for match in FACT_TOKEN_PATTERN.finditer(text)
    }


def extract_significant_words(text: str) -> set[str]:
    return {
        word.casefold()
        for word in WORD_PATTERN.findall(text)
        if word.casefold() not in STOP_WORDS
    }


def find_unsupported_claim_markers(source_text: str, generated_text: str) -> set[str]:
    """Find derived quantitative claims whose marker is absent from the source."""
    unsupported = set()
    for pattern in CLAIM_MARKER_PATTERNS:
        if pattern.search(source_text):
            continue
        unsupported.update(match.group(0).casefold() for match in pattern.finditer(generated_text))
    return unsupported
