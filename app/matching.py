import re
from typing import Any


# Explicit-text signals for human review only. They are not weighted, scored,
# or used to rank housing applicants.
SIGNALS: dict[str, dict[str, Any]] = {
    'shared_wg_life': {
        'label': 'Shared WG life',
        'keywords': [
            'zusammen kochen', 'gemeinsam kochen', 'wg-abend', 'wg abend', 'spieleabend',
            'gemeinsam zeit', 'zusammen zeit', 'wg leben', 'wg-leben', 'freundschaftlich',
            'gesellig', 'quatschen', 'zusammen raus', 'shared dinner', 'cook together',
            'spend time together', 'social flatshare',
        ],
    },
    'cleanliness': {
        'label': 'Cleanliness & shared chores',
        'keywords': [
            'ordentlich', 'sauberkeit', 'sauber', 'putzplan', 'putzen', 'aufräumen',
            'clean', 'cleanliness', 'tidy', 'chores',
        ],
    },
    'privacy_and_boundaries': {
        'label': 'Privacy & respectful boundaries',
        'keywords': [
            'privatsphäre', 'privatsphaere', 'rückzug', 'rueckzug', 'ruhe', 'respekt',
            'respektvoll', 'privacy', 'quiet time', 'own space', 'boundaries',
        ],
    },
    'reliability_and_communication': {
        'label': 'Reliability & communication',
        'keywords': [
            'zuverlässig', 'zuverlaessig', 'verlässlich', 'verlaesslich', 'kommunikation',
            'absprechen', 'bescheid sagen', 'unkompliziert', 'responsible', 'reliable',
            'dependable', 'communicat',
        ],
    },
    'friends_and_social_life': {
        'label': 'Friends / social life',
        'keywords': [
            'freunde', 'freundinnen', 'gäste', 'gaeste', 'besuch', 'party', 'feiern',
            'konzert', 'theater', 'sport', 'hobby', 'friends', 'guests', 'social life',
        ],
    },
    'viewing_and_move_in': {
        'label': 'Viewing / move-in logistics',
        'keywords': [
            'besichtigung', 'online', 'video call', 'videocall', 'vor ort', 'einzug',
            'zwischenmiete', 'untermiete', 'sublet', 'viewing', 'move in', 'available',
            'flexibel',
        ],
    },
}


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+|\n+', text) if s.strip()]


def _contains_any(text: str, values: list[str]) -> bool:
    low = text.casefold()
    return any(value in low for value in values)


def _detail_summary(text: str) -> dict[str, Any]:
    words = re.findall(r"\b[\w'’-]+\b", text, flags=re.UNICODE)
    topics = {
        'personal_intro': _contains_any(text, ['ich bin', 'mein name', 'über mich', 'about me']),
        'work_or_study': _contains_any(text, ['studiere', 'studium', 'student', 'studentin', 'arbeite', 'job', 'beruf', 'ausbildung', 'work']),
        'hobbies_or_social_life': _contains_any(text, ['freizeit', 'hobby', 'sport', 'freunde', 'freundinnen', 'theater', 'konzert', 'wandern', 'tanze', 'volleyball']),
        'wg_expectations': _contains_any(text, ['wg leben', 'wg-leben', 'mir wäre eine wg', 'mir waere eine wg', 'gemeinsam', 'zusammen kochen', 'privatsphäre', 'privatsphaere']),
        'move_in_or_duration': _contains_any(text, ['einzug', 'ab sofort', 'ab dem', 'zwischenmiete', 'untermiete', 'monate', 'move in', 'sublet']),
        'viewing_availability': _contains_any(text, ['besichtigung', 'flexibel', 'vorbeikommen', 'online', 'video call', 'videocall', 'viewing']),
    }
    covered = sum(topics.values())
    normalized = text.casefold()
    availability_only = (
        len(words) <= 20
        and any(phrase in normalized for phrase in [
            'noch frei', 'noch verfügbar', 'noch verfuegbar', 'noch da',
            'is it available', 'still available', 'zimmer noch frei',
        ])
    )
    if availability_only or (len(words) < 25 and covered <= 1):
        level = 'sparse'
    elif len(words) >= 90 or covered >= 5:
        level = 'detailed'
    else:
        level = 'medium'
    return {
        'level': level,
        'detail_level': level,
        'word_count': len(words),
        'covered_topics': covered,
        'wg_topics_mentioned': covered,
        'topics': topics,
        'availability_only': availability_only,
        'note': 'Measures how much relevant information was provided, not applicant suitability.',
    }


def extract_application_signals(text: str, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    """Surface explicit application facts and WG-value evidence for human review."""
    normalized = text.casefold()
    sentences = _sentences(text)
    criteria = []

    for key, config in SIGNALS.items():
        matched = [kw for kw in config['keywords'] if kw in normalized]
        evidence: list[str] = []
        if matched:
            for sentence in sentences:
                low = sentence.casefold()
                if any(keyword in low for keyword in matched):
                    evidence.append(sentence[:280])
                if len(evidence) >= 2:
                    break
        criteria.append({
            'key': key,
            'label': config['label'],
            'mentioned': bool(matched),
            'evidence': evidence,
        })

    return {
        'profile': profile or {},
        'application_detail': _detail_summary(text),
        'criteria': criteria,
        'note': (
            'Structured summary from explicit application/profile information only. '
            'Volunteered age, gender and other profile facts can be displayed for roommates, '
            'but sensitive traits are not used to score, rank, or recommend housing applicants.'
        ),
    }
