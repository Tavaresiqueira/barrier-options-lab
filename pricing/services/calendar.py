from datetime import date, timedelta

import exchange_calendars as xcals
import pandas as pd


def b3_sessions(start: date, end: date) -> list[date]:
    calendar = xcals.get_calendar("BVMF", start=str(start - timedelta(days=10)), end=str(end + timedelta(days=10)))
    sessions = calendar.sessions
    sessions = sessions[(sessions >= pd.Timestamp(start)) & (sessions <= pd.Timestamp(end))]
    return [session.date() for session in sessions]


def observation_dates(start: date, end: date, convention: str) -> list[date]:
    sessions = b3_sessions(start, end)
    if not sessions:
        return [end]
    if convention == "daily_close":
        return sessions
    frame = pd.DataFrame({"date": pd.to_datetime(sessions)})
    if convention == "weekly":
        return frame.groupby(frame["date"].dt.to_period("W"))["date"].max().dt.date.tolist()
    if convention == "monthly":
        return frame.groupby(frame["date"].dt.to_period("M"))["date"].max().dt.date.tolist()
    if convention == "maturity_only":
        return [sessions[-1]]
    return sessions
