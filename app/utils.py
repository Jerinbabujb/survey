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

TEAM_QNS=[
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

def normalize_survey_name(input_name: str) -> str:
    """Standardizes input to MSES, ICSES, or TSES."""
    if not input_name: return ""
    name = input_name.strip().upper()
    
    # Check short codes
    if name in SURVEY_DETAILS:
        return name
        
    # Check full names
    for key, data in SURVEY_DETAILS.items():
        if name == data["full_name"].upper():
            return key
    return name

def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()
SCORES = {
    5: "Strongly Agree",
    4: "Agree",
    3: "Satisfactory",
    2: "Disagree",
    1: "Strongly Disagree",
}


# Management Satisfaction Evaluation Survey
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


# Internal Customer Satisfaction Evaluation Survey
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
    if 36 <= total <= 40:
        return "Exceptional leadership, highly supportive, inspires and motivates the team consistently."
    elif 29 <= total <= 35:
        return "Frequently goes beyond expectations, provides strong support and communication."
    elif 20 <= total <= 28:
        return "Performs at expected level, provides adequate support, guidance, and communication."
    else:
        return "Performance below expectations, needs improvement in support, communication, or leadership."


# Team Satisfaction Evaluation Survey
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

from typing import Optional, Iterable


from typing import List

def weighted_score(score: int, survey_questions: List[str]) -> int:
    """
    Multiply the score of each question by the total number of questions in that survey.
    """
    num_questions = len(survey_questions)
    return score * num_questions








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


