import Levenshtein
import re
from typing import Tuple


def analyze_pronunciation(expected: str, actual: str) -> dict:
    """
    Analyze pronunciation similarity and provide feedback
    Returns:
        {
            "is_correct": bool,
            "similarity_score": float (0-1),
            "feedback": str,
            "phonetic_similarity": float (0-1)
        }
    """
    # Normalize text
    expected_clean = re.sub(r'[^a-z ]', '', expected.lower())
    actual_clean = re.sub(r'[^a-z ]', '', actual.lower())

    # Calculate similarity metrics
    levenshtein_distance = Levenshtein.distance(expected_clean, actual_clean)
    max_length = max(len(expected_clean), len(actual_clean))
    similarity_score = 1 - (levenshtein_distance / max_length) if max_length > 0 else 0

    # Basic phonetic analysis (simplified)
    phonetic_similarity = calculate_phonetic_similarity(expected_clean, actual_clean)

    # Determine feedback
    if similarity_score >= 0.9:
        return {
            "is_correct": True,
            "similarity_score": similarity_score,
            "feedback": "Excellent! Your pronunciation was perfect.",
            "phonetic_similarity": phonetic_similarity
        }
    elif similarity_score >= 0.7:
        return {
            "is_correct": False,
            "similarity_score": similarity_score,
            "feedback": f"Good try! You said '{actual}'. Try to emphasize the '{get_difference(expected_clean, actual_clean)}' sound.",
            "phonetic_similarity": phonetic_similarity
        }
    else:
        return {
            "is_correct": False,
            "similarity_score": similarity_score,
            "feedback": f"Let's try again. The correct word is '{expected}'. Listen carefully to the sounds.",
            "phonetic_similarity": phonetic_similarity
        }


def calculate_phonetic_similarity(expected: str, actual: str) -> float:
    """Simplified phonetic similarity calculation"""
    # This is a placeholder - consider using a phonetic algorithm like Soundex or Metaphone
    vowel_sounds = {'a', 'e', 'i', 'o', 'u'}
    expected_vowels = [c for c in expected if c in vowel_sounds]
    actual_vowels = [c for c in actual if c in vowel_sounds]

    if not expected_vowels or not actual_vowels:
        return 0.0

    matches = sum(1 for e, a in zip(expected_vowels, actual_vowels) if e == a)
    return matches / max(len(expected_vowels), len(actual_vowels))


def get_difference(expected: str, actual: str) -> str:
    """Identify the differing part between two words"""
    for i, (e, a) in enumerate(zip(expected, actual)):
        if e != a:
            return expected[i:i + 2]  # Return the differing part
    return expected[-1]  # If all else fails, return last character