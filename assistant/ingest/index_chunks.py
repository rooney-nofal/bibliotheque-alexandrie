"""Turns every passage into a vector and stores it in the vector database."""

from __future__ import annotations                            # lets us write modern type hints safely

import argparse                                                # reads options typed after the command, like --size
import json                                                    # reads the passage files
import time                                                    # measures how long the embedding takes

from assistant.config import load_config, project_path         # our own settings loader
from assistant.core.embeddings import embed_passages, get_embedder      # the model and the prefixes
from assistant.core.vector_store import collection_name, open_client, reset_collection   # the database helpers

WRITE_BATCH = 500                                              # how many passages we hand to the database at a time


def load_chunks(path) -> list[dict]:                           # reads one passage file
    """Read a .jsonl file where every line is one passage."""
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:                                            # the entry point: what runs when we start this file
    """Embed every passage of every chunk size and store the vectors in Chroma."""
    parser = argparse.ArgumentParser(description="Embed the passages and store them in the vector database.")
    parser.add_argument("--size", type=int, default=None, help="index only this chunk size")
    args = parser.parse_args()                                 # read what was typed after the command

    config = load_config()                                     # load every setting
    settings = config["embeddings"]                            # the embedding section of the settings
    processed_dir = project_path(config["corpus"]["processed_dir"])     # where the passage files are
    sizes = [args.size] if args.size else config["chunking"]["sizes_to_test"]    # one size, or both

    print(f"Loading embedding model {settings['model']} on {settings['device']} (first run downloads it)...")
    model = get_embedder(settings)                             # load the model once, reused for every size
    client = open_client(config)                               # open the vector database

    for size in sizes:                                         # do the whole corpus once per chunk size
        chunks = load_chunks(processed_dir / f"chunks_{size}.jsonl")     # read that size's passages
        texts = [f"{chunk['title']} > {chunk['section']}\n{chunk['text']}" for chunk in chunks]
        print(f"\nSize {size}: embedding {len(chunks)} passages...")     # say what is about to happen
        started = time.time()                                  # note the time before we start
        vectors = embed_passages(settings, model, texts)       # turn every passage into a vector
        elapsed = time.time() - started                        # how long that took

        name = collection_name(config, size)                   # the collection for this chunk size
        collection = reset_collection(client, name)            # empty it, so re-running never duplicates
        for start in range(0, len(chunks), WRITE_BATCH):       # write in batches rather than all at once
            window = chunks[start : start + WRITE_BATCH]       # this batch of passages
            collection.add(                                    # store them in the database
                ids=[chunk["chunk_id"] for chunk in window],   # each passage's unique name
                embeddings=[vector.tolist() for vector in vectors[start : start + WRITE_BATCH]],   # its vector
                documents=[chunk["text"] for chunk in window], # the passage text itself, to show later
                metadatas=[{                                   # everything we need to cite the source
                    "url": chunk["url"],                       # the page's public address
                    "title": chunk["title"],                   # the page's title
                    "section": chunk["section"],               # the section inside that page
                    "file": chunk["file"],                     # the file it came from
                    "characters": chunk["characters"],         # how long the passage is
                    "chunk_size": size,                        # which chunk size produced it
                } for chunk in window],
            )
        print(f"  stored {collection.count()} vectors in collection '{name}' ({elapsed:.1f}s to embed, {len(vectors[0])} dimensions)")

    print("\nIndexing complete.")                              # final line, so a long run ends clearly


if __name__ == "__main__":                                     # only run main() when started directly
    main()                                                     # start the program