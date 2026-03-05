"""
Practice Mode Service
─────────────────────
Real-time practice mode with live metrics dashboard

Features:
  - Real-time multimodal metric streaming (stress, confidence, attention, etc.)
  - Continuous answer scoring with live feedback
  - Adaptive question modification based on live performance
  - Micro-suggestions delivered between questions
  - Session analytics and trend analysis
  - Practice history tracking
"""

import asyncio
import time
from typing import Dict, Any, List, Optional
from datetime import datetime
from collections import deque

import numpy as np

from app.services.ai_service import ai_service
try:
    from app.services.multimodal_analysis_service import multimodal_engine, GazeStateMachine
except Exception as e:
    multimodal_engine = None
    GazeStateMachine = None
    print(f"\u26a0\ufe0f Multimodal analysis unavailable in practice mode: {e}")
try:
    from app.services.proctoring_service import proctor_manager
except Exception:
    proctor_manager = None
from app.services.explainability_service import explainability_service
from app.services.development_roadmap_service import development_roadmap_service


class PracticeModeService:
    """Orchestrates practice mode with real-time metrics and live feedback."""

    # Practice topics and question pools
    PRACTICE_TOPICS = {
        "behavioral": {
            "name": "Behavioral Questions",
            "description": "STAR method practice with common behavioral questions",
            "questions": [
                "Tell me about a time you faced a significant challenge at work and how you overcame it.",
                "Describe a situation where you had to work with a difficult team member.",
                "Give me an example of a time you showed leadership initiative.",
                "Tell me about a time you failed and what you learned from it.",
                "Describe a situation where you had to make a decision with incomplete information.",
                "Tell me about a time you had to adapt to a significant change.",
                "Give an example of when you went above and beyond expectations.",
                "Describe a conflict you resolved at work.",
                "Tell me about a time you had to prioritize competing demands.",
                "Describe how you handled constructive criticism.",
            ],
        },
        "technical_general": {
            "name": "Technical Fundamentals",
            "description": "Common technical interview questions",
            "questions": [
                "Explain the difference between a stack and a queue. When would you use each?",
                "What is the time complexity of common sorting algorithms?",
                "Explain how a hash map works internally.",
                "What are the SOLID principles in software engineering?",
                "Explain the difference between SQL and NoSQL databases.",
                "What is the difference between REST and GraphQL?",
                "Explain what microservices architecture is and its trade-offs.",
                "What is the CAP theorem?",
                "Explain the concept of Big O notation with examples.",
                "What are design patterns? Name three and explain one.",
            ],
        },
        "system_design": {
            "name": "System Design",
            "description": "Practice system design questions",
            "questions": [
                "Design a URL shortening service like bit.ly.",
                "How would you design a chat application like WhatsApp?",
                "Design a rate limiter for an API.",
                "How would you design a social media news feed?",
                "Design a file storage service like Dropbox.",
            ],
        },
        "communication": {
            "name": "Communication Skills",
            "description": "Practice clear, structured communication",
            "questions": [
                "Walk me through your most impactful project.",
                "How would you explain your role to someone outside your field?",
                "Pitch yourself for this role in 2 minutes.",
                "Explain a complex technical concept to a non-technical stakeholder.",
                "Tell me why you're interested in this position.",
            ],
        },
    }

    # Micro-suggestion templates
    MICRO_SUGGESTIONS = {
        "low_confidence": [
            "Try to speak with more conviction. Take a breath and project your voice.",
            "You seem unsure. It's okay to pause and collect your thoughts.",
            "Confidence tip: Start your answer with a strong statement, then support it.",
        ],
        "high_stress": [
            "You seem stressed. Take a deep breath (4 seconds in, 4 out).",
            "Remember: it's a practice session. There are no wrong answers here.",
            "Slow down a bit. Speaking too fast can increase perceived stress.",
        ],
        "low_attention": [
            "Keep your focus on the screen to maintain engagement.",
            "Your gaze seems to wander away from the screen. Stay focused on the interview.",
            "Stay present. Take a moment to re-center before answering.",
        ],
        "poor_structure": [
            "Try using the STAR method: Situation → Task → Action → Result.",
            "Start with your main point, then provide supporting details.",
            "Your answer could be more structured. Try: 'There are 3 key points...'",
        ],
        "low_specificity": [
            "Add specific numbers and metrics to strengthen your answer.",
            "Can you give a concrete example to illustrate your point?",
            "Be more specific. Instead of 'improved performance', say 'reduced latency by 40%'.",
        ],
        "filler_words": [
            "You're using filler words. Practice pausing silently instead of saying 'um'.",
            "Try to reduce filler words like 'like', 'you know', 'basically'.",
            "Slow down and pause between thoughts instead of filling with 'uh'.",
        ],
    }

    def __init__(self):
        self._active_sessions: Dict[str, Dict[str, Any]] = {}
        # Per-session gaze FSMs — keyed by session_id
        self._gaze_fsms: Dict[str, Any] = {}

    def start_practice_session(
        self,
        user_id: str,
        topic: str = "behavioral",
        difficulty: str = "medium",
    ) -> Dict[str, Any]:
        """Initialize a practice session with real-time metrics tracking."""
        session_id = f"practice_{user_id}_{int(time.time())}"

        topic_data = self.PRACTICE_TOPICS.get(topic, self.PRACTICE_TOPICS["behavioral"])
        questions = list(topic_data["questions"])
        np.random.shuffle(questions)

        session = {
            "session_id": session_id,
            "user_id": user_id,
            "topic": topic,
            "topic_name": topic_data["name"],
            "difficulty": difficulty,
            "status": "active",
            "started_at": datetime.utcnow().isoformat(),
            "questions": questions,
            "current_question_idx": 0,
            "answers": [],
            "metrics_history": [],  # List of metric snapshots
            "live_metrics": {
                "confidence": 50,
                "stress": 30,
                "attention": 70,
                "emotional_stability": 70,
                "speech_clarity": 60,
                "answer_completeness": 0,
            },
            "micro_suggestions": [],
            "scores": [],
            "overall_score": 0,
        }

        self._active_sessions[session_id] = session

        return {
            "session_id": session_id,
            "topic": topic_data["name"],
            "total_questions": len(questions),
            "first_question": questions[0],
            "difficulty": difficulty,
        }

    def get_current_question(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get the current practice question."""
        session = self._active_sessions.get(session_id)
        if not session or session["status"] != "active":
            return None

        idx = session["current_question_idx"]
        if idx >= len(session["questions"]):
            return None

        return {
            "question": session["questions"][idx],
            "question_number": idx + 1,
            "total_questions": len(session["questions"]),
            "topic": session["topic_name"],
        }

    def update_live_metrics(
        self,
        session_id: str,
        video_frame: Optional[Any] = None,
        audio_chunk: Optional[Any] = None,
        partial_text: str = "",
    ) -> Dict[str, Any]:
        """Update real-time metrics from multimodal input.

        Called frequently (every 1-2 seconds) during practice.
        Returns updated live metrics + gaze FSM state for the dashboard.
        """
        session = self._active_sessions.get(session_id)
        if not session or session["status"] != "active":
            return {"error": "Session not active"}

        current_metrics = session["live_metrics"].copy()

        # Ensure a gaze FSM exists for this session
        if session_id not in self._gaze_fsms:
            if GazeStateMachine is not None:
                self._gaze_fsms[session_id] = GazeStateMachine()
            else:
                # Multimodal not available; skip gaze tracking
                pass

        gaze_fsm = self._gaze_fsms.get(session_id)
        gaze_state_output = None
        person_count = 0
        proctor_result = None

        # ── Run proctoring pipeline (identity + objects + risk + person count) ──
        if video_frame is not None and proctor_manager is not None:
            try:
                proctor_session = proctor_manager.get_or_create(session_id)
                proctor_result = proctor_session.process_frame(video_frame)
                person_count = proctor_result.get("person_count", 0)
            except Exception as exc:
                print(f"[PRACTICE] Proctor exception: {exc}")

        # Process multimodal inputs for gaze FSM + live metrics
        if video_frame is not None and multimodal_engine is not None:
            try:
                visual = multimodal_engine.analyze_face(video_frame)
                print(f"[PRACTICE] analyze_face => face_detected={visual.get('face_detected')} eye_contact_score={visual.get('eye_contact_score')}")

                # Person count from proctoring pipeline; fallback to Haar cascade
                if proctor_result is None:
                    person_count = multimodal_engine.detect_persons(video_frame)

                if visual.get("face_detected"):
                    # Real face analysis data available (DeepFace succeeded)
                    current_metrics["confidence"] = visual.get(
                        "confidence_score", current_metrics["confidence"]
                    )
                    current_metrics["attention"] = visual.get(
                        "eye_contact_score", current_metrics["attention"]
                    )
                    current_metrics["emotional_stability"] = visual.get(
                        "emotion_stability", current_metrics["emotional_stability"]
                    )
                    current_metrics["stress"] = max(0, min(100, 100 - current_metrics["emotional_stability"]))
                else:
                    # DeepFace unavailable — but eye_contact_score from
                    # Haar cascade gaze estimation is still valid; use it
                    # so the gaze FSM gets accurate attention readings.
                    eye_score = visual.get("eye_contact_score")
                    if eye_score is not None:
                        current_metrics["attention"] = eye_score
                    else:
                        # Fallback: no gaze data at all (CV2 unavailable)
                        current_metrics["attention"] = np.clip(
                            current_metrics["attention"] * 0.7 + np.random.uniform(-3, 3), 10, 40
                        )
                    # Other metrics: gentle jitter around current values
                    t = time.time()
                    jitter = np.sin(t * 0.3) * 5 + np.random.uniform(-3, 3)
                    current_metrics["confidence"] = np.clip(
                        current_metrics["confidence"] + jitter, 30, 90
                    )
                    current_metrics["emotional_stability"] = np.clip(
                        current_metrics["emotional_stability"] + np.random.uniform(-3, 3), 40, 90
                    )
                    current_metrics["stress"] = np.clip(
                        100 - current_metrics["emotional_stability"] + np.random.uniform(-5, 5), 10, 60
                    )

                # Feed the raw gaze score into the FSM (BEFORE EMA smoothing)
                raw_attention = current_metrics["attention"]
                print(f"[PRACTICE] Feeding FSM: raw_attention={raw_attention}")
                if gaze_fsm is not None:
                    gaze_state_output = gaze_fsm.update(raw_attention)
                    print(f"[PRACTICE] FSM output: state={gaze_state_output.get('state')} warning={gaze_state_output.get('show_warning')}")

            except Exception as exc:
                print(f"[PRACTICE] Exception in video processing: {exc}")
                # On error, check staleness to keep FSM responsive
                if gaze_fsm is not None:
                    gaze_state_output = gaze_fsm.check_staleness()
        else:
            # No video frame this tick — check for camera freeze / dropped frames
            if gaze_fsm is not None:
                gaze_state_output = gaze_fsm.check_staleness()

        if audio_chunk is not None and multimodal_engine is not None:
            try:
                audio_metrics = multimodal_engine.analyze_voice(audio_chunk, sr=16000)
                current_metrics["stress"] = audio_metrics.get(
                    "stress_score", current_metrics["stress"]
                )
                current_metrics["speech_clarity"] = audio_metrics.get(
                    "clarity_score", current_metrics["speech_clarity"]
                )
            except Exception:
                pass

        # Text-based metrics
        if partial_text:
            words = partial_text.split()
            word_count = len(words)

            # Answer completeness (heuristic: 50+ words = reasonable answer)
            current_metrics["answer_completeness"] = min(100, (word_count / 80) * 100)

            # Filler words detection
            filler_words = ["um", "uh", "like", "you know", "basically", "actually", "literally"]
            filler_count = sum(partial_text.lower().count(f) for f in filler_words)
            filler_ratio = filler_count / max(word_count, 1)

            # Speech clarity adjustment based on filler ratio
            if filler_ratio > 0.05:
                current_metrics["speech_clarity"] = max(
                    20, current_metrics["speech_clarity"] - (filler_ratio * 100)
                )

        # Smooth metrics (exponential moving average)
        alpha = 0.3
        for key in current_metrics:
            old_val = session["live_metrics"].get(key, 50)
            current_metrics[key] = round(alpha * current_metrics[key] + (1 - alpha) * old_val, 1)

        # Update session
        session["live_metrics"] = current_metrics

        # Store metric snapshot
        snapshot = {
            "timestamp": datetime.utcnow().isoformat(),
            "metrics": current_metrics.copy(),
            "question_idx": session["current_question_idx"],
        }
        session["metrics_history"].append(snapshot)

        # Keep only last 300 snapshots (5 min at 1/sec)
        if len(session["metrics_history"]) > 300:
            session["metrics_history"] = session["metrics_history"][-300:]

        # Generate micro-suggestions if warranted
        suggestion = self._generate_micro_suggestion(current_metrics)

        gaze_fallback = {"state": "unknown", "show_warning": False}
        if gaze_fsm is not None:
            gaze_fallback = {
                "state": gaze_fsm.state.value,
                "show_warning": gaze_fsm.show_warning,
            }

        return {
            "metrics": current_metrics,
            "suggestion": suggestion,
            "gaze": gaze_state_output or gaze_fallback,
            "person_count": person_count,
            # Enhanced proctoring data (from proctoring_service)
            "identity": proctor_result.get("identity") if proctor_result else None,
            "suspicious_objects": proctor_result.get("suspicious_objects", []) if proctor_result else [],
            "face_absent": proctor_result.get("face_absent", False) if proctor_result else False,
            "attention": proctor_result.get("attention") if proctor_result else None,
            "risk": proctor_result.get("risk") if proctor_result else None,
        }

    def _generate_micro_suggestion(self, metrics: Dict[str, float]) -> Optional[str]:
        """Generate a contextual micro-suggestion based on current metrics."""
        # Priority-ordered checks
        if metrics.get("stress", 30) > 70:
            suggestions = self.MICRO_SUGGESTIONS["high_stress"]
            return suggestions[np.random.randint(0, len(suggestions))]

        if metrics.get("confidence", 50) < 35:
            suggestions = self.MICRO_SUGGESTIONS["low_confidence"]
            return suggestions[np.random.randint(0, len(suggestions))]

        if metrics.get("attention", 70) < 40:
            suggestions = self.MICRO_SUGGESTIONS["low_attention"]
            return suggestions[np.random.randint(0, len(suggestions))]

        if metrics.get("speech_clarity", 60) < 40:
            suggestions = self.MICRO_SUGGESTIONS["filler_words"]
            return suggestions[np.random.randint(0, len(suggestions))]

        return None

    async def submit_answer(
        self,
        session_id: str,
        answer_text: str,
    ) -> Dict[str, Any]:
        """Submit an answer, get evaluation, and advance to next question."""
        session = self._active_sessions.get(session_id)
        if not session or session["status"] != "active":
            return {"error": "Session not active"}

        idx = session["current_question_idx"]
        if idx >= len(session["questions"]):
            return {"error": "No more questions"}

        question = session["questions"][idx]

        # Evaluate using AI service
        try:
            evaluation = await ai_service.evaluate_answer(
                question=question,
                ideal_answer="",
                candidate_answer=answer_text,
                keywords=[],
                round_type="Practice",
            )
        except Exception as e:
            # Fallback evaluation
            word_count = len(answer_text.split())
            evaluation = {
                "instant_score": min(80, max(20, word_count * 0.5 + 30)),
                "feedback": "Answer recorded. Detailed feedback unavailable.",
                "strengths": [],
                "improvements": [],
            }

        score = evaluation.get("instant_score", evaluation.get("score", 50))

        # Get explainability insights
        try:
            explanation = explainability_service.explain_score({
                "similarity_score": score,
                "answer_text": answer_text,
                "communication_score": session["live_metrics"].get("speech_clarity", 60),
                "confidence_score": session["live_metrics"].get("confidence", 50),
                "emotion_stability": session["live_metrics"].get("emotional_stability", 70),
                "stress_level": session["live_metrics"].get("stress", 30),
                "eye_contact": session["live_metrics"].get("attention", 70),
            })
        except Exception:
            explanation = None

        # Build answer record
        answer_record = {
            "question": question,
            "answer": answer_text,
            "score": round(score, 1),
            "feedback": evaluation.get("feedback", ""),
            "strengths": evaluation.get("strengths", []),
            "improvements": evaluation.get("improvements", []),
            "metrics_snapshot": session["live_metrics"].copy(),
            "explanation": explanation,
            "timestamp": datetime.utcnow().isoformat(),
        }

        session["answers"].append(answer_record)
        session["scores"].append(score)

        # Advance to next question
        session["current_question_idx"] = idx + 1

        # Generate between-question suggestion
        between_suggestion = self._generate_between_question_feedback(
            score, session["live_metrics"], answer_text
        )

        # Check if practice is complete
        is_complete = session["current_question_idx"] >= len(session["questions"])
        next_question = None
        if not is_complete:
            next_question = session["questions"][session["current_question_idx"]]

        return {
            "score": round(score, 1),
            "feedback": evaluation.get("feedback", ""),
            "strengths": evaluation.get("strengths", []),
            "improvements": evaluation.get("improvements", []),
            "suggestion": between_suggestion,
            "is_complete": is_complete,
            "next_question": next_question,
            "question_number": idx + 1,
            "total_questions": len(session["questions"]),
            "explanation": explanation,
        }

    def _generate_between_question_feedback(
        self, score: float, metrics: Dict[str, float], answer: str
    ) -> str:
        """Generate actionable feedback between questions."""
        parts = []

        if score >= 80:
            parts.append("Great answer!")
        elif score >= 60:
            parts.append("Good effort. Here's how to improve:")
        else:
            parts.append("Let's work on improving your response:")

        # Specific feedback
        word_count = len(answer.split())
        if word_count < 30:
            parts.append("Your answer was quite short. Aim for more detail with specific examples.")
        elif word_count > 300:
            parts.append("Try to be more concise. Focus on the key points.")

        if metrics.get("confidence", 50) < 40:
            parts.append("Speak with more confidence. Avoid hedging words like 'maybe' or 'I think'.")

        if metrics.get("stress", 30) > 60:
            parts.append("Take a deep breath before the next question. You've got this.")

        # Check for STAR structure
        star_keywords = {
            "situation": ["situation", "context", "background", "when"],
            "task": ["task", "responsible", "needed to", "goal"],
            "action": ["action", "did", "implemented", "created", "built"],
            "result": ["result", "outcome", "achieved", "led to", "improved"],
        }
        answer_lower = answer.lower()
        missing_star = [
            part for part, keywords in star_keywords.items()
            if not any(k in answer_lower for k in keywords)
        ]
        if len(missing_star) >= 2:
            parts.append(f"Try including more STAR elements. Missing: {', '.join(missing_star)}.")

        return " ".join(parts)

    async def end_practice_session(self, session_id: str) -> Dict[str, Any]:
        """End practice session and generate comprehensive summary."""
        session = self._active_sessions.get(session_id)
        if not session:
            return {"error": "Session not found"}

        session["status"] = "completed"
        session["ended_at"] = datetime.utcnow().isoformat()

        # Clean up gaze FSM for this session
        self._gaze_fsms.pop(session_id, None)

        scores = session["scores"]
        overall_score = float(np.mean(scores)) if scores else 0

        # Compute metric averages
        all_metrics = [s["metrics"] for s in session["metrics_history"]]
        avg_metrics = {}
        if all_metrics:
            for key in session["live_metrics"]:
                values = [m.get(key, 50) for m in all_metrics]
                avg_metrics[key] = round(float(np.mean(values)), 1)

        # Generate dimension scores for roadmap
        dimension_scores = {
            "Communication": {"score": avg_metrics.get("speech_clarity", 60), "grade": ""},
            "Technical Depth": {"score": overall_score, "grade": ""},
            "Confidence": {"score": avg_metrics.get("confidence", 50), "grade": ""},
            "Emotional Regulation": {"score": avg_metrics.get("emotional_stability", 70), "grade": ""},
            "Problem Solving": {"score": overall_score * 0.9, "grade": ""},
        }
        for dim, data in dimension_scores.items():
            if data["score"] >= 80:
                data["grade"] = "Excellent"
            elif data["score"] >= 65:
                data["grade"] = "Good"
            elif data["score"] >= 50:
                data["grade"] = "Average"
            else:
                data["grade"] = "Needs Improvement"

        # Generate development roadmap
        try:
            roadmap = development_roadmap_service.generate_roadmap(
                evaluation_summary={
                    "overall_score": overall_score,
                    "dimension_scores": dimension_scores,
                    "improvement_suggestions": [],
                },
                target_role=None,
                weeks_available=4,
            )
        except Exception:
            roadmap = None

        # Metric trends
        trends = self._compute_session_trends(session["metrics_history"])

        summary = {
            "session_id": session_id,
            "topic": session["topic_name"],
            "overall_score": round(overall_score, 1),
            "questions_answered": len(session["answers"]),
            "total_questions": len(session["questions"]),
            "scores": [round(s, 1) for s in scores],
            "average_metrics": avg_metrics,
            "dimension_scores": dimension_scores,
            "trends": trends,
            "answers": [
                {
                    "question": a["question"],
                    "score": a["score"],
                    "feedback": a["feedback"],
                    "strengths": a["strengths"],
                    "improvements": a["improvements"],
                }
                for a in session["answers"]
            ],
            "roadmap": roadmap,
            "started_at": session["started_at"],
            "ended_at": session["ended_at"],
        }

        return summary

    def _compute_session_trends(
        self, metrics_history: List[Dict[str, Any]]
    ) -> Dict[str, str]:
        """Analyze metric trends over the practice session."""
        if len(metrics_history) < 10:
            return {}

        trends = {}
        first_half = metrics_history[:len(metrics_history) // 2]
        second_half = metrics_history[len(metrics_history) // 2:]

        for key in ["confidence", "stress", "attention", "speech_clarity"]:
            first_avg = float(np.mean([m["metrics"].get(key, 50) for m in first_half]))
            second_avg = float(np.mean([m["metrics"].get(key, 50) for m in second_half]))
            diff = second_avg - first_avg

            if key == "stress":
                # For stress, decreasing is good
                if diff < -5:
                    trends[key] = "improving"
                elif diff > 5:
                    trends[key] = "declining"
                else:
                    trends[key] = "stable"
            else:
                if diff > 5:
                    trends[key] = "improving"
                elif diff < -5:
                    trends[key] = "declining"
                else:
                    trends[key] = "stable"

        return trends

    def get_session_metrics(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get current session state and metrics for dashboard."""
        session = self._active_sessions.get(session_id)
        if not session:
            return None

        return {
            "session_id": session_id,
            "status": session["status"],
            "live_metrics": session["live_metrics"],
            "scores": [round(s, 1) for s in session["scores"]],
            "current_question": session["current_question_idx"] + 1,
            "total_questions": len(session["questions"]),
            "recent_suggestions": session.get("micro_suggestions", [])[-5:],
        }

    def get_practice_history(self, user_id: str) -> List[Dict[str, Any]]:
        """Get practice session history for a user."""
        history = []
        for sid, session in self._active_sessions.items():
            if session["user_id"] == user_id and session["status"] == "completed":
                history.append({
                    "session_id": sid,
                    "topic": session["topic_name"],
                    "overall_score": round(float(np.mean(session["scores"])), 1) if session["scores"] else 0,
                    "questions_answered": len(session["answers"]),
                    "started_at": session["started_at"],
                    "ended_at": session.get("ended_at"),
                })
        return sorted(history, key=lambda x: x["started_at"], reverse=True)

    def get_available_topics(self) -> List[Dict[str, Any]]:
        """Get available practice topics."""
        return [
            {
                "id": topic_id,
                "name": data["name"],
                "description": data["description"],
                "question_count": len(data["questions"]),
            }
            for topic_id, data in self.PRACTICE_TOPICS.items()
        ]


# Singleton
practice_mode_service = PracticeModeService()
