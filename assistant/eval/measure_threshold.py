"""Measures similarity scores for answerable and unanswerable questions, to choose a refusal threshold."""

from __future__ import annotations                            # lets us write modern type hints safely

import json                                                    # reads the question files and writes the results

from assistant.config import load_config, project_path         # our own settings loader
from assistant.core.embeddings import get_embedder             # the embedding model
from assistant.core.search import search                       # the search function
from assistant.core.vector_store import collection_name, open_client, open_collection   # database helpers


def top_similarities(config, model, collection, questions: list[dict]) -> list[tuple[str, float, str]]:
    """For each question, record how close the single best passage was."""
    rows = []                                                  # one row per question
    for item in questions:                                     # go through the questions
        hits = search(config, model, collection, item["question"])      # find the closest passages
        rows.append((item["id"], round(hits[0]["similarity"], 4), hits[0]["url"]))   # keep the best one
    return rows                                                # hand the rows back


def main() -> None:                                            # the entry point: what runs when we start this file
    """Compare the scores of real questions against questions the corpus cannot answer."""
    config = load_config()                                     # load every setting
    size = config["chunking"]["chosen"]                        # the chunk size we settled on
    eval_dir = project_path("eval")                            # where the question files live
    answerable = json.loads((eval_dir / "questions.json").read_text(encoding="utf-8"))
    unanswerable = json.loads((eval_dir / "questions_unanswerable.json").read_text(encoding="utf-8"))

    model = get_embedder(config["embeddings"])                 # load the embedding model once
    collection = open_collection(open_client(config), collection_name(config, size))   # the passages

    good = top_similarities(config, model, collection, answerable)         # scores for real questions
    bad = top_similarities(config, model, collection, unanswerable)        # scores for impossible ones

    print(f"Chunk size {size}, {len(good)} answerable and {len(bad)} unanswerable questions.\n")
    print("ANSWERABLE (we want these ABOVE the threshold):")
    for qid, score, url in sorted(good, key=lambda r: r[1]):    # weakest first, as those set the limit
        print(f"  {qid}  {score:.4f}  {url}")
    print("\nUNANSWERABLE (we want these BELOW the threshold):")
    for qid, score, url in sorted(bad, key=lambda r: r[1], reverse=True):   # strongest first, same reason
        print(f"  {qid}  {score:.4f}  {url}")

    lowest_good = min(s for _, s, _ in good)                   # the weakest real question
    highest_bad = max(s for _, s, _ in bad)                    # the most convincing impostor
    print(f"\nlowest answerable  = {lowest_good:.4f}")
    print(f"highest unanswerable = {highest_bad:.4f}")
    if lowest_good > highest_bad:                              # if the two groups do not touch
        suggestion = round((lowest_good + highest_bad) / 2, 4) # a threshold halfway between them
        print(f"\nThe two groups DO NOT overlap. A threshold of {suggestion} separates them perfectly.")
    else:                                                      # if they do touch, no clean line exists
        overlap_good = [q for q, s, _ in good if s <= highest_bad]         # the real questions at risk
        print(f"\nThe two groups OVERLAP. No single threshold separates them cleanly.")
        print(f"Answerable questions scoring below the worst unanswerable one: {', '.join(overlap_good)}")
        print("Pick a threshold by deciding which mistake costs more: refusing a real question, or answering a bad one.")

    out = eval_dir / "threshold_measurement.json"              # where the evidence is stored
    out.write_text(json.dumps({                                # the full numbers, for the README
        "chunk_size": size,
        "answerable": [{"id": q, "similarity": s, "url": u} for q, s, u in good],
        "unanswerable": [{"id": q, "similarity": s, "url": u} for q, s, u in bad],
        "lowest_answerable": lowest_good,
        "highest_unanswerable": highest_bad,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {out.name}")


if __name__ == "__main__":                                     # only run main() when started directly
    main()                                                     # start the program