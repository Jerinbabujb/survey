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


SCORES = {
    5: "Strongly Agree",
    4: "Agree",
    3: "Satisfactory",
    2: "Disagree",
    1: "Strongly Disagree",
}


def score_category(total: int) -> str:
    if total >= 46:
        return "Outstanding"
    if total >= 36:
        return "Exceeds Target"
    if total >= 26:
        return "Meets Target"
    return "Below Target"

from typing import Optional, Iterable


def calculate_total_score(scores: Iterable[int]) -> int:
    """
    Multiply EACH question score by 10, then sum.
    Example: [5,4,5] -> 50 + 40 + 50 = 140
    """
    total = 0
    for score in scores:
        if score == 5:
            total += 10
        else:  # 1, 2, 3, 4
            total += 9
    return total





import hashlib

def hash_token(token: str) -> str:
    """Generate a SHA-256 hash of a given token."""
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def get_score_category(score: int) -> str:
    if 46 <= score <= 50:
        return "Outstanding"
    elif 36 <= score <= 45:
        return "Exceeds Target"
    elif 26 <= score <= 35:
        return "Meets Target"
    else:  # 10–25
        return "Below Target"
