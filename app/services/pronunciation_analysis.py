import re
from Levenshtein import distance as levenshtein_distance
from metaphone import doublemetaphone
from collections import Counter

# Enhanced phoneme groups for ASD speech patterns
PHONEME_GROUPS = [
    {'r', 'l', 'w', 'ɹ', 'ʋ'},  # All liquid/glide variations
    {'s', 'sh', 'z', 'th', 'f', 'θ', 'ð'},  # Fricatives
    {'t', 'd', 'ʔ', 'ɾ'},  # Stops and flaps
    {'k', 'g', 'q'},  # Velars
    {'m', 'n', 'ŋ'},  # Nasals
    {'p', 'b', 'β'},  # Bilabials
    {'ch', 'sh', 'j', 'zh'},  # Affricates
    {'ah', 'a', 'æ', 'ə'},  # Vowel variations
    {'oh', 'o', 'ɔ', 'ow'},  # Back vowels
    {'ee', 'i', 'ɪ', 'iy'},  # Front vowels
]

VOWEL_SOUNDS = {'a', 'e', 'i', 'o', 'u', 'y', 'æ', 'ɑ', 'ɛ', 'ɪ', 'ɔ', 'ʊ', 'ʌ', 'ə'}


def normalize_disfluencies(text: str) -> str:
    """Normalize ASD speech patterns including:
    - Stuttering (t-t-tomato)
    - Partial repetitions (to-to-tomato)
    - Whispered speech
    - Echolalia
    """
    # Convert to lowercase and remove punctuation
    text = text.lower()
    text = re.sub(r'[^a-z ]', '', text)

    # Handle stuttering and partial repetitions
    text = re.sub(r'\b(\w)[- ]+\1', r'\1', text)  # t-tomato → tomato
    text = re.sub(r'(\w+)[ -]+\1', r'\1', text)  # tomato tomato → tomato

    # Take the last attempt if multiple exist
    words = text.split()
    return words[-1] if words else ""


def is_echolalic(actual: str) -> bool:
    """Detect immediate echolalia patterns"""
    words = actual.lower().split()
    return len(words) > 1 and len(set(words)) == 1


def get_phonetic_variants(word: str) -> set:
    """Generate possible ASD phonetic variants"""
    variants = set()
    for i in range(len(word)):
        # Generate substitutions for each phoneme group
        for group in PHONEME_GROUPS:
            if word[i] in group:
                for sound in group:
                    variants.add(word[:i] + sound + word[i + 1:])
    return variants


def calculate_asd_similarity(expected: str, actual: str) -> float:
    """Specialized similarity metric for ASD speech"""
    # Generate all acceptable variants
    expected_variants = get_phonetic_variants(expected) | {expected}

    # Check for direct matches
    if actual in expected_variants:
        return 1.0

    # Phonetic similarity with relaxed thresholds
    expected_meta = doublemetaphone(expected)
    actual_meta = doublemetaphone(actual)

    # Primary metaphone match
    if expected_meta[0] and expected_meta[0] == actual_meta[0]:
        return 0.9

    # Secondary metaphone match
    if expected_meta[1] and expected_meta[1] == actual_meta[1]:
        return 0.8

    # Length-adjusted similarity
    lev_dist = levenshtein_distance(expected, actual)
    max_len = max(len(expected), len(actual), 1)
    base_score = 1 - (lev_dist / max_len)

    # Boost score for ASD patterns
    asd_boosts = [
        (0.2, lambda: abs(len(expected) - len(actual)) <= 2),  # Length difference
        (0.15, lambda: expected[0] == actual[0]),  # Initial sound match
        (0.1, lambda: expected[-1] == actual[-1]),  # Final sound match
    ]

    for boost, condition in asd_boosts:
        if condition():
            base_score = min(1.0, base_score + boost)

    return base_score


def analyze_pronunciation(expected: str, actual: str) -> dict:
    """Comprehensive ASD pronunciation analysis"""
    # Normalize inputs
    expected_clean = re.sub(r'[^a-z]', '', expected.lower())
    actual_clean = normalize_disfluencies(actual)

    # Handle echolalia first
    if is_echolalic(actual):
        return {
            "is_correct": True,
            "similarity_score": 0.95,
            "feedback": "Good repeating! Now try saying it just once.",
            "phonetic_similarity": 0.95,
            "special_case": "echolalia"
        }

    # Calculate specialized similarity
    similarity = calculate_asd_similarity(expected_clean, actual_clean)

    # Determine correctness with ASD-friendly thresholds
    is_correct = similarity >= 0.7

    # Generate developmentally appropriate feedback
    if is_correct:
        if similarity >= 0.9:
            feedback = "Perfect! You said it just right!"
        else:
            diff = get_most_different_sound(expected_clean, actual_clean)
            feedback = f"Great try! Very close - the '{diff}' sound was almost perfect!"
    else:
        diff = get_most_different_sound(expected_clean, actual_clean)
        feedback = f"Let's practice together: '{expected}'. Focus on the '{diff}' sound."

    return {
        "is_correct": is_correct,
        "similarity_score": similarity,
        "feedback": feedback,
        "phonetic_similarity": similarity,
        "special_case": "echolalia" if is_echolalic(actual) else None
    }


def get_most_different_sound(expected: str, actual: str) -> str:
    """Identify the most divergent phoneme"""
    for i, (e_char, a_char) in enumerate(zip(expected, actual)):
        if e_char != a_char:
            # Find which phoneme group they belong to
            e_group = next((g for g in PHONEME_GROUPS if e_char in g), {e_char})
            a_group = next((g for g in PHONEME_GROUPS if a_char in g), {a_char})

            # If in different groups, return context
            if not e_group.intersection(a_group):
                return f"{a_char}→{e_char}"

    return expected[:2]  # Default to first syllable if no clear difference

# def get_difference(expected: str, actual: str) -> str:
#     """Find the first differing sound"""
#     expected_norm = normalize_phonemes(expected)
#     actual_norm = normalize_phonemes(actual)
#
#     for i, (e, a) in enumerate(zip(expected_norm, actual_norm)):
#         if e != a:
#             # Return context around the difference
#             start = max(0, i-1)
#             return expected[start:i+2]
#
#     return expected[-1] if expected else ""


def detect_stuttering(transcription: str) -> bool:
    words = transcription.lower().split()
    for i in range(len(words) - 1):
        if words[i] == words[i + 1]:
            return True
    return False


def detect_echolalia(expected: str, actual: str) -> bool:
    return expected.strip().lower() == actual.strip().lower()
