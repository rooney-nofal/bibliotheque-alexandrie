"""The complete chain: search, decide whether to answer, prompt the model, verify its citations."""

from __future__ import annotations                            # lets us write modern type hints safely

import re                                                      # finds the [1] style citations in the answer
import time                                                    # measures how long the whole chain takes

from assistant.core.llm import generate                        # sends the prompt to the chosen model
from assistant.core.prompting import REFUSAL, build_prompt     # the refusal wording and the prompt builder
from assistant.core.search import search                       # finds the passages

CITATION_PATTERN = re.compile(r"\[(\d+)\]")                    # matches [1], [2], [12] and captures the number


def extract_citations(text: str) -> list[int]:                 # pulls the passage numbers out of an answer
    """Return every passage number the answer cites, in order, without repeats."""
    seen, ordered = set(), []                                  # what we have already seen, and the result
    for found in CITATION_PATTERN.findall(text):               # every [n] in the answer
        number = int(found)                                    # as a number, not text
        if number not in seen:                                 # skip one we already recorded
            seen.add(number)                                   # remember it
            ordered.append(number)                             # and keep it in the order it appeared
    return ordered                                             # hand the list back


def _is_refusal(text: str) -> bool:                            # did the model decline to answer?
    """Recognise the refusal even if the model adds a full stop or changes capitals."""
    cleaned = text.strip().rstrip(".").casefold()              # ignore spaces, trailing dots and capitals
    return cleaned.startswith(REFUSAL.rstrip(".").casefold())  # compare against our agreed wording


def answer_question(config: dict, model, collection, question: str, prompt_version: str | None = None) -> dict:
    """Answer one question end to end, refusing when the library has nothing close enough."""
    started = time.time()                                      # note the time before anything happens
    hits = search(config, model, collection, question)         # find the closest passages
    best = hits[0]["similarity"] if hits else 0.0              # how close the best one was
    threshold = config["retrieval"]["min_similarity"]          # the line we measured in step 5.1

    if not hits or best < threshold:                           # nothing close enough to be worth answering
        return {                                               # refuse here, before any model is called
            "question": question, "answer": REFUSAL, "refused": True, "refused_by": "threshold",
            "best_similarity": round(best, 4), "passages_used": 0, "sources": [],
            "citations": {"found": [], "valid": [], "invalid": []}, "warnings": [],
            "cached": False, "seconds": round(time.time() - started, 3), "model": None,
        }

    prompt = build_prompt(config, question, hits, prompt_version)   # the rules, the passages and the question
    reply = generate(config, prompt)                           # ask the model, using the cache if possible
    text = reply["text"].strip()                               # its answer, tidied

    found = extract_citations(text)                            # which passages it claims to have used
    valid = [n for n in found if 1 <= n <= len(hits)]          # the ones that really exist in what we sent
    invalid = [n for n in found if n not in valid]             # anything else is invented
    sources = [{"n": n, "title": hits[n - 1]["title"], "section": hits[n - 1]["section"], "url": hits[n - 1]["url"]} for n in valid]

    refused = _is_refusal(text)                                # the model may decline on content
    warnings = []                                              # problems worth reporting, not crashing on
    if invalid:                                                # it cited a passage we never gave it
        warnings.append(f"model cited passages that were not provided: {invalid}")
    if not refused and not valid:                              # it answered but backed nothing up
        warnings.append("answer contains no valid citation")

    return {                                                   # everything the caller might need
        "question": question, "answer": text, "refused": refused,
        "refused_by": "model" if refused else None,            # who refused: the threshold or the model
        "best_similarity": round(best, 4), "passages_used": len(hits),
        "sources": [] if refused else sources,                 # a refusal cites nothing
        "citations": {"found": found, "valid": valid, "invalid": invalid},
        "warnings": warnings, "cached": reply["cached"],
        "seconds": round(time.time() - started, 3), "model": reply["model"],
    }