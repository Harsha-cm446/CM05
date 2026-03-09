"""
Mock Interview Router — Optimized Performance Architecture
───────────────────────────────────────────────────────────
  • Two-phase evaluation: instant score → background deep analysis
  • Parallel: evaluate answer + pre-generate next question simultaneously
  • Active-time timer: pauses during AI processing
  • Pre-generation of questions for zero-wait transitions
"""

import asyncio
import time
import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel

from bson import ObjectId
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.core.database import get_database
from app.core.security import get_current_user
from app.models.schemas import MockInterviewStart, QuestionResponse, AnswerSubmit
from app.services.ai_service import ai_service
from app.services.report_service import generate_pdf_report
from app.services.practice_mode_service import practice_mode_service
from app.services.data_collection_service import data_collection_service

try:
    from app.services.proctoring_service import proctor_manager
except Exception:
    proctor_manager = None

router = APIRouter(prefix="/api/mock-interview", tags=["Mock Interview"])

TECH_CUTOFF = 70.0


# ── Start ─────────────────────────────────────────────

@router.post("/start")
async def start_mock_interview(data: MockInterviewStart, user: dict = Depends(get_current_user)):
    db = get_database()
    start_ts = time.time()

    # Analyze JD and GitHub profile in parallel if provided
    jd_analysis = None
    github_profile = None
    tasks = []

    if data.job_description:
        tasks.append(("jd", ai_service.analyze_job_description(
            data.job_description, data.job_role
        )))

    github_username = None
    if data.github_url:
        import re
        gh = data.github_url.strip().rstrip("/")
        m = re.search(r"github\.com/([A-Za-z0-9\-_]+)", gh)
        github_username = m.group(1) if m else (gh if "/" not in gh and "." not in gh else None)
        if github_username:
            tasks.append(("github", data_collection_service.analyze_github_profile(github_username)))

    if tasks:
        results = await asyncio.gather(*[t[1] for t in tasks], return_exceptions=True)
        for (key, _), result in zip(tasks, results):
            if isinstance(result, Exception):
                continue
            if key == "jd":
                jd_analysis = result
            elif key == "github":
                github_profile = result

    # Store GitHub profile in user document for future use
    if github_profile and "error" not in github_profile:
        await db.users.update_one(
            {"_id": user["_id"]},
            {"$set": {"github_profile": github_profile, "github_username": github_username}},
        )

    # Build enriched context from GitHub for question generation
    github_context = ""
    if github_profile and "error" not in github_profile:
        langs = ", ".join(github_profile.get("primary_languages", [])[:5])
        repos = ", ".join([r["name"] for r in github_profile.get("repositories", [])[:5]])
        github_context = f"\nCandidate GitHub: languages={langs}; repos={repos}; stars={github_profile.get('total_stars', 0)}"

    # ── Load stored candidate profile (from Data Collection page) ──
    user_doc = await db.users.find_one({"_id": user["_id"]})
    candidate_profile_context = ""
    stored_profile = user_doc.get("candidate_profile") if user_doc else None
    parsed_resume = user_doc.get("parsed_resume") if user_doc else None

    profile_parts = []
    if parsed_resume:
        skills = parsed_resume.get("skills", [])
        if skills:
            profile_parts.append(f"Resume Skills: {', '.join(skills[:15])}")
        yoe = parsed_resume.get("years_of_experience", 0)
        if yoe:
            profile_parts.append(f"Experience: {yoe} years")
        degrees = parsed_resume.get("degrees", [])
        if degrees:
            profile_parts.append(f"Education: {', '.join(degrees[:3])}")
        certs = parsed_resume.get("certifications", [])
        if certs:
            profile_parts.append(f"Certifications: {', '.join(certs[:5])}")
    elif stored_profile:
        resume_data = stored_profile.get("resume", {})
        skills = resume_data.get("skills", [])
        if skills:
            profile_parts.append(f"Resume Skills: {', '.join(skills[:15])}")
        yoe = resume_data.get("years_of_experience", 0)
        if yoe:
            profile_parts.append(f"Experience: {yoe} years")

    if stored_profile and stored_profile.get("profile_summary"):
        profile_parts.append(stored_profile["profile_summary"])

    if profile_parts:
        candidate_profile_context = "\nCandidate Profile: " + " | ".join(profile_parts)

    session_doc = {
        "user_id": str(user["_id"]),
        "job_role": data.job_role,
        "difficulty": data.difficulty.value,
        "job_description": data.job_description or "",
        "experience_level": data.experience_level or "",
        "jd_analysis": jd_analysis,
        "github_profile": github_profile if github_profile and "error" not in github_profile else None,
        "linkedin_url": data.linkedin_url or "",
        "candidate_profile_context": candidate_profile_context,
        "status": "in_progress",
        "current_round": "Technical",
        "duration_minutes": data.duration_minutes,
        "questions": [],
        "responses": [],
        "current_question_index": 0,
        "technical_score": None,
        "hr_score": None,
        "processing_time_total": 0.0,  # Track cumulative AI processing time
        "proctoring": {
            "gaze_violations": 0,
            "multi_person_alerts": 0,
            "tab_switches": 0,
            "total_away_time_sec": 0,
            "suspicious_objects_detected": 0,
            "identity_mismatches": 0,
            "violation_log": [],
        },
        "created_at": datetime.utcnow(),
        "started_at": datetime.utcnow(),
    }
    result = await db.mock_sessions.insert_one(session_doc)
    session_id = str(result.inserted_id)

    # Initialise proctoring session for identity verification & risk scoring
    if proctor_manager is not None:
        proctor_manager.get_or_create(session_id)

    # ── Fetch questions from user's previous sessions (same role) ──
    # This ensures a returning user gets fresh questions instead of repeats
    prev_session_questions = []
    try:
        past_cursor = db.mock_sessions.find(
            {
                "user_id": str(user["_id"]),
                "job_role": data.job_role,
                "_id": {"$ne": ObjectId(session_id)},
            },
            {"questions.question": 1},
        ).sort("created_at", -1).limit(5)  # Last 5 sessions
        async for past in past_cursor:
            for q in past.get("questions", []):
                if q.get("question") and q["question"] not in prev_session_questions:
                    prev_session_questions.append(q["question"])
    except Exception:
        pass  # Non-critical — proceed without history

    # Generate the first Technical question (enriched with GitHub + profile context)
    enriched_jd = (data.job_description or "") + github_context + candidate_profile_context
    question_data = await ai_service.generate_question(
        job_role=data.job_role,
        difficulty=data.difficulty.value,
        previous_questions=prev_session_questions,
        round_type="Technical",
        job_description=enriched_jd,
        experience_level=data.experience_level or "",
        jd_analysis=jd_analysis,
        candidate_profile_context=candidate_profile_context,
        session_id=session_id,
    )

    question_doc = {
        "question_id": str(uuid.uuid4()),
        "question": question_data["question"],
        "ideal_answer": question_data.get("ideal_answer", ""),
        "keywords": question_data.get("keywords", []),
        "difficulty": data.difficulty.value,
        "round": "Technical",
        "is_coding": question_data.get("is_coding", False),
    }
    await db.mock_sessions.update_one(
        {"_id": ObjectId(session_id)},
        {"$push": {"questions": question_doc}},
    )

    # Track startup processing time
    startup_processing = time.time() - start_ts
    await db.mock_sessions.update_one(
        {"_id": ObjectId(session_id)},
        {"$inc": {"processing_time_total": startup_processing}},
    )

    return {
        "session_id": session_id,
        "question": QuestionResponse(
            question_id=question_doc["question_id"],
            question=question_doc["question"],
            difficulty=question_doc["difficulty"],
            question_number=1,
            round=question_doc["round"],
            is_coding=question_doc["is_coding"],
        ),
        "round": "Technical",
        "duration_minutes": data.duration_minutes,
        "time_status": ai_service.check_time_status(
            session_doc["started_at"], data.duration_minutes, startup_processing
        ),
    }


# ── Submit Answer (optimized: parallel eval + question gen) ──

@router.post("/{session_id}/answer")
async def submit_answer(
    session_id: str,
    answer: AnswerSubmit,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
):
    db = get_database()
    processing_start = time.time()

    session = await db.mock_sessions.find_one({"_id": ObjectId(session_id)})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session["user_id"] != str(user["_id"]):
        raise HTTPException(status_code=403, detail="Not your session")
    # Fetch questions from user's past sessions (same role) for cross-session diversity
    past_session_questions = []
    try:
        past_cursor = db.mock_sessions.find(
            {
                "user_id": str(user["_id"]),
                "job_role": session["job_role"],
                "_id": {"$ne": ObjectId(session_id)},
            },
            {"questions.question": 1},
        ).sort("created_at", -1).limit(5)
        async for past in past_cursor:
            for q in past.get("questions", []):
                if q.get("question") and q["question"] not in past_session_questions:
                    past_session_questions.append(q["question"])
    except Exception:
        pass
    # Check time (using active time)
    started_at = session.get("started_at", session["created_at"])
    duration = session.get("duration_minutes", 20)
    proc_total = session.get("processing_time_total", 0.0)
    time_status = ai_service.check_time_status(started_at, duration, proc_total)

    # Find the question
    question_doc = None
    for q in session["questions"]:
        if q["question_id"] == answer.question_id:
            question_doc = q
            break
    if not question_doc:
        raise HTTPException(status_code=404, detail="Question not found")

    answer_text = answer.answer_text
    is_coding = question_doc.get("is_coding", False)
    next_q_data = None  # Will be set in parallel for non-coding path

    # Track how many coding questions have been asked so far
    coding_count = sum(1 for q in session["questions"] if q.get("is_coding"))

    # ── PHASE 1: Instant evaluation (< 2 seconds) ────
    if is_coding and answer.code_text:
        # Code evaluation still uses LLM
        code_eval = await ai_service.evaluate_code(
            question=question_doc["question"],
            ideal_answer=question_doc["ideal_answer"],
            submitted_code=answer.code_text,
            language=answer.code_language or "python",
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
            original_question=question_doc["question"],
            submitted_code=answer.code_text,
            code_eval=code_eval,
            language=answer.code_language or "python",
            difficulty=session.get("difficulty", "medium"),
        )
    else:
        # Two-phase: get instant score first for fast UX
        instant_eval = ai_service.evaluate_answer_instant(
            question=question_doc["question"],
            ideal_answer=question_doc["ideal_answer"],
            candidate_answer=answer_text,
            keywords=question_doc.get("keywords", []),
            round_type=question_doc.get("round", "Technical"),
        )

        # ── Run deep evaluation + next question generation IN PARALLEL ──
        current_round = session.get("current_round", "Technical")
        all_responses = session.get("responses", [])
        last_score = instant_eval.get("overall_score", 50)
        next_difficulty = ai_service.determine_next_difficulty(
            last_score, session.get("difficulty", "medium")
        )
        prev_questions = [q["question"] for q in session["questions"]] + past_session_questions
        prev_answers = [r["answer_text"] for r in all_responses] + [answer_text]

        # Fire both tasks in parallel
        deep_eval_task = ai_service.evaluate_answer_deep(
            question=question_doc["question"],
            ideal_answer=question_doc["ideal_answer"],
            candidate_answer=answer_text,
            keywords=question_doc.get("keywords", []),
            instant_result=instant_eval,
            round_type=question_doc.get("round", "Technical"),
        )

        next_q_task = ai_service.generate_question(
            job_role=session["job_role"],
            difficulty=next_difficulty,
            previous_questions=prev_questions,
            round_type=current_round,
            job_description=session.get("job_description", ""),
            experience_level=session.get("experience_level", ""),
            previous_answers=prev_answers,
            last_score=last_score,
            jd_analysis=session.get("jd_analysis"),
            candidate_profile_context=session.get("candidate_profile_context", ""),
            coding_count=coding_count,
            session_id=session_id,
        )

        try:
            deep_eval, next_q_data = await asyncio.gather(deep_eval_task, next_q_task)
            evaluation = deep_eval
        except Exception:
            evaluation = instant_eval
            next_q_data = None

    # Save response
    response_doc = {
        "question_id": answer.question_id,
        "answer_text": answer_text,
        "code_text": answer.code_text,
        "evaluation": evaluation,
        "answered_at": datetime.utcnow(),
    }

    current_idx = session["current_question_index"] + 1
    processing_time = time.time() - processing_start
    proc_total += processing_time

    await db.mock_sessions.update_one(
        {"_id": ObjectId(session_id)},
        {
            "$push": {"responses": response_doc},
            "$set": {"current_question_index": current_idx},
            "$inc": {"processing_time_total": processing_time},
        },
    )

    # Re-check time with updated processing overhead
    time_status = ai_service.check_time_status(started_at, duration, proc_total)

    # ── Time expired → end interview ──
    if time_status["is_expired"]:
        await _complete_session(db, session_id, session)
        return {
            "evaluation": evaluation,
            "is_complete": True,
            "reason": "time_expired",
            "time_status": time_status,
            "message": "Interview time has expired. Generating your report.",
        }

    current_round = session.get("current_round", "Technical")
    all_responses = session.get("responses", []) + [response_doc]

    # ── Check round transition: Technical → HR ──
    if current_round == "Technical":
        tech_responses = [
            r for r in all_responses
            if any(
                q.get("round") == "Technical"
                for q in session["questions"]
                if q["question_id"] == r["question_id"]
            )
        ]
        tech_score = ai_service.calculate_round_score(tech_responses)

        tech_time_limit = duration * 0.6
        active_elapsed = time_status["elapsed_minutes"]
        if active_elapsed >= tech_time_limit and len(tech_responses) >= 3:
            if not ai_service.should_proceed_to_hr(tech_score, TECH_CUTOFF):
                await db.mock_sessions.update_one(
                    {"_id": ObjectId(session_id)},
                    {"$set": {
                        "technical_score": tech_score,
                        "status": "completed",
                        "completed_at": datetime.utcnow(),
                        "termination_reason": "technical_score_below_cutoff",
                    }},
                )
                return {
                    "evaluation": evaluation,
                    "is_complete": True,
                    "reason": "technical_cutoff_not_met",
                    "technical_score": tech_score,
                    "time_status": time_status,
                    "message": f"Technical round score ({tech_score}%) is below the {TECH_CUTOFF}% cutoff. Interview ended.",
                }
            else:
                current_round = "HR"
                await db.mock_sessions.update_one(
                    {"_id": ObjectId(session_id)},
                    {"$set": {"current_round": "HR", "technical_score": tech_score}},
                )

                # Need to generate HR question if round changed (next_q_data was for Technical)
                if not is_coding:
                    next_q_data = await ai_service.generate_question(
                        job_role=session["job_role"],
                        difficulty=ai_service.determine_next_difficulty(
                            evaluation.get("overall_score", 50), session.get("difficulty", "medium")
                        ),
                        previous_questions=[q["question"] for q in session["questions"]] + past_session_questions,
                        round_type="HR",
                        job_description=session.get("job_description", ""),
                        experience_level=session.get("experience_level", ""),
                        previous_answers=[r["answer_text"] for r in all_responses],
                        last_score=evaluation.get("overall_score", 50),
                        jd_analysis=session.get("jd_analysis"),
                        candidate_profile_context=session.get("candidate_profile_context", ""),
                        coding_count=coding_count,
                        session_id=session_id,
                    )

    # ── Generate next question (if not already done in parallel or via code follow-up) ──
    if not next_q_data:
        last_score = evaluation.get("overall_score", 50)
        next_difficulty = ai_service.determine_next_difficulty(
            last_score, session.get("difficulty", "medium")
        )
        prev_questions = [q["question"] for q in session["questions"]] + past_session_questions
        prev_answers = [r["answer_text"] for r in all_responses]

        next_q_data = await ai_service.generate_question(
            job_role=session["job_role"],
            difficulty=next_difficulty,
            previous_questions=prev_questions,
            round_type=current_round,
            job_description=session.get("job_description", ""),
            experience_level=session.get("experience_level", ""),
            previous_answers=prev_answers,
            last_score=last_score,
            jd_analysis=session.get("jd_analysis"),
            candidate_profile_context=session.get("candidate_profile_context", ""),
            coding_count=coding_count,
            session_id=session_id,
        )
    else:
        next_difficulty = ai_service.determine_next_difficulty(
            evaluation.get("overall_score", 50), session.get("difficulty", "medium")
        )

    next_question_doc = {
        "question_id": str(uuid.uuid4()),
        "question": next_q_data["question"],
        "ideal_answer": next_q_data.get("ideal_answer", ""),
        "keywords": next_q_data.get("keywords", []),
        "difficulty": next_difficulty,
        "round": current_round,
        "is_coding": next_q_data.get("is_coding", False),
    }
    await db.mock_sessions.update_one(
        {"_id": ObjectId(session_id)},
        {
            "$push": {"questions": next_question_doc},
            "$set": {"difficulty": next_difficulty},
        },
    )

    return {
        "evaluation": evaluation,
        "next_question": QuestionResponse(
            question_id=next_question_doc["question_id"],
            question=next_question_doc["question"],
            difficulty=next_question_doc["difficulty"],
            question_number=current_idx + 1,
            round=current_round,
            is_coding=next_question_doc["is_coding"],
            is_wrap_up=time_status["is_wrap_up"],
        ),
        "is_complete": False,
        "round": current_round,
        "time_status": time_status,
    }


# ── Time Check ────────────────────────────────────────

@router.get("/{session_id}/time")
async def check_time(session_id: str, user: dict = Depends(get_current_user)):
    db = get_database()
    session = await db.mock_sessions.find_one({"_id": ObjectId(session_id)})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    started_at = session.get("started_at", session["created_at"])
    duration = session.get("duration_minutes", 20)
    proc_total = session.get("processing_time_total", 0.0)
    return ai_service.check_time_status(started_at, duration, proc_total)


# ── Force End ─────────────────────────────────────────

@router.post("/{session_id}/end")
async def end_interview(session_id: str, user: dict = Depends(get_current_user)):
    db = get_database()
    session = await db.mock_sessions.find_one({"_id": ObjectId(session_id)})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session["user_id"] != str(user["_id"]):
        raise HTTPException(status_code=403, detail="Not your session")

    await _complete_session(db, session_id, session)
    return {"detail": "Interview ended", "session_id": session_id}


# ── Report ────────────────────────────────────────────

@router.get("/{session_id}/report")
async def get_report(session_id: str, user: dict = Depends(get_current_user)):
    if not ObjectId.is_valid(session_id):
        raise HTTPException(status_code=400, detail="Invalid session ID")
    db = get_database()
    session = await db.mock_sessions.find_one({"_id": ObjectId(session_id)})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session["user_id"] != str(user["_id"]):
        raise HTTPException(status_code=403, detail="Not your session")

    report = await ai_service.generate_report(session=session, user=user)
    return report


@router.get("/{session_id}/report/pdf")
async def get_report_pdf(session_id: str, user: dict = Depends(get_current_user)):
    if not ObjectId.is_valid(session_id):
        raise HTTPException(status_code=400, detail="Invalid session ID")
    db = get_database()
    session = await db.mock_sessions.find_one({"_id": ObjectId(session_id)})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session["user_id"] != str(user["_id"]):
        raise HTTPException(status_code=403, detail="Not your session")

    report = await ai_service.generate_report(session=session, user=user)
    pdf_bytes = generate_pdf_report(report)

    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=interview_report_{session_id}.pdf"},
    )


# ── History ───────────────────────────────────────────

@router.get("/history/me")
async def my_history(user: dict = Depends(get_current_user)):
    db = get_database()
    cursor = db.mock_sessions.find(
        {"user_id": str(user["_id"])}
    ).sort("created_at", -1).limit(20)

    sessions = []
    async for s in cursor:
        # Compute overall score from round scores
        tech = s.get("technical_score")
        hr = s.get("hr_score")
        scores = [sc for sc in [tech, hr] if sc is not None]
        overall = round(sum(scores) / len(scores), 1) if scores else None

        sessions.append({
            "session_id": str(s["_id"]),
            "job_role": s.get("job_role", ""),
            "difficulty": s.get("difficulty", "medium"),
            "status": s.get("status", ""),
            "current_round": s.get("current_round", "Technical"),
            "questions_answered": len(s.get("responses", [])),
            "technical_score": tech,
            "hr_score": hr,
            "overall_score": overall,
            "created_at": s.get("created_at"),
            "completed_at": s.get("completed_at"),
        })
    return sessions


# ── Proctoring Violation Logging ──────────────────────

class ProctoringViolationRequest(BaseModel):
    violation_type: str  # "gaze_away", "multi_person", "tab_switch"
    duration_sec: Optional[float] = 0
    details: Optional[str] = ""


@router.post("/{session_id}/proctoring/violation")
async def log_proctoring_violation(
    session_id: str,
    body: ProctoringViolationRequest,
    user: dict = Depends(get_current_user),
):
    """Log a proctoring violation (gaze away, multi-person, tab switch)."""
    db = get_database()
    session = await db.mock_sessions.find_one({"_id": ObjectId(session_id)})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session["user_id"] != str(user["_id"]):
        raise HTTPException(status_code=403, detail="Not your session")

    violation_entry = {
        "type": body.violation_type,
        "timestamp": datetime.utcnow().isoformat(),
        "duration_sec": body.duration_sec or 0,
        "details": body.details or "",
    }

    # Increment counters based on violation type
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

    await db.mock_sessions.update_one(
        {"_id": ObjectId(session_id)},
        update_ops,
    )

    return {"status": "logged"}


@router.get("/{session_id}/proctoring/summary")
async def get_proctoring_summary(
    session_id: str,
    user: dict = Depends(get_current_user),
):
    """Get proctoring summary for a session."""
    db = get_database()
    session = await db.mock_sessions.find_one({"_id": ObjectId(session_id)})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session["user_id"] != str(user["_id"]):
        raise HTTPException(status_code=403, detail="Not your session")

    proctoring = session.get("proctoring", {})
    gaze_v = proctoring.get("gaze_violations", 0)
    multi_p = proctoring.get("multi_person_alerts", 0)
    tab_s = proctoring.get("tab_switches", 0)
    away_time = proctoring.get("total_away_time_sec", 0)
    suspicious_objs = proctoring.get("suspicious_objects_detected", 0)
    identity_mismatches = proctoring.get("identity_mismatches", 0)

    total_violations = gaze_v + multi_p + tab_s + suspicious_objs + identity_mismatches

    # Compute integrity score (100 = perfect, deductions for violations)
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
        "violation_log": proctoring.get("violation_log", [])[-20:],  # Last 20
    }


# ── Proctoring: Face Registration ─────────────────────

class MockFaceRegisterRequest(BaseModel):
    video_frame: str  # base64-encoded JPEG


@router.post("/{session_id}/proctoring/register-face")
async def register_mock_face(
    session_id: str,
    body: MockFaceRegisterRequest,
    user: dict = Depends(get_current_user),
):
    """Register a face frame for identity verification baseline during mock interview."""
    db = get_database()
    session = await db.mock_sessions.find_one({"_id": ObjectId(session_id)})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session["user_id"] != str(user["_id"]):
        raise HTTPException(status_code=403, detail="Not your session")

    if proctor_manager is None:
        return {"registered": False, "message": "Proctoring service unavailable"}

    proctor_session = proctor_manager.get_or_create(session_id)
    return proctor_session.register_face(body.video_frame)


# ── Proctoring: Integrity Report ──────────────────────

@router.get("/{session_id}/proctoring/integrity-report")
async def get_mock_integrity_report(
    session_id: str,
    user: dict = Depends(get_current_user),
):
    """Generate a comprehensive integrity report for this mock interview."""
    db = get_database()
    session = await db.mock_sessions.find_one({"_id": ObjectId(session_id)})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session["user_id"] != str(user["_id"]):
        raise HTTPException(status_code=403, detail="Not your session")

    if proctor_manager is None:
        return {"error": "Proctoring service unavailable"}

    proctor_session = proctor_manager.get(session_id)
    if proctor_session is None:
        proctoring = session.get("proctoring", {})
        return {
            "final_verdict": "UNKNOWN",
            "integrity_score": max(0, 100 - (proctoring.get("gaze_violations", 0) * 3) -
                                   (proctoring.get("multi_person_alerts", 0) * 15) -
                                   (proctoring.get("tab_switches", 0) * 10)),
            "violations": {"total_count": len(proctoring.get("violation_log", []))},
            "message": "Report generated from stored data (session already ended)",
        }

    return proctor_session.generate_report()


# ── Practice Mode: Live Metrics ───────────────────────

class PracticeMetricsRequest(BaseModel):
    partial_text: str = ""
    video_frame: Optional[str] = None  # base64-encoded JPEG frame


@router.post("/{session_id}/practice/metrics")
async def update_practice_metrics(
    session_id: str,
    body: PracticeMetricsRequest,
    user: dict = Depends(get_current_user),
):
    """
    Compute and return real-time practice metrics for the live dashboard.
    Called periodically by the frontend during mock interviews.
    Requires partial_text (the candidate's in-progress answer) to compute
    real text-based metrics. Returns empty if no text provided.
    """
    partial_text = body.partial_text.strip()

    # Always process video for gaze tracking, even without answer text
    has_text = partial_text and len(partial_text) >= 5

    db = get_database()
    session = await db.mock_sessions.find_one({"_id": ObjectId(session_id)})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session["user_id"] != str(user["_id"]):
        raise HTTPException(status_code=403, detail="Not your session")

    # Ensure there's a practice session tracker
    practice_id = f"mock_{session_id}"
    if practice_id not in practice_mode_service._active_sessions:
        # Initialise a practice tracker for this mock session
        practice_mode_service._active_sessions[practice_id] = {
            "user_id": str(user["_id"]),
            "status": "active",
            "started_at": datetime.utcnow(),
            "metrics_history": [],
            "live_metrics": {
                "confidence": 0, "stress": 0, "attention": 0,
                "speech_clarity": 0, "emotional_stability": 0,
                "answer_completeness": 0,
            },
            "current_question_idx": 0,
            "answers": [],
            "questions": [],
            "topic": "mock_interview",
            "topic_name": "Mock Interview",
        }

    # Decode video frame if provided
    video_frame_data = None
    if body.video_frame:
        # Pass base64 string directly — multimodal_engine.analyze_face expects base64
        video_frame_data = body.video_frame

    # Generate live metrics via the practice service — pass the actual answer text and video
    result = practice_mode_service.update_live_metrics(
        practice_id,
        partial_text=partial_text if has_text else "",
        video_frame=video_frame_data,
    )

    # Persist proctoring detections to DB (lightweight upserts for objects/identity)
    proctor_update = {}
    suspicious_objs = result.get("suspicious_objects", [])
    if suspicious_objs:
        for obj in suspicious_objs:
            obj_entry = {
                "type": obj.get("type", "unknown"),
                "timestamp": datetime.utcnow().isoformat(),
                "confidence": obj.get("confidence", 0),
            }
            proctor_update.setdefault("$push", {})["proctoring.violation_log"] = {
                "type": "suspicious_object",
                "timestamp": datetime.utcnow().isoformat(),
                "details": f"Detected: {obj.get('type', 'unknown')}",
            }
        proctor_update.setdefault("$inc", {})["proctoring.suspicious_objects_detected"] = len(suspicious_objs)

    identity = result.get("identity")
    if identity is not None and identity.get("verified") is False:
        proctor_update.setdefault("$inc", {})["proctoring.identity_mismatches"] = 1
        proctor_update.setdefault("$push", {})["proctoring.violation_log"] = {
            "type": "identity_mismatch",
            "timestamp": datetime.utcnow().isoformat(),
            "details": f"Person change detected (similarity: {identity.get('similarity', 0):.3f})",
        }

    if proctor_update:
        await db.mock_sessions.update_one(
            {"_id": ObjectId(session_id)},
            proctor_update,
        )

    return {
        "metrics": result.get("metrics") if has_text else None,
        "suggestion": result.get("suggestion") if has_text else None,
        "gaze": result.get("gaze"),
        "person_count": result.get("person_count", 0),
        # Enhanced proctoring data (from proctoring_service via practice_mode_service)
        "identity": result.get("identity"),
        "suspicious_objects": result.get("suspicious_objects", []),
        "face_absent": result.get("face_absent", False),
        "attention": result.get("attention"),
        "risk": result.get("risk"),
    }


@router.get("/{session_id}/practice/summary")
async def get_practice_summary(
    session_id: str,
    user: dict = Depends(get_current_user),
):
    """Return aggregated practice analytics for a completed mock session."""
    db = get_database()
    session = await db.mock_sessions.find_one({"_id": ObjectId(session_id)})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session["user_id"] != str(user["_id"]):
        raise HTTPException(status_code=403, detail="Not your session")

    practice_id = f"mock_{session_id}"
    tracker = practice_mode_service._active_sessions.get(practice_id)

    # Build summary from session responses
    responses = session.get("responses", [])
    scores = [r.get("evaluation", {}).get("overall_score", 0) for r in responses]

    summary = {
        "session_id": session_id,
        "total_questions": len(responses),
        "average_score": round(sum(scores) / len(scores), 1) if scores else 0,
        "score_trend": scores,
        "metrics_snapshots": tracker.get("metrics_history", [])[-20:] if tracker else [],
        "strongest_area": "N/A",
        "weakest_area": "N/A",
    }

    # Determine strongest/weakest from last metrics snapshot
    if tracker and tracker.get("live_metrics"):
        m = tracker["live_metrics"]
        metric_keys = ["confidence", "stress", "attention", "speech_clarity",
                       "emotional_stability", "answer_completeness"]
        vals = {k: m.get(k, 50) for k in metric_keys}
        if vals:
            summary["strongest_area"] = max(vals, key=vals.get).replace("_", " ").title()
            summary["weakest_area"] = min(vals, key=vals.get).replace("_", " ").title()

    return summary


# ── Helpers ───────────────────────────────────────────

async def _complete_session(db, session_id: str, session: dict):
    """Mark session as completed and compute round scores."""
    questions = session.get("questions", [])
    responses = session.get("responses", [])

    tech_responses = [
        r for r in responses
        if any(
            q.get("round") == "Technical"
            for q in questions
            if q["question_id"] == r["question_id"]
        )
    ]
    hr_responses = [
        r for r in responses
        if any(
            q.get("round") == "HR"
            for q in questions
            if q["question_id"] == r["question_id"]
        )
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

    await db.mock_sessions.update_one(
        {"_id": ObjectId(session_id)},
        {"$set": update_fields},
    )

    # Clean up in-memory session data to prevent memory leaks
    try:
        ai_service.cleanup_session(session_id)
        from app.services.rl_adaptation_service import rl_adaptation_service
        rl_adaptation_service.cleanup_session(session_id)
        # Clean up proctoring session
        if proctor_manager is not None:
            proctor_manager.remove(session_id)
    except Exception:
        pass
