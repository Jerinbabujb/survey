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


def weighted_score(score: int) -> int:
    """Return weighted score for a single question."""
    score=int(score)
    return score * 9







import hashlib

def hash_token(token: str) -> str:
    """Generate a SHA-256 hash of a given token."""
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def get_score_category(score: int) -> str:
    if 41 <= score <= 45:
        return "Outstanding"
    elif 32 <= score <= 40:
        return "Exceeds Target"
    elif 23 <= score <= 31:
        return "Meets Target"
    else:  # 10–25
        return "Below Target"


def get_score_category_score(score: int) -> str:
    if 41 <= score <= 45:
        return "Exceptional leadership, highly supportive, inspires and motivates the team consistently."
    elif 32 <= score <= 40:
        return "Frequently goes beyond expectations, provides strong support and communication."
    elif 23 <= score <= 31:
        return "Performs at expected level, provides adequate support, guidance, and communication."
    else:  # 10–25
        return "Performance below expectations, needs improvement in support, communication, or leadership."


