"""
Intelligent Question Generation Service
────────────────────────────────────────
Component 2: 4 Specialized LLM-based Question Generators
  • Behavioral Model — STAR-method questions, past experiences
  • Technical Model — Domain-specific, coding, system design
  • Situational Model — Hypothetical scenarios, problem-solving
  • Cultural Fit Model — Values alignment, team dynamics

Architecture:
  ┌──────────────────┐
  │ Question Request  │
  └────────┬─────────┘
           │
  ┌────────▼─────────┐
  │ Question Router   │──▶ Selects model based on round + context
  └────────┬─────────┘
           │
  ┌────────┴──────────────────────────────┐
  │         │            │                │
  ▼         ▼            ▼                ▼
┌──────┐ ┌──────┐ ┌──────────┐ ┌──────────────┐
│Behav.│ │Tech. │ │Situational│ │Cultural Fit  │
│Model │ │Model │ │Model      │ │Model         │
└──────┘ └──────┘ └──────────┘ └──────────────┘
           │
  ┌────────▼─────────┐
  │ Quality Filter   │──▶ Redundancy check, difficulty calibration
  └────────┬─────────┘
           │
  ┌────────▼─────────┐
  │ Question + Rubric │
  └──────────────────┘

Training Architecture (LoRA Fine-Tuning):
  Base Model: Gemini 2.5 Flash (google-generativeai)
  Adapter: LoRA (rank=16, alpha=32)
  Dataset: Interview question-answer pairs per category
  Evaluation: BLEU, ROUGE-L, Question Quality Score
"""

import json
import re
import asyncio
import hashlib
from typing import List, Dict, Any, Optional
from datetime import datetime

import numpy as np

try:
    from sentence_transformers import SentenceTransformer
    from sklearn.metrics.pairwise import cosine_similarity
    ST_AVAILABLE = True
except ImportError:
    ST_AVAILABLE = False

from app.core.config import settings


# ── Question Templates ────────────────────────────────

BEHAVIORAL_TEMPLATES = [
    "Tell me about a time when you {scenario}. What was the situation, your approach, and the outcome?",
    "Describe a situation where you had to {scenario}. How did you handle it?",
    "Give me an example of when you {scenario}. Walk me through your thought process.",
    "Share an experience where you {scenario}. What did you learn from it?",
]

BEHAVIORAL_SCENARIOS = [
    "dealt with a difficult team member",
    "had to meet a tight deadline",
    "made a mistake and had to fix it",
    "led a team through a challenging project",
    "had to persuade others to accept your idea",
    "received critical feedback and acted on it",
    "had to prioritize competing demands",
    "went above and beyond your job responsibilities",
    "had to adapt to a significant change",
    "resolved a conflict between team members",
]

TECHNICAL_QUESTION_TYPES = [
    "conceptual", "coding", "system_design", "debugging",
    "architecture", "tradeoff_analysis", "optimization",
]

SITUATIONAL_TEMPLATES = [
    "Imagine you are a {role} and {scenario}. What would you do?",
    "If you were assigned to {scenario}, how would you approach it?",
    "Suppose {scenario} happens during a critical project. Walk me through your response.",
    "You've just joined a team and discover {scenario}. What steps would you take?",
]

CULTURAL_FIT_AREAS = [
    "teamwork", "communication", "innovation", "work_ethic",
    "adaptability", "leadership", "integrity", "growth_mindset",
]


class QuestionGenerationService:
    """4-model intelligent question generation with quality filtering."""

    def __init__(self):
        self._question_history: Dict[str, List[str]] = {}

    @property
    def embedding_model(self):
        from app.services.model_registry import model_registry
        return model_registry.embedding_model

    @property
    def gemini_client(self):
        from app.services.model_registry import model_registry
        return model_registry.gemini_client

    async def _llm_generate(self, prompt: str, system: str = "", fast: bool = False) -> str:
        """Call Gemini API with automatic model + key fallback on quota errors."""
        from app.services.model_registry import model_registry
        max_tokens = 1024 if fast else 2048
        result = await model_registry.llm_generate(prompt, system, fast=fast, max_tokens=max_tokens)
        if not result:
            print(f"[QuestionGen] ⚠️ Gemini returned empty — will use template fallback. "
                  f"Key configured: {bool(model_registry.gemini_client)}, "
                  f"Active model: {model_registry.active_model}")
        else:
            print(f"[QuestionGen] ✅ Gemini generated {len(result)} chars via {model_registry.active_model}")
        return result

    def _parse_json(self, text: str) -> dict:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
        return {}

    # ── Model 1: Behavioral Question Generator ───────

    async def generate_behavioral_question(
        self,
        job_role: str,
        difficulty: str,
        previous_questions: List[str],
        candidate_context: Dict[str, Any] = None,
        jd_analysis: Dict[str, Any] = None,
        candidate_profile_context: str = "",
    ) -> Dict[str, Any]:
        """Generate a behavioral (STAR-method) interview question."""
        soft_skills = []
        if jd_analysis:
            soft_skills = jd_analysis.get("soft_skills", [])

        profile_inst = ""
        if candidate_profile_context:
            profile_inst = f"\n{candidate_profile_context}\nTailor the question to the candidate's background when relevant."

        prompt = f"""Generate a BEHAVIORAL interview question for a {job_role} candidate.
Difficulty: {difficulty}
Soft skills to evaluate: {json.dumps(soft_skills) if soft_skills else 'teamwork, communication, leadership'}
{profile_inst}

RULES:
- The question MUST be SHORT (1-2 sentences, max 25 words).
- Ask about a real past experience using STAR method.
- Do NOT write long multi-part questions.
- Good example: "Tell me about a time you resolved a team conflict."
- Bad example: "Can you describe a situation in your previous role where you encountered a significant challenge with a team member, detailing what happened, what you did, and what the outcome was?"

Previously asked (DO NOT repeat any of these): {json.dumps(previous_questions[-15:])}

Return ONLY valid JSON:
{{
  "question": "Short behavioral question (1-2 sentences)",
  "ideal_answer": "Humanized first-person answer using natural STAR storytelling (2-3 sentences)",
  "evaluation_keywords": ["keyword1", "keyword2", "keyword3", "keyword4", "keyword5"],
  "competency_evaluated": "the soft skill being tested",
  "difficulty_level": "{difficulty}",
  "star_expectations": {{
    "situation": "What situation should be described",
    "task": "What task/challenge was involved",
    "action": "What actions are expected",
    "result": "What results/outcomes to look for"
  }}
}}"""

        system = "You are an expert behavioral interviewer. Generate SHORT, CONCISE STAR-method questions (1-2 sentences max). Never write long or multi-part questions. Return valid JSON only."
        response = await self._llm_generate(prompt, system)
        parsed = self._parse_json(response)

        if not parsed or "question" not in parsed:
            import random
            scenario = random.choice(BEHAVIORAL_SCENARIOS)
            template = random.choice(BEHAVIORAL_TEMPLATES)
            q = template.format(scenario=scenario)
            # Ensure fallback is concise
            if len(q.split()) > 25:
                q = f"Tell me about a time you {scenario}."
            parsed = {
                "question": q,
                "ideal_answer": f"Use the STAR method: describe the Situation, your Task, the Actions you took, and the Result when you {scenario}.",
                "evaluation_keywords": ["situation", "task", "action", "result", "learning"],
                "competency_evaluated": "behavioral competency",
                "difficulty_level": difficulty,
            }

        parsed["question_type"] = "behavioral"
        parsed["round"] = "HR"
        parsed["is_coding"] = False
        parsed.setdefault("evaluation_keywords", ["teamwork", "communication"])
        parsed["keywords"] = parsed["evaluation_keywords"]
        return parsed

    # ── Model 2: Technical Question Generator ────────

    async def generate_technical_question(
        self,
        job_role: str,
        difficulty: str,
        previous_questions: List[str],
        question_subtype: str = "conceptual",
        jd_analysis: Dict[str, Any] = None,
        last_score: float = None,
        last_answer: str = None,
        candidate_profile_context: str = "",
    ) -> Dict[str, Any]:
        """Generate a technical interview question."""
        tech_skills = []
        tech_topics = []
        if jd_analysis:
            tech_skills = jd_analysis.get("required_skills", [])
            tech_topics = jd_analysis.get("technical_topics", [])

        followup = ""
        if last_score is not None:
            if last_score >= 80:
                followup = "The candidate scored well. Ask a harder follow-up that probes deeper."
            elif last_score >= 50:
                followup = "Moderate performance. Ask a clarification question."
            else:
                followup = "Weak answer. Simplify and move to a related easier topic."

        is_coding = question_subtype == "coding"
        coding_inst = ""
        if is_coding:
            coding_inst = "This MUST be a coding question. Include problem statement, constraints, and expected I/O."

        profile_inst = ""
        if candidate_profile_context:
            profile_inst = f"\n{candidate_profile_context}\nTailor the question to the candidate's background when relevant."

        prompt = f"""Generate a TECHNICAL ({question_subtype}) interview question for {job_role}.
Difficulty: {difficulty}
Skills to evaluate: {json.dumps(tech_skills[:8]) if tech_skills else job_role}
Topics: {json.dumps(tech_topics[:5]) if tech_topics else 'relevant domain topics'}
{followup}
{coding_inst}
{profile_inst}

RULES:
- The question MUST be SHORT and DIRECT (1-2 sentences, max 30 words).
- Ask ONE clear technical thing. No long preambles or multi-part questions.
- Good: "What is the difference between TCP and UDP?"
- Good: "How would you optimize a slow SQL query?"
- Bad: "Can you explain in detail the various differences between TCP and UDP protocols, including their use cases, advantages, disadvantages, and when you would choose one over the other?"

Previously asked (NEVER repeat): {json.dumps(previous_questions[-15:])}

Return ONLY valid JSON:
{{
  "question": "Short technical question (1-2 sentences)",
  "ideal_answer": "Short humanized answer in first-person, conversational tone (2-3 sentences)",
  "evaluation_keywords": ["kw1", "kw2", "kw3", "kw4", "kw5"],
  "difficulty_level": "{difficulty}",
  "is_coding": {str(is_coding).lower()},
  "topic": "primary topic being tested",
  "expected_depth": "conceptual|practical|advanced",
  "followup_if_strong": "Harder follow-up (1 sentence)",
  "followup_if_weak": "Simpler fallback (1 sentence)"
}}"""

        system = f"You are an expert {job_role} technical interviewer. Generate SHORT, CONCISE questions (1-2 sentences max). Never write long or multi-part questions. Return valid JSON only."
        response = await self._llm_generate(prompt, system)
        parsed = self._parse_json(response)

        if not parsed or "question" not in parsed:
            parsed = {
                "question": f"What are the key concepts a {job_role} should know about {question_subtype}?",
                "ideal_answer": f"Cover the core {question_subtype} concepts, real-world usage, and best practices relevant to {job_role}.",
                "evaluation_keywords": ["concepts", "best practices", "experience", "architecture", "implementation"],
                "difficulty_level": difficulty,
                "is_coding": is_coding,
                "topic": job_role,
            }

        parsed["question_type"] = "technical"
        parsed["question_subtype"] = question_subtype
        parsed["round"] = "Technical"
        parsed.setdefault("is_coding", is_coding)
        parsed.setdefault("evaluation_keywords", ["technical", "depth"])
        parsed["keywords"] = parsed["evaluation_keywords"]
        return parsed

    # ── Model 3: Situational Question Generator ──────

    async def generate_situational_question(
        self,
        job_role: str,
        difficulty: str,
        previous_questions: List[str],
        jd_analysis: Dict[str, Any] = None,
        candidate_profile_context: str = "",
    ) -> Dict[str, Any]:
        """Generate a hypothetical scenario-based question."""
        responsibilities = []
        if jd_analysis:
            responsibilities = jd_analysis.get("key_responsibilities", [])

        profile_inst = ""
        if candidate_profile_context:
            profile_inst = f"\n{candidate_profile_context}\nTailor the scenario to the candidate's experience when relevant."

        prompt = f"""Generate a SITUATIONAL interview question for {job_role}.
Difficulty: {difficulty}
Job Responsibilities: {json.dumps(responsibilities[:5]) if responsibilities else 'general role duties'}
{profile_inst}

RULES:
- Present a brief realistic scenario and ask how they'd handle it.
- Keep the question SHORT (1-3 sentences max, under 35 words).
- Good: "Your team misses a sprint deadline. How do you handle it?"
- Bad: "Imagine you are working on a critical project and your team has been struggling with meeting deadlines due to various factors including scope creep and resource constraints. How would you approach this situation?"

Previously asked (NEVER repeat): {json.dumps(previous_questions[-15:])}

Return ONLY valid JSON:
{{
  "question": "Short situational question (1-3 sentences)",
  "ideal_answer": "Short humanized first-person approach (2-3 sentences)",
  "evaluation_keywords": ["kw1", "kw2", "kw3", "kw4", "kw5"],
  "difficulty_level": "{difficulty}",
  "scenario_type": "conflict|deadline|resource|technical_failure|stakeholder|priority",
  "skills_evaluated": ["skill1", "skill2"]
}}"""

        system = "You are an expert situational interviewer. Create SHORT, CONCISE scenario questions (1-3 sentences max). Never write long or wordy questions. Return valid JSON only."
        response = await self._llm_generate(prompt, system)
        parsed = self._parse_json(response)

        if not parsed or "question" not in parsed:
            parsed = {
                "question": f"A critical system fails before a major release. As a {job_role}, what do you do first?",
                "ideal_answer": "Immediate triage, stakeholder communication, root cause analysis, implement fix, and plan a post-mortem.",
                "evaluation_keywords": ["triage", "communication", "problem-solving", "prioritization", "follow-up"],
                "difficulty_level": difficulty,
                "scenario_type": "technical_failure",
            }

        parsed["question_type"] = "situational"
        parsed["round"] = "Technical"
        parsed["is_coding"] = False
        parsed.setdefault("evaluation_keywords", ["judgment", "reasoning"])
        parsed["keywords"] = parsed["evaluation_keywords"]
        return parsed

    # ── Model 4: Cultural Fit Question Generator ─────

    async def generate_cultural_fit_question(
        self,
        job_role: str,
        difficulty: str,
        previous_questions: List[str],
        company_values: List[str] = None,
        jd_analysis: Dict[str, Any] = None,
        candidate_profile_context: str = "",
    ) -> Dict[str, Any]:
        """Generate cultural fit assessment question."""
        values = company_values or ["teamwork", "innovation", "integrity", "growth"]

        profile_inst = ""
        if candidate_profile_context:
            profile_inst = f"\n{candidate_profile_context}\nTailor the question to the candidate's background when relevant."

        prompt = f"""Generate a CULTURAL FIT interview question for {job_role}.
Difficulty: {difficulty}
Company values: {json.dumps(values)}
{profile_inst}

RULES:
- Keep the question SHORT (1-2 sentences, max 25 words).
- Good: "What kind of work environment helps you do your best work?"
- Bad: "Can you describe in detail the type of organizational culture and work environment that you find most conducive to your professional growth and productivity?"

Previously asked (NEVER repeat): {json.dumps(previous_questions[-15:])}

Return ONLY valid JSON:
{{
  "question": "Short cultural fit question (1-2 sentences)",
  "ideal_answer": "Short humanized first-person response (2-3 sentences)",
  "evaluation_keywords": ["kw1", "kw2", "kw3", "kw4", "kw5"],
  "difficulty_level": "{difficulty}",
  "value_assessed": "the specific value being evaluated",
  "red_flags": ["things that indicate poor cultural fit"],
  "green_flags": ["things that indicate good cultural fit"]
}}"""

        system = "You are an expert HR cultural fit assessor. Generate SHORT, CONCISE questions (1-2 sentences max). Never write long or wordy questions. Return valid JSON only."
        response = await self._llm_generate(prompt, system)
        parsed = self._parse_json(response)

        if not parsed or "question" not in parsed:
            parsed = {
                "question": "What kind of work environment helps you do your best work?",
                "ideal_answer": "Show self-awareness, team orientation, and alignment with collaborative, growth-focused values.",
                "evaluation_keywords": ["culture", "teamwork", "values", "collaboration", "growth"],
                "difficulty_level": difficulty,
                "value_assessed": "teamwork",
            }

        parsed["question_type"] = "cultural_fit"
        parsed["round"] = "HR"
        parsed["is_coding"] = False
        parsed.setdefault("evaluation_keywords", ["culture", "values"])
        parsed["keywords"] = parsed["evaluation_keywords"]
        return parsed

    # ── Question Router ───────────────────────────────

    async def generate_question_smart(
        self,
        job_role: str,
        difficulty: str,
        previous_questions: List[str],
        round_type: str = "Technical",
        question_number: int = 1,
        total_planned: int = 10,
        jd_analysis: Dict[str, Any] = None,
        last_score: float = None,
        last_answer: str = None,
        candidate_profile_context: str = "",
        coding_count: int = 0,
        **kwargs,
    ) -> Dict[str, Any]:
        """Smart question router that selects the appropriate model."""
        import random as _rand
        # Determine question type based on round and progression
        progress = question_number / max(total_planned, 1)

        # ── Coding question insertion logic ──
        # Only in Technical round, after initial conceptual questions,
        # with decreasing probability as more coding Qs are asked.
        # Max 2 coding questions per session.
        # GUARANTEE: at least one coding question by mid-session (progress >= 0.5).
        should_code = False
        if round_type == "Technical" and coding_count < 2:
            if coding_count == 0 and progress >= 0.5:
                # Guarantee: force the first coding question by mid-session
                should_code = True
                print(f"[QuestionGen] GUARANTEED coding question: progress={progress:.2f}, coding_count={coding_count}")
            elif progress >= 0.2:
                # Probabilistic: base 30% chance, reduced by 15% per existing coding Q
                coding_prob = max(0.0, 0.30 - (coding_count * 0.15))
                should_code = _rand.random() < coding_prob

        print(f"[QuestionGen] smart_route: q_num={question_number}, total={total_planned}, "
              f"progress={progress:.2f}, round={round_type}, coding_count={coding_count}, "
              f"should_code={should_code}")

        if round_type == "Technical":
            if should_code:
                # Probabilistic coding question
                return await self.generate_technical_question(
                    job_role, difficulty, previous_questions,
                    question_subtype="coding", jd_analysis=jd_analysis,
                    last_score=last_score, last_answer=last_answer,
                    candidate_profile_context=candidate_profile_context,
                )
            elif progress < 0.3:
                # Start with conceptual
                return await self.generate_technical_question(
                    job_role, difficulty, previous_questions,
                    question_subtype="conceptual", jd_analysis=jd_analysis,
                    last_score=last_score, last_answer=last_answer,
                    candidate_profile_context=candidate_profile_context,
                )
            elif progress < 0.5:
                # Practical / system design
                return await self.generate_technical_question(
                    job_role, difficulty, previous_questions,
                    question_subtype="system_design", jd_analysis=jd_analysis,
                    last_score=last_score, last_answer=last_answer,
                    candidate_profile_context=candidate_profile_context,
                )
            elif progress < 0.7:
                # Situational/tradeoff
                return await self.generate_situational_question(
                    job_role, difficulty, previous_questions, jd_analysis=jd_analysis,
                    candidate_profile_context=candidate_profile_context,
                )
            else:
                # Deep technical
                return await self.generate_technical_question(
                    job_role, difficulty, previous_questions,
                    question_subtype="architecture", jd_analysis=jd_analysis,
                    last_score=last_score, last_answer=last_answer,
                    candidate_profile_context=candidate_profile_context,
                )
        else:  # HR round
            if progress < 0.4:
                return await self.generate_behavioral_question(
                    job_role, difficulty, previous_questions,
                    jd_analysis=jd_analysis,
                    candidate_profile_context=candidate_profile_context,
                )
            elif progress < 0.7:
                return await self.generate_situational_question(
                    job_role, difficulty, previous_questions,
                    jd_analysis=jd_analysis,
                    candidate_profile_context=candidate_profile_context,
                )
            else:
                return await self.generate_cultural_fit_question(
                    job_role, difficulty, previous_questions,
                    jd_analysis=jd_analysis,
                    candidate_profile_context=candidate_profile_context,
                )

    # ── Redundancy Elimination ────────────────────────

    def check_question_redundancy(
        self, new_question: str, previous_questions: List[str], threshold: float = 0.75
    ) -> bool:
        """Check if a new question is too similar to previously asked questions.
        Returns True if redundant (should be rejected).
        """
        if not previous_questions:
            return False

        # Fast text-based check first (works even without embedding model)
        new_lower = new_question.lower().strip()
        for prev in previous_questions:
            prev_lower = prev.lower().strip()
            # Exact or near-exact match
            if new_lower == prev_lower:
                return True
            # High word overlap check
            new_words = set(new_lower.split())
            prev_words = set(prev_lower.split())
            if new_words and prev_words:
                overlap = len(new_words & prev_words) / max(len(new_words), len(prev_words))
                if overlap > 0.8:
                    return True

        # Semantic similarity check (if embedding model available)
        if not self.embedding_model:
            return False

        embeddings = self.embedding_model.encode(
            [new_question] + previous_questions
        )
        new_emb = embeddings[0:1]
        prev_embs = embeddings[1:]

        similarities = cosine_similarity(new_emb, prev_embs)[0]
        max_similarity = float(np.max(similarities))

        return max_similarity > threshold

    # ── Question Quality Evaluation ───────────────────

    def evaluate_question_quality(self, question_data: Dict[str, Any]) -> Dict[str, float]:
        """Evaluate the quality of a generated question."""
        question = question_data.get("question", "")
        ideal_answer = question_data.get("ideal_answer", "")
        keywords = question_data.get("evaluation_keywords", [])

        scores = {}

        # Clarity: question length and structure
        word_count = len(question.split())
        if 10 <= word_count <= 50:
            scores["clarity"] = 90
        elif 5 <= word_count <= 80:
            scores["clarity"] = 70
        else:
            scores["clarity"] = 40

        # Specificity: contains role/topic-specific terms
        scores["specificity"] = min(100, len(keywords) * 15)

        # Answer quality: ideal answer comprehensiveness
        answer_words = len(ideal_answer.split())
        if answer_words >= 50:
            scores["answer_quality"] = 90
        elif answer_words >= 20:
            scores["answer_quality"] = 70
        else:
            scores["answer_quality"] = 40

        # Evaluation readiness: has keywords for scoring
        scores["evaluation_readiness"] = min(100, len(keywords) * 20)

        # Overall quality score
        scores["overall_quality"] = round(
            scores["clarity"] * 0.25 +
            scores["specificity"] * 0.25 +
            scores["answer_quality"] * 0.30 +
            scores["evaluation_readiness"] * 0.20,
            1
        )

        return scores

    # ── Difficulty Calibration ────────────────────────

    def calibrate_difficulty(
        self,
        current_difficulty: str,
        recent_scores: List[float],
        target_success_rate: float = 0.65,
    ) -> str:
        """Calibrate question difficulty based on recent performance.

        Uses Item Response Theory (IRT) inspired approach:
        - If success rate > target + 0.15: increase difficulty
        - If success rate < target - 0.15: decrease difficulty
        - Otherwise: maintain current difficulty
        """
        if not recent_scores:
            return current_difficulty

        success_rate = sum(1 for s in recent_scores if s >= 60) / len(recent_scores)

        difficulty_ladder = ["easy", "medium", "hard"]
        current_idx = difficulty_ladder.index(current_difficulty) if current_difficulty in difficulty_ladder else 1

        if success_rate > target_success_rate + 0.15:
            new_idx = min(current_idx + 1, 2)
        elif success_rate < target_success_rate - 0.15:
            new_idx = max(current_idx - 1, 0)
        else:
            new_idx = current_idx

        return difficulty_ladder[new_idx]


# ── LoRA Fine-Tuning Guide ───────────────────────────
#
# Dataset Preparation:
#   Format: {"instruction": "Generate a {type} question for {role}",
#            "input": "context/JD", "output": "question JSON"}
#   Sources: Interview guides, Glassdoor, LeetCode, behavioral banks
#   Size: 5000+ samples per model type
#
# Training Pipeline:
#   from peft import LoraConfig, get_peft_model
#   from transformers import AutoModelForCausalLM, TrainingArguments
#
#   lora_config = LoraConfig(
#       r=16,               # LoRA rank
#       lora_alpha=32,       # Scaling factor
#       target_modules=["q_proj", "v_proj"],
#       lora_dropout=0.05,
#       bias="none",
#       task_type="CAUSAL_LM",
#   )
#
#   model = AutoModelForCausalLM.from_pretrained("meta-llama/Llama-3.3-70B-Instruct")
#   model = get_peft_model(model, lora_config)
#
#   training_args = TrainingArguments(
#       output_dir="./lora_behavioral",
#       num_train_epochs=3,
#       per_device_train_batch_size=4,
#       learning_rate=2e-4,
#       warmup_steps=100,
#       logging_steps=50,
#   )
#
# Evaluation Metrics:
#   - BLEU score for answer quality
#   - ROUGE-L for coverage
#   - Human eval: relevance, difficulty accuracy, question quality


# Singleton
question_generation_service = QuestionGenerationService()
