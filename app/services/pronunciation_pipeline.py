import re

import Levenshtein
from metaphone import doublemetaphone
from g2p_en import G2p
import nltk
from num2words import num2words

nltk.download('averaged_perceptron_tagger_eng')

from nltk.corpus import cmudict




g2p = G2p()
cmu_dict = cmudict.dict()

# Common pronunciation problems for Kenyan speakers
KENYAN_PRONUNCIATION_PATTERNS = {
    ("L", "R"): "Focus on the 'L' sound. Touch your tongue to the roof of your mouth.",
    ("R", "L"): "Focus on the 'R' sound. Round your lips slightly.",
    ("TH", "T"): "Place your tongue gently between your teeth for the 'TH' sound.",
    ("V", "F"): "Use your teeth and bottom lip to produce the 'V' sound.",
    ("SH", "S"): "Push air through your lips to make the 'SH' sound."
}


# ------------------------------------------------
# TEXT NORMALIZATION
# ------------------------------------------------

def normalize_text(text):
    text = text.lower()
    text = re.sub(r'[^\w\s]', '', text)

    words = text.split()
    normalized_words = []

    for word in words:
        if word.isdigit():
            try:
                normalized_words.append(num2words(int(word)))
            except:
                normalized_words.append(word)
        else:
            normalized_words.append(word)

    return " ".join(normalized_words).strip()



# ------------------------------------------------
# PHONEME EXTRACTION
# ------------------------------------------------

def get_phonemes(word):

    word = word.lower()

    if word in cmu_dict:
        return cmu_dict[word][0]

    # fallback using g2p
    phonemes = g2p(word)

    return [p for p in phonemes if p != " "]


# ------------------------------------------------
# LEVENSHTEIN SIMILARITY
# ------------------------------------------------

def compute_similarity(expected, actual):

    distance = Levenshtein.distance(expected, actual)

    return 1 - distance / max(len(expected), len(actual))


# ------------------------------------------------
# LETTER SUBSTITUTION DETECTION
# ------------------------------------------------

def detect_letter_substitutions(expected, actual):

    substitutions = []

    min_len = min(len(expected), len(actual))

    for i in range(min_len):

        if expected[i] != actual[i]:

            substitutions.append({
                "position": i,
                "expected": expected[i],
                "actual": actual[i]
            })

    return substitutions


# ------------------------------------------------
# PHONEME COMPARISON
# ------------------------------------------------

def detect_phoneme_errors(expected_word, actual_word):

    expected_ph = get_phonemes(expected_word)
    actual_ph = get_phonemes(actual_word)

    errors = []

    # If identical → no errors
    if expected_ph == actual_ph:
        return errors

    min_len = min(len(expected_ph), len(actual_ph))

    for i in range(min_len):
        if expected_ph[i] != actual_ph[i]:
            errors.append({
                "position": i,
                "expected": expected_ph[i],
                "actual": actual_ph[i]
            })

    return errors


# ------------------------------------------------
# PHONETIC MATCH USING METAPHONE
# ------------------------------------------------

def phonetic_similarity(expected, actual):

    expected_ph = get_phonemes(expected)
    actual_ph = get_phonemes(actual)

    if not expected_ph or not actual_ph:
        return False

    return expected_ph == actual_ph


# ------------------------------------------------
# ERROR CLASSIFICATION
# ------------------------------------------------

def classify_error(similarity, phonetic_match, phoneme_errors):

    if phonetic_match and not phoneme_errors:
        return "correct"

    # Exact match (safe fallback)
    if similarity == 1:
        return "correct"

    # Minor pronunciation issues
    if phoneme_errors and phonetic_match:
        return "minor_pronunciation_error"

    # Close attempt
    if similarity > 0.7:
        return "close_pronunciation"

    return "incorrect"


# ------------------------------------------------
# THERAPY FEEDBACK GENERATION
# ------------------------------------------------

def generate_feedback(expected, actual, phoneme_errors, substitutions, error_type):

    if error_type == "correct":
        return f"Great job! You pronounced '{expected}' correctly."

    if phoneme_errors:

        error = phoneme_errors[0]

        expected_ph = error["expected"]
        actual_ph = error["actual"]

        for pattern in KENYAN_PRONUNCIATION_PATTERNS:

            if expected_ph.startswith(pattern[0]) and actual_ph.startswith(pattern[1]):

                tip = KENYAN_PRONUNCIATION_PATTERNS[pattern]

                return (
                    f"Nice try! You said '{actual}'. "
                    f"The correct word is '{expected}'. "
                    f"It sounds like '{actual_ph}' instead of '{expected_ph}'. "
                    f"{tip} Try again."
                )

        return (
            f"Good try! You said '{actual}', but the correct pronunciation is '{expected}'. "
            f"Listen carefully and try again."
        )

    if substitutions:

        sub = substitutions[0]

        return (
            f"Nice try! You said '{actual}'. "
            f"It looks like '{sub['actual']}' was used instead of '{sub['expected']}'. "
            f"Let's try saying '{expected}' again."
        )

    return f"Let's try again. The correct word is '{expected}'."


# ------------------------------------------------
# WORD LEVEL ANALYSIS
# ------------------------------------------------

def analyze_word(expected_word, actual_word):

    expected_word = normalize_text(expected_word)
    actual_word = normalize_text(actual_word)

    similarity = compute_similarity(expected_word, actual_word)

    phonetic_match = phonetic_similarity(expected_word, actual_word)

    substitutions = detect_letter_substitutions(expected_word, actual_word)

    phoneme_errors = detect_phoneme_errors(expected_word, actual_word)

    if phonetic_match and not phoneme_errors:
        substitutions = []
        similarity = 1.0

    error_type = classify_error(similarity, phonetic_match, phoneme_errors)

    feedback = generate_feedback(
        expected_word,
        actual_word,
        phoneme_errors,
        substitutions,
        error_type
    )

    return {
        "expected": expected_word,
        "actual": actual_word,
        "similarity_score": round(similarity, 2),
        "phonetic_match": phonetic_match,
        "phoneme_errors": phoneme_errors,
        "substitutions": substitutions,
        "error_type": error_type,
        "feedback": feedback,
        "is_correct": error_type == "correct"
    }


# ------------------------------------------------
# SENTENCE LEVEL ANALYSIS
# ------------------------------------------------
def generate_sentence_feedback(word_analysis, expected_sentence):
    """
    Generate comprehensive feedback for sentence pronunciation
    """
    correct_words = [w for w in word_analysis if w["is_correct"]]
    incorrect_words = [w for w in word_analysis if not w["is_correct"]]

    total_words = len(word_analysis)
    correct_count = len(correct_words)

    # If all words are correct
    if correct_count == total_words:
        return "Excellent! You pronounced the entire sentence correctly!"

    # Build feedback for incorrect words
    if incorrect_words:
        # Get unique incorrect words with their issues
        word_feedback = []
        for word_result in incorrect_words:
            expected = word_result["expected"]
            actual = word_result["actual"]
            error_type = word_result["error_type"]

            if error_type == "close_pronunciation":
                word_feedback.append(f"'{expected}' (you said '{actual}' - close!)")
            else:
                word_feedback.append(f"'{expected}' (you said '{actual}')")

        # Create feedback message
        if len(word_feedback) == 1:
            wrong_words_text = word_feedback[0]
            feedback = f"Good try! Let's practice {wrong_words_text} again."
        else:
            # Join with commas and 'and' for the last item
            if len(word_feedback) > 1:
                wrong_words_text = ", ".join(word_feedback[:-1]) + f" and {word_feedback[-1]}"
            else:
                wrong_words_text = word_feedback[0]

            feedback = f"Good effort! Pay attention to {wrong_words_text}. Let's practice these words."

        # Add encouragement based on progress
        if correct_count > total_words / 2:
            feedback = f"You got {correct_count} out of {total_words} words correct! " + feedback
        else:
            feedback = f"You correctly said {correct_count} words. " + feedback

        return feedback

    return "Let's practice the entire sentence again."


def analyze_sentence(expected_sentence, actual_sentence):
    """
    Analyze sentence pronunciation with detailed word-by-word comparison
    """
    expected_words = normalize_text(expected_sentence).split()
    actual_words = normalize_text(actual_sentence).split()

    results = []

    # Handle cases where user says more or fewer words
    max_len = max(len(expected_words), len(actual_words))

    for i in range(max_len):
        if i < len(expected_words) and i < len(actual_words):
            # Both expected and actual words exist
            word_result = analyze_word(expected_words[i], actual_words[i])

            # Add position information for better tracking
            word_result["position"] = i
            word_result["expected_word"] = expected_words[i]
            word_result["actual_word"] = actual_words[i]

            results.append(word_result)

        elif i < len(expected_words):
            # User missed a word (said fewer words)
            results.append({
                "expected": expected_words[i],
                "actual": "[missing]",
                "similarity_score": 0.0,
                "phonetic_match": False,
                "phoneme_errors": [],
                "substitutions": [],
                "error_type": "missing_word",
                "feedback": f"You missed the word '{expected_words[i]}'",
                "is_correct": False,
                "position": i,
                "expected_word": expected_words[i],
                "actual_word": None
            })
        else:
            # User added extra words
            results.append({
                "expected": "[unexpected]",
                "actual": actual_words[i],
                "similarity_score": 0.0,
                "phonetic_match": False,
                "phoneme_errors": [],
                "substitutions": [],
                "error_type": "extra_word",
                "feedback": f"You added an extra word '{actual_words[i]}'",
                "is_correct": False,
                "position": i,
                "expected_word": None,
                "actual_word": actual_words[i]
            })

    correct_count = sum(1 for r in results if r["is_correct"])
    total_expected = len(expected_words)
    similarity = correct_count / total_expected if total_expected > 0 else 0

    # Generate appropriate feedback
    feedback = generate_sentence_feedback(results, expected_sentence)

    return {
        "word_analysis": results,
        "correct_word_count": correct_count,
        "total_word_count": total_expected,
        "similarity_score": round(similarity, 2),
        "feedback": feedback
    }


# ------------------------------------------------
# MAIN ENTRY FUNCTION
# ------------------------------------------------

def analyse_pronunciation(expected, actual):
    """
    Main entry function for pronunciation analysis
    """
    if len(expected.split()) > 1:
        # Sentence analysis
        sentence_analysis = analyze_sentence(expected, actual)

        # Calculate if the entire sentence is correct
        is_fully_correct = (
                sentence_analysis["correct_word_count"] == sentence_analysis["total_word_count"]
        )

        # Collect all substitutions from incorrect words for error tracking
        all_substitutions = []
        for word_result in sentence_analysis["word_analysis"]:
            if not word_result["is_correct"] and "substitutions" in word_result:
                all_substitutions.extend(word_result["substitutions"])

        return {
            "is_correct": is_fully_correct,
            "similarity_score": sentence_analysis["similarity_score"],
            "word_analysis": sentence_analysis["word_analysis"],
            "correct_word_count": sentence_analysis["correct_word_count"],
            "total_word_count": sentence_analysis["total_word_count"],
            "error_type": "sentence_errors" if not is_fully_correct else "correct",
            "substitutions": all_substitutions,
            "feedback": sentence_analysis["feedback"],
            # Add summary of incorrect words for quick reference
            "incorrect_words": [
                {
                    "expected": w["expected"],
                    "actual": w["actual"],
                    "error_type": w["error_type"]
                }
                for w in sentence_analysis["word_analysis"]
                if not w["is_correct"]
            ]
        }
    else:
        # Single word analysis
        word_result = analyze_word(expected, actual)

        # Add sentence-level fields for consistency
        word_result["word_analysis"] = [word_result.copy()]
        word_result["correct_word_count"] = 1 if word_result["is_correct"] else 0
        word_result["total_word_count"] = 1
        word_result["incorrect_words"] = [] if word_result["is_correct"] else [{
            "expected": expected,
            "actual": actual,
            "error_type": word_result["error_type"]
        }]

        # Ensure error_type is set (should be from analyze_word, but just in case)
        if "error_type" not in word_result:
            word_result["error_type"] = "correct" if word_result["is_correct"] else "incorrect"

        return word_result
