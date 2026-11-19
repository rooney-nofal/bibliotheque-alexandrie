"""The Streamlit interface: the page a student actually uses."""

from __future__ import annotations                            # lets us write modern type hints safely

import sys                                                     # so we can adjust where Python looks for modules
from datetime import datetime                                  # to show times in the reader's own timezone
from pathlib import Path                                       # to find the project root from this file

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # makes "assistant" importable however this is launched

import requests                                                # to talk to our own API over HTTP
import streamlit as st                                         # the interface framework

from assistant.config import load_config                       # our own settings loader

REFUSAL_HINT = {                                               # a plain explanation of why it declined
    "threshold": "Aucun passage de la documentation n'était assez proche de la question.",
    "model": "Les passages trouvés ne contenaient pas la réponse.",
}


def local_time(stamp: str, pattern: str) -> str:
    """Turn the stored UTC timestamp into the reader's own local time."""
    return datetime.fromisoformat(stamp).astimezone().strftime(pattern)   # UTC in, local out


def api_call(method: str, path: str, payload: dict | None = None):
    """Send one request to our API and return the decoded answer."""
    config = st.session_state.config                           # the settings, loaded once per session
    url = config["api"]["base_url"] + path                     # the full address, never hardcoded
    timeout = config["api"]["timeout_seconds"]                 # give up after this many seconds
    if method == "GET":                                        # reading something
        response = requests.get(url, timeout=timeout)
    else:                                                      # asking a question
        response = requests.post(url, json=payload, timeout=timeout)
    if response.status_code >= 400:                            # the API reported a problem
        raise RuntimeError(response.json().get("detail", response.text))   # show its own message
    return response.json()                                     # the useful part


def show_connection_error(error: Exception) -> None:
    """Explain that the API is not running, and how to start it."""
    st.error("Le serveur n'a pas répondu. Démarrez-le dans un autre terminal :")
    st.code("python -m uvicorn assistant.api.main:app --reload", language="powershell")
    st.caption(str(error)[:200])                               # the technical detail, kept small


def render_result(result: dict) -> None:
    """Draw the answer, its sources, and the monitoring figures."""
    st.divider()                                               # a thin rule between question and answer
    with st.container(border=True):                            # the answer sits in a bordered card
        st.markdown(result["answer"])                          # the French text, with its [n] markers
        if result["refused"]:                                  # the assistant declined to answer
            st.caption(REFUSAL_HINT.get(result["refused_by"], ""))   # why it declined
    if result["sources"]:                                      # only the passages actually cited
        st.markdown("###### Sources")
        for source in result["sources"]:
            st.markdown(f"**[{source['n']}]**  [{source['section']}]({source['url']})")   # clickable
    columns = st.columns(4)                                    # the monitoring row the brief asks for
    columns[0].metric("Temps", f"{result['seconds']:.2f} s")   # response time
    columns[1].metric("Passages", result["passages_used"])     # how many passages were used
    columns[2].metric("Similarité", f"{result['best_similarity']:.3f}")   # retrieval quality
    columns[3].metric("Cache", "oui" if result["cached"] else "non")      # cache hit or real call
    for warning in result["warnings"]:                         # citation problems, if any
        st.warning(warning)


def page_assistant() -> None:
    """The main page: ask a question, read the answer."""
    st.title("La Bibliothèque d'Alexandrie")
    st.caption(
        "Posez une question sur FastAPI. L'assistant répond uniquement à partir de la "
        "documentation officielle, en citant ses sources. S'il ne trouve pas la réponse, "
        "il répond « Je ne sais pas. »"
    )
    with st.form("question_form"):                             # a form submits once, not on every keystroke
        question = st.text_area(
            "Votre question",
            placeholder="Comment déclarer un paramètre de requête optionnel ?",
            height=100,
            label_visibility="collapsed",                      # the placeholder is label enough
        )
        submitted = st.form_submit_button("Demander", type="primary")   # the sky blue button
    if submitted:                                              # the user pressed the button
        if len(question.strip()) < 3:                          # same minimum the API enforces
            st.warning("Écrivez une question un peu plus longue.")
        else:
            with st.spinner("Recherche dans la documentation..."):      # something to watch while it works
                try:
                    st.session_state.result = api_call("POST", "/question", {"question": question.strip()})
                except requests.RequestException as error:     # the server is not running
                    st.session_state.result = None
                    show_connection_error(error)
                except RuntimeError as error:                  # the server answered with an error
                    st.session_state.result = None
                    st.error(str(error))
    if st.session_state.get("result"):                         # keep the answer on screen across reruns
        render_result(st.session_state.result)


def page_statistics() -> None:
    """The monitoring page: how the assistant has behaved overall."""
    st.title("Statistiques")
    try:
        stats = api_call("GET", "/stats")                      # the aggregated numbers
    except requests.RequestException as error:
        show_connection_error(error)
        return
    if not stats.get("total"):                                 # nothing recorded yet
        st.info("Aucune question enregistrée pour l'instant.")
        return
    columns = st.columns(4)                                    # the headline figures
    columns[0].metric("Questions", stats["total"])
    columns[1].metric("Taux de refus", f"{stats['refusal_rate']:.0%}")
    columns[2].metric("Temps moyen", f"{stats['avg_seconds_live']:.2f} s")
    columns[3].metric("Taux de cache", f"{stats['cache_rate']:.0%}")
    columns = st.columns(4)                                    # the second row, more detailed
    columns[0].metric("Refus avant le modèle", stats["refused_by_threshold"])
    columns[1].metric("Refus par le modèle", stats["refused_by_model"])
    columns[2].metric("Passages (moyenne)", stats["avg_passages"])
    columns[3].metric("Similarité (moyenne)", f"{stats['avg_similarity']:.3f}")
    st.caption(                                                # the honest version of "average time"
        f"Temps moyen : {stats['avg_seconds_live']:.2f} s quand le modèle répond, "
        f"{stats['avg_seconds_cached']:.2f} s quand le cache répond."
    )
    st.divider()
    rows = api_call("GET", "/recent")                          # the individual rows
    answered = [                                               # only questions the model really answered
        row
        for row in reversed(rows)                              # oldest first, so the chart reads left to right
        if not row["cached"] and row["refused_by"] != "threshold"   # a cache hit or an early refusal is not a model call
    ][-20:]                                                    # the last twenty of them
    if answered:
        st.markdown("###### Temps de réponse des dernières questions traitées par le modèle (secondes)")
        st.bar_chart(
            {
                "heure": [local_time(row["asked_at"], "%H:%M:%S") for row in answered],   # the x axis
                "secondes": [row["seconds"] for row in answered],                          # the y axis
            },
            x="heure",                                         # label each bar with its time
            y="secondes",                                      # the height of each bar
            color="#1E9BD7",                                   # the one accent colour
            height=220,                                        # keep it modest, it is not the main content
        )
    st.markdown("###### Dernières questions")
    st.dataframe(                                              # the same data as a readable table
        [
            {
                "Date": local_time(row["asked_at"], "%Y-%m-%d %H:%M"),   # shown in local time
                "Question": row["question"],
                "Refus": "oui" if row["refused"] else "non",
                "Temps": round(row["seconds"], 2),
                "Passages": row["passages_used"],
                "Cache": "oui" if row["cached"] else "non",
            }
            for row in rows[:25]
        ],
        hide_index=True,
        width="stretch",
    )


def page_privacy() -> None:
    """The notice the brief asks for: what is stored, and what leaves the machine."""
    st.title("Confidentialité")
    st.markdown(
        """
Cet assistant enregistre et transmet un minimum d'informations. Voici lesquelles, précisément.

###### Ce qui est enregistré sur cette machine
Pour chaque question : la date, le texte de la question, le temps de réponse, le nombre de
passages utilisés, le refus éventuel, le score de similarité, le modèle et la version du prompt.
Ces lignes sont écrites dans un fichier local (`data/monitoring.sqlite`) qui n'est pas publié
sur GitHub.

###### Ce qui quitte cette machine
Pour rédiger la réponse, la question et les passages de documentation retenus sont envoyés
à Anthropic via OpenRouter. La documentation indexée, les vecteurs et l'historique restent
locaux. Aucune autre donnée n'est transmise.

###### Ce qui n'est pas collecté
Aucun compte, aucun cookie, aucune adresse IP, aucun identifiant d'utilisateur. Les lignes
enregistrées ne sont rattachées à aucune personne.

###### Vos droits
L'historique complet tient dans un seul fichier : le supprimer efface toutes les données.
L'enregistrement peut être désactivé dans `config.yaml` : `monitoring.enabled: false` arrête
tout enregistrement, `monitoring.store_questions: false` conserve les statistiques sans
enregistrer le texte des questions.

###### Recommandation
N'écrivez pas de données personnelles dans vos questions : elles seraient enregistrées
localement et transmises au fournisseur du modèle.
        """
    )


st.set_page_config(page_title="La Bibliothèque d'Alexandrie", page_icon=":books:", layout="centered")

if "config" not in st.session_state:                           # load the settings once per visitor
    st.session_state.config = load_config()

st.sidebar.title("Alexandrie")                                 # the wordmark
st.sidebar.caption("Assistant de documentation")
page = st.sidebar.radio("Navigation", ["Assistant", "Statistiques", "Confidentialité"], label_visibility="collapsed")
st.sidebar.divider()
try:
    health = api_call("GET", "/health")                        # show what the server is serving
    st.sidebar.caption(
        f"Corpus : {health['corpus']}  \n"
        f"Passages indexés : {health['passages_indexed']}  \n"
        f"Taille des chunks : {health['chunk_size']}  \n"
        f"Prompt : {health['prompt_version']}  \n"
        f"Modèle : {health['llm_model']}"
    )
except requests.RequestException:                              # the API is not running
    st.sidebar.caption(":red[Serveur hors ligne]")

if page == "Assistant":                                        # draw whichever page is selected
    page_assistant()
elif page == "Statistiques":
    page_statistics()
else:
    page_privacy()