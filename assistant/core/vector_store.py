"""Opens the vector database and names the collection that holds each chunk size."""

from __future__ import annotations                            # lets us write modern type hints safely

import chromadb                                                # the vector database

from assistant.config import project_path                      # turns a config path into a real one


def open_client(config: dict):                                 # opens the database stored on disk
    """Open the Chroma database in the folder named in config.yaml, creating it if needed."""
    path = project_path(config["vector_store"]["path"])        # where the database lives
    path.mkdir(parents=True, exist_ok=True)                    # create the folder if it is missing
    return chromadb.PersistentClient(path=str(path))           # open it so the data survives between runs


def collection_name(config: dict, chunk_size: int) -> str:     # one collection per chunk size we compare
    """Build the collection name for a chunk size, e.g. fastapi_docs_1500."""
    return f"{config['vector_store']['collection']}_{chunk_size}"


def reset_collection(client, name: str):                       # start a collection from scratch
    """Delete the collection if it exists, then create an empty one that compares by cosine similarity."""
    try:                                                       # the collection may not exist yet
        client.delete_collection(name)                         # remove the old one, so re-indexing never duplicates
    except Exception:                                          # Chroma raises if the name is unknown
        pass                                                   # which is fine on a first run
    return client.create_collection(name=name, configuration={"hnsw": {"space": "cosine"}})


def open_collection(client, name: str):                        # reach an existing collection, for searching
    """Open a collection that already exists."""
    return client.get_collection(name=name)