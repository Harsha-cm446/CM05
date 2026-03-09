"""
Candidate AI Interview Router — Assessment Mode (Optimized)
───────────────────────────────────────────────────────────
Token-based (no login required) endpoints for candidates invited by HR.
  • Active-time timer: pauses during AI processing
  • Parallel: evaluate answer + pre-generate next question simultaneously
  • Two-phase evaluation: instant score → background deep analysis
  • Two rounds: Technical → HR (70% cutoff)
  • JD-driven adaptive question generation
  • Code question support
"""

import asyncio
import time
import uuid
from datetime import datetime
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from app.core.database import get_database
from app.core.config import settings
from app.services.ai_service import ai_service
from app.services.report_service import generate_pdf_report
from app.services.practice_mode_service import practice_mode_service

try:
    from app.services.multimodal_analysis_service import multimodal_engine, GazeStateMachine
except Exception:
    multimodal_engine = None
    GazeStateMachine = None

try:
    from app.services.proctoring_service import proctor_manager
except Exception:
    proctor_manager = None

# Per-candidate-session gaze FSMs (keyed by ai_session ObjectId string)
_candidate_gaze_fsms = {}

router = APIRouter(prefix="/api/candidate-interview", tags=["Candidate AI Interview"])

TECH_CUTOFF = 70.0


# ── Schemas ───────────────────────────────────────────

class CandidateStartRequest(BaseModel):
    candidate_name: str


class CandidateAnswerRequest(BaseModel):
    question_id: str
    answer_text: str
    code_text: Optional[str] = None
    code_language: Optional[str] = None


# ── Public URL helper ─────────────────────────────────

@router.get("/public-url")
async def get_public_url():
    """Return configured public URL so frontend can generate shareable links."""
    return {"public_url": settings.PUBLIC_URL or settings.FRONTEND_URL}


# ── Helpers ───────────────────────────────────────────

async def _get_candidate_by_token(token: str):
    db = get_database()
    candidate = await db.candidates.find_one({"unique_token": token})
    if not candidate:
        raise HTTPException(status_code=404, detail="Invalid interview link")
    return candidate


async def _get_session_for_candidate(candidate: dict):
    db = get_database()
    session = await db.interview_sessions.find_one(
        {"_id": ObjectId(candidate["interview_session_id"])}
    )
    if not session:
        raise HTTPException(status_code=404, detail="Interview session not found")
    return session


# ── GET /{token}/info ─────────────────────────────────

@router.get("/{token}/info")
async def get_interview_info(token: str):
    """Return session info so the candidate sees job role, company, etc."""
    db = get_database()
    candidate = await _get_candidate_by_token(token)
    session = await _get_session_for_candidate(candidate)

    ai_session = await db.candidate_ai_sessions.find_one(
        {"candidate_token": token}
    )

    ai_session_status = ai_session.get("status") if ai_session else None

    # Auto-complete if in_progress but time has expired (candidate closed browser)
    if ai_session and ai_session_status == "in_progress":
        started_at = ai_session.get("started_at", ai_session.get("created_at"))
        duration = ai_session.get("duration_minutes", session.get("duration_minutes", 30))
        proc_total = ai_session.get("processing_time_total", 0.0)
        time_status = ai_service.check_time_status(started_at, duration, proc_total)
        if time_status and time_status.get("is_expired"):
            try:
                await _complete_candidate_session(
                    db, ai_session, candidate, ai_session.get("responses", [])
                )
                ai_session_status = "completed"
            except Exception:
                pass

    return {
        "job_role": session.get("job_role", ""),
        "company_name": session.get("company_name", ""),
        "duration_minutes": session.get("duration_minutes", 30),
        "scheduled_time": session.get("scheduled_time"),
        "job_description": session.get("job_description", ""),
        "experience_level": session.get("experience_level", ""),
        "candidate_email": candidate.get("email", ""),
        "candidate_status": candidate.get("status", "invited"),
        "ai_session_id": str(ai_session["_id"]) if ai_session else None,
        "ai_session_status": ai_session_status,
        "interview_session_id": candidate.get("interview_session_id", ""),
    }


# ── POST /{token}/start ──────────────────────────────

@router.post("/{token}/start")
async def start_candidate_interview(token: str, body: CandidateStartRequest):
    """Start an AI-conducted interview for the candidate."""
    db = get_database()
    start_ts = time.time()
    candidate = await _get_candidate_by_token(token)
    session = await _get_session_for_candidate(candidate)

    # Check if already has an active/completed session
    existing = await db.candidate_ai_sessions.find_one({"candidate_token": token})
    if existing and existing.get("status") == "completed":
        raise HTTPException(status_code=400, detail="Interview already completed")
    if existing and existing.get("status") == "in_progress":
        # Resume: return current question
        current_q_index = len(existing.get("responses", []))
        if current_q_index < len(existing.get("questions", [])):
            q = existing["questions"][current_q_index]
            started_at = existing.get("started_at", existing["created_at"])
            duration = existing.get("duration_minutes", session.get("duration_minutes", 30))
            proc_total = existing.get("processing_time_total", 0.0)
            return {
                "session_id": str(existing["_id"]),
                "interview_session_id": candidate.get("interview_session_id", ""),
                "question": {
                    "question_id": q["question_id"],
                    "question": q["question"],
                    "difficulty": q["difficulty"],
                    "question_number": current_q_index + 1,
                    "round": q.get("round", "Technical"),
                    "is_coding": q.get("is_coding", False),
                },
                "resumed": True,
                "round": existing.get("current_round", "Technical"),
                "duration_minutes": duration,
                "time_status": ai_service.check_time_status(started_at, duration, proc_total),
            }

    job_role = session.get("job_role", "General")
    job_description = session.get("job_description", "")
    experience_level = session.get("experience_level", "")
    duration_minutes = session.get("duration_minutes", 30)
    difficulty = "medium"

    # Analyze JD if provided
    jd_analysis = None
    if job_description:
        jd_analysis = await ai_service.analyze_job_description(job_description, job_role)

    # ── Collect questions from other candidates in the same session ──
    # This ensures each candidate gets different questions for a fair assessment
    other_candidate_questions = []
    try:
        other_cursor = db.candidate_ai_sessions.find(
            {
                "interview_session_id": candidate["interview_session_id"],
                "candidate_token": {"$ne": token},
            },
            {"questions.question": 1},
        )
        async for other_sess in other_cursor:
            for q in other_sess.get("questions", []):
                if q.get("question") and q["question"] not in other_candidate_questions:
                    other_candidate_questions.append(q["question"])
    except Exception:
        pass  # Non-critical

    # Also check if this candidate has past completed sessions (re-take scenario)
    past_candidate_questions = []
    try:
        past_sessions = db.candidate_ai_sessions.find(
            {
                "candidate_email": candidate.get("email", ""),
                "status": "completed",
            },
            {"questions.question": 1},
        ).sort("created_at", -1).limit(3)
        async for past in past_sessions:
            for q in past.get("questions", []):
                if q.get("question") and q["question"] not in past_candidate_questions:
                    past_candidate_questions.append(q["question"])
    except Exception:
        pass

    # Merge: prioritize avoiding other-candidate questions + past questions
    avoid_questions = other_candidate_questions + past_candidate_questions

    # Generate first question
    # Use token as session_id for tracking (unique per candidate, available before DB insert)
    q_data = await ai_service.generate_question(
        job_role, difficulty, avoid_questions,
        round_type="Technical",
        job_description=job_description,
        experience_level=experience_level,
        jd_analysis=jd_analysis,
        session_id=token,
    )
    question_id = str(uuid.uuid4())

    started_at = datetime.utcnow()
    startup_processing = time.time() - start_ts

    ai_session_doc = {
        "candidate_token": token,
        "candidate_id": str(candidate["_id"]),
        "candidate_name": body.candidate_name,
        "candidate_email": candidate.get("email", ""),
        "interview_session_id": candidate["interview_session_id"],
        "job_role": job_role,
        "job_description": job_description,
        "experience_level": experience_level,
        "jd_analysis": jd_analysis,
        "difficulty": difficulty,
        "status": "in_progress",
        "current_round": "Technical",
        "duration_minutes": duration_minutes,
        "questions": [
            {
                "question_id": question_id,
                "question": q_data["question"],
                "ideal_answer": q_data.get("ideal_answer", ""),
                "keywords": q_data.get("keywords", []),
                "difficulty": difficulty,
                "round": "Technical",
                "is_coding": q_data.get("is_coding", False),
            }
        ],
        "responses": [],
        "technical_score": None,
        "hr_score": None,
        "processing_time_total": startup_processing,
        "proctoring": {
            "gaze_violations": 0,
            "multi_person_alerts": 0,
            "tab_switches": 0,
            "total_away_time_sec": 0,
            "suspicious_objects_detected": 0,
            "identity_mismatches": 0,
            "violation_log": [],
        },
        "created_at": started_at,
        "started_at": started_at,
    }

    result = await db.candidate_ai_sessions.insert_one(ai_session_doc)
    session_id = str(result.inserted_id)

    # Initialise proctoring session for identity verification & risk scoring
    if proctor_manager is not None:
        proctor_manager.get_or_create(session_id)

    # Update candidate status
    await db.candidates.update_one(
        {"_id": candidate["_id"]},
        {"$set": {"status": "joined", "joined_at": datetime.utcnow(), "name": body.candidate_name}},
    )

    return {
        "session_id": session_id,
        "interview_session_id": candidate.get("interview_session_id", ""),
        "question": {
            "question_id": question_id,
            "question": q_data["question"],
            "difficulty": difficulty,
            "question_number": 1,
            "round": "Technical",
            "is_coding": q_data.get("is_coding", False),
        },
        "resumed": False,
        "round": "Technical",
        "duration_minutes": duration_minutes,
        "time_status": ai_service.check_time_status(started_at, duration_minutes, startup_processing),
    }


# ── POST /{token}/answer (parallel eval + question gen) ──

@router.post("/{token}/answer")
async def submit_candidate_answer(token: str, body: CandidateAnswerRequest):
    """Evaluate answer and return next question — optimized with parallel operations."""
    db = get_database()
    processing_start = time.time()
    candidate = await _get_candidate_by_token(token)
    ai_session = await db.candidate_ai_sessions.find_one({"candidate_token": token})

    if not ai_session:
        raise HTTPException(status_code=404, detail="Interview not started")
    if ai_session["status"] == "completed":
        raise HTTPException(status_code=400, detail="Interview already completed")

    # Collect questions from other candidates in the same session for diversity
    other_candidate_questions = []
    try:
        other_cursor = db.candidate_ai_sessions.find(
            {
                "interview_session_id": ai_session["interview_session_id"],
                "candidate_token": {"$ne": token},
            },
            {"questions.question": 1},
        )
        async for other_sess in other_cursor:
            for q in other_sess.get("questions", []):
                if q.get("question") and q["question"] not in other_candidate_questions:
                    other_candidate_questions.append(q["question"])
    except Exception:
        pass

    # Check time (using active time)
    started_at = ai_session.get("started_at", ai_session["created_at"])
    duration = ai_session.get("duration_minutes", 30)
    proc_total = ai_session.get("processing_time_total", 0.0)
    time_status = ai_service.check_time_status(started_at, duration, proc_total)

    # Find matching question
    q_doc = next((q for q in ai_session["questions"] if q["question_id"] == body.question_id), None)
    if not q_doc:
        raise HTTPException(status_code=404, detail="Question not found")

    is_coding = q_doc.get("is_coding", False)
    answer_text = body.answer_text
    next_q_data = None  # Will be set in parallel for non-coding path

    # Track how many coding questions have been asked so far
    coding_count = sum(1 for q in ai_session["questions"] if q.get("is_coding"))

    # ── Evaluate ──────────────────────────────────────
    if is_coding and body.code_text:
        code_eval = await ai_service.evaluate_code(
            question=q_doc["question"],
            ideal_answer=q_doc.get("ideal_answer", ""),
            submitted_code=body.code_text,
            language=body.code_language or "python",
        )
        evaluation = {
            "content_score": code_eval.get("correctness_score", 0),
            "keyword_score": code_eval.get("quality_score", 0),
            "depth_score": code_eval.get("efficiency_score", 0),
            "communication_score": code_eval.get("quality_score", 0),
            "confidence_score": 50.0,
            "overall_score": code_eval.get("overall_score", 0),
            "similarity_score": code_eval.get("correctness_score", 0),
            "keyword_coverage": 0,
            "keywords_matched": [],
            "keywords_missed": [],
            "feedback": code_eval.get("feedback", ""),
            "answer_strength": "strong" if code_eval.get("overall_score", 0) >= 80 else (
                "moderate" if code_eval.get("overall_score", 0) >= 50 else "weak"
            ),
            "code_evaluation": code_eval,
        }

        # Build a verbal follow-up about the submitted code logic
        next_q_data = ai_service.build_code_followup_question(
            original_question=q_doc["question"],
            submitted_code=body.code_text,
            code_eval=code_eval,
            language=body.code_language or "python",
            difficulty=ai_session.get("difficulty", "medium"),
        )
    else:
        # Two-phase: instant score first
        instant_eval = ai_service.evaluate_answer_instant(
            question=q_doc["question"],
            ideal_answer=q_doc.get("ideal_answer", ""),
            candidate_answer=answer_text,
            keywords=q_doc.get("keywords", []),
            round_type=q_doc.get("round", "Technical"),
        )

        # Parallel: deep evaluation + next question generation
        current_round = ai_session.get("current_round", "Technical")
        all_responses = ai_session.get("responses", [])
        last_score = instant_eval.get("overall_score", 50)
        next_difficulty = ai_service.determine_next_difficulty(
            last_score, ai_session.get("difficulty", "medium")
        )
        prev_questions = [q["question"] for q in ai_session["questions"]] + other_candidate_questions
        prev_answers = [r["answer_text"] for r in all_responses] + [answer_text]

        deep_eval_task = ai_service.evaluate_answer_deep(
            question=q_doc["question"],
            ideal_answer=q_doc.get("ideal_answer", ""),
            candidate_answer=answer_text,
            keywords=q_doc.get("keywords", []),
            instant_result=instant_eval,
            round_type=q_doc.get("round", "Technical"),
        )

        next_q_task = ai_service.generate_question(
            job_role=ai_session["job_role"],
            difficulty=next_difficulty,
            previous_questions=prev_questions,
            round_type=current_round,
            job_description=ai_session.get("job_description", ""),
            experience_level=ai_session.get("experience_level", ""),
            previous_answers=prev_answers,
            last_score=last_score,
            jd_analysis=ai_session.get("jd_analysis"),
            coding_count=coding_count,
            session_id=str(ai_session["_id"]),
        )

        try:
            deep_eval, next_q_data = await asyncio.gather(deep_eval_task, next_q_task)
            evaluation = deep_eval
        except Exception:
            evaluation = instant_eval
            next_q_data = None

    # Save response
    response_doc = {
        "question_id": body.question_id,
        "answer_text": answer_text,
        "code_text": body.code_text,
        "evaluation": evaluation,
        "answered_at": datetime.utcnow(),
    }

    answered_count = len(ai_session.get("responses", [])) + 1
    processing_time = time.time() - processing_start
    proc_total += processing_time

    await db.candidate_ai_sessions.update_one(
        {"_id": ai_session["_id"]},
        {
            "$push": {"responses": response_doc},
            "$inc": {"processing_time_total": processing_time},
        },
    )

    # Re-check time with updated processing overhead
    time_status = ai_service.check_time_status(started_at, duration, proc_total)
    all_responses = ai_session.get("responses", []) + [response_doc]

    # ── Time expired → end interview ──
    if time_status["is_expired"]:
        await _complete_candidate_session(db, ai_session, candidate, all_responses)
        return {
            "evaluation": evaluation,
            "is_complete": True,
            "reason": "time_expired",
            "time_status": time_status,
            "next_question": None,
            "session_id": str(ai_session["_id"]),
        }

    current_round = ai_session.get("current_round", "Technical")

    # ── Check round transition: Technical → HR ──
    if current_round == "Technical":
        tech_responses = [
            r for r in all_responses
            if any(
                q.get("round") == "Technical"
                for q in ai_session["questions"]
                if q["question_id"] == r["question_id"]
            )
        ]
        tech_score = ai_service.calculate_round_score(tech_responses)

        tech_time_limit = duration * 0.6
        active_elapsed = time_status["elapsed_minutes"]
        if active_elapsed >= tech_time_limit and len(tech_responses) >= 3:
            if not ai_service.should_proceed_to_hr(tech_score, TECH_CUTOFF):
                await db.candidate_ai_sessions.update_one(
                    {"_id": ai_session["_id"]},
                    {"$set": {
                        "technical_score": tech_score,
                        "status": "completed",
                        "completed_at": datetime.utcnow(),
                        "termination_reason": "technical_score_below_cutoff",
                    }},
                )
                await db.candidates.update_one(
                    {"_id": candidate["_id"]},
                    {"$set": {"status": "completed"}},
                )
                return {
                    "evaluation": evaluation,
                    "is_complete": True,
                    "reason": "technical_cutoff_not_met",
                    "technical_score": tech_score,
                    "time_status": time_status,
                    "next_question": None,
                    "session_id": str(ai_session["_id"]),
                    "message": f"Technical round score ({tech_score}%) is below the {TECH_CUTOFF}% cutoff.",
                }
            else:
                current_round = "HR"
                await db.candidate_ai_sessions.update_one(
                    {"_id": ai_session["_id"]},
                    {"$set": {"current_round": "HR", "technical_score": tech_score}},
                )

                # Need HR question since parallel gen was for Technical round
                if not is_coding:
                    next_q_data = await ai_service.generate_question(
                        job_role=ai_session["job_role"],
                        difficulty=ai_service.determine_next_difficulty(
                            evaluation.get("overall_score", 50), ai_session.get("difficulty", "medium")
                        ),
                        previous_questions=[q["question"] for q in ai_session["questions"]] + other_candidate_questions,
                        round_type="HR",
                        job_description=ai_session.get("job_description", ""),
                        experience_level=ai_session.get("experience_level", ""),
                        previous_answers=[r["answer_text"] for r in all_responses],
                        last_score=evaluation.get("overall_score", 50),
                        jd_analysis=ai_session.get("jd_analysis"),
                        coding_count=coding_count,
                        session_id=str(ai_session["_id"]),
                    )

    # ── Generate next question (if not already done in parallel or via code follow-up) ──
    if not next_q_data:
        last_score = evaluation.get("overall_score", 50)
        next_difficulty = ai_service.determine_next_difficulty(
            last_score, ai_session.get("difficulty", "medium")
        )
        prev_questions = [q["question"] for q in ai_session["questions"]] + other_candidate_questions
        prev_answers = [r["answer_text"] for r in all_responses]

        next_q_data = await ai_service.generate_question(
            job_role=ai_session["job_role"],
            difficulty=next_difficulty,
            previous_questions=prev_questions,
            round_type=current_round,
            job_description=ai_session.get("job_description", ""),
            experience_level=ai_session.get("experience_level", ""),
            previous_answers=prev_answers,
            last_score=last_score,
            jd_analysis=ai_session.get("jd_analysis"),
            coding_count=coding_count,
            session_id=str(ai_session["_id"]),
        )
    else:
        next_difficulty = ai_service.determine_next_difficulty(
            evaluation.get("overall_score", 50), ai_session.get("difficulty", "medium")
        )

    next_qid = str(uuid.uuid4())
    next_q_doc = {
        "question_id": next_qid,
        "question": next_q_data["question"],
        "ideal_answer": next_q_data.get("ideal_answer", ""),
        "keywords": next_q_data.get("keywords", []),
        "difficulty": next_difficulty,
        "round": current_round,
        "is_coding": next_q_data.get("is_coding", False),
    }

    await db.candidate_ai_sessions.update_one(
        {"_id": ai_session["_id"]},
        {
            "$push": {"questions": next_q_doc},
            "$set": {"difficulty": next_difficulty},
        },
    )

    return {
        "evaluation": evaluation,
        "is_complete": False,
        "next_question": {
            "question_id": next_qid,
            "question": next_q_data["question"],
            "difficulty": next_difficulty,
            "question_number": answered_count + 1,
            "round": current_round,
            "is_coding": next_q_data.get("is_coding", False),
            "is_wrap_up": time_status["is_wrap_up"],
        },
        "round": current_round,
        "time_status": time_status,
        "session_id": str(ai_session["_id"]),
    }


# ── GET /{token}/time ────────────────────────────────

@router.get("/{token}/time")
async def check_candidate_time(token: str):
    db = get_database()
    ai_session = await db.candidate_ai_sessions.find_one({"candidate_token": token})
    if not ai_session:
        raise HTTPException(status_code=404, detail="Interview not started")
    started_at = ai_session.get("started_at", ai_session["created_at"])
    duration = ai_session.get("duration_minutes", 30)
    proc_total = ai_session.get("processing_time_total", 0.0)
    time_status = ai_service.check_time_status(started_at, duration, proc_total)

    # Auto-complete if time expired and still in_progress
    if ai_session.get("status") == "in_progress" and time_status.get("is_expired"):
        try:
            candidate = await _get_candidate_by_token(token)
            await _complete_candidate_session(
                db, ai_session, candidate, ai_session.get("responses", [])
            )
            time_status["auto_completed"] = True
        except Exception:
            pass

    return time_status


# ── POST /{token}/end ─────────────────────────────────

@router.post("/{token}/end")
async def end_candidate_interview(token: str):
    db = get_database()
    candidate = await _get_candidate_by_token(token)
    ai_session = await db.candidate_ai_sessions.find_one({"candidate_token": token})
    if not ai_session:
        raise HTTPException(status_code=404, detail="Interview not started")

    all_responses = ai_session.get("responses", [])
    await _complete_candidate_session(db, ai_session, candidate, all_responses)
    return {"detail": "Interview ended", "session_id": str(ai_session["_id"])}


# ── GET /{token}/report ──────────────────────────────

@router.get("/{token}/report")
async def get_candidate_report(token: str):
    """Generate a full report for the candidate (also visible to HR)."""
    db = get_database()
    await _get_candidate_by_token(token)
    ai_session = await db.candidate_ai_sessions.find_one({"candidate_token": token})

    if not ai_session:
        raise HTTPException(status_code=404, detail="Interview not started")

    user_proxy = {"name": ai_session.get("candidate_name", "Candidate")}
    report = await ai_service.generate_report(session=ai_session, user=user_proxy)
    report["candidate_email"] = ai_session.get("candidate_email", "")
    return report


# ── GET /{token}/report/pdf ──────────────────────────

@router.get("/{token}/report/pdf")
async def get_candidate_report_pdf(token: str):
    """Generate and download a PDF performance report for the candidate."""
    db = get_database()
    await _get_candidate_by_token(token)
    ai_session = await db.candidate_ai_sessions.find_one({"candidate_token": token})

    if not ai_session:
        raise HTTPException(status_code=404, detail="Interview not started")

    try:
        user_proxy = {"name": ai_session.get("candidate_name", "Candidate")}
        report = await ai_service.generate_report(session=ai_session, user=user_proxy)
        report["candidate_email"] = ai_session.get("candidate_email", "")
        pdf_bytes = generate_pdf_report(report)
    except Exception as e:
        print(f"[PDF] Error generating PDF for token {token[:8]}: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate PDF report")

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=report_{token[:8]}.pdf"},
    )


# ── GET /session/{session_id}/progress ────────────────

@router.get("/session/{session_id}/progress")
async def get_session_progress(session_id: str):
    """Return progress of all candidates for HR monitoring."""
    db = get_database()
    cursor = db.candidate_ai_sessions.find({"interview_session_id": session_id})
    results = []
    async for ai_sess in cursor:
        responses = ai_sess.get("responses", [])
        answered = len(responses)

        avg_scores = {}
        if responses:
            for key in ["content_score", "communication_score", "overall_score", "keyword_coverage"]:
                vals = [r.get("evaluation", {}).get(key, 0) for r in responses]
                avg_scores[key] = round(sum(vals) / len(vals), 1)
        else:
            avg_scores = {
                "content_score": 0,
                "communication_score": 0,
                "overall_score": 0,
                "keyword_coverage": 0,
            }

        questions = ai_sess.get("questions", [])
        current_question = None
        if answered < len(questions):
            current_question = questions[answered].get("question", "")

        latest_eval = responses[-1].get("evaluation", {}) if responses else None

        # Time status (with active-time tracking)
        started_at = ai_sess.get("started_at", ai_sess.get("created_at"))
        duration = ai_sess.get("duration_minutes", 30)
        proc_total = ai_sess.get("processing_time_total", 0.0)
        time_status = ai_service.check_time_status(started_at, duration, proc_total) if started_at else None

        # ── Auto-complete expired in_progress sessions ──
        # If a candidate started the interview and closed the browser, the status
        # remains "in_progress" forever. Detect this by checking if time has expired
        # and auto-complete the session.
        session_status = ai_sess.get("status", "unknown")
        if session_status == "in_progress" and time_status and time_status.get("is_expired"):
            try:
                candidate = await db.candidates.find_one({"unique_token": ai_sess.get("candidate_token")})
                await _complete_candidate_session(db, ai_sess, candidate or {}, responses)
                session_status = "completed"
            except Exception as e:
                print(f"Auto-complete failed for {ai_sess.get('candidate_email')}: {e}")

        results.append({
            "candidate_name": ai_sess.get("candidate_name", "Unknown"),
            "candidate_email": ai_sess.get("candidate_email", ""),
            "status": session_status,
            "current_round": ai_sess.get("current_round", "Technical"),
            "answered": answered,
            "total_questions": answered,
            "avg_scores": avg_scores,
            "current_question": current_question,
            "latest_evaluation": latest_eval,
            "started_at": ai_sess.get("created_at"),
            "completed_at": ai_sess.get("completed_at"),
            "session_id": str(ai_sess["_id"]),
            "candidate_token": ai_sess.get("candidate_token", ""),
            "technical_score": ai_sess.get("technical_score"),
            "hr_score": ai_sess.get("hr_score"),
            "termination_reason": ai_sess.get("termination_reason"),
            "time_status": time_status,
            "proctoring": ai_sess.get("proctoring", {}),
        })

    return results


# ── GET /session/{session_id}/duplicate-questions ─────

@router.get("/session/{session_id}/duplicate-questions")
async def get_duplicate_questions(session_id: str):
    """Find questions that were asked to multiple candidates in the same session."""
    db = get_database()
    cursor = db.candidate_ai_sessions.find({"interview_session_id": session_id})

    # Collect: question_text -> list of {candidate_name, candidate_email, round, difficulty}
    question_map = {}  # question_text -> [candidate info]
    async for ai_sess in cursor:
        candidate_name = ai_sess.get("candidate_name", "Unknown")
        candidate_email = ai_sess.get("candidate_email", "")
        for q in ai_sess.get("questions", []):
            q_text = q.get("question", "").strip()
            if not q_text:
                continue
            q_lower = q_text.lower()
            # Find or create entry using case-insensitive matching
            matched_key = None
            for existing_key in question_map:
                if existing_key.lower() == q_lower:
                    matched_key = existing_key
                    break
            if matched_key is None:
                matched_key = q_text
                question_map[matched_key] = []
            question_map[matched_key].append({
                "candidate_name": candidate_name,
                "candidate_email": candidate_email,
                "round": q.get("round", "Technical"),
                "difficulty": q.get("difficulty", "medium"),
            })

    # Filter to only questions asked to 2+ candidates
    duplicates = []
    for question_text, candidates_list in question_map.items():
        if len(candidates_list) >= 2:
            # Deduplicate by email (same candidate shouldn't appear twice for same question)
            seen_emails = set()
            unique_candidates = []
            for c in candidates_list:
                if c["candidate_email"] not in seen_emails:
                    seen_emails.add(c["candidate_email"])
                    unique_candidates.append(c)
            if len(unique_candidates) >= 2:
                duplicates.append({
                    "question": question_text,
                    "candidate_count": len(unique_candidates),
                    "candidates": unique_candidates,
                })

    # Sort by number of candidates (most duplicated first)
    duplicates.sort(key=lambda x: x["candidate_count"], reverse=True)

    return {
        "total_duplicate_questions": len(duplicates),
        "duplicates": duplicates,
    }


# ── Helpers ───────────────────────────────────────────

async def _complete_candidate_session(db, ai_session: dict, candidate: dict, all_responses: list):
    """Mark candidate session as completed and compute round scores."""
    questions = ai_session.get("questions", [])

    tech_responses = [
        r for r in all_responses
        if any(q.get("round") == "Technical" for q in questions if q["question_id"] == r["question_id"])
    ]
    hr_responses = [
        r for r in all_responses
        if any(q.get("round") == "HR" for q in questions if q["question_id"] == r["question_id"])
    ]

    tech_score = ai_service.calculate_round_score(tech_responses)
    hr_score = ai_service.calculate_round_score(hr_responses)

    update_fields = {
        "status": "completed",
        "completed_at": datetime.utcnow(),
        "technical_score": tech_score,
        "hr_score": hr_score,
    }

    # Save proctoring integrity report before cleanup
    session_id = str(ai_session["_id"])
    if proctor_manager is not None:
        proctor_session = proctor_manager.get(session_id)
        if proctor_session is not None:
            try:
                integrity_report = proctor_session.generate_report()
                update_fields["proctoring.integrity_report"] = integrity_report
                update_fields["proctoring.identity_mismatches"] = integrity_report.get("identity", {}).get("mismatches", 0)
                update_fields["proctoring.suspicious_objects_detected"] = integrity_report.get("proctoring_stats", {}).get("suspicious_objects_detected", 0)
                update_fields["proctoring.risk_verdict"] = integrity_report.get("final_verdict", "UNKNOWN")
                update_fields["proctoring.integrity_score"] = integrity_report.get("integrity_score", 100)
            except Exception:
                pass

    await db.candidate_ai_sessions.update_one(
        {"_id": ai_session["_id"]},
        {"$set": update_fields},
    )
    await db.candidates.update_one(
        {"_id": candidate["_id"]},
        {"$set": {"status": "completed"}},
    )

    # Clean up in-memory session data to prevent memory leaks
    try:
        ai_service.cleanup_session(session_id)
        from app.services.rl_adaptation_service import rl_adaptation_service
        rl_adaptation_service.cleanup_session(session_id)
        # Clean up gaze FSM for this candidate session
        _candidate_gaze_fsms.pop(session_id, None)
        # Clean up proctoring session
        if proctor_manager is not None:
            proctor_manager.remove(session_id)
    except Exception:
        pass


# ── Proctoring Violation Logging ──────────────────────

class CandidateProctoringViolationRequest(BaseModel):
    violation_type: str  # "gaze_away", "multi_person", "tab_switch"
    duration_sec: Optional[float] = 0
    details: Optional[str] = ""


@router.post("/{token}/proctoring/violation")
async def log_candidate_proctoring_violation(token: str, body: CandidateProctoringViolationRequest):
    """Log a proctoring violation for a candidate interview (token-based, no auth)."""
    db = get_database()
    await _get_candidate_by_token(token)
    ai_session = await db.candidate_ai_sessions.find_one({"candidate_token": token})
    if not ai_session:
        raise HTTPException(status_code=404, detail="Interview not started")

    violation_entry = {
        "type": body.violation_type,
        "timestamp": datetime.utcnow().isoformat(),
        "duration_sec": body.duration_sec or 0,
        "details": body.details or "",
    }

    inc_fields = {}
    if body.violation_type == "gaze_away":
        inc_fields["proctoring.gaze_violations"] = 1
        inc_fields["proctoring.total_away_time_sec"] = body.duration_sec or 0
    elif body.violation_type == "multi_person":
        inc_fields["proctoring.multi_person_alerts"] = 1
    elif body.violation_type == "tab_switch":
        inc_fields["proctoring.tab_switches"] = 1

    update_ops = {"$push": {"proctoring.violation_log": violation_entry}}
    if inc_fields:
        update_ops["$inc"] = inc_fields

    await db.candidate_ai_sessions.update_one(
        {"_id": ai_session["_id"]},
        update_ops,
    )

    return {"status": "logged"}


@router.get("/{token}/proctoring/summary")
async def get_candidate_proctoring_summary(token: str):
    """Get proctoring summary for a candidate interview."""
    db = get_database()
    await _get_candidate_by_token(token)
    ai_session = await db.candidate_ai_sessions.find_one({"candidate_token": token})
    if not ai_session:
        raise HTTPException(status_code=404, detail="Interview not started")

    proctoring = ai_session.get("proctoring", {})
    gaze_v = proctoring.get("gaze_violations", 0)
    multi_p = proctoring.get("multi_person_alerts", 0)
    tab_s = proctoring.get("tab_switches", 0)
    away_time = proctoring.get("total_away_time_sec", 0)
    suspicious_objs = proctoring.get("suspicious_objects_detected", 0)
    identity_mismatches = proctoring.get("identity_mismatches", 0)

    total_violations = gaze_v + multi_p + tab_s + suspicious_objs + identity_mismatches
    integrity_score = max(0, 100 - (gaze_v * 3) - (multi_p * 15) - (tab_s * 10)
                         - (away_time * 0.5) - (suspicious_objs * 10) - (identity_mismatches * 25))

    return {
        "gaze_violations": gaze_v,
        "multi_person_alerts": multi_p,
        "tab_switches": tab_s,
        "total_away_time_sec": round(away_time, 1),
        "suspicious_objects_detected": suspicious_objs,
        "identity_mismatches": identity_mismatches,
        "total_violations": total_violations,
        "integrity_score": round(integrity_score, 1),
        "violation_log": proctoring.get("violation_log", [])[-20:],
    }


# ── Proctoring: Live Gaze & Person Detection ─────────

class CandidateGazeAnalysisRequest(BaseModel):
    video_frame: Optional[str] = None  # base64-encoded JPEG frame


@router.post("/{token}/proctoring/analyze")
async def analyze_candidate_frame(token: str, body: CandidateGazeAnalysisRequest):
    """
    Analyze a video frame for gaze direction, multi-person detection,
    identity verification, suspicious objects, and risk scoring.
    """
    db = get_database()
    candidate = await _get_candidate_by_token(token)
    ai_session = await db.candidate_ai_sessions.find_one({"candidate_token": token})
    if not ai_session:
        raise HTTPException(status_code=404, detail="Interview not started")

    session_id = str(ai_session["_id"])

    # Ensure a GazeStateMachine exists for this candidate session
    if session_id not in _candidate_gaze_fsms:
        if GazeStateMachine is None:
            return {"gaze": {"state": "ATTENTIVE", "show_warning": False}, "person_count": 0}
        _candidate_gaze_fsms[session_id] = GazeStateMachine()

    gaze_fsm = _candidate_gaze_fsms[session_id]
    gaze_state_output = None
    person_count = 0
    proctor_result = None

    if body.video_frame:
        # ── Run full proctoring pipeline (identity + objects + risk) ──
        if proctor_manager is not None:
            proctor_session = proctor_manager.get_or_create(session_id)
            try:
                proctor_result = proctor_session.process_frame(body.video_frame)
                person_count = proctor_result.get("person_count", 0)
            except Exception as exc:
                print(f"[PROCTOR] Exception: {exc}")

        # ── Run gaze FSM (existing logic — only for eye_contact_score → FSM) ──
        # Person count already obtained from proctor_result above; no need to call detect_persons
        if multimodal_engine is not None:
            try:
                visual = multimodal_engine.analyze_face(body.video_frame)

                eye_contact_score = visual.get("eye_contact_score")
                if eye_contact_score is not None:
                    gaze_state_output = gaze_fsm.update(eye_contact_score)
                else:
                    gaze_state_output = gaze_fsm.check_staleness()
            except Exception as exc:
                print(f"[CANDIDATE GAZE] Exception in video processing: {exc}")
                gaze_state_output = gaze_fsm.check_staleness()
        else:
            gaze_state_output = gaze_fsm.check_staleness()
    else:
        gaze_state_output = gaze_fsm.check_staleness()

    response = {
        "gaze": gaze_state_output or {
            "state": gaze_fsm.state.value,
            "show_warning": gaze_fsm.show_warning,
        },
        "person_count": person_count,
    }

    # Attach proctoring data if available
    if proctor_result:
        response["identity"] = proctor_result.get("identity")
        response["suspicious_objects"] = proctor_result.get("suspicious_objects", [])
        response["face_absent"] = proctor_result.get("face_absent", False)
        response["attention"] = proctor_result.get("attention")
        response["risk"] = proctor_result.get("risk")

        # Persist proctoring detections to DB
        proctor_update = {}
        suspicious_objs = proctor_result.get("suspicious_objects", [])
        if suspicious_objs:
            for obj in suspicious_objs:
                proctor_update.setdefault("$push", {})["proctoring.violation_log"] = {
                    "type": "suspicious_object",
                    "timestamp": datetime.utcnow().isoformat(),
                    "details": f"Detected: {obj.get('type', 'unknown')}",
                }
            proctor_update.setdefault("$inc", {})["proctoring.suspicious_objects_detected"] = len(suspicious_objs)

        identity = proctor_result.get("identity")
        if identity is not None and identity.get("verified") is False:
            proctor_update.setdefault("$inc", {})["proctoring.identity_mismatches"] = 1
            proctor_update.setdefault("$push", {})["proctoring.violation_log"] = {
                "type": "identity_mismatch",
                "timestamp": datetime.utcnow().isoformat(),
                "details": f"Person change detected (similarity: {identity.get('similarity', 0):.3f})",
            }

        if proctor_update:
            await db.candidate_ai_sessions.update_one(
                {"_id": ai_session["_id"]},
                proctor_update,
            )

    return response


# ── Proctoring: Face Registration ─────────────────────

class CandidateFaceRegisterRequest(BaseModel):
    video_frame: str  # base64-encoded JPEG


@router.post("/{token}/proctoring/register-face")
async def register_candidate_face(token: str, body: CandidateFaceRegisterRequest):
    """Register a face frame for identity verification baseline.

    Call 5-10 times at the start of the interview to build a reference embedding.
    """
    db = get_database()
    await _get_candidate_by_token(token)
    ai_session = await db.candidate_ai_sessions.find_one({"candidate_token": token})
    if not ai_session:
        raise HTTPException(status_code=404, detail="Interview not started")

    session_id = str(ai_session["_id"])

    if proctor_manager is None:
        return {"registered": False, "message": "Proctoring service unavailable"}

    proctor_session = proctor_manager.get_or_create(session_id)
    result = proctor_session.register_face(body.video_frame)
    return result


# ── Proctoring: Integrity Report ──────────────────────

@router.get("/{token}/proctoring/integrity-report")
async def get_candidate_integrity_report(token: str):
    """Generate a comprehensive integrity report for this candidate's interview."""
    db = get_database()
    await _get_candidate_by_token(token)
    ai_session = await db.candidate_ai_sessions.find_one({"candidate_token": token})
    if not ai_session:
        raise HTTPException(status_code=404, detail="Interview not started")

    session_id = str(ai_session["_id"])

    if proctor_manager is None:
        return {"error": "Proctoring service unavailable"}

    proctor_session = proctor_manager.get(session_id)
    if proctor_session is None:
        # Session already cleaned up — return stored proctoring data
        proctoring = ai_session.get("proctoring", {})
        return {
            "final_verdict": "UNKNOWN",
            "integrity_score": max(0, 100 - (proctoring.get("gaze_violations", 0) * 3) -
                                   (proctoring.get("multi_person_alerts", 0) * 15) -
                                   (proctoring.get("tab_switches", 0) * 10)),
            "violations": {"total_count": len(proctoring.get("violation_log", []))},
            "message": "Report generated from stored data (session already ended)",
        }

    return proctor_session.generate_report()
