"""The statistical capability surface: what the engine can do, and how far.

Read-only, database-free, and deliberately separate from every calculation
route. It answers "what may I rely on" rather than "what is the answer for my
study", and those are different questions with different failure modes.
"""

from app.statistics.routes import router

__all__ = ["router"]
