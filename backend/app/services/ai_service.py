"""
AI Interview Engine — Optimized Performance Architecture
─────────────────────────────────────────────────────────
Optimizations:
  • Model warm-loading at startup (not per-request)
  • Gemini API (gemini-2.5-flash) with multi-key fallback for LLM inference
  • Two-phase evaluation: instant score (<2s) + background deep analysis
  • Parallel evaluation with asyncio.gather()
  • Reduced LLM calls: local scoring for similarity/keywords/communication
  • Active-time-only timer (pauses during AI processing)
  • Pre-generation of questions during answer evaluation
"""

import asyncio
import json
import re
from typing import List, Dict, Any, Optional
from datetime import datetime

import numpy as np
try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None
    print("⚠️ sentence-transformers not available — embedding features disabled")
from sklearn.metrics.pairwise import cosine_similarity
import nltk
from nltk.corpus import wordnet
try:
    nltk.download('wordnet', quiet=True)
    nltk.download('omw-1.4', quiet=True)
except Exception:
    pass

from app.core.config import settings

# Import services for report enrichment and integrated AI subsystems
from app.services.explainability_service import explainability_service
from app.services.development_roadmap_service import development_roadmap_service
from app.services.question_generation_service import question_generation_service
from app.services.rl_adaptation_service import rl_adaptation_service
from app.services.multimodal_analysis_service import MultimodalAnalysisEngine
from app.utils.calibrator import score_calibrator
from sklearn.feature_extraction.text import CountVectorizer

multimodal_engine = MultimodalAnalysisEngine()


# ── Master system prompt injected into every LLM call ──────

MASTER_SYSTEM_PROMPT = """You are an advanced AI Interview Engine designed to simulate a real-world corporate interview.
You must conduct the interview exactly like a senior interviewer at a top company (Google, Microsoft, Amazon level).

CORE RULES:
1. NEVER repeat a question or ask a semantically similar variation of a previously asked question.
2. The interview is TIME-BASED — keep generating questions until the allocated time expires.
3. All questions MUST be derived from the Job Description, required skills, tools, and responsibilities.
4. There are TWO rounds: Technical (Round 1) then HR (Round 2).
   - Technical: core skills, problem-solving, scenario-based, tool-specific, system-design questions.
   - HR: behavioral (STAR method), cultural fit, conflict resolution, leadership, career goals, situational judgment.
5. Adapt difficulty based on the candidate's last answer score:
   - Strong (>80%): increase difficulty significantly, ask deeper follow-up, probe edge cases.
   - Moderate (50-80%): ask clarification, probe practical understanding, give a scenario.
   - Weak (<50%): simplify slightly, ask a supportive fallback, or move to an easier related topic.
6. Follow-up questions MUST be context-aware and directly reference the candidate's previous answer.
7. Always generate 2-3 distinct ideal reference answers (conceptual, practical, and example-based) and 5-7 evaluation keywords.
8. Always return valid JSON — no markdown, no extra text.

QUESTION VARIETY (mix these types across the interview):
- Conceptual: "Explain how X works and why it matters"
- Scenario-based: "Given situation X, how would you approach..."
- Problem-solving: "Design a solution for..."
- Experience-based: "Tell me about a time when..."
- Trade-off analysis: "Compare X vs Y, when would you choose each?"
- Debugging: "This code/system has issue X, how would you diagnose it?"
- System design: "How would you architect a system that..."

IDEAL ANSWER QUALITY:
- The ideal_answer must be CONCISE yet insightful (2-4 sentences MAX for non-coding, 5-10 lines MAX for coding)
- Write like a confident professional speaking naturally in an interview — NOT an essay or textbook
- Use first-person, conversational language: "In my experience...", "What I'd do here is...", "I've found that..."
- NO bullet points, NO numbered lists, NO headers — just natural flowing speech
- Include ONE specific example, technology, or metric to show depth (not a laundry list)
- For HR questions, weave STAR naturally: "When I was at X, we faced Y, so I did Z, and the result was..."
- For coding questions, show clean working code with brief inline comments — no lengthy explanations
- Think: "How would a senior engineer actually answer this in a real interview?" — brief, confident, specific
"""


class AIService:
    """High-performance AI interview engine with warm-loaded models and parallel evaluation."""

    # Maximum cached questions / session counts before cleanup
    _MAX_CACHE_SIZE = 200
    _MAX_SESSION_COUNTS = 500

    def __init__(self):
        self._warmed_up = False
        self._warmup_lock = asyncio.Lock()
        # Cache for pre-generated questions
        self._question_cache: Dict[str, Dict] = {}
        # Track question counts per session for the smart router
        self._session_question_counts: Dict[str, int] = {}

    def cleanup_session(self, session_id: str):
        """Remove session-scoped data to prevent memory leaks."""
        self._session_question_counts.pop(session_id, None)
        # Remove any stale cached questions for this session
        keys_to_remove = [k for k in self._question_cache if session_id in k]
        for k in keys_to_remove:
            self._question_cache.pop(k, None)
        # Enforce global caps
        if len(self._question_cache) > self._MAX_CACHE_SIZE:
            # Evict oldest entries (FIFO)
            excess = len(self._question_cache) - self._MAX_CACHE_SIZE
            for k in list(self._question_cache.keys())[:excess]:
                del self._question_cache[k]

    # ── Warm-up: Load models once at startup ──────────

    async def warm_up(self):
        """Lightweight startup — initialize shared model registry."""
        if self._warmed_up:
            return
        async with self._warmup_lock:
            if self._warmed_up:
                return
            print("🔄 Initializing AI service...")

            # Use shared model registry (single instance for all services)
            from app.services.model_registry import model_registry
            model_registry.warm_up()

            if model_registry.gemini_client:
                print(f"  ✅ Gemini configured (model: {settings.GEMINI_MODEL}, keys: {model_registry.total_keys})")
            else:
                print("  ⚠️ GEMINI_API_KEY not set — LLM calls will return empty results")

            self._warmed_up = True
            print("✅ AI Engine ready — models will load on first use")

    async def shutdown(self):
        """Cleanup on app shutdown."""
        pass  # Gemini SDK doesn't require explicit cleanup

    @property
    def embedding_model(self) -> Any:
        from app.services.model_registry import model_registry
        return model_registry.embedding_model

    # ── LLM helpers ─────────────────────────────────

    async def _llm_generate(self, prompt: str, system: str = "", fast: bool = False) -> str:
        """Call Gemini API with automatic model + key fallback on quota errors.
        fast=True uses lower token limit."""
        from app.services.model_registry import model_registry
        full_system = MASTER_SYSTEM_PROMPT + "\n\n" + system
        result = await model_registry.llm_generate(prompt, full_system, fast=fast)
        if not result:
            provider = (model_registry.last_provider or "unknown").upper()
            provider_model = model_registry.last_provider_model or model_registry.active_model
            print(f"[AIService] ⚠️ LLM returned empty — fallback will be used. "
                  f"Last provider: {provider}, model: {provider_model}")
        return result

    def _parse_json_from_response(self, text: str) -> dict:
        """Extract JSON from LLM response text."""
        json_match = re.search(r"\{[\s\S]*\}", text)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass
        return {}

    def _normalize_ideal_answers(
        self,
        ideal_answer: str = "",
        ideal_answers: Optional[List[Any]] = None,
    ) -> List[Dict[str, str]]:
        """Return 2-3 normalized ideal answers for robust best-match scoring."""
        normalized: List[Dict[str, str]] = []

        for item in ideal_answers or []:
            if isinstance(item, dict):
                txt = str(item.get("answer", "")).strip()
                typ = str(item.get("type", "theoretical")).strip() or "theoretical"
            else:
                txt = str(item or "").strip()
                typ = "theoretical"
            if txt:
                normalized.append({"answer": txt, "type": typ})

        if not normalized and ideal_answer:
            base = str(ideal_answer).strip()
            if base:
                normalized = [
                    {"answer": base, "type": "theoretical"},
                    {"answer": f"In practice, I would apply this by {base.lower()}", "type": "practical"},
                    {"answer": f"For example, in a production setting I would demonstrate this by {base.lower()}", "type": "example_based"},
                ]

        if not normalized:
            normalized = [
                {"answer": "A strong answer should explain the concept clearly, apply it practically, and provide a concrete example.", "type": "theoretical"},
                {"answer": "In practice, I would describe implementation trade-offs, risks, and measurable outcomes.", "type": "practical"},
                {"answer": "For example, I would cite a real project where this approach improved reliability or performance.", "type": "example_based"},
            ]

        return normalized[:3]

    def _merge_multimodal_metrics(self, live_metrics: Optional[Dict[str, Any]]) -> Dict[str, float]:
        """Normalize live multimodal metrics to [0,1] for RL adaptation."""
        m = live_metrics or {}

        def _norm01(val: Any, default: float) -> float:
            try:
                v = float(val)
            except (TypeError, ValueError):
                return default
            if v > 1.0:
                v = v / 100.0
            return max(0.0, min(1.0, v))

        return {
            "confidence": _norm01(m.get("confidence"), 0.5),
            "stress": _norm01(m.get("stress"), 0.3),
            "attention": _norm01(m.get("attention"), 0.6),
        }

    def _ensure_question_multiref(self, question_data: Dict[str, Any], round_type: str) -> Dict[str, Any]:
        """Ensure generated question payload always contains 2-3 ideal references."""
        refs = self._normalize_ideal_answers(
            ideal_answer=str(question_data.get("ideal_answer", "")),
            ideal_answers=question_data.get("ideal_answers"),
        )
        question_data["ideal_answers"] = refs
        question_data["ideal_answer"] = refs[0]["answer"]
        question_data.setdefault("round", round_type)
        return question_data

    # ── JD Analysis ───────────────────────────────────

    async def analyze_job_description(self, job_description: str, job_title: str) -> Dict[str, Any]:
        """Extract skills, responsibilities, tools, and soft-skill expectations from a JD."""
        prompt = f"""Analyze this Job Description and extract structured information.

Job Title: {job_title}
Job Description:
{job_description}

Return ONLY a JSON object:
{{
  "required_skills": ["skill1", "skill2"],
  "key_responsibilities": ["resp1", "resp2"],
  "tools_and_frameworks": ["tool1", "tool2"],
  "soft_skills": ["soft1", "soft2"],
  "experience_expectations": "summary of expected experience",
  "technical_topics": ["topic1", "topic2"],
  "hr_topics": ["topic1", "topic2"]
}}"""

        response = await self._llm_generate(prompt, "You are a JD analysis expert. Return valid JSON only.")
        parsed = self._parse_json_from_response(response)
        if not parsed:
            parsed = {
                "required_skills": [job_title, "problem-solving", "communication"],
                "key_responsibilities": ["Perform role duties", "Collaborate with team"],
                "tools_and_frameworks": [],
                "soft_skills": ["teamwork", "communication", "leadership"],
                "experience_expectations": "Relevant industry experience",
                "technical_topics": [job_title],
                "hr_topics": ["motivation", "teamwork", "conflict resolution"],
            }
        return parsed

    # ── Question Generation (with pre-generation cache) ──

    async def generate_question(
        self,
        job_role: str,
        difficulty: str,
        previous_questions: List[str],
        round_type: str = "Technical",
        job_description: str = "",
        experience_level: str = "",
        previous_answers: List[str] = None,
        last_score: float = None,
        jd_analysis: Dict[str, Any] = None,
        is_coding_question: bool = False,
        session_id: str = None,
        candidate_profile_context: str = "",
        coding_count: int = 0,
        live_metrics: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Generate an adaptive interview question using specialized generators
        with RL-based difficulty calibration and redundancy checking."""

        # ── RL-based difficulty adaptation ──
        calibrated_difficulty = difficulty
        try:
            if session_id:
                # Create RL session if first question
                q_num = self._session_question_counts.get(session_id, 0)
                if q_num == 0:
                    rl_adaptation_service.create_session(session_id, max_questions=15)
                self._session_question_counts[session_id] = q_num + 1

                # CRITICAL ORDER: record previous score FIRST so environment
                # state is current before computing next action.
                # Previous code called get_next_action before record_response,
                # meaning the agent always acted on stale state.
                if last_score is not None:
                    rl_adaptation_service.record_response(session_id, last_score / 100.0)

                if jd_analysis:
                    known_topics = list(dict.fromkeys(
                        (jd_analysis.get("technical_topics", []) or []) +
                        (jd_analysis.get("hr_topics", []) or [])
                    ))
                    covered_topics = [
                        t for t in known_topics
                        if any(t.lower() in (q or "").lower() for q in (previous_questions or [])[-10:])
                    ]
                    rl_adaptation_service.update_topic_coverage(session_id, covered_topics)

                # Now get next action with updated environment state
                perf = (last_score / 100.0) if last_score is not None else 0.5
                mm = self._merge_multimodal_metrics(live_metrics)
                perf = max(0.0, min(1.0, (perf * 0.8) + (mm["attention"] * 0.2)))
                action = rl_adaptation_service.get_next_action(
                    session_id,
                    confidence=mm["confidence"],
                    performance=perf,
                    stress=mm["stress"],
                )
                calibrated_difficulty = action.get("recommended_difficulty", difficulty)
        except Exception as e:
            print(f"[RL adaptation] Falling back to heuristic difficulty: {e}")
            calibrated_difficulty = difficulty

        # Also use question_generation_service's difficulty calibration as a cross-check
        if last_score is not None:
            recent_scores = [last_score]
            if previous_answers:
                recent_scores = [last_score]  # Could track more history
            cal_diff = question_generation_service.calibrate_difficulty(
                calibrated_difficulty, recent_scores
            )
            calibrated_difficulty = cal_diff

        # ── Route to specialized question generator ──
        try:
            q_num = self._session_question_counts.get(session_id or "", 1)
            total_planned = 15

            print(f"[SessionTrack] session_id={session_id}, q_num={q_num}, "
                  f"total_planned={total_planned}, progress={q_num/total_planned:.2f}, "
                  f"coding_count={coding_count}, round={round_type}, "
                  f"difficulty={calibrated_difficulty}")

            question_data = await question_generation_service.generate_question_smart(
                job_role=job_role,
                difficulty=calibrated_difficulty,
                previous_questions=previous_questions,
                round_type=round_type,
                question_number=q_num,
                total_planned=total_planned,
                jd_analysis=jd_analysis,
                last_score=last_score,
                last_answer=previous_answers[-1] if previous_answers else None,
                candidate_profile_context=candidate_profile_context,
                coding_count=coding_count,
            )

            # Redundancy check using sentence embeddings
            if question_data and question_data.get("question"):
                is_redundant = question_generation_service.check_question_redundancy(
                    question_data["question"], previous_questions, threshold=0.75
                )
                if is_redundant:
                    print("[QuestionGen] Redundancy detected, falling back to monolithic generator")
                    question_data = None  # Fall through to the fallback

            if question_data and question_data.get("question"):
                # Evaluate quality
                quality = question_generation_service.evaluate_question_quality(question_data)
                if quality.get("overall_quality", 100) < 40:
                    print(f"[QuestionGen] Low quality ({quality.get('overall_quality')}), falling back")
                    question_data = None  # Fall through

        except Exception as e:
            print(f"[QuestionGen] Smart router failed, using fallback: {e}")
            question_data = None

        # ── Fallback: monolithic LLM generator (original logic) ──
        if not question_data or "question" not in question_data:
            question_data = await self._generate_question_fallback(
                job_role, calibrated_difficulty, previous_questions,
                round_type, job_description, experience_level,
                previous_answers, last_score, jd_analysis, is_coding_question,
            )

        question_data.setdefault("round", round_type)
        question_data.setdefault("evaluation_keywords", question_data.get("keywords", ["experience", "skills"]))
        question_data.setdefault("difficulty_level", calibrated_difficulty)
        question_data.setdefault("is_coding", False)
        question_data.setdefault("followup_trigger_conditions", {})
        question_data["keywords"] = question_data["evaluation_keywords"]
        question_data = self._ensure_question_multiref(question_data, round_type)

        return question_data

    async def _generate_question_fallback(
        self,
        job_role: str,
        difficulty: str,
        previous_questions: List[str],
        round_type: str = "Technical",
        job_description: str = "",
        experience_level: str = "",
        previous_answers: List[str] = None,
        last_score: float = None,
        jd_analysis: Dict[str, Any] = None,
        is_coding_question: bool = False,
    ) -> Dict[str, Any]:
        """Fallback monolithic question generator using direct LLM call."""

        prev_q_text = "\n".join(f"- {q}" for q in previous_questions[-15:]) if previous_questions else "None"
        prev_a_text = ""
        if previous_answers and len(previous_answers) > 0:
            last_answer = previous_answers[-1] if previous_answers else ""
            prev_a_text = f"\nCandidate's last answer: {last_answer}"

        followup_instruction = ""
        if last_score is not None:
            if last_score >= 80:
                followup_instruction = "The candidate scored well. INCREASE difficulty. Ask a deeper technical follow-up related to their last answer."
            elif last_score >= 50:
                followup_instruction = "The candidate gave a moderate answer. Ask a clarification question or probe their practical understanding."
            else:
                followup_instruction = "The candidate struggled. Ask a simpler, supportive question on a related topic or move to an easier area."

        jd_context = ""
        if job_description:
            jd_context = f"\nFull Job Description:\n{job_description}\n"
        if jd_analysis:
            jd_context += f"\nExtracted Skills: {json.dumps(jd_analysis.get('required_skills', []))}"
            jd_context += f"\nKey Responsibilities: {json.dumps(jd_analysis.get('key_responsibilities', []))}"
            jd_context += f"\nTools & Frameworks: {json.dumps(jd_analysis.get('tools_and_frameworks', []))}"
            if round_type == "HR":
                jd_context += f"\nSoft Skills to Evaluate: {json.dumps(jd_analysis.get('soft_skills', []))}"
                jd_context += f"\nHR Topics: {json.dumps(jd_analysis.get('hr_topics', []))}"
            else:
                jd_context += f"\nTechnical Topics: {json.dumps(jd_analysis.get('technical_topics', []))}"

        coding_instruction = ""
        if is_coding_question:
            coding_instruction = """
This must be a CODING question. Ask the candidate to write code to solve a specific problem.
Include in the question: the problem statement, expected input/output, and any constraints.
The ideal_answer should contain clean working code with brief comments (no lengthy explanations).
Set "is_coding": true in the response."""

        # Add randomization seed for variety across sessions
        import random
        variety_seed = random.randint(1, 10000)
        topic_angles = [
            "a practical scenario", "a conceptual deep-dive", "a real-world problem",
            "a comparison or trade-off analysis", "a design challenge",
            "an optimization problem", "a debugging scenario", "a best-practices discussion",
            "an architecture decision", "a recent technology trend",
        ]
        chosen_angle = random.choice(topic_angles)

        prompt = f"""Generate a {round_type} interview question for a {job_role} position.
Experience Level: {experience_level or 'Not specified'}
Difficulty: {difficulty}
Round: {round_type}
{jd_context}

Previously asked questions (DO NOT repeat these or ask semantically similar questions — pick a DIFFERENT topic/angle each time):
{prev_q_text}
{prev_a_text}

{followup_instruction}
{coding_instruction}

CRITICAL RULES:
1. The question MUST be SHORT and CONCISE — ideally 1-2 sentences (max 30 words).
2. Do NOT add long preambles, context paragraphs, or multi-part questions.
3. Ask ONE clear thing. Examples of GOOD questions:
   - "What is the difference between an abstract class and an interface?"
   - "How would you optimize a slow database query?"
   - "Tell me about a time you resolved a team conflict."
4. BAD questions are overly long, multi-part, or contain unnecessary context.
5. The ideal_answer should be a HUMANIZED, conversational answer (2-4 sentences) — like a confident professional speaking naturally. Use first-person ("I", "In my experience..."). NO bullet points.
6. Create a UNIQUE question DIFFERENT from all previously asked questions.
7. Approach this from the angle of: {chosen_angle}.

Variety seed: {variety_seed}

Return ONLY a JSON object in this exact format:
{{
  "round": "{round_type}",
  "question": "Your SHORT interview question here (1-2 sentences max)",
  "ideal_answer": "Short humanized answer in first-person (2-4 sentences, conversational tone)",
    "ideal_answers": [
        {{"answer": "Version 1", "type": "theoretical"}},
        {{"answer": "Version 2", "type": "practical"}},
        {{"answer": "Version 3", "type": "example_based"}}
    ],
  "evaluation_keywords": ["keyword1", "keyword2", "keyword3", "keyword4", "keyword5"],
  "difficulty_level": "{difficulty}",
  "is_coding": false,
  "followup_trigger_conditions": {{
    "strong_answer": "Harder follow-up question (1 sentence)",
    "moderate_answer": "Clarification follow-up (1 sentence)",
    "weak_answer": "Simpler fallback question (1 sentence)"
  }}
}}"""

        system = f"You are an expert {round_type} interviewer. Generate SHORT, CONCISE, and relevant questions (1-2 sentences max). Never write long or multi-part questions. Always return valid JSON."

        response = await self._llm_generate(prompt, system)
        parsed = self._parse_json_from_response(response)

        if not parsed or "question" not in parsed:
            if round_type == "HR":
                fallback_questions = [
                    "Tell me about a time you handled a conflict in your team.",
                    "What motivates you in your career?",
                    "Describe a situation where you showed leadership.",
                    "Where do you see yourself in five years?",
                    "How do you handle tight deadlines?",
                    "What is your biggest professional achievement?",
                    "Why are you interested in this role?",
                    "How do you prioritize when everything is urgent?",
                ]
            else:
                fallback_questions = [
                    f"What are the key principles of {job_role}?",
                    f"Describe a tough technical problem you solved recently.",
                    f"What tools and frameworks do you prefer as a {job_role} and why?",
                    f"How would you design a scalable system for a typical {job_role} task?",
                    f"What is your approach to debugging production issues?",
                    f"Explain a complex {job_role} concept in simple terms.",
                    f"What are common performance bottlenecks in {job_role} work?",
                    f"How do you ensure code quality in your projects?",
                ]

            chosen = fallback_questions[0]
            for fq in fallback_questions:
                if fq not in previous_questions:
                    chosen = fq
                    break

            parsed = {
                "round": round_type,
                "question": chosen,
                "ideal_answer": "A strong answer should cover relevant experience, specific examples, and demonstrate domain knowledge.",
                "evaluation_keywords": ["experience", "skills", "knowledge", "examples", "approach"],
                "difficulty_level": difficulty,
                "is_coding": False,
                "followup_trigger_conditions": {},
            }

        return parsed

    # ── Pre-generate next question (fire-and-forget) ──

    async def pre_generate_question(self, cache_key: str, **kwargs):
        """Pre-generate the next question in the background while evaluation runs."""
        try:
            q = await self.generate_question(**kwargs)
            self._question_cache[cache_key] = q
        except Exception as e:
            print(f"Pre-generation failed: {e}")

    def get_cached_question(self, cache_key: str) -> Optional[Dict]:
        """Get a pre-generated question from the cache."""
        return self._question_cache.pop(cache_key, None)

    # ── TWO-PHASE ANSWER EVALUATION ───────────────────
    #
    # Phase 1 (Instant, < 2s): Semantic similarity + keyword match + communication heuristics
    # Phase 2 (Background):    LLM depth analysis + AI feedback
    #

    async def evaluate_answer_instant(
        self,
        question: str,
        ideal_answer: str,
        candidate_answer: str,
        keywords: List[str],
        round_type: str = "Technical",
        scoring_weights: Dict[str, float] = None,
        live_confidence: float = None,
        ideal_answers: Optional[List[Any]] = None,
    ) -> Dict[str, Any]:
        """Phase 1: Instant scoring using local models only (no LLM calls).
        Returns a score within ~1-2 seconds.
        """
        if not candidate_answer.strip():
            return {
                "content_score": 0, "keyword_score": 0, "depth_score": 0,
                "communication_score": 0, "confidence_score": 0, "overall_score": 0,
                "similarity_score": 0, "keyword_coverage": 0,
                "keywords_matched": [], "keywords_missed": keywords,
                "feedback": "No answer provided.",
                "answer_strength": "weak",
                "phase": "instant",
            }

        refs = self._normalize_ideal_answers(ideal_answer=ideal_answer, ideal_answers=ideal_answers)
        ref_texts = [r["answer"] for r in refs]

        # 1. Best-match semantic scoring across all ideal references
        from app.services.model_registry import model_registry
        if model_registry.cross_encoder:
            pairs = [(ref, candidate_answer) for ref in ref_texts]
            pred_scores = model_registry.cross_encoder.predict(pairs)
            pred_arr = np.array(pred_scores, dtype=float).reshape(-1)
            best_idx = int(np.argmax(pred_arr))
            best_raw = float(pred_arr[best_idx])
            sim_score = 100.0 / (1.0 + np.exp(-best_raw))
        else:
            embeddings = await asyncio.to_thread(self.embedding_model.encode, ref_texts + [candidate_answer])
            cand_emb = embeddings[-1]
            ref_embs = embeddings[:-1]
            sims = cosine_similarity([cand_emb], ref_embs)[0]
            best_idx = int(np.argmax(sims))
            raw_sim = float(sims[best_idx])
            sim_score = max(0.0, min(100.0, (raw_sim - 0.05) / 0.70 * 100))

        # 2. Semantic Keyword matching + WordNet synonym expansion
        answer_lower = candidate_answer.lower()
        matched = []
        missed = []
        
        # Tokenize candidate answer for n-grams
        try:
            vectorizer = CountVectorizer(ngram_range=(1, 3))
            vectorizer.fit([answer_lower])
            candidate_ngrams = set(vectorizer.get_feature_names_out())
        except ValueError:
            candidate_ngrams = set(answer_lower.split())
            
        for k in keywords:
            k_lower = k.lower()
            if k_lower in answer_lower:
                matched.append(k)
                continue
            
            # WordNet Synonym expansion
            synonyms = set()
            for syn in wordnet.synsets(k_lower):
                for l in syn.lemmas():
                    synonyms.add(l.name().replace('_', ' ').lower())
            
            if any(syn in answer_lower for syn in synonyms):
                matched.append(k)
                continue
                
            # Semantic matching via embeddings against n-grams if not found
            # (Simplified heuristics to keep instant scoring fast)
            if model_registry.embedding_model:
                try:
                    k_emb = model_registry.embedding_model.encode(k_lower)
                    # Use a wider n-gram sample to reduce false keyword misses.
                    n_gram_list = list(candidate_ngrams)[:60]
                    if n_gram_list:
                        n_embs = model_registry.embedding_model.encode(n_gram_list)
                        sims = cosine_similarity([k_emb], n_embs)[0]
                        if np.max(sims) > 0.70:
                            matched.append(k)
                            continue
                except Exception:
                    pass
            
            missed.append(k)

        keyword_pct = (len(matched) / max(len(keywords), 1)) * 100

        # 3. Communication score (heuristic — instant)
        word_count = len(candidate_answer.split())
        sentences = [s.strip() for s in candidate_answer.split(".") if s.strip()]
        # Base score from response length
        if word_count < 10:
            comm_score = 15
        elif word_count < 20:
            comm_score = 35
        elif word_count < 50:
            comm_score = 65
        elif word_count < 100:
            comm_score = 78
        elif word_count < 200:
            comm_score = 86
        else:
            comm_score = 88
        # Bonus for structured multi-sentence answers
        if len(sentences) >= 3:
            comm_score = min(100, comm_score + 8)
        if len(sentences) >= 5:
            comm_score = min(100, comm_score + 5)
        # Bonus for transition words indicating structured thinking
        structure_markers = ['firstly', 'secondly', 'however', 'moreover', 'for example',
                            'in addition', 'furthermore', 'therefore', 'in conclusion',
                            'on the other hand', 'specifically', 'for instance']
        marker_count = sum(1 for m in structure_markers if m in candidate_answer.lower())
        comm_score = min(100, comm_score + marker_count * 3)

        # 4. Depth estimate (heuristic based on similarity + length + keywords)
        depth_score = min(100, sim_score * 0.5 + keyword_pct * 0.3 + min(word_count, 100) * 0.2)

        # 5. Content accuracy
        content_score = (sim_score * 0.6) + (keyword_pct * 0.4)

        # 6. Confidence score uses live value if available, else infer from text signals
        if live_confidence is not None:
            confidence_score = live_confidence
        else:
            confidence_score = multimodal_engine.analyze_text_confidence(candidate_answer)

        # 7. Overall score
        w = scoring_weights or {}
        overall = (
            content_score * w.get("content", 0.40)
            + keyword_pct * w.get("keyword", 0.20)
            + depth_score * w.get("depth", 0.15)
            + comm_score * w.get("communication", 0.15)
            + confidence_score * w.get("confidence", 0.10)
        )
        
        # 8. Isotonic Regression Calibration
        overall = score_calibrator.calibrate(overall)

        if overall >= 80:
            answer_strength = "strong"
        elif overall >= 50:
            answer_strength = "moderate"
        else:
            answer_strength = "weak"

        # Detailed heuristic feedback (no LLM)
        feedback_parts = []
        if sim_score >= 70:
            feedback_parts.append("Your answer aligns well with the expected response.")
        elif sim_score >= 40:
            feedback_parts.append("Your answer partially covers the expected content.")
        else:
            feedback_parts.append("Your answer doesn't closely match what was expected.")

        if keyword_pct >= 70:
            feedback_parts.append("Good use of relevant technical terminology.")
        elif missed:
            feedback_parts.append(f"Consider mentioning: {', '.join(missed[:3])}.")

        if word_count < 30:
            feedback_parts.append("Try to elaborate more — provide specific examples and details.")
        elif len(sentences) < 3:
            feedback_parts.append("Structure your answer into multiple points for clarity.")

        if overall >= 75:
            feedback_parts.append("Strong response overall!")
        elif overall < 40:
            feedback_parts.append("Review the core concepts and practice with concrete examples.")

        feedback = " ".join(feedback_parts)

        return {
            "content_score": round(content_score, 1),
            "keyword_score": round(keyword_pct, 1),
            "depth_score": round(depth_score, 1),
            "communication_score": round(comm_score, 1),
            "confidence_score": round(confidence_score, 1),
            "overall_score": round(overall, 1),
            "similarity_score": round(sim_score, 1),
            "keyword_coverage": round(keyword_pct, 1),
            "keywords_matched": matched,
            "keywords_missed": missed,
            "feedback": feedback,
            "answer_strength": answer_strength,
            "best_matching_ideal_answer_index": int(best_idx),
            "phase": "instant",
        }

    async def evaluate_answer_deep(
        self,
        question: str,
        ideal_answer: str,
        candidate_answer: str,
        keywords: List[str],
        instant_result: Dict[str, Any],
        round_type: str = "Technical",
        scoring_weights: Dict[str, float] = None,
        ideal_answers: Optional[List[Any]] = None,
    ) -> Dict[str, Any]:
        """Phase 2: Deep LLM analysis with calibrated anti-collapse blending.

        Key behavior:
        - Blend: llm 70% + instant 20% + sim 10%
        - Floor: keep at least 68% of instant score
        - Depth: additive +/-5 adjustment
        - Rubric-failure floor: keep at least 72% of instant score
        """
        try:
            refs = self._normalize_ideal_answers(ideal_answer=ideal_answer, ideal_answers=ideal_answers)
            best_idx = int(instant_result.get("best_matching_ideal_answer_index", 0))
            best_idx = max(0, min(best_idx, len(refs) - 1))
            instant_overall = float(instant_result.get("overall_score", 0.0))
            sim_guard = float(instant_result.get("similarity_score", 0.0))

            # Run rubric over top references and keep the best human-like alignment.
            ranked_refs = sorted(
                enumerate(refs),
                key=lambda x: 0 if x[0] == best_idx else 1,
            )
            top_refs = ranked_refs[: min(3, len(ranked_refs))]
            rubric_tasks = [
                self._evaluate_rubric(question, ref["answer"], candidate_answer, round_type)
                for _, ref in top_refs
            ]
            depth_task = self._evaluate_depth(question, candidate_answer, sim_guard)
            feedback_task = self._get_ai_feedback(question, candidate_answer, instant_overall, round_type)

            rubric_results, depth_score, feedback = await asyncio.gather(
                asyncio.gather(*rubric_tasks),
                depth_task,
                feedback_task,
            )

            rubric = {}
            rubric_ref_idx = best_idx
            best_rubric_overall = -1.0
            for (idx, _), candidate_rubric in zip(top_refs, rubric_results):
                if candidate_rubric and "overall" in candidate_rubric:
                    cand_overall = float(candidate_rubric.get("overall", 0.0))
                    if cand_overall > best_rubric_overall:
                        best_rubric_overall = cand_overall
                        rubric = candidate_rubric
                        rubric_ref_idx = idx

            if rubric and rubric.get("overall"):
                llm_score = float(rubric["overall"])

                # Use rubric depth if present, but do not discard standalone depth signal.
                if rubric.get("depth"):
                    depth_score = max(depth_score, float(rubric["depth"]) * 0.9)

                # Primary blend: rubric leads, instant protects, sim grounds semantics.
                overall = (
                    llm_score * 0.70
                    + instant_overall * 0.20
                    + sim_guard * 0.10
                )

                # Additive depth adjustment, bounded to avoid instability.
                depth_delta = (depth_score - 60.0) * 0.08
                depth_delta = max(-5.0, min(5.0, depth_delta))
                overall += depth_delta

                # Slightly widen distribution around mid-point.
                overall = ((overall - 50.0) * 1.18) + 50.0

                # Floor protection: prevent severe drops from instant evidence.
                overall = max(overall, instant_overall * 0.68)

                # Small keyword evidence bonus.
                keyword_score = float(instant_result.get("keyword_score", 0.0))
                if keyword_score >= 60.0:
                    kw_bonus = (keyword_score - 60.0) * 0.05
                    overall = min(100.0, overall + kw_bonus)

                overall = score_calibrator.calibrate(overall)
                overall = max(0.0, min(100.0, overall))

            else:
                # Rubric failed: weighted fallback with floor protection.
                content_score = instant_result["content_score"]
                keyword_pct = instant_result["keyword_score"]
                comm_score = instant_result["communication_score"]
                confidence_score = instant_result.get("confidence_score", 50.0)
                w = scoring_weights or {}
                overall = (
                    content_score * w.get("content", 0.40)
                    + keyword_pct * w.get("keyword", 0.20)
                    + depth_score * w.get("depth", 0.15)
                    + comm_score * w.get("communication", 0.15)
                    + confidence_score * w.get("confidence", 0.10)
                )
                overall = ((overall - 50.0) * 1.10) + 50.0
                overall = max(overall, instant_overall * 0.72)
                overall = score_calibrator.calibrate(overall)
                overall = max(0.0, min(100.0, overall))

            if overall >= 80:
                answer_strength = "strong"
            elif overall >= 50:
                answer_strength = "moderate"
            else:
                answer_strength = "weak"

            return {
                **instant_result,
                "depth_score": round(depth_score, 1),
                "overall_score": round(overall, 1),
                "feedback": feedback if feedback else instant_result["feedback"],
                "answer_strength": answer_strength,
                "best_matching_ideal_answer_index": rubric_ref_idx,
                "phase": "deep",
            }
        except Exception as e:
            print(f"Deep evaluation error: {e}")
            return {**instant_result, "phase": "deep_failed"}

    async def evaluate_answer(
        self,
        question: str,
        ideal_answer: str,
        candidate_answer: str,
        keywords: List[str],
        round_type: str = "Technical",
        is_coding: bool = False,
        scoring_weights: Dict[str, float] = None,
        live_confidence: float = None,
        ideal_answers: Optional[List[Any]] = None,
    ) -> Dict[str, Any]:
        """Full evaluation: runs instant first, then deep in parallel.
        Returns the best available result.
        """
        # Phase 1: Instant (< 2s)
        instant = await self.evaluate_answer_instant(
            question, ideal_answer, candidate_answer, keywords, round_type,
            scoring_weights=scoring_weights,
            live_confidence=live_confidence,
            ideal_answers=ideal_answers,
        )

        # Phase 2: Deep (parallel LLM calls)
        try:
            deep = await asyncio.wait_for(
                self.evaluate_answer_deep(
                    question, ideal_answer, candidate_answer, keywords, instant, round_type,
                    scoring_weights=scoring_weights,
                    ideal_answers=ideal_answers,
                ),
                timeout=60.0,  # Increased timeout for paper benchmark parallelization
            )
            return deep
        except asyncio.TimeoutError:
            print("⚠️ Deep evaluation timed out, using instant scores")
            return instant

    async def _evaluate_depth(self, question: str, answer: str, sim_score: float) -> float:
        """Evaluate depth of knowledge with calibrated partial-credit anchors."""
        prompt = f"""Evaluate the depth of knowledge in this interview answer on a 0-100 scale.

CALIBRATION - Apply generous partial credit:
  - Any specific tool, framework, or technology mentioned -> at least 55
  - Any practical example or real-world scenario -> at least 65
  - Multiple concepts with explanation of why/how -> 75+
  - Expert reasoning with trade-offs and alternatives -> 85+
  - Only score below 40 if the answer is generic with zero concrete substance

Question: {question}
Answer: {answer}

Depth Rubric:
- 85-100: Expert - specific real examples, advanced concepts, edge cases
- 70-84: Proficient - practical methods, shows real-world experience
- 55-69: Competent - core concepts covered, some practical awareness
- 40-54: Basic - surface level, mostly theoretical
- 20-39: Superficial - buzzwords, weak understanding
- 0-19: Inadequate - irrelevant, incorrect, or empty

Return ONLY a JSON object: {{"depth_score": <number>}}"""

        try:
            response = await self._llm_generate(
                prompt,
                "You are a calibrated depth evaluator. Apply partial credit. Return only valid JSON.",
                fast=False,
            )
            parsed = self._parse_json_from_response(response)
            score = parsed.get("depth_score", sim_score * 0.9)
            return max(0, min(100, float(score)))
        except Exception:
            return sim_score * 0.9

    async def _evaluate_rubric(
        self,
        question: str,
        ideal_answer: str,
        candidate_answer: str,
        round_type: str,
    ) -> dict:
        """Full rubric evaluation using LLM - 5 dimensions on 0-100 scale.
        Uses calibrated anchors and full-budget inference for stability."""
        prompt = f"""You are a calibrated interview scoring expert. Score this answer fairly and accurately.

CALIBRATION ANCHORS (align your scores with human expert benchmarks):
  - Completely wrong or empty answer -> overall ~10-20
  - Vague buzzwords only, no real substance -> overall ~25-40
  - Partial answer: correct direction but missing key concepts -> overall ~45-60
  - Solid answer covering core concepts with practical sense -> overall ~65-78
  - Strong answer with depth, examples, and clear understanding -> overall ~79-90
  - Exceptional expert-level answer -> overall ~91-100

CRITICAL RULES:
  - Do not default to conservative 50-60 range.
  - Apply partial credit: if 60% of ideal is covered, score around 60-65.
  - If answer is correct and relevant, score at least 65.
  - If answer shows solid understanding with specific details, score at least 75.
  - Only score below 50 if answer is fundamentally wrong or empty.
  - Concise correct answer is better than long vague answer. Do not penalize brevity.

Question: {question}
Ideal Answer: {ideal_answer}
Candidate Answer: {candidate_answer}
Interview Type: {round_type}

Score each dimension on 0-100:
- accuracy: Is the conceptual core correct?
- completeness: Are the important aspects covered?
- depth: Does the candidate go beyond surface level?
- relevance: Does the answer address what was asked?
- clarity: Is the communication clear and organized?

Formula: overall = (accuracy*0.30) + (completeness*0.25) + (depth*0.25) + (relevance*0.10) + (clarity*0.10)

Return ONLY valid JSON with no explanation, no markdown, no backticks:
{{"accuracy": <0-100>, "completeness": <0-100>, "depth": <0-100>, "relevance": <0-100>, "clarity": <0-100>, "overall": <0-100>, "rationale": "<one sentence>"}}"""

        try:
            response = await self._llm_generate(
                prompt,
                "You are a calibrated interview scoring expert. Use the full 0-100 scale and return only valid JSON.",
                fast=False,
            )
            parsed = self._parse_json_from_response(response)
            if parsed and "overall" in parsed:
                for key in ["accuracy", "completeness", "depth", "relevance", "clarity", "overall"]:
                    if key in parsed:
                        parsed[key] = max(0.0, min(100.0, float(parsed[key])))
                return parsed
        except Exception as e:
            print(f"[_evaluate_rubric] Failed: {e}")
        return {}

    async def _get_ai_feedback(
        self, question: str, answer: str, score: float, round_type: str = "Technical"
    ) -> str:
        prompt = f"""Evaluate this {round_type} interview answer briefly (2-3 sentences).
Question: {question}
Answer: {answer}
Score: {score}/100

Provide constructive feedback: what was good, what could be improved, and one specific suggestion."""

        system = "You are an expert interviewer providing brief, constructive, actionable feedback."
        try:
            result = await self._llm_generate(prompt, system, fast=True)
            if result.strip():
                return result.strip()
        except Exception:
            pass

        if score >= 70:
            return "Good answer with relevant details. Consider adding more specific examples to strengthen your response."
        elif score >= 40:
            return "Decent answer but could be more detailed. Include specific examples and demonstrate deeper knowledge."
        else:
            return "Answer needs improvement. Focus on addressing the question directly with relevant examples and key concepts."

    # ── Code Follow-up Question ───────────────────────

    def build_code_followup_question(
        self,
        original_question: str,
        submitted_code: str,
        code_eval: Dict[str, Any],
        language: str = "python",
        difficulty: str = "medium",
    ) -> Dict[str, Any]:
        """Build a verbal follow-up question about the candidate's code logic.

        Uses the follow_up_questions produced by evaluate_code(). If none are
        available, generates a sensible default based on the code evaluation
        scores.  The returned dict matches the standard question format and
        is always a NON-coding verbal question (is_coding=False).
        """
        import random

        follow_ups = code_eval.get("follow_up_questions", [])

        # Pick a follow-up or generate one based on weakest area
        if follow_ups:
            chosen = random.choice(follow_ups)
        else:
            # Derive from weakest score
            scores = {
                "correctness": code_eval.get("correctness_score", 50),
                "efficiency": code_eval.get("efficiency_score", 50),
                "edge_cases": code_eval.get("edge_case_score", 50),
                "quality": code_eval.get("quality_score", 50),
            }
            weakest = min(scores, key=scores.get)
            defaults = {
                "correctness": "Walk me through your code logic step by step. How does it handle the expected input?",
                "efficiency": "What is the time and space complexity of your solution? Can you optimize it?",
                "edge_cases": "What edge cases could break your solution, and how would you handle them?",
                "quality": "How would you refactor this code to make it more readable and maintainable?",
            }
            chosen = defaults[weakest]

        return {
            "question": chosen,
            "ideal_answer": f"Candidate should demonstrate deep understanding of their code: {code_eval.get('feedback', 'Explain the logic, trade-offs, and potential improvements.')}",
            "ideal_answers": [
                {
                    "answer": f"I would explain the core logic, complexity, and correctness of my approach clearly using this code as reference: {code_eval.get('feedback', 'Explain the logic and trade-offs.')}",
                    "type": "theoretical",
                },
                {
                    "answer": "In practice, I would walk through edge cases, then show what I would refactor for readability and performance.",
                    "type": "practical",
                },
                {
                    "answer": "For example, I would test empty input, boundary values, and worst-case size to prove behavior under pressure.",
                    "type": "example_based",
                },
            ],
            "evaluation_keywords": ["logic", "complexity", "edge cases", "optimization", "explanation"],
            "keywords": ["logic", "complexity", "edge cases", "optimization", "explanation"],
            "difficulty_level": difficulty,
            "is_coding": False,
            "question_type": "code_followup",
            "round": "Technical",
            "is_code_followup": True,
        }

    # ── Evaluate Code Submission ──────────────────────

    async def evaluate_code(
        self,
        question: str,
        ideal_answer: str,
        submitted_code: str,
        language: str = "python",
    ) -> Dict[str, Any]:
        """Evaluate a coding question submission."""
        prompt = f"""Evaluate this code submission for an interview coding question.

Question: {question}
Expected Solution: {ideal_answer}
Submitted Code ({language}):
```{language}
{submitted_code}
```

Evaluate on:
1. Correctness (does it solve the problem?) - 0-100
2. Code quality (readability, naming, structure) - 0-100
3. Efficiency (time/space complexity) - 0-100
4. Edge case handling - 0-100

Also generate 2-3 follow-up questions about the code logic.

Return ONLY a JSON object:
{{
  "correctness_score": <number>,
  "quality_score": <number>,
  "efficiency_score": <number>,
  "edge_case_score": <number>,
  "overall_score": <number>,
  "feedback": "Brief constructive feedback",
  "follow_up_questions": ["q1", "q2"]
}}"""

        response = await self._llm_generate(prompt, "You are an expert code reviewer. Return valid JSON only.")
        parsed = self._parse_json_from_response(response)

        if not parsed or "overall_score" not in parsed:
            embeddings = await asyncio.to_thread(self.embedding_model.encode, [ideal_answer, submitted_code])
            sim = float(cosine_similarity([embeddings[0]], [embeddings[1]])[0][0]) * 100
            parsed = {
                "correctness_score": round(sim, 1),
                "quality_score": 50.0,
                "efficiency_score": 50.0,
                "edge_case_score": 40.0,
                "overall_score": round(sim * 0.8, 1),
                "feedback": "Code submitted. Review the expected solution for comparison.",
                "follow_up_questions": [
                    "Can you explain the time complexity of your solution?",
                    "How would you handle edge cases?",
                ],
            }

        return parsed

    # ── Round Transition Logic ────────────────────────

    def calculate_round_score(self, responses: List[dict]) -> float:
        """Calculate average overall score for a set of responses."""
        if not responses:
            return 0.0
        scores = [r.get("evaluation", {}).get("overall_score", 0) for r in responses]
        return round(sum(scores) / len(scores), 1)

    def should_proceed_to_hr(self, technical_score: float, cutoff: float = 70.0) -> bool:
        """Check if candidate qualifies for HR round."""
        return technical_score >= cutoff

    def determine_next_difficulty(self, last_score: float, current_difficulty: str) -> str:
        """Adapt difficulty based on last answer performance."""
        if last_score >= 80:
            return "hard"
        elif last_score >= 50:
            return "medium"
        else:
            return "easy"

    # ── ACTIVE-TIME TIMER (pauses during AI processing) ──

    def check_time_status(
        self,
        start_time: datetime,
        duration_minutes: int,
        processing_time_seconds: float = 0,
    ) -> Dict[str, Any]:
        """Check interview time status using ACTIVE TIME only.
        
        Subtracts cumulative AI processing time from elapsed time
        so candidates aren't penalized for slow evaluation.
        """
        now = datetime.utcnow()
        wall_elapsed = (now - start_time).total_seconds() / 60
        # Subtract processing overhead from elapsed time
        active_elapsed = max(0, wall_elapsed - (processing_time_seconds / 60))
        remaining = max(0, duration_minutes - active_elapsed)

        return {
            "elapsed_minutes": round(active_elapsed, 1),
            "remaining_minutes": round(remaining, 1),
            "remaining_seconds": int(remaining * 60),
            "is_expired": remaining <= 0,
            "is_wrap_up": 0 < remaining < 2,
            "progress_pct": min(100, round((active_elapsed / max(duration_minutes, 1)) * 100, 1)),
            "wall_elapsed_minutes": round(wall_elapsed, 1),
        }

    # ── Report Generation ─────────────────────────────

    async def generate_report(self, session: dict, user: dict) -> dict:
        """Generate comprehensive two-round interview report."""
        questions = session.get("questions", [])
        responses = session.get("responses", [])

        tech_evaluations = []
        hr_evaluations = []
        all_scores = {
            "content": [], "keyword": [], "depth": [],
            "communication": [], "confidence": [], "overall": [],
        }

        for resp in responses:
            q_doc = next(
                (q for q in questions if q["question_id"] == resp["question_id"]),
                None,
            )
            if not q_doc:
                continue

            ev = resp.get("evaluation", {})
            round_type = q_doc.get("round", "Technical")
            ideal_refs = self._normalize_ideal_answers(
                ideal_answer=q_doc.get("ideal_answer", ""),
                ideal_answers=q_doc.get("ideal_answers"),
            )

            eval_entry = {
                "question": q_doc["question"],
                "answer": resp["answer_text"],
                "ideal_answer": ideal_refs[0]["answer"],
                "ideal_answers": ideal_refs,
                "round": round_type,
                "difficulty": q_doc.get("difficulty", "medium"),
                "is_coding": q_doc.get("is_coding", False),
                "code_text": resp.get("code_text", ""),
                "code_language": resp.get("code_language", ""),
                "scores": {
                    "content_score": ev.get("content_score", 0),
                    "keyword_score": ev.get("keyword_score", ev.get("keyword_coverage", 0)),
                    "depth_score": ev.get("depth_score", 0),
                    "communication_score": ev.get("communication_score", 0),
                    "confidence_score": ev.get("confidence_score", 50),
                    "overall_score": ev.get("overall_score", 0),
                },
                "feedback": ev.get("feedback", ""),
                "keywords_matched": ev.get("keywords_matched", []),
                "keywords_missed": ev.get("keywords_missed", []),
                "answer_strength": ev.get("answer_strength", "moderate"),
                "best_matching_ideal_answer_index": ev.get("best_matching_ideal_answer_index", 0),
            }

            if round_type == "HR":
                hr_evaluations.append(eval_entry)
            else:
                tech_evaluations.append(eval_entry)

            for key in ["content", "keyword", "depth", "communication", "confidence", "overall"]:
                score_key = f"{key}_score"
                all_scores[key].append(ev.get(score_key, ev.get(key, 0)))

        def safe_avg(lst):
            return round(sum(lst) / max(len(lst), 1), 1)

        tech_scores = [e["scores"]["overall_score"] for e in tech_evaluations]
        hr_scores = [e["scores"]["overall_score"] for e in hr_evaluations]
        tech_avg = safe_avg(tech_scores)
        hr_avg = safe_avg(hr_scores)
        overall_avg = safe_avg(tech_scores + hr_scores)

        overall_scores = {
            "content_score": safe_avg(all_scores["content"]),
            "keyword_score": safe_avg(all_scores["keyword"]),
            "depth_score": safe_avg(all_scores["depth"]),
            "communication_score": safe_avg(all_scores["communication"]),
            "confidence_score": safe_avg(all_scores["confidence"]),
            "overall_score": overall_avg,
        }

        strengths, weaknesses, suggestions = self._analyze_performance(
            overall_scores, tech_evaluations + hr_evaluations
        )

        if tech_avg >= 70 and hr_avg >= 60:
            recommendation = "Selected"
            confidence_analysis = "Strong candidate with good technical and interpersonal skills."
        elif tech_avg >= 70:
            recommendation = "Maybe — HR skills need improvement"
            confidence_analysis = "Technically strong but needs improvement in soft skills."
        elif tech_avg >= 50:
            recommendation = "Not Selected — Below threshold"
            confidence_analysis = "Candidate shows potential but did not meet the required technical cutoff."
        else:
            recommendation = "Not Selected"
            confidence_analysis = "Candidate needs significant improvement in technical knowledge."

        comm_avg = overall_scores["communication_score"]
        if comm_avg >= 80:
            comm_feedback = "Excellent communication skills. Answers are well-structured and articulate."
        elif comm_avg >= 60:
            comm_feedback = "Good communication. Could improve answer structure and depth."
        elif comm_avg >= 40:
            comm_feedback = "Average communication. Needs to practice structuring responses clearly."
        else:
            comm_feedback = "Communication needs significant improvement. Practice the STAR method for behavioral questions."

        # ── Explainability Service: SHAP-based dimension analysis ──
        try:
            avg_answer_text = " ".join(
                e.get("answer", "")[:200] for e in (tech_evaluations + hr_evaluations)[:5]
            )
            explainability_eval = {
                "content_score": overall_scores["content_score"],
                "similarity_score": overall_scores["content_score"],
                "keyword_coverage": overall_scores["keyword_score"],
                "keyword_score": overall_scores["keyword_score"],
                "depth_score": overall_scores["depth_score"],
                "communication_score": overall_scores["communication_score"],
                "confidence_score": overall_scores["confidence_score"],
                "fluency_score": overall_scores.get("communication_score", 50),
                "eye_contact": overall_scores.get("confidence_score", 50),
                "emotion_stability": max(50, overall_scores.get("confidence_score", 50) - 5),
                "stress_level": max(0, 100 - overall_scores.get("confidence_score", 50)),
                "facial_confidence": overall_scores.get("confidence_score", 50),
                "specificity_score": overall_scores.get("depth_score", 50),
                "answer_text": avg_answer_text,
            }
            explainability_result = explainability_service.explain_score(explainability_eval)
        except Exception as e:
            print(f"[Report] Explainability service error: {e}")
            explainability_result = None

        # ── Development Roadmap Service: personalized improvement plan ──
        try:
            # Build dimension_scores dict matching roadmap service expectations
            dim_scores_for_roadmap = {}
            if explainability_result and "dimension_scores" in explainability_result:
                dim_scores_for_roadmap = explainability_result["dimension_scores"]
            else:
                # Fallback: build from raw scores
                def _grade(s):
                    if s >= 85: return "Excellent"
                    if s >= 70: return "Good"
                    if s >= 55: return "Average"
                    if s >= 40: return "Below Average"
                    return "Needs Improvement"

                dim_scores_for_roadmap = {
                    "Communication": {"score": overall_scores["communication_score"], "grade": _grade(overall_scores["communication_score"])},
                    "Technical Depth": {"score": overall_scores["content_score"], "grade": _grade(overall_scores["content_score"])},
                    "Confidence": {"score": overall_scores["confidence_score"], "grade": _grade(overall_scores["confidence_score"])},
                    "Emotional Regulation": {"score": max(50, overall_scores["confidence_score"] - 5), "grade": _grade(max(50, overall_scores["confidence_score"] - 5))},
                    "Problem Solving": {"score": overall_scores["depth_score"], "grade": _grade(overall_scores["depth_score"])},
                }

            roadmap_eval_summary = {
                "overall_score": overall_avg,
                "dimension_scores": dim_scores_for_roadmap,
                "improvement_suggestions": (
                    explainability_result.get("improvement_suggestions", [])
                    if explainability_result else []
                ),
            }
            job_role = session.get("job_role", "")
            development_roadmap = development_roadmap_service.generate_roadmap(
                roadmap_eval_summary, target_role=job_role, weeks_available=8
            )
        except Exception as e:
            print(f"[Report] Development roadmap service error: {e}")
            development_roadmap = None

        # ── Candidate Profile Summary (from Data Collection) ──
        candidate_profile_summary = None
        profile_context = session.get("candidate_profile_context", "")
        if profile_context:
            candidate_profile_summary = {
                "profile_used": True,
                "context": profile_context,
            }
        # Also pull structured data from user doc if present
        candidate_profile = user.get("candidate_profile", {})
        if candidate_profile:
            if candidate_profile_summary is None:
                candidate_profile_summary = {"profile_used": True}
            candidate_profile_summary["skills"] = candidate_profile.get("skills", [])
            candidate_profile_summary["experience_years"] = candidate_profile.get("experience_years")
            candidate_profile_summary["education"] = candidate_profile.get("education", [])
            candidate_profile_summary["certifications"] = candidate_profile.get("certifications", [])
            candidate_profile_summary["github_stats"] = candidate_profile.get("github_stats")

        return {
            "session_id": str(session.get("_id", "")),
            "candidate_name": user.get("name", "Candidate"),
            "job_role": session.get("job_role", ""),
            "total_questions": len(responses),
            "technical_questions": len(tech_evaluations),
            "hr_questions": len(hr_evaluations),
            "technical_score": tech_avg,
            "hr_score": hr_avg,
            "overall_score": overall_avg,
            "overall_scores": overall_scores,
            "question_evaluations": tech_evaluations + hr_evaluations,
            "strengths": strengths,
            "weaknesses": weaknesses,
            "improvement_suggestions": suggestions,
            "communication_feedback": comm_feedback,
            "confidence_analysis": confidence_analysis,
            "recommendation": recommendation,
            "round_summary": {
                "technical": {
                    "score": tech_avg,
                    "questions_asked": len(tech_evaluations),
                    "passed": tech_avg >= 70,
                },
                "hr": {
                    "score": hr_avg,
                    "questions_asked": len(hr_evaluations),
                    "passed": hr_avg >= 60,
                },
            },
            "generated_at": datetime.utcnow().isoformat(),
            # ── Enriched analysis from integrated services ──
            "explainability": explainability_result,
            "development_roadmap": development_roadmap,
            # ── Proctoring data ──
            "proctoring": session.get("proctoring", {}),
            # ── Emotion timeline for sentiment chart ──
            "emotion_timeline": session.get("emotion_timeline", []),
            # ── Candidate Profile from Data Collection ──
            "candidate_profile_summary": candidate_profile_summary,
        }

    def _analyze_performance(self, scores: dict, evaluations: list) -> tuple:
        """Generate dynamic, interview-specific strengths, weaknesses, and suggestions
        based on actual question-level performance data."""
        strengths = []
        weaknesses = []
        suggestions = []

        content = scores.get("content_score", 0)
        comm = scores.get("communication_score", 0)
        depth = scores.get("depth_score", 0)
        keyword = scores.get("keyword_score", 0)
        confidence = scores.get("confidence_score", 0)
        overall = scores.get("overall_score", 0)

        # ── Dimension-level analysis ──────────────────
        if content >= 70:
            strengths.append(f"Strong technical knowledge (Content: {content:.0f}%)")
        else:
            weaknesses.append(f"Content relevance needs work (Content: {content:.0f}%)")

        if comm >= 70:
            strengths.append(f"Clear and structured communication (Communication: {comm:.0f}%)")
        else:
            weaknesses.append(f"Communication could be more structured (Communication: {comm:.0f}%)")

        if depth >= 70:
            strengths.append(f"Good depth of understanding (Depth: {depth:.0f}%)")
        else:
            weaknesses.append(f"Answers lack depth and detail (Depth: {depth:.0f}%)")

        if keyword >= 70:
            strengths.append(f"Effective use of domain terminology (Keywords: {keyword:.0f}%)")
        else:
            weaknesses.append(f"Missing key technical terms (Keywords: {keyword:.0f}%)")

        if confidence >= 70:
            strengths.append(f"Confident and composed delivery (Confidence: {confidence:.0f}%)")
        elif confidence < 45:
            weaknesses.append(f"Appeared nervous or uncertain (Confidence: {confidence:.0f}%)")

        # ── Question-level analysis: find specific weak topics ──
        weak_questions = []
        strong_questions = []
        all_missed_keywords = []
        weak_topics = set()
        strong_topics = set()

        for e in evaluations:
            q_score = e.get("scores", {}).get("overall_score", 0)
            q_text = e.get("question", "")
            topic = e.get("topic", "") or e.get("question_subtype", "")
            missed = e.get("keywords_missed", [])
            round_type = e.get("round", "Technical")

            if q_score < 50:
                weak_questions.append({"question": q_text, "score": q_score, "round": round_type})
                if topic:
                    weak_topics.add(topic)
            elif q_score >= 75:
                strong_questions.append({"question": q_text, "score": q_score, "round": round_type})
                if topic:
                    strong_topics.add(topic)

            all_missed_keywords.extend(missed)

        # Report specific struggled questions
        if weak_questions:
            weak_count = len(weak_questions)
            total = len(evaluations)
            weaknesses.append(f"Struggled with {weak_count}/{total} questions (scored below 50%)")

            # Show the weakest questions specifically
            worst = sorted(weak_questions, key=lambda x: x["score"])[:3]
            for w in worst:
                short_q = w["question"][:60] + "..." if len(w["question"]) > 60 else w["question"]
                weaknesses.append(f"  Low score on: \"{short_q}\" ({w['score']:.0f}%)")

        if strong_questions and len(strong_questions) >= 2:
            strengths.append(f"Excelled in {len(strong_questions)}/{len(evaluations)} questions (scored 75%+)")

        # ── Dynamic suggestions based on actual gaps ──
        # Sort dimensions by score to prioritize weakest areas
        dims = [
            ("Content", content, "Study core concepts for the role. Review textbooks, documentation, and practice explaining topics out loud."),
            ("Communication", comm, "Practice the STAR method (Situation, Task, Action, Result). Record yourself answering and review for clarity."),
            ("Depth", depth, "Go deeper in your answers. Include specific examples, metrics, trade-offs, and real-world scenarios."),
            ("Keywords", keyword, "Review job descriptions for your target role. Use relevant technical terms naturally in your answers."),
            ("Confidence", confidence, "Practice mock interviews regularly. Prepare 2-3 strong examples for common question types."),
        ]
        dims_sorted = sorted(dims, key=lambda d: d[1])

        # Suggest improvements for the weakest 2-3 dimensions
        for name, score, suggestion in dims_sorted:
            if score < 70:
                suggestions.append(f"[{name} - {score:.0f}%] {suggestion}")
            if len(suggestions) >= 3 and score >= 50:
                break  # Enough suggestions for moderate performers

        # Keyword-specific suggestions
        if all_missed_keywords:
            # Get top missed keywords (most frequently missed)
            from collections import Counter
            keyword_counts = Counter(all_missed_keywords)
            top_missed = [kw for kw, _ in keyword_counts.most_common(5)]
            suggestions.append(f"Focus on these missed keywords: {', '.join(top_missed)}")

        # Weak topic suggestions
        if weak_topics:
            suggestions.append(f"Revise these weak areas: {', '.join(list(weak_topics)[:4])}")

        # Round-specific advice
        tech_evals = [e for e in evaluations if e.get("round") != "HR"]
        hr_evals = [e for e in evaluations if e.get("round") == "HR"]
        if tech_evals:
            tech_avg = sum(e.get("scores", {}).get("overall_score", 0) for e in tech_evals) / len(tech_evals)
            if tech_avg < 50:
                suggestions.append("Technical round needs significant work. Focus on fundamentals and practice coding problems daily.")
        if hr_evals:
            hr_avg = sum(e.get("scores", {}).get("overall_score", 0) for e in hr_evals) / len(hr_evals)
            if hr_avg < 50:
                suggestions.append("HR round needs improvement. Prepare stories about teamwork, leadership, and conflict resolution.")

        # Ensure we always have at least one suggestion
        if not strengths:
            strengths.append("Shows willingness to practice and improve")
        if not suggestions:
            suggestions.append("Maintain your strong performance by continuing regular practice")

        return strengths, weaknesses, suggestions


# Singleton
ai_service = AIService()
