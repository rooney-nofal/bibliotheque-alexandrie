"""Finds the passages closest to a question in the vector database."""

from __future__ import annotations                            # lets us write modern type hints safely

from assistant.core.embeddings import embed_query              # turns a question into a vector


def search(config: dict, model, collection, question: str, top_k: int | None = None) -> list[dict]:
    """Return the passages closest to the question, each with its source and a similarity score."""
    vector = embed_query(config["embeddings"], model, question)        # the question, as a vector
    count = top_k or config["retrieval"]["top_k"]                      # how many passages to fetch
    result = collection.query(                                         # ask the database for the closest ones
        query_embeddings=[vector.tolist()],                            # our question vector
        n_results=count,                                               # how many passages to return
        include=["documents", "metadatas", "distances"],               # the text, its source, and the scores
    )
    hits = []                                                          # the passages we will hand back
    for text, meta, distance in zip(result["documents"][0], result["metadatas"][0], result["distances"][0]):
        hits.append({                                                  # repackage each result in a simple shape
            "text": text,                                              # the passage itself
            "url": meta["url"],                                        # the page it came from, for citing
            "title": meta["title"],                                    # that page's title
            "section": meta["section"],                                # the section inside the page
            "distance": float(distance),                               # 0 means identical, larger means further away
            "similarity": 1.0 - float(distance),                       # the same thing the other way round, easier to read
        })
    return hits                                                        # hand the list back, closest first