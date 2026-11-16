"""Loads the embedding model and turns text into vectors, using the prefixes the model expects."""

from __future__ import annotations                            # lets us write modern type hints safely

from functools import lru_cache                                # remembers a result so the work is done only once

from sentence_transformers import SentenceTransformer          # the library that runs open-source embedding models


@lru_cache(maxsize=2)                                          # keep the loaded model in memory instead of reloading it
def _load(model_name: str, device: str) -> SentenceTransformer:
    """Download the model the first time, then load it from the local cache."""
    return SentenceTransformer(model_name, device=device)      # hand back a ready-to-use model


def get_embedder(settings: dict) -> SentenceTransformer:       # the model named in config.yaml
    """Return the embedding model chosen in config.yaml."""
    return _load(settings["model"], settings["device"])        # name and device both come from the settings


def embed_passages(settings: dict, model, texts: list[str], show_progress: bool = True):
    """Turn a list of passages into vectors, adding the prefix the model was trained to expect."""
    prefixed = [settings["passage_prefix"] + text for text in texts]        # every passage gets the passage prefix
    return model.encode(                                       # run them all through the model
        prefixed,                                              # the prefixed passages
        batch_size=settings["batch_size"],                     # how many to process at a time, to limit memory use
        normalize_embeddings=True,                             # scale every vector to length 1, so cosine works cleanly
        show_progress_bar=show_progress,                       # show a progress bar, since this takes minutes
    )


def embed_query(settings: dict, model, question: str):         # one question, turned into one vector
    """Turn a user's question into a vector, using the query prefix instead of the passage one."""
    return model.encode([settings["query_prefix"] + question], normalize_embeddings=True)[0]