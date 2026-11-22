"""
Fuzzy search of verified students by the name part of their institutional email.

Student emails follow `<name>-<campus><yy>@student.tarc.edu.my`, e.g. `tanweiming-wm24`
or `tan.wei.ming-wm24`. The name part is the only real name the bot holds.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher

logger = logging.getLogger("tarveri")

# Trailing campus letters + 2-digit intake year, e.g. "-wm24".
_EMAIL_SUFFIX = re.compile(r"-[a-z]{1,3}\d{2}$")
_NON_LETTERS = re.compile(r"[^a-z]+")

MIN_SCORE = 0.8


@dataclass(frozen=True)
class StudentNameMatch:
    discord_user_id: int
    name: str
    score: float
    faculty_code: str | None
    campus_code: str | None
    level_code: str | None
    is_alumni: bool


def extract_email_name(email: str) -> str | None:
    """Returns the name part of a student email as lowercase words, e.g. 'tan wei ming'."""
    if not email or "@" not in email:
        return None
    local = email.strip().lower().split("@", 1)[0]
    local = _EMAIL_SUFFIX.sub("", local)
    words = _NON_LETTERS.sub(" ", local).split()
    return " ".join(words) or None


def _best_window_ratio(token: str, text: str) -> float:
    """Best similarity of `token` against any slice of `text` of about the same length."""
    if token in text:
        return 1.0
    if len(token) <= 3:
        # Short words ("lim", "tan") are too easy to near-match by accident: require an exact hit.
        return 0.0
    best = SequenceMatcher(None, token, text).ratio()
    for size in {max(1, len(token) - 1), len(token), len(token) + 1}:
        for start in range(0, max(1, len(text) - size + 1)):
            best = max(best, SequenceMatcher(None, token, text[start : start + size]).ratio())
    return best


def name_match_score(query: str, name: str) -> float:
    """Scores 0..1 how well `query` matches `name`.

    Handles partial names, any word order, missing or extra spaces, and small typos:
    'weiming tan', 'tan wei mng' and 'tanweiming' all match 'tan wei ming'.
    """
    q_tokens = _NON_LETTERS.sub(" ", (query or "").lower()).split()
    n_compact = _NON_LETTERS.sub("", (name or "").lower())
    if not q_tokens or not n_compact:
        return 0.0
    q_compact = "".join(q_tokens)
    if q_compact == n_compact:
        return 1.0
    if q_compact in n_compact:
        return 0.95
    whole = SequenceMatcher(None, q_compact, n_compact).ratio()
    # Every query word must appear (roughly) somewhere in the name, in any order.
    per_token = [_best_window_ratio(t, n_compact) for t in q_tokens]
    tokens = sum(per_token) / len(per_token) * 0.95
    return max(whole, tokens)


def search_students_by_name(
    query: str,
    records: Iterable[tuple[int, str, str | None, str | None, bool, str]],
    decrypt: Callable[[str], str],
    member_ids: set[int] | None = None,
    limit: int = 10,
) -> list[StudentNameMatch]:
    """Ranks email-verified students by how well their email name matches `query`.

    `records` come from `Database.get_email_verified_students()`. When `member_ids` is given,
    only those Discord users are considered (the current server's members).
    """
    matches: list[StudentNameMatch] = []
    for user_id, faculty, campus, level, is_alumni, encrypted in records:
        if member_ids is not None and user_id not in member_ids:
            continue
        try:
            name = extract_email_name(decrypt(encrypted))
        except Exception as exc:
            logger.debug("Skipping undecryptable email for user %s: %s", user_id, exc)
            continue
        if not name:
            continue
        score = name_match_score(query, name)
        if score >= MIN_SCORE:
            matches.append(StudentNameMatch(user_id, name, score, faculty, campus, level, is_alumni))
    matches.sort(key=lambda m: (-m.score, m.name))
    return matches[:limit]
