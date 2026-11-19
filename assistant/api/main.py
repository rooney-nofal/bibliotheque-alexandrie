"""The HTTP API: one endpoint that answers a question, with its sources and timing."""

from __future__ import annotations                            # lets us write modern type hints safely

import sqlite3                                                 # so we can catch monitoring database errors
from contextlib import asynccontextmanager                     # lets us run setup code once, at startup

from fastapi import FastAPI, HTTPException, Request            # the web framework and its error type
from pydantic import BaseModel, Field                          # describes and checks the shape of the data

from assistant.config import load_config                       # our own settings loader
from assistant.core.chain import answer_question               # the full question-to-answer chain
from assistant.core.embeddings import get_embedder             # the embedding model
from assistant.core.llm import LLMError                        # raised when the model cannot be reached
from assistant.core.vector_store import collection_name, open_client, open_collection   # database helpers
from assistant.monitoring.logger import log_request, read_rows, summarise                # usage statistics                         # usage statistics


class Question(BaseModel):                                     # what a caller must send us
    """The request body of POST /question."""
    question: str = Field(..., min_length=3, max_length=1000, description="the question, in French")
    prompt_version: str | None = Field(None, description="prompt version to use, for example v1")


class Source(BaseModel):                                       # one cited passage
    """A source the answer relies on."""
    n: int                                                     # the number used in the answer, as in [1]
    title: str                                                 # the page's title
    section: str                                               # the section inside that page
    url: str                                                   # the address a student can open


class Answer(BaseModel):                                       # what we send back
    """The response body of POST /question."""
    question: str                                              # the question we were asked
    answer: str                                                # the answer in French, or the refusal
    refused: bool                                              # whether the assistant declined
    refused_by: str | None                                     # "threshold" or "model", when it declined
    sources: list[Source]                                      # the passages actually cited
    best_similarity: float                                     # how close the closest passage was
    passages_used: int                                         # how many passages were sent to the model
    seconds: float                                             # the response time, which the brief asks for
    cached: bool                                               # whether the cache answered instead of the model
    model: str | None                                          # which model wrote it
    warnings: list[str]                                        # citation problems worth surfacing


@asynccontextmanager                                           # marks this as startup-and-shutdown code
async def lifespan(app: FastAPI):
    """Load the model and open the database once, when the server starts."""
    config = load_config()                                     # load every setting
    app.state.config = config                                  # keep them for every request
    app.state.model = get_embedder(config["embeddings"])       # loading this takes seconds, so do it once
    app.state.collection = open_collection(                    # open the passages once too
        open_client(config), collection_name(config, config["chunking"]["chosen"])
    )
    app.state.passages = app.state.collection.count()          # how many passages we are serving
    yield                                                      # the server runs here; nothing to clean up after


app = FastAPI(                                                 # the application itself
    title="Bibliotheque d'Alexandrie",                         # shown in the automatic documentation
    description="Documentation assistant answering in French from official FastAPI documentation.",
    version="1.0.0",                                           # our version, not FastAPI's
    lifespan=lifespan,                                         # the startup code above
)


@app.get("/health")                                            # a simple address to check the server is alive
def health(request: Request) -> dict:
    """Report that the service is up, and what it is currently serving."""
    config = request.app.state.config                          # the settings loaded at startup
    return {                                                   # everything a monitor would want to see
        "status": "ok",                                        # the service is answering
        "corpus": config["corpus"]["name"],                    # which documentation is loaded
        "passages_indexed": request.app.state.passages,        # how many passages are searchable
        "chunk_size": config["chunking"]["chosen"],            # which chunk size is in use
        "prompt_version": config["prompt"]["version"],         # which prompt version is in use
        "llm_model": config["llm"]["model"],                   # which model writes the answers
    }


@app.get("/stats")                                             # the numbers the statistics page shows
def stats(request: Request) -> dict:
    """Report how the assistant has behaved across every question it has answered."""
    config = request.app.state.config                          # the settings loaded at startup
    return summarise(config)                                   # totals, refusal rate, timings, cache rate


@app.get("/recent")                                            # the table at the bottom of that page
def recent(request: Request, limit: int = 50) -> list[dict]:
    """Return the most recently answered questions, newest first."""
    return read_rows(request.app.state.config, limit)          # straight from the monitoring database

@app.post("/question", response_model=Answer)                  # the endpoint the brief asks for
def ask(payload: Question, request: Request) -> dict:
    """Answer one question, returning the answer, its sources and the time taken."""
    config = request.app.state.config                          # the settings loaded at startup
    try:                                                       # the chain can fail in two expected ways
        result = answer_question(                              # run the same chain the command line uses
            config,                                            # the settings
            request.app.state.model,                           # the embedding model, already loaded
            request.app.state.collection,                      # the passages, already open
            payload.question,                                  # what the caller asked
            payload.prompt_version,                            # which prompt version they asked for
        )
    except FileNotFoundError as error:                         # an unknown prompt version was requested
        raise HTTPException(status_code=400, detail=str(error))          # that is the caller's mistake
    except LLMError as error:                                  # the model is down, rate limited or misconfigured
        raise HTTPException(status_code=503, detail=f"the language model is unavailable: {error}")
    try:                                                       # recording must never destroy a good answer
        log_request(config, result, payload.prompt_version or config["prompt"]["version"])
    except sqlite3.Error as error:                             # a locked or unwritable database, for example
        result["warnings"] = result["warnings"] + [f"monitoring failed: {error}"]   # say so, do not crash
    return result                                              # the answer goes back either way