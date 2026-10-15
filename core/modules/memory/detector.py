import re
from core.pipeline.nlp.french_normalizer import normalize_text


def normalize(text: str) -> str:
    return normalize_text(text)


def detect_memory_intent(text: str) -> dict:
    value = normalize(text)

    # Explicit first-person facts are memories even when the user does not use
    # an imperative such as "mémorise".  Core only classifies the statement;
    # Oblivia remains responsible for understanding and storing its meaning.
    personal_fact_patterns = (
        r"^je suis\s+\S",
        r"^je m'appelle\s+\S",
        r"^ma femme s'appelle\s+\S",
        r"^mon fils s'appelle\s+\S",
        r"^j'habite a\s+\S",
        r"^j'habite maintenant a\s+\S",
        r"^j'ai habite a\s+.+\s+il y a\s+[0-9]+\s+ans?",
        r"^j'habitais a\s+.+\s+avant",
        r"^avant j'habitais a\s+\S",
        r"^je n'ai jamais habite a\s+\S",
        r"^je n'habitais pas a\s+\S",
        r"^ce n'est pas vrai je n'ai jamais habite a\s+\S",
        r"^j'aime\s+(?!quoi$)\S",
        r"^je travaille chez\s+\S",
        r"^je travaille maintenant chez\s+\S",
        r"^je suis ne le\s+\S",
        r"^je suis nee le\s+\S",
        r"^en fait je m'appelle\s+\S",
        r"^je n'aime plus\s+\S",
        r"^en fait j'aime a nouveau\s+\S",
        r"^j'ai aussi un enfant\s+\S",
        r"^j'ai (?:[0-9]+|un|une|deux|trois|quatre|cinq|six|sept|huit|neuf|dix) enfants?\s*",
        r"^mes enfants s'appellent\s+\S",
        r"^mes enfants sont\s+\S",
        r"^j'ai achete\s+\S",
        r"^j'ai (?:un|une)\s+\S",
        r"^je possede\s+\S",
        r"^j'utilise\s+\S",
        r"^(?:mon|ma|mes)\s+.+\s+(?:est|sont)(?: maintenant)?\s+\S",
        r"^(?:mon|ma|mes)\s+.+\s+s'appelle\s+\S",
        r"^(?!comment\s).+\s+s'appelle\s+\S",
        r"^j'ai remplace\s+.+\s+par\s+\S",
    )

    remember_patterns = [
        "retiens que",
        "memorise que",
        "souviens toi que",
        "note que",
        "garde en memoire que",
    ]

    recall_patterns = [
        "que viens tu de memoriser",
        "qu as tu memorise",
        "que sais tu",
        "que sais tu sur",
        "que sais tu de ta memoire",
        "comment est organisee ta memoire",
        "comment est organise ta memoire",
        "comment est structuree ta memoire",
        "comment fonctionne ta memoire",
        "tu te souviens",
        "te rappelles tu",
        "qu as tu en memoire",
        "liste ta memoire",
        "montre ta memoire",
        "qui est papa",
        "comment s'appelle ma femme",
        "qu'est ce que j'aime boire",
        "que j'aime boire",
        "comment je m'appelle",
        "qui est mon fils",
        "ou est ce que j'habite",
        "ou est ce que je travaille",
        "ou est ce que j'habitais avant",
        "ou habitais je avant",
        "ou ai je vecu",
        "dans quelles villes ai je vecu",
        "ou travaillais je avant",
        "comment je m'appelais avant",
        "comment s'appelait ma femme avant",
        "j'aime quoi",
        "qui suis je",
        "parle moi de moi",
        "presente moi",
        "que sais tu de moi",
        "fais un resume de ce que tu sais sur moi",
        "qui est ma femme",
        "qui est mon epouse",
        "ou ai je travaille",
        "qu'est ce que j'aime",
        "qu'est ce que j'aimais avant",
        "combien ai je d'enfants",
        "comment s'appellent mes enfants",
        "qui sont mes enfants",
        "quels anciens souvenirs possedes tu",
        "quelles informations ne sont plus actuelles",
        "quelles informations sont obsoletes",
        "montre moi tout ce que tu sais",
        "montre toute ma memoire",
        "quels souvenirs possedes tu",
        "combien de souvenirs as tu sur moi",
        "quels types d'informations connais tu",
        "quels predicats connais tu sur moi",
        "ai je des informations contradictoires",
        "as tu detecte des conflits",
        "y a t il des souvenirs retractes",
        "as tu des informations douteuses",
        "y a t il des donnees obsoletes",
        "qui habite avec moi",
        "qui depend de moi",
        "qui fait partie de mon foyer",
        "si je demenage qui demenage probablement avec moi",
        "qui est lie a moi",
        "qui fait partie de ma famille",
        "qui partage ma vie",
        "tu me connais bien",
        "est ce que tu te souviens de moi",
        "as tu appris des choses sur moi",
        "qu'est ce que tu retiens principalement de moi",
        "qu'est ce qui me caracterise",
        "que pourrais tu raconter sur moi a quelqu'un",
        "si tu devais me presenter que dirais tu",
        "quelle est la derniere chose importante que tu as apprise sur moi",
        "quel est mon telephone",
        "quel telephone j'utilise",
        "quel smartphone ai je",
        "quels appareils je possede",
        "qu'est ce que j'ai achete",
        "tu te souviens de mon telephone",
    ]

    forget_patterns = [
        "oublie que",
        "oublie ce que",
        "efface de ta memoire",
    ]

    if any(p in value for p in remember_patterns) or any(
        re.match(pattern, value) for pattern in personal_fact_patterns
    ):
        return {"matched": True, "kind": "remember", "confidence": 0.95}

    if any(p in value for p in forget_patterns):
        return {"matched": True, "kind": "forget", "confidence": 0.95}

    if any(p in value for p in recall_patterns):
        return {"matched": True, "kind": "recall", "confidence": 0.9}

    personal_recall_patterns = (
        r"^quel(?:le)? est (?:mon|ma|mes)\s+.+$",
        r"^de quelle couleur est (?:mon|ma|mes)\s+.+$",
        r"^ou est (?:mon|ma|mes)\s+.+$",
        r"^comment s'appelle (?:mon|ma|mes)\s+.+$",
        r"^quel(?:le)? (?:systeme|solution|appareil).+j'utilise$",
    )
    if any(re.match(pattern, value) for pattern in personal_recall_patterns):
        return {"matched": True, "kind": "recall", "confidence": 0.95}

    if re.fullmatch(r"qui est [a-z][a-z0-9' ]*", value):
        return {"matched": True, "kind": "recall", "confidence": 0.85}

    return {"matched": False, "kind": None, "confidence": 0.0}
