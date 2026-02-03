import hashlib
from typing import List

# ===============================
# Survey Questions
# ===============================

QUESTIONS = [
    "How satisfied are you with the overall performance of the employee?",
    "How effectively does the employee align their team’s objectives with overall company strategy?",
    "How satisfied are you with the level of internal support provided by the employee?",
    "How effective is the employee in communicating with the Executive Leadership Team?",
    "How collaborative is the employee when working cross-functionally on company-wide initiatives?",
    "How proactive is the employee in anticipating challenges and escalating issues appropriately?",
    "Does the employee contribute positively to the company performance?",
    "How effective is the employee in identifying, managing, and communicating risks that could impact company performance or reputation?",
]

CLIENT_QNS = [
    "How effective is the employee in communicating with you?",
    "How collaborative is the employee when working cross functionally with your department?",
    "How responsive is the employee in addressing feedback, questions, or internal requests?",
    "How satisfied are you with the quality of the support provided by the employee?",
    "How effectively does the employee understand your needs and take appropriate action to resolve issues?",
    "How effectively does the employee demonstrate accountability within their function?",
    "How often does the employee proactively identify and address opportunities for improvement?",
]

TEAM_QNS = [
    "How satisfied are you with the support provided by your line manager for achieving your goals?",
    "Do you believe that your line manager communicates the organization's vision clearly?",
    "How approachable do you find your line manager when you have concerns or issues?",
    "How effective is communication by your line manager regarding important updates and changes within the organization?",
    "How often does your line manager provide constructive feedback on your performance in a timely manner?",
    "How would you rate the effectiveness of decisions made by your line manager?",
    "How effectively does your line manager manage the team and priorities?",
    "How effectively does your line manager create a positive impact on team morale and motivation?",
    "How effectively does your line manager actively listen to feedback and ideas?",
    "Does your line manager demonstrate respect and fairness toward others?",
    "Are the tasks assigned by your line manager part of your job description (JD)?",
    "Does your line manager give clear instructions that are in line with SOPs/policies? If exceptions occur, are they clearly justified?",
    "Is your current role aligned with your previous experiences and professional path?",
    "Are you overburdened with your assigned tasks? If yes, has this been addressed by your line manager?",
    "Do you have the required tools to complete your job?",
    "Do you have the required resources within the department for completion of tasks?",
]

# ===============================
# Survey Metadata
# ===============================

SURVEY_DETAILS = {
    "MSES": {
        "full_name": "Management Satisfaction Survey",
        "questions": QUESTIONS
    },
    "ICSES": {
        "full_name": "Internal Customer Satisfaction Survey",
        "questions": CLIENT_QNS
    },
    "TSES": {
        "full_name": "Team Satisfaction Survey",
        "questions": TEAM_QNS
    }
}

# ===============================
# Normalize Survey Name
# ===============================

def normalize_survey_name(input_name: str) -> str:
    """
    Standardizes input to MSES, ICSES, or TSES.
    Accepts either short code or full survey name.
    """
    if not input_name:
        return ""

    name = input_name.strip().upper()

    # Check short codes
    if name in SURVEY_DETAILS:
        return name

    # Check full names
    for key, data in SURVEY_DETAILS.items():
        if name == data["full_name"].upper() \
           or name == data["full_name"].replace(" Survey", "").upper():  # optional shorthand
            return key

    # If no match, return as-is (or raise error later)
    return name

# ===============================
# Score Mapping
# ===============================

SCORES = {
    5: "Strongly Agree",
    4: "Agree",
    3: "Satisfactory",
    2: "Disagree",
    1: "Strongly Disagree",
}

# ===============================
# Hashing Utility
# ===============================

def hash_token(token: str) -> str:
    """Generate a SHA-256 hash of a given token."""
    return hashlib.sha256(token.encode('utf-8')).hexdigest()

# ===============================
# Survey Scoring and Descriptions
# ===============================

# ---- Management Satisfaction Survey ----
def management_score_category(total: int) -> str:
    if 36 <= total <= 40:
        return "Outstanding"
    elif 29 <= total <= 35:
        return "Exceeds Target"
    elif 20 <= total <= 28:
        return "Meets Target"
    else:
        return "Below Target"

def management_score_description(total: int) -> str:
    if 32 <= total <= 35:
        return "Exceptional leadership; highly supportive, consistently inspires and motivates the team."
    elif 26 <= total <= 31:
        return "Frequently goes beyond expectations; provides strong support and effective communication."
    elif 18 <= total <= 25:
        return "Performs at expected level; provides adequate support, guidance, and communication."
    else:
        return "Performance below expectations; improvement needed in leadership, support, or communication."

# ---- Internal Customer Satisfaction Survey ----
def client_score_category(total: int) -> str:
    if 32 <= total <= 35:
        return "Outstanding"
    elif 26 <= total <= 31:
        return "Exceeds Target"
    elif 18 <= total <= 25:
        return "Meets Target"
    else:
        return "Below Target"

def client_score_description(total: int) -> str:
    if 32 <= total <= 35:
        return "Exceptional support; consistently meets client needs and provides strong communication."
    elif 26 <= total <= 31:
        return "Frequently goes beyond expectations; provides strong support and communication."
    elif 18 <= total <= 25:
        return "Performs at expected level; provides adequate support and responsiveness."
    else:
        return "Performance below expectations; improvement needed in support or communication."

# ---- Team Satisfaction Survey ----
def team_score_category(total: int) -> str:
    if 75 <= total <= 80:
        return "Outstanding"
    elif 65 <= total <= 74:
        return "Exceeds Target"
    elif 48 <= total <= 64:
        return "Meets Target"
    else:
        return "Below Target"

def team_score_description(total: int) -> str:
    if 75 <= total <= 80:
        return "Exceptional leadership, highly supportive, inspires and motivates the team consistently."
    elif 65 <= total <= 74:
        return "Frequently goes beyond expectations, provides strong support and communication."
    elif 48 <= total <= 64:
        return "Performs at expected level, provides adequate support, guidance, and communication."
    else:
        return "Performance below expectations, needs improvement in support, communication, or leadership."

# ===============================
# Score Calculation
# ===============================

def calculate_total_score(scores: List[int]) -> int:
    """
    Calculate total score by summing all question scores.
    No weighting applied.
    """
    return sum(scores)


from typing import Dict, List
from collections import defaultdict

from app.utils import SURVEY_DETAILS, management_score_category, client_score_category, team_score_category

GRADING_FUNCTIONS = {
    "MSES": management_score_category,
    "ICSES": client_score_category,
    "TSES": team_score_category,
}

def aggregate_employee_scores(employee):
    """
    Returns a dict like:
    {
        "MSES": {"num_submissions": 3, "total_score": 87, "avg_score": 29, "category": "Exceeds Target"},
        "ICSES": {...},
    }
    """
    result = {}

    # Iterate all manager summaries
    for manager_data in getattr(employee, "manager_summary", {}).values():
        for survey in manager_data["surveys"]:
            s_code = survey["survey_name"]
            res = survey.get("result")
            if not res:
                continue

            total_score = res.get("total_score", 0)
            if s_code not in result:
                result[s_code] = {
                    "num_submissions": 0,
                    "total_score": 0,
                    "avg_score": 0,
                    "category": "N/A"
                }

            result[s_code]["num_submissions"] += 1
            result[s_code]["total_score"] += total_score

    # Compute average and category
    for s_code, data in result.items():
        if data["num_submissions"] > 0:
            data["avg_score"] = round(data["total_score"] / data["num_submissions"], 2)
            grading_func = GRADING_FUNCTIONS.get(s_code)
            if grading_func:
                data["category"] = grading_func(data["avg_score"])
            else:
                data["category"] = "N/A"
        else:
            data["avg_score"] = 0
            data["category"] = "N/A"

    return result


