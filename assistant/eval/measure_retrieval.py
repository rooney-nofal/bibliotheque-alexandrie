"""Measures how often the right page appears in the top results, for each chunk size."""

from __future__ import annotations                            # lets us write modern type hints safely

import json                                                    # reads the questions and writes the results

from assistant.config import load_config, project_path         # our own settings loader
from assistant.core.embeddings import get_embedder             # the embedding model
from assistant.core.search import search                       # the search function we just wrote
from assistant.core.vector_store import collection_name, open_client, open_collection   # the database helpers


def main() -> None:                                            # the entry point: what runs when we start this file
    """Run every test question against every chunk size and report the scores."""
    config = load_config()                                     # load every setting
    top_k = config["retrieval"]["top_k"]                       # how many passages count as "the top results"
    questions = json.loads((project_path("eval") / "questions.json").read_text(encoding="utf-8"))
    model = get_embedder(config["embeddings"])                 # load the embedding model once
    client = open_client(config)                               # open the vector database

    summary, details = {}, {}                                  # the scores, and the per-question records
    for size in config["chunking"]["sizes_to_test"]:           # test each chunk size in turn
        collection = open_collection(client, collection_name(config, size))     # that size's collection
        hits_at_1 = hits_at_k = 0                              # how many questions were answered at rank 1, and in the top k
        rows = []                                              # one record per question
        for item in questions:                                 # go through every test question
            found = search(config, model, collection, item["question"], top_k=top_k)    # search for it
            urls = [hit["url"] for hit in found]               # the pages that came back, in order
            rank = urls.index(item["expected_url"]) + 1 if item["expected_url"] in urls else 0   # 0 means not found
            hits_at_1 += 1 if rank == 1 else 0                 # count a win if it came first
            hits_at_k += 1 if rank > 0 else 0                  # count a win if it appeared at all
            rows.append({                                      # record what happened, so misses can be inspected
                "id": item["id"],                              # the question's identifier
                "question": item["question"],                  # the question itself
                "expected_url": item["expected_url"],          # the page that should have been found
                "rank": rank,                                  # where it actually appeared, 0 if absent
                "top_urls": urls,                              # what came back instead
                "best_similarity": round(found[0]["similarity"], 4),    # how close the closest passage was
            })
        total = len(questions)                                 # how many questions we asked
        summary[size] = {"recall_at_1": hits_at_1 / total, f"recall_at_{top_k}": hits_at_k / total}
        details[size] = rows                                   # keep the per-question records for this size
        print(f"chunk size {size:>5}:  recall@1 = {hits_at_1}/{total} ({100*hits_at_1/total:.0f}%)   recall@{top_k} = {hits_at_k}/{total} ({100*hits_at_k/total:.0f}%)")

    best = max(summary, key=lambda s: (summary[s][f"recall_at_{top_k}"], summary[s]["recall_at_1"]))
    print(f"\nBest chunk size by recall@{top_k}: {best}")      # the winner, decided by the measurement
    print("Misses:")                                           # and which questions failed, so we can look at them
    for size in details:                                       # for each chunk size
        missed = [row["id"] for row in details[size] if row["rank"] == 0]        # the questions it got wrong
        print(f"  size {size}: {', '.join(missed) if missed else 'none'}")

    out = project_path("eval") / "retrieval_results.json"      # where the full results go
    out.write_text(json.dumps({"top_k": top_k, "summary": summary, "details": details}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {out.name}")                               # say where the evidence was saved


if __name__ == "__main__":                                     # only run main() when started directly
    main()                                                     # start the program