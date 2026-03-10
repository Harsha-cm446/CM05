import uuid
from datetime import datetime
from typing import List

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException

from app.core.database import get_database
from app.core.security import get_hr_user
from app.models.schemas import (
    InterviewSessionCreate,
    InterviewSessionResponse,
    CandidateInvite,
    CandidateResponse,
)
from app.services.email_service import send_interview_invitations

router = APIRouter(prefix="/api/interviews", tags=["Interview Sessions"])


@router.post("/sessions", response_model=InterviewSessionResponse, status_code=201)
async def create_session(data: InterviewSessionCreate, hr_user: dict = Depends(get_hr_user)):
    db = get_database()
    session_token = str(uuid.uuid4())

    # Normalize scoring weights: if provided, ensure they sum to 1.0
    weights_dict = None
    if data.scoring_weights:
        w = data.scoring_weights
        total = w.content + w.keyword + w.depth + w.communication + w.confidence
        if total > 0:
            weights_dict = {
                "content": round(w.content / total, 4),
                "keyword": round(w.keyword / total, 4),
                "depth": round(w.depth / total, 4),
                "communication": round(w.communication / total, 4),
                "confidence": round(w.confidence / total, 4),
            }

    doc = {
        "job_role": data.job_role,
        "scheduled_time": data.scheduled_time,
        "duration_minutes": data.duration_minutes,
        "company_name": data.company_name or hr_user.get("name", "Company"),
        "description": data.description,
        "job_description": data.job_description or "",
        "experience_level": data.experience_level or "",
        "scoring_weights": weights_dict,
        "technical_cutoff": data.technical_cutoff,
        "session_token": session_token,
        "status": "pending",
        "created_by": str(hr_user["_id"]),
        "created_by_email": hr_user["email"],
        "candidate_count": 0,
        "created_at": datetime.utcnow(),
    }
    result = await db.interview_sessions.insert_one(doc)
    doc["id"] = str(result.inserted_id)
    return InterviewSessionResponse(**doc)


@router.get("/sessions", response_model=List[InterviewSessionResponse])
async def list_sessions(hr_user: dict = Depends(get_hr_user)):
    db = get_database()
    cursor = db.interview_sessions.find({"created_by": str(hr_user["_id"])}).sort("created_at", -1)
    sessions = []
    async for s in cursor:
        s["id"] = str(s["_id"])
        sessions.append(InterviewSessionResponse(**s))
    return sessions


@router.get("/sessions/{session_id}", response_model=InterviewSessionResponse)
async def get_session(session_id: str, hr_user: dict = Depends(get_hr_user)):
    db = get_database()
    session = await db.interview_sessions.find_one({"_id": ObjectId(session_id)})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    session["id"] = str(session["_id"])
    return InterviewSessionResponse(**session)


@router.post("/sessions/{session_id}/invite", response_model=List[CandidateResponse])
async def invite_candidates(
    session_id: str, invite: CandidateInvite, hr_user: dict = Depends(get_hr_user)
):
    db = get_database()
    session = await db.interview_sessions.find_one({"_id": ObjectId(session_id)})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    candidates = []
    for email in invite.emails:
        unique_token = str(uuid.uuid4())
        candidate_doc = {
            "email": email,
            "interview_session_id": session_id,
            "unique_token": unique_token,
            "status": "invited",
            "invited_at": datetime.utcnow(),
            "joined_at": None,
        }
        result = await db.candidates.insert_one(candidate_doc)
        candidate_doc["id"] = str(result.inserted_id)
        candidates.append(CandidateResponse(**candidate_doc))

    # Update candidate count
    await db.interview_sessions.update_one(
        {"_id": ObjectId(session_id)},
        {"$inc": {"candidate_count": len(invite.emails)}},
    )

    # Send invitation emails (fire-and-forget style via background)
    await send_interview_invitations(
        candidates=candidates,
        session=session,
        company_name=session.get("company_name", "Company"),
    )

    return candidates


@router.get("/sessions/{session_id}/candidates", response_model=List[CandidateResponse])
async def list_candidates(session_id: str, hr_user: dict = Depends(get_hr_user)):
    db = get_database()
    cursor = db.candidates.find({"interview_session_id": session_id})
    result = []
    async for c in cursor:
        c["id"] = str(c["_id"])
        result.append(CandidateResponse(**c))
    return result


@router.post("/sessions/{session_id}/end")
async def end_session(session_id: str, hr_user: dict = Depends(get_hr_user)):
    """End an interview session and force-complete all in-progress candidate interviews."""
    db = get_database()
    session = await db.interview_sessions.find_one({"_id": ObjectId(session_id)})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session["created_by"] != str(hr_user["_id"]):
        raise HTTPException(status_code=403, detail="Not your session")

    # Mark session as completed
    await db.interview_sessions.update_one(
        {"_id": ObjectId(session_id)},
        {"$set": {"status": "completed", "ended_at": datetime.utcnow()}},
    )

    # Force-complete all in-progress candidate AI sessions for this session
    candidates = []
    async for c in db.candidates.find({"interview_session_id": session_id}):
        candidates.append(c)

    ended_count = 0
    for candidate in candidates:
        if candidate.get("status") in ("invited", "joined"):
            ai_session = await db.candidate_ai_sessions.find_one(
                {"candidate_token": candidate["unique_token"]}
            )
            if ai_session and ai_session.get("status") != "completed":
                await db.candidate_ai_sessions.update_one(
                    {"_id": ai_session["_id"]},
                    {"$set": {"status": "completed", "completed_at": datetime.utcnow(), "end_reason": "session_ended_by_hr"}},
                )
                ended_count += 1
            await db.candidates.update_one(
                {"_id": candidate["_id"]},
                {"$set": {"status": "completed"}},
            )

    return {"detail": "Session ended", "candidates_ended": ended_count}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, hr_user: dict = Depends(get_hr_user)):
    db = get_database()
    await db.interview_sessions.delete_one({"_id": ObjectId(session_id)})
    await db.candidates.delete_many({"interview_session_id": session_id})
    return {"detail": "Session deleted"}


# ── HR Dashboard Analytics ────────────────────────────

@router.get("/analytics/dashboard")
async def get_hr_analytics(hr_user: dict = Depends(get_hr_user)):
    """Aggregate analytics across all sessions created by this HR user."""
    db = get_database()
    hr_id = str(hr_user["_id"])

    # Get all sessions for this HR
    sessions = []
    async for s in db.interview_sessions.find({"created_by": hr_id}):
        sessions.append(s)

    if not sessions:
        return {
            "total_sessions": 0,
            "total_candidates": 0,
            "completed_interviews": 0,
            "avg_overall_score": 0,
            "avg_technical_score": 0,
            "avg_hr_score": 0,
            "pass_rate": 0,
            "top_failing_skills": [],
            "score_distribution": [],
            "monthly_trend": [],
            "role_breakdown": [],
        }

    session_ids = [str(s["_id"]) for s in sessions]

    # Get all candidate AI sessions for these interview sessions
    ai_sessions = []
    async for ai_sess in db.candidate_ai_sessions.find(
        {"interview_session_id": {"$in": session_ids}, "status": "completed"}
    ):
        ai_sessions.append(ai_sess)

    total_candidates = sum(s.get("candidate_count", 0) for s in sessions)
    completed = len(ai_sessions)

    # Compute aggregate scores
    overall_scores = []
    tech_scores = []
    hr_scores = []
    skill_fails = {"content": 0, "keyword": 0, "depth": 0, "communication": 0, "confidence": 0}
    score_buckets = {"0-20": 0, "21-40": 0, "41-60": 0, "61-80": 0, "81-100": 0}
    monthly_data = {}
    role_data = {}

    for ai_sess in ai_sessions:
        responses = ai_sess.get("responses", [])
        questions = ai_sess.get("questions", [])

        # Per-question scores
        for resp in responses:
            ev = resp.get("evaluation", {})
            o_score = ev.get("overall_score", 0)
            overall_scores.append(o_score)

            # Score distribution
            if o_score <= 20:
                score_buckets["0-20"] += 1
            elif o_score <= 40:
                score_buckets["21-40"] += 1
            elif o_score <= 60:
                score_buckets["41-60"] += 1
            elif o_score <= 80:
                score_buckets["61-80"] += 1
            else:
                score_buckets["81-100"] += 1

            # Track failing skills (< 50)
            for dim in skill_fails:
                if ev.get(f"{dim}_score", 50) < 50:
                    skill_fails[dim] += 1

        ts = ai_sess.get("technical_score")
        hs = ai_sess.get("hr_score")
        if ts is not None:
            tech_scores.append(ts)
        if hs is not None:
            hr_scores.append(hs)

        # Monthly trend
        created = ai_sess.get("created_at")
        if created:
            month_key = created.strftime("%Y-%m")
            if month_key not in monthly_data:
                monthly_data[month_key] = {"interviews": 0, "total_score": 0}
            monthly_data[month_key]["interviews"] += 1
            if ts is not None:
                monthly_data[month_key]["total_score"] += ts

        # Role breakdown
        role = ai_sess.get("job_role", "Unknown")
        if role not in role_data:
            role_data[role] = {"count": 0, "total_score": 0, "passed": 0}
        role_data[role]["count"] += 1
        if ts is not None:
            role_data[role]["total_score"] += ts
            if ts >= 70:
                role_data[role]["passed"] += 1

    safe_avg = lambda lst: round(sum(lst) / len(lst), 1) if lst else 0

    # Top failing skills
    top_failing = sorted(skill_fails.items(), key=lambda x: x[1], reverse=True)
    top_failing_skills = [
        {"skill": k.replace("_", " ").title(), "fail_count": v}
        for k, v in top_failing if v > 0
    ]

    # Monthly trend
    monthly_trend = sorted([
        {
            "month": k,
            "interviews": v["interviews"],
            "avg_score": round(v["total_score"] / v["interviews"], 1) if v["interviews"] else 0,
        }
        for k, v in monthly_data.items()
    ], key=lambda x: x["month"])

    # Role breakdown
    role_breakdown = sorted([
        {
            "role": k,
            "count": v["count"],
            "avg_score": round(v["total_score"] / v["count"], 1) if v["count"] else 0,
            "pass_rate": round((v["passed"] / v["count"]) * 100, 1) if v["count"] else 0,
        }
        for k, v in role_data.items()
    ], key=lambda x: x["count"], reverse=True)

    passed_count = sum(1 for s in tech_scores if s >= 70)
    pass_rate = round((passed_count / len(tech_scores)) * 100, 1) if tech_scores else 0

    return {
        "total_sessions": len(sessions),
        "total_candidates": total_candidates,
        "completed_interviews": completed,
        "avg_overall_score": safe_avg(overall_scores),
        "avg_technical_score": safe_avg(tech_scores),
        "avg_hr_score": safe_avg(hr_scores),
        "pass_rate": pass_rate,
        "top_failing_skills": top_failing_skills[:5],
        "score_distribution": [
            {"range": k, "count": v} for k, v in score_buckets.items()
        ],
        "monthly_trend": monthly_trend[-12:],
        "role_breakdown": role_breakdown,
    }


@router.get("/analytics/comparison/{session_id}")
async def get_candidate_comparison(session_id: str, hr_user: dict = Depends(get_hr_user)):
    """Side-by-side comparison of all candidates in a session."""
    db = get_database()

    session = await db.interview_sessions.find_one({"_id": ObjectId(session_id)})
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session["created_by"] != str(hr_user["_id"]):
        raise HTTPException(status_code=403, detail="Not your session")

    candidates = []
    async for ai_sess in db.candidate_ai_sessions.find(
        {"interview_session_id": session_id, "status": "completed"}
    ):
        responses = ai_sess.get("responses", [])
        questions = ai_sess.get("questions", [])

        # Compute dimension averages
        dims = {"content": [], "keyword": [], "depth": [], "communication": [], "confidence": [], "overall": []}
        for resp in responses:
            ev = resp.get("evaluation", {})
            for d in dims:
                dims[d].append(ev.get(f"{d}_score", 0))

        safe_avg = lambda lst: round(sum(lst) / len(lst), 1) if lst else 0

        proctoring = ai_sess.get("proctoring", {})
        integrity_score = proctoring.get("integrity_score",
            max(0, 100 - proctoring.get("gaze_violations", 0) * 3
                    - proctoring.get("multi_person_alerts", 0) * 15
                    - proctoring.get("tab_switches", 0) * 10))

        candidates.append({
            "candidate_name": ai_sess.get("candidate_name", "Unknown"),
            "candidate_email": ai_sess.get("candidate_email", ""),
            "candidate_token": ai_sess.get("candidate_token", ""),
            "technical_score": ai_sess.get("technical_score", 0),
            "hr_score": ai_sess.get("hr_score", 0),
            "dimension_scores": {d: safe_avg(v) for d, v in dims.items()},
            "total_questions": len(responses),
            "current_round": ai_sess.get("current_round", "Technical"),
            "termination_reason": ai_sess.get("termination_reason"),
            "integrity_score": round(integrity_score, 1),
            "proctoring": {
                "gaze_violations": proctoring.get("gaze_violations", 0),
                "multi_person_alerts": proctoring.get("multi_person_alerts", 0),
                "tab_switches": proctoring.get("tab_switches", 0),
            },
            "completed_at": ai_sess.get("completed_at"),
        })

    # Sort by overall score descending
    candidates.sort(key=lambda c: c["dimension_scores"].get("overall", 0), reverse=True)

    return {
        "session_id": session_id,
        "job_role": session.get("job_role", ""),
        "candidates": candidates,
    }
