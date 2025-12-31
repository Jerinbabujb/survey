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
    "How proactive is the department head in anticipating challenges and escalating issues appropriately?",
    "How effectively does the department head demonstrate leadership within their team (e.g., motivation, accountability, clarity)?",
    "How effectively does the department head model company values and culture in their day-to-day leadership?",
    "Does the department head have a positive impact on company performance this year?",
    "How effectively does the department head identify, manage, and communicate risks that could impact company performance or reputation?",
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
    Convert raw survey score (1–5) into weighted score.
    Rule:
      5 -> 10
      1–4 -> 9
    """
    return 10 if score == 5 else 9


def calculate_total_score(scores: Iterable[int]) -> int:
    """
    Calculate total weighted score for a submission.
    Example:
      [5, 5, 4, 3] -> 10 + 10 + 9 + 9 = 38
    """
    return sum(normalize_score(score) for score in scores)


def get_score_category(total_score: int) -> str:
    """
    Convert total weighted score into performance category.
    Total score range (10 questions):
      46–50 -> Outstanding
      36–45 -> Exceeds Target
      26–35 -> Meets Target
      10–25 -> Below Target
    """
    if total_score >= 46:
        return "Outstanding"
    if total_score >= 36:
        return "Exceeds Target"
    if total_score >= 26:
        return "Meets Target"
    return "Below Target"

# =========================
# Security Utilities
# =========================

def hash_token(token: str) -> str:
    """
    Generate a SHA-256 hash for survey tokens.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
