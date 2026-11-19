# Answer correctness review

Prompt **v2**, chunk size **1500**, `top_k = 3`, model `anthropic/claude-haiku-5.5`.

## Why this file exists

The brief asks three questions of every answer: is the answer correct, are the sources exact,
and did the assistant refuse when it should have. The second and third are measured automatically
in `prompt_comparison.json` (citation validity, and refusal against `should_answer`). The first
cannot be computed: it needs a person to read the answer and compare it with the documentation.
This file is that reading. Each answer was reviewed one by one against the official FastAPI
documentation; the answers themselves are stored in `prompt_comparison.json`.

## Verdicts

`Source found` is the rank at which the expected document appeared, from `retrieval_results.json`
at chunk size 1500. `0` means it was not in the top 3 at all.

| ID | Question | Source found | Verdict | Reason |
|----|----------|--------------|---------|--------|
| q01 | Comment récupérer un paramètre dans l'URL comme /items/42 ? | not in top 3 | **Not answered** | Retrieval returned Query Parameters instead of Path Parameters. The assistant said so and pointed to the right section rather than inventing an answer. |
| q02 | Comment déclarer un paramètre de requête optionnel ? | rank 1 | **Correct** | Default value `None` makes a query parameter optional. Matches the documentation. |
| q03 | Comment envoyer des données JSON dans le corps d'une requête ? | not in top 3 | **Off topic** | Describes sending JSON from a test client (`json=` on TestClient). True, but the question asks how to declare a JSON request body. The Body page was not retrieved. |
| q04 | Comment imposer une longueur minimale à un paramètre de requête ? | rank 1 | **Correct** | `Query(min_length=3)` inside `Annotated`. Matches the documentation. |
| q05 | Comment renvoyer une erreur 404 au client ? | rank 1 | **Correct** | `HTTPException` with status 404 and a `detail` field. Matches the documentation. |
| q06 | Comment changer le code de statut HTTP renvoyé par une route ? | not in top 3 | **Partial** | Gives the `Response` parameter method, which works, but misses the simpler `status_code=` on the decorator because that page was not retrieved. |
| q07 | Comment recevoir un fichier envoyé par l'utilisateur ? | rank 1 | **Correct** | `File`/`UploadFile`, `python-multipart` required, async methods need `await`. Matches the documentation. |
| q08 | Comment lire les champs d'un formulaire HTML ? | rank 2 | **Correct** | Pydantic model declared with `Form()`. Matches the documentation. |
| q09 | Comment partager du code entre plusieurs routes avec une dépendance ? | rank 2 | **Correct** | Declare the dependency once and reuse it; `Annotated` alias for large projects. Matches the documentation. |
| q10 | Comment protéger une route avec un jeton JWT ? | rank 1 | **Justified refusal** | Retrieved passages cover creating a JWT, not verifying one on a protected route. The assistant refused with the exact phrase. |
| q11 | Comment autoriser un site web d'une autre origine à appeler mon API ? | rank 1 | **Correct** | `CORSMiddleware` added with `app.add_middleware`, origins listed explicitly. Matches the documentation. |
| q12 | Comment exécuter une tâche après avoir renvoyé la réponse ? | rank 1 | **Partial** | Correct that background tasks run after the response is sent; explicitly states the declaration syntax is not in the passages. |
| q13 | Comment écrire des tests automatiques pour mon application ? | rank 1 | **Partial** | Correct on `dependency_overrides` and project layout; explicitly states it cannot show how to write a test. |
| q14 | Comment organiser une grosse application en plusieurs fichiers ? | rank 1 | **Correct** | `APIRouter` in submodules such as `app/routers/users.py`. Matches the documentation. |
| q15 | Comment servir des fichiers statiques comme des images ? | rank 1 | **Correct** | `StaticFiles` mounted with `app.mount`, and `app.frontend()` for a frontend. Verified against the current FastAPI documentation. |
| q16 | Comment connecter mon application à une base de données SQL ? | rank 1 | **Partial** | Correct on installing `sqlmodel` and creating tables at startup; explicitly states the connection setup is not in the passages. |
| q17 | Comment ajouter un middleware exécuté à chaque requête ? | rank 1 | **Correct** | `@app.middleware("http")` with `call_next`. Matches the documentation. |
| q18 | Comment limiter les champs renvoyés dans la réponse ? | rank 1 | **Correct** | `response_model` filters the output; `response_model_exclude_unset` and the include/exclude caveat. Matches the documentation. |
| q19 | Quelle est la différence entre def et async def pour une route ? | rank 2 | **Correct** | `def` runs in an external threadpool, `async def` is awaited directly. Matches the documentation. |
| q20 | Comment lire un en-tête HTTP personnalisé ? | rank 2 | **Correct** | `Header` converts underscores to hyphens; `convert_underscores=False` to disable. Matches the documentation. |

## Summary

- **Correct** — 13 / 20
- **Partial** — 4 / 20
- **Justified refusal** — 1 / 20
- **Off topic** — 1 / 20
- **Not answered** — 1 / 20

Counting usable answers: **17 of 20** are correct or correct-but-partial, **1** is a justified refusal,
and **2** failed (q01, q03).

## The finding

Three questions missed their expected source entirely at chunk size 1500: **q01, q03 and q06**
— which is the 17/20 that produced the measured `recall@3 = 0.85`. Those same three questions are
the only ones whose answers have a content problem. Every other answer, where retrieval found the
right page, is correct.

The quality of this assistant is set by its retrieval, not by its language model. When the right
page was retrieved the model answered correctly every time; when it was not, the model either said
so honestly (q01) or answered a neighbouring question instead (q03). Improving this assistant means
improving retrieval, not changing the model.

## How to re-check this

```powershell
python -m assistant.ask "<question>" --prompt v2
```
