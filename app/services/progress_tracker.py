import uuid
from datetime import datetime, timedelta
from typing import Dict, List
import pandas as pd
from sqlalchemy.orm import Session, joinedload
from ..models import TherapySession


class ProgressTracker:
    def __init__(self, db: Session):
        self.db = db

    def get_progress_trends(self, child_id: uuid.UUID) -> Dict:
        """Get weekly/monthly progress trends"""
        weekly = self._get_timeframe_trend(child_id, days=7)
        monthly = self._get_timeframe_trend(child_id, days=30)

        return {
            "weekly_trend": self._calculate_trend(weekly),
            "monthly_trend": self._calculate_trend(monthly),
            "improvement_areas": self._identify_improvement_areas(weekly, monthly)
        }

    def _get_timeframe_trend(self, child_id: uuid.UUID, days: int) -> pd.DataFrame:
        """Get performance data for specific timeframe"""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)

        sessions = self.db.query(TherapySession) \
            .options(joinedload(TherapySession.activities),
                     joinedload(TherapySession.category)) \
            .filter(
            TherapySession.child_id == child_id,
            TherapySession.start_time >= start_date,
            TherapySession.start_time <= end_date
        ) \
            .all()

        data = []
        for session in sessions:
            if session.activities:
                avg_score = sum(
                    a.pronunciation_score for a in session.activities
                    if a.pronunciation_score is not None
                ) / len(session.activities)

                data.append({
                    "date": session.start_time.date(),
                    "score": avg_score,
                    "category": session.category.name
                })

        return pd.DataFrame(data)

    def _calculate_trend(self, data: pd.DataFrame) -> Dict:
        """Calculate trend metrics from data"""
        if data.empty:
            return {"trend": "no data", "rate": 0}

        data['date'] = pd.to_datetime(data['date'])
        data = data.set_index('date').sort_index()

        # Resample to weekly means
        weekly = data['score'].resample('W').mean()

        # Calculate trend
        if len(weekly) > 1:
            slope = (weekly.iloc[-1] - weekly.iloc[0]) / len(weekly)
            trend = "improving" if slope > 0 else "declining" if slope < 0 else "stable"
            return {
                "trend": trend,
                "rate": abs(slope),
                "current_score": weekly.iloc[-1],
                "starting_score": weekly.iloc[0]
            }
        return {"trend": "insufficient data", "rate": 0}

    def _identify_improvement_areas(self, weekly: pd.DataFrame, monthly: pd.DataFrame) -> List[str]:
        """Identify areas needing improvement based on trends"""
        improvement_areas = []

        # Check weekly data
        if not weekly.empty:
            weekly_low = weekly[weekly['score'] < 0.6]
            if not weekly_low.empty:
                weak_categories = weekly_low['category'].value_counts().index.tolist()
                improvement_areas.append(
                    f"Recent challenges with: {', '.join(weak_categories[:3])}"
                )

        # Check monthly data
        if not monthly.empty:
            monthly_avg = monthly.groupby('category')['score'].mean()
            if not monthly_avg.empty:
                weakest_category = monthly_avg.idxmin()
                improvement_areas.append(
                    f"Long-term focus needed on: {weakest_category}"
                )

        return improvement_areas if improvement_areas else ["No specific improvement areas identified"]