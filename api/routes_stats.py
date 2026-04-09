"""Statistics, salary insights, and trend endpoints."""

from fastapi import APIRouter, Query, Request
from typing import Optional
from api.middleware import limiter
from core import db

router = APIRouter()


@router.get("/summary")
@limiter.limit("30/minute")
async def stats_summary(request: Request):
    """Aggregated stats for the dashboard home page."""
    today = db._fetchone(
        "SELECT COUNT(*) as count FROM jobs WHERE created_at > now() - make_interval(days := 1)"
    )
    week = db._fetchone(
        "SELECT COUNT(*) as count FROM jobs WHERE created_at > now() - make_interval(days := 7)"
    )
    total = db._fetchone("SELECT COUNT(*) as count FROM jobs")

    by_source = db._fetchall(
        """SELECT source, COUNT(*) as count FROM jobs
           WHERE created_at > now() - make_interval(days := 7)
           GROUP BY source ORDER BY count DESC"""
    )

    by_topic = db._fetchall(
        """SELECT unnest(topics) as topic, COUNT(*) as count FROM jobs
           WHERE created_at > now() - make_interval(days := 7)
           GROUP BY topic ORDER BY count DESC"""
    )

    top_companies = db._fetchall(
        """SELECT company, COUNT(*) as count FROM jobs
           WHERE created_at > now() - make_interval(days := 7)
             AND company != ''
           GROUP BY company ORDER BY count DESC LIMIT 10"""
    )

    return {
        "jobs_today": today["count"] if today else 0,
        "jobs_week": week["count"] if week else 0,
        "jobs_total": total["count"] if total else 0,
        "by_source": by_source,
        "by_topic": by_topic,
        "top_companies": top_companies,
    }


@router.get("/salary")
@limiter.limit("20/minute")
async def salary_stats(
    request: Request,
    role: Optional[str] = Query(None, description="Role keyword (e.g. backend, python)"),
    country: Optional[str] = Query(None, description="Country ISO code"),
    seniority: Optional[str] = Query(None, description="Seniority level"),
):
    """Salary breakdown by role, country, and seniority."""
    conditions = ["salary_min IS NOT NULL", "created_at > now() - make_interval(days := 30)"]
    params = []

    if role:
        conditions.append("title ILIKE %s")
        params.append(f"%{role}%")
    if country:
        conditions.append("country = %s")
        params.append(country)
    if seniority:
        conditions.append("seniority = %s")
        params.append(seniority)

    where = " AND ".join(conditions)

    overall = db._fetchone(
        f"""SELECT
              COUNT(*) as sample_size,
              ROUND(AVG(salary_min)) as avg_min,
              ROUND(AVG(salary_max)) as avg_max,
              MIN(salary_min) as lowest,
              MAX(salary_max) as highest,
              ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY salary_min)) as median_min
            FROM jobs WHERE {where}""",
        tuple(params),
    )

    by_seniority = db._fetchall(
        f"""SELECT seniority,
              COUNT(*) as count,
              ROUND(AVG(salary_min)) as avg_min,
              ROUND(AVG(salary_max)) as avg_max
            FROM jobs WHERE {where}
            GROUP BY seniority ORDER BY avg_min DESC""",
        tuple(params),
    )

    return {
        "overall": overall,
        "by_seniority": by_seniority,
        "filters": {"role": role, "country": country, "seniority": seniority},
    }


@router.get("/trends")
@limiter.limit("20/minute")
async def skill_trends(
    request: Request,
    period: str = Query("7d", description="Period: 7d, 14d, 30d"),
):
    """Skill trends with week-over-week change."""
    days = {"7d": 7, "14d": 14, "30d": 30}.get(period, 7)

    # Current period
    current = db._fetchall(
        """SELECT unnest(tags) as skill, COUNT(*) as count
           FROM jobs WHERE created_at > now() - make_interval(days := %s)
           GROUP BY skill ORDER BY count DESC LIMIT 20""",
        (days,),
    )

    # Previous period (for comparison)
    previous = db._fetchall(
        """SELECT unnest(tags) as skill, COUNT(*) as count
           FROM jobs WHERE created_at BETWEEN
             now() - make_interval(days := %s)
             AND now() - make_interval(days := %s)
           GROUP BY skill ORDER BY count DESC LIMIT 20""",
        (days * 2, days),
    )

    prev_map = {r["skill"]: r["count"] for r in previous}
    trends = []
    for row in current:
        skill = row["skill"]
        current_count = row["count"]
        prev_count = prev_map.get(skill, 0)
        change = ((current_count - prev_count) / max(prev_count, 1)) * 100
        trends.append({
            "skill": skill,
            "count": current_count,
            "previous_count": prev_count,
            "change_percent": round(change, 1),
        })

    return {"period": period, "trends": trends}
