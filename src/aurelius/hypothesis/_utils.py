"""Shared utilities for the hypothesis package."""
from __future__ import annotations

# Stopwords for Jaccard similarity and vagueness checks.
# Includes structural hypothesis words (if/when/then/among/over) and
# high-frequency domain words (returns/positive/negative/high/low) that
# appear in nearly every hypothesis and carry no discriminating signal.
STOPWORDS: frozenset[str] = frozenset(
    "the a an of to in and or for is are we our this that with on by as at from be "
    "these those it its their they can using use based over under into than then "
    "which has have had not but also more most any all each per across among between "
    "if when then among over across within returns positive negative high low top bottom".split()
)
