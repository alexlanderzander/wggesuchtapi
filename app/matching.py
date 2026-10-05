import re
from typing import Any


RUBRIC: dict[str, dict[str, Any]] = {
    'social_wg': {
        'label': 'Shared WG life',
        'weight': 30,
        'keywords': [
            'zusammen kochen', 'gemeinsam kochen', 'wg-abend', 'wg abend', 'spieleabend',
            'gemeinsam zeit', 'zusammen zeit', 'gesellig', 'quatschen', 'unternehm', 'freundschaftlich',
            'wg leben', 'wg-leben', 'shared dinner', 'cook together', 'spend time together', 'social',
        ],
    },
    'cleanliness': {
        'label': 'Cleanliness & shared chores',
        'weight': 25,
        'keywords': [
            'ordentlich', 'sauberkeit', 'sauber', 'putzplan', 'putzen', 'aufräumen',
            'clean', 'cleanliness', 'tidy', 'chores',
        ],
    },
    'privacy': {
        'label': 'Privacy & respectful boundaries',
        'weight': 20,
        'keywords': [
            'privatsphäre', 'privatsphaere', 'rückzug', 'rueckzug', 'ruhe', 'respekt', 'respektvoll',
            'privacy', 'respect', 'quiet time', 'own space',
        ],
    },
    'reliability': {
        'label': 'Reliability & communication',
        'weight': 15,
        'keywords': [
            'zuverlässig', 'zuverlaessig', 'verlässlich', 'unkompliziert', 'kommunikation', 'absprechen',
            'reliable', 'communicat', 'dependable', 'responsible',
        ],
    },
    'logistics': {
        'label': 'Viewing / move-in flexibility',
        'weight': 10,
        'keywords': [
            'flexibel', 'besichtigung', 'online', 'video call', 'videocall', 'vor ort', 'einzug',
            'zwischenmiete', 'untermiete', 'sublet', 'viewing', 'move in', 'available',
        ],
    },
}


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+|\n+', text) if s.strip()]


def score_application(text: str) -> dict[str, Any]:
    normalized = text.casefold()
    sentences = _sentences(text)
    criteria = []
    weighted_points = 0.0
    total_weight = sum(item['weight'] for item in RUBRIC.values())

    for key, config in RUBRIC.items():
        matched = [kw for kw in config['keywords'] if kw in normalized]
        evidence = []
        if matched:
            for sentence in sentences:
                low = sentence.casefold()
                if any(keyword in low for keyword in matched):
                    evidence.append(sentence[:280])
                if len(evidence) >= 2:
                    break
            signal = 1.0
            weighted_points += config['weight']
            state = 'positive evidence'
        else:
            signal = 0.0
            state = 'not mentioned'
        criteria.append({
            'key': key,
            'label': config['label'],
            'weight': config['weight'],
            'signal': signal,
            'state': state,
            'evidence': evidence,
        })

    score = round(100 * weighted_points / total_weight)
    return {
        'score': score,
        'criteria': criteria,
        'note': 'Pre-screen coverage score based only on explicit application text; not an acceptance decision.',
    }
