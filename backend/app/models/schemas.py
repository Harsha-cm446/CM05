from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


# ─── Enums ───────────────────────────────────────────

class UserRole(str, Enum):
    student = "student"
    hr = "hr"
    admin = "admin"


class InterviewStatus(str, Enum):
    pending = "pending"
    in_progress = "in_progress"
    completed = "completed"
    cancelled = "cancelled"


class CandidateStatus(str, Enum):
    invited = "invited"
    joined = "joined"
    completed = "completed"
    no_show = "no_show"


class DifficultyLevel(str, Enum):
    easy = "easy"
    medium = "medium"
    hard = "hard"


class InterviewRound(str, Enum):
    technical = "Technical"
    hr = "HR"


# ─── User ────────────────────────────────────────────

class UserCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=6)
    role: UserRole = UserRole.student


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    email: Optional[EmailStr] = None


class UserResponse(BaseModel):
    id: str
    name: str
    email: str
    role: str
    created_at: Optional[datetime] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


# ─── Interview Session ──────────────────────────────

class ScoringWeights(BaseModel):
    content: float = Field(default=0.40, ge=0, le=1)
    keyword: float = Field(default=0.20, ge=0, le=1)
    depth: float = Field(default=0.15, ge=0, le=1)
    communication: float = Field(default=0.15, ge=0, le=1)
    confidence: float = Field(default=0.10, ge=0, le=1)


class InterviewSessionCreate(BaseModel):
    job_role: str = Field(..., min_length=2)
    scheduled_time: datetime
    duration_minutes: int = Field(default=30, ge=5, le=180)
    company_name: Optional[str] = None
    description: Optional[str] = None
    job_description: Optional[str] = None
    experience_level: Optional[str] = None
    scoring_weights: Optional[ScoringWeights] = None
    technical_cutoff: float = Field(default=70.0, ge=0, le=100)


class InterviewSessionResponse(BaseModel):
    id: str
    job_role: str
    scheduled_time: datetime
    duration_minutes: int
    company_name: Optional[str]
    description: Optional[str]
    session_token: str
    status: str
    created_by: str
    candidate_count: int = 0
    created_at: datetime
    technical_cutoff: float = 70.0


# ─── Candidate ──────────────────────────────────────

class CandidateInvite(BaseModel):
    emails: List[EmailStr]


class CandidateResponse(BaseModel):
    id: str
    email: str
    interview_session_id: str
    unique_token: str
    status: str
    joined_at: Optional[datetime] = None


# ─── Mock Interview (Student) ───────────────────────

class MockInterviewStart(BaseModel):
    job_role: str = Field(..., min_length=2)
    difficulty: DifficultyLevel = DifficultyLevel.medium
    job_description: Optional[str] = None
    experience_level: Optional[str] = None
    duration_minutes: int = Field(default=20, ge=5, le=120)
    github_url: Optional[str] = None
    linkedin_url: Optional[str] = None


class QuestionResponse(BaseModel):
    question_id: str
    question: str
    difficulty: str
    question_number: int
    total_questions: Optional[int] = None
    round: str = "Technical"
    is_coding: bool = False
    is_wrap_up: bool = False


class AnswerSubmit(BaseModel):
    question_id: str
    answer_text: str
    audio_base64: Optional[str] = None
    code_text: Optional[str] = None
    code_language: Optional[str] = None


# ─── Evaluation ─────────────────────────────────────

class EvaluationScore(BaseModel):
    content_score: float = Field(ge=0, le=100)
    communication_score: float = Field(ge=0, le=100)
    confidence_score: float = Field(ge=0, le=100)
    emotion_score: float = Field(ge=0, le=100)
    overall_score: float = Field(ge=0, le=100)
    keyword_coverage: float = Field(ge=0, le=100)
    similarity_score: float = Field(ge=0, le=100)


class QuestionEvaluation(BaseModel):
    question: str
    answer: str
    ideal_answer: str
    scores: EvaluationScore
    feedback: str
    keywords_matched: List[str]
    keywords_missed: List[str]


class InterviewReport(BaseModel):
    session_id: str
    candidate_name: str
    job_role: str
    total_questions: int
    overall_scores: EvaluationScore
    question_evaluations: List[QuestionEvaluation]
    strengths: List[str]
    weaknesses: List[str]
    improvement_suggestions: List[str]
    generated_at: datetime
