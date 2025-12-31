from typing import Iterable
import hashlib

# =========================
# Survey Questions
# =========================

QUESTIONS = [
    "How satisfied are you with the overall performance of the department head?",
    "How effectively does the department head align their team’s objectives with overall company strategy?",
    "How satisfied are you with the level of internal support provided by the department head?",
    "How effective is the department head in communicating with the Executive Leadership Team?",
    "How collaborative is the department head when working cross-functionally on company-wide initiatives?",
]

# =========================
# Score Labels
# =========================

SCORES = {
    5: "Strongly Agree",
    4: "Agree",
    3: "Satisfactory",
    2: "Disagree",
    1: "Strongly Disagree",
}

# =========================
# Scoring Logic
# =========================

def normalize_score(score: int) -> int:
    """
    Convert raw score (1–5) into weighted score.
    Rule:
      5 -> 10
      1–4 -> 9
    """
    return 10 if score == 5 else 9


def calculate_total_score(scores: Iterable[int]) -> int:
    """
    Calculate total weighted score.

    Example:
      [5, 4, 3, 2, 1]
      -> 10 + 9 + 9 + 9 + 9
      -> 46 (if 5 questions, max = 45)
    """
    return sum(normalize_score(score) for score in scores)


def get_score_category(total_score: int) -> str:
    """
    Convert total weighted score into a performance category.

    Score Ranges:
      41–45 -> Outstanding
      32–40 -> Exceeds Target
      23–31 -> Meets Target
       9–22 -> Below Target
    """
    if 41 <= total_score <= 45:
        return "Outstanding"
    elif 32 <= total_score <= 40:
        return "Exceeds Target"
    elif 23 <= total_score <= 31:
        return "Meets Target"
    else:
        return "Below Target"

# =========================
# Security Utilities
# =========================

def hash_token(token: str) -> str:
    """
    Generate a SHA-256 hash for survey tokens.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
