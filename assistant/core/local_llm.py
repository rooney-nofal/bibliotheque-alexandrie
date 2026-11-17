"""Runs a small open model on this computer, so questions never leave the machine."""

from __future__ import annotations                            # lets us write modern type hints safely

import re                                                      # used to strip the model's thinking block
from functools import lru_cache                                # remembers the loaded model instead of reloading it

import torch                                                   # the engine that runs the model
from transformers import AutoModelForCausalLM, AutoTokenizer   # loads open models from Hugging Face

# Some models wrap private reasoning in <think>...</think>; we remove it before showing an answer.
THINKING_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


@lru_cache(maxsize=1)                                          # load the model once, reuse it afterwards
def _load(model_name: str):
    """Download the model the first time, then load it from the local cache."""
    tokenizer = AutoTokenizer.from_pretrained(model_name)      # turns text into numbers the model understands
    model = AutoModelForCausalLM.from_pretrained(model_name)   # the model itself
    model.eval()                                               # switch to answering mode, not training mode
    return tokenizer, model                                    # hand both back together


def generate_local(settings: dict, prompt: str) -> tuple[str, dict]:
    """Answer one prompt using the model running on this computer."""
    tokenizer, model = _load(settings["local_model"])          # the model named in config.yaml
    conversation = [{"role": "user", "content": prompt}]       # our prompt, as a chat message
    rendered = tokenizer.apply_chat_template(                  # lay it out the way this model expects
        conversation,                                          # the message
        tokenize=False,                                        # give us text, we turn it into numbers next
        add_generation_prompt=True,                            # end with the marker that says "now answer"
        enable_thinking=False,                                 # ask it not to write private reasoning first
    )
    inputs = tokenizer([rendered], return_tensors="pt")        # turn the text into numbers
    with torch.no_grad():                                      # we are answering, not learning: save memory
        produced = model.generate(                             # run the model
            **inputs,                                          # the prompt, as numbers
            max_new_tokens=settings["max_tokens"],             # the longest answer we allow
            do_sample=False,                                   # always pick the most likely word, no randomness
            pad_token_id=tokenizer.eos_token_id,               # avoids a harmless warning on some models
        )
    new_tokens = produced[0][inputs["input_ids"].shape[1]:]    # keep only what the model added, not our prompt
    answer = tokenizer.decode(new_tokens, skip_special_tokens=True)     # turn the numbers back into text
    answer = THINKING_BLOCK.sub("", answer).strip()            # drop any thinking block that slipped through
    usage = {                                                  # how many tokens went in and came out
        "prompt_tokens": int(inputs["input_ids"].shape[1]),    # the prompt's length
        "completion_tokens": int(new_tokens.shape[0]),         # the answer's length
    }
    return answer, usage                                       # same shape as the hosted client returns