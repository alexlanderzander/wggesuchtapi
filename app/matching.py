import re
from typing import Any


# Explicit-text signals only. These are displayed as evidence for human review;
# they are not weighted, scored, or used to rank housing applicants.
SIGNALS: dict[str, dict[str, Any]] = {
    'shared_wg_life': {
        'label': 'Shared WG life mentioned',
        'keywords': [
            'zusammen kochen', 'gemeinsam kochen', 'wg-abend', 'wg abend', 'spieleabend',
            'gemeinsam zeit', 'zusammen zeit', 'wg leben', 'wg-leben',
            'shared dinner', 'cook together', 'spend time together',
        ],
    },
    'cleaning_routines': {
        'label': 'Cleaning / shared chores mentioned',
        'keywords': [
            'ordentlich', 'sauberkeit', 'sauber', 'putzplan', 'putzen', 'aufräumen',
            'clean', 'cleanliness', 'tidy', 'chores',
        ],
    },
    'privacy_boundaries': {
        'label': 'Privacy / personal space mentioned',
        'keywords': [
            'privatsphäre', 'privatsphaere', 'rückzug', 'rueckzug', 'ruhe', 'respekt',
            'privacy', 'quiet time', 'own space',
        ],
    },
    'viewing_logistics': {
        'label': 'Viewing / move-in logistics mentioned',
        'keywords': [
            'besichtigung', 'online', 'video call', 'videocall', 'vor ort', 'einzug',
            'zwischenmiete', 'untermiete', 'sublet', 'viewing', 'move in', 'available',
        ],
    },
}


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+|\n+', text) if s.strip()]


def extract_application_signals(text: str) -> dict[str, Any]:
    """Surface explicit statements without making a housing recommendation."""
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
        'criteria': criteria,
        'note': (
            'Evidence summary from explicit application text only. '
            'No score or recommendation is produced; roommates make the housing decision.'
        ),
    }
