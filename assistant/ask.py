"""Ask the assistant one question from the command line."""

from __future__ import annotations                            # lets us write modern type hints safely

import argparse                                                # reads the question typed after the command

from assistant.config import load_config                       # our own settings loader
from assistant.core.chain import answer_question               # the full question-to-answer chain
from assistant.core.embeddings import get_embedder             # the embedding model
from assistant.core.vector_store import collection_name, open_client, open_collection   # database helpers


def main() -> None:                                            # the entry point: what runs when we start this file
    """Ask one question and print the answer, its sources, and how it was produced."""
    parser = argparse.ArgumentParser(description="Ask the documentation assistant a question.")
    parser.add_argument("question", help="the question, in French, between quotes")
    parser.add_argument("--prompt", default=None, help="prompt version to use, for example v2")
    args = parser.parse_args()                                 # read what was typed after the command

    config = load_config()                                     # load every setting
    model = get_embedder(config["embeddings"])                 # load the embedding model
    collection = open_collection(open_client(config), collection_name(config, config["chunking"]["chosen"]))

    result = answer_question(config, model, collection, args.question, args.prompt)   # run the chain

    print(f"\nQuestion : {result['question']}")                # show the question back
    print(f"\n{result['answer']}\n")                           # the answer itself
    if result["sources"]:                                      # if the answer cited anything
        print("Sources :")                                     # list them with their real addresses
        for source in result["sources"]:                       # one line per cited passage
            print(f"  [{source['n']}] {source['section']}")    # which section it came from
            print(f"      {source['url']}")                    # and the page a student can open
    print(f"\n(similarity {result['best_similarity']} | passages {result['passages_used']} | "
          f"{result['seconds']}s | cached {result['cached']} | refused {result['refused']}"
          f"{' by ' + result['refused_by'] if result['refused_by'] else ''})")
    for warning in result["warnings"]:                         # anything suspicious about the citations
        print(f"WARNING: {warning}")                           # shown plainly rather than hidden


if __name__ == "__main__":                                     # only run main() when started directly
    main()                                                     # start the program