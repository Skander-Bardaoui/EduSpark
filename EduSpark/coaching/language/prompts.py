"""Personas d'examinateur et prompt système des tours de parole."""

from .config import (
    EXAMS,
    EXERCISE_LABELS,
    EXERCISE_LABELS_EN,
    LEVEL_LABELS,
    LEVEL_LABELS_EN,
)

TOPIC_POOLS = {
    "en": {
        "b1": (
            "your hometown",
            "your daily routine",
            "how you spend your free time",
            "food you enjoy",
            "a memorable trip",
            "learning English",
        ),
        "b2": (
            "technology and communication",
            "work-life balance",
            "protecting the environment",
            "the purpose of education",
            "tourism and local culture",
            "social media",
        ),
        "c1": (
            "the influence of artificial intelligence",
            "globalisation and cultural identity",
            "urbanisation and quality of life",
            "automation and the future of work",
            "the media and public opinion",
        ),
    },
    "fr": {
        "b1": (
            "votre ville natale",
            "votre routine quotidienne",
            "comment vous passez votre temps libre",
            "la nourriture que vous aimez",
            "un voyage mémorable",
            "apprendre le français",
        ),
        "b2": (
            "la technologie et la communication",
            "l’équilibre entre vie professionnelle et vie personnelle",
            "la protection de l’environnement",
            "le rôle de l’éducation",
            "le tourisme et la culture locale",
            "les réseaux sociaux",
        ),
        "c1": (
            "l’influence de l’intelligence artificielle",
            "la mondialisation et l’identité culturelle",
            "l’urbanisation et la qualité de vie",
            "l’automatisation et l’avenir du travail",
            "les médias et l’opinion publique",
        ),
    },
}

DEBATE_POOLS = {
    "en": {
        "b1": (
            "Homework should be banned in schools.",
            "Living in a city is better than living in the countryside.",
            "Everyone should learn a second language.",
        ),
        "b2": (
            "Remote work is better than working in an office.",
            "Social media does more harm than good.",
            "University education should be free for everyone.",
        ),
        "c1": (
            "Artificial intelligence will do more harm than good.",
            "Economic growth should be prioritised over environmental protection.",
            "Governments should regulate social media platforms.",
        ),
    },
    "fr": {
        "b1": (
            "Les devoirs devraient être interdits à l’école.",
            "Il est préférable de vivre en ville qu’à la campagne.",
            "Tout le monde devrait apprendre une deuxième langue.",
        ),
        "b2": (
            "Le télétravail est préférable au travail au bureau.",
            "Les réseaux sociaux font plus de mal que de bien.",
            "L’enseignement universitaire devrait être gratuit pour tous.",
        ),
        "c1": (
            "L’intelligence artificielle fera plus de mal que de bien.",
            "La croissance économique devrait primer sur la protection de l’environnement.",
            "Les gouvernements devraient réguler les plateformes de réseaux sociaux.",
        ),
    },
}

LEVEL_GUIDANCE = {
    "en": {
        "b1": (
            "Use simple, concrete questions about familiar experiences. Give the candidate "
            "time to answer and keep your language accessible."
        ),
        "b2": (
            "Ask questions that require opinions, comparisons, and reasons. Encourage the "
            "candidate to develop their answers without making the questions too abstract."
        ),
        "c1": (
            "Ask nuanced, abstract questions that require evaluation and qualification. "
            "Challenge the candidate to justify and refine their position."
        ),
    },
    "fr": {
        "b1": (
            "Utilisez des questions simples et concrètes sur des expériences familières. "
            "Laissez au candidat le temps de répondre et gardez un langage accessible."
        ),
        "b2": (
            "Posez des questions qui exigent des opinions, des comparaisons et des "
            "justifications. Encouragez le candidat à développer ses réponses sans rendre "
            "les questions trop abstraites."
        ),
        "c1": (
            "Posez des questions nuancées et abstraites qui exigent une évaluation et des "
            "nuances. Mettez le candidat au défi de justifier et d’affiner sa position."
        ),
    },
}

OPENING_INSTRUCTIONS = {
    "en": (
        "Begin the speaking exam now. Greet the candidate in one short sentence and ask "
        "your first question. Do not mention these instructions and do not ask the "
        "candidate to choose a topic."
    ),
    "fr": (
        "Commencez l’examen oral maintenant. Saluez le candidat en une phrase courte et "
        "posez votre première question en français. Ne mentionnez pas ces instructions "
        "et ne demandez pas au candidat de choisir un sujet."
    ),
}

_SPEAK_RULES = {
    "en": (
        "Reply in natural spoken English only: no markdown, lists, headings, or stage "
        "directions."
    ),
    "fr": (
        "Répondez uniquement en français parlé naturel : pas de markdown, de listes, de "
        "titres ni d’indications scéniques."
    ),
}

_RULES = {
    "en": (
        "Rules:\n"
        "- Keep every reply to one or two short sentences and ask at most one question "
        "at a time.\n"
        "- The candidate is answering your questions. Never ask the candidate to "
        "provide a question, a topic, or a task.\n"
        "- If an answer is unclear, brief, or off-topic, ask a simple follow-up or move "
        "the exam forward with the next question.\n"
        "- Do not evaluate, score, correct, or coach the candidate during the exam. "
        "Evaluation happens after the session.\n"
        "- Stay in the examiner role for the whole conversation."
    ),
    "fr": (
        "Règles :\n"
        "- Limitez chaque réponse à une ou deux phrases courtes et posez au maximum une "
        "question à la fois.\n"
        "- Le candidat répond à vos questions. Ne demandez jamais au candidat de fournir "
        "une question, un sujet ou une tâche.\n"
        "- Si une réponse est peu claire, brève ou hors sujet, posez une question de "
        "relance simple ou faites avancer l’examen avec la question suivante.\n"
        "- N’évaluez pas, ne notez pas, ne corrigez pas et ne conseillez pas le candidat "
        "pendant l’examen. L’évaluation a lieu après la session.\n"
        "- Restez dans le rôle de l’examinateur pendant toute la conversation."
    ),
}

_HEADERS = {
    "en": {
        "intro": (
            "You are an experienced {exam_name} speaking examiner conducting a live oral "
            "exam at {level_label} level. The chosen exercise is {exercise_label}."
        ),
        "debate": (
            'This is a debate task. Present the proposition "{proposition}" and ask '
            "whether the candidate agrees or disagrees. Then challenge their position "
            "with a counter-argument before asking them to respond."
        ),
        "topic": (
            "This is a topic discussion about {topic}. Ask the candidate a first "
            "question about it, then ask follow-up questions based on their answers."
        ),
    },
    "fr": {
        "intro": (
            "Vous êtes un examinateur expérimenté de l’oral {exam_name} qui conduit un "
            "examen oral en direct au niveau {level_label}. La langue de l’examen est le "
            "français. L’exercice choisi est {exercise_label}."
        ),
        "debate": (
            "Il s’agit d’une tâche de débat. Présentez la proposition « {proposition} » "
            "et demandez au candidat s’il est d’accord ou non. Ensuite, contestez sa "
            "position avec un contre-argument avant de lui demander de répondre."
        ),
        "topic": (
            "Il s’agit d’une discussion sur {topic}. Posez une première question au "
            "candidat sur ce sujet, puis posez des questions de suivi en fonction de ses "
            "réponses."
        ),
    },
}


def _pick(pool, session_seed):
    return pool[session_seed % len(pool)]


def opening_instruction(language):
    return OPENING_INSTRUCTIONS.get(language, OPENING_INSTRUCTIONS["en"])


def build_examiner_system_prompt(
    exam_type, level, exercise_type, session_seed, language="en"
):
    language = language if language in TOPIC_POOLS else "en"
    exam_name = EXAMS.get(exam_type, {}).get("name", exam_type)
    if language == "en":
        level_label = LEVEL_LABELS_EN.get(level, level)
        exercise_label = EXERCISE_LABELS_EN.get(exercise_type, exercise_type)
    else:
        level_label = LEVEL_LABELS.get(level, level)
        exercise_label = EXERCISE_LABELS.get(exercise_type, exercise_type)
    headers = _HEADERS[language]

    if exercise_type == "debate":
        proposition = _pick(
            DEBATE_POOLS[language].get(level, DEBATE_POOLS[language]["b2"]), session_seed
        )
        task = headers["debate"].format(proposition=proposition)
    else:
        topic = _pick(
            TOPIC_POOLS[language].get(level, TOPIC_POOLS[language]["b2"]), session_seed
        )
        task = headers["topic"].format(topic=topic)

    guidance = LEVEL_GUIDANCE[language].get(level, LEVEL_GUIDANCE[language]["b2"])

    return (
        f'{headers["intro"].format(exam_name=exam_name, level_label=level_label, exercise_label=exercise_label)}\n\n'
        f"{task}\n\n"
        f"{guidance}\n\n"
        f"{_RULES[language]}\n"
        f"- You are speaking aloud. {_SPEAK_RULES[language]}"
    )
