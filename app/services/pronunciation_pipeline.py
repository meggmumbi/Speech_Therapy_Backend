import Levenshtein
from metaphone import doublemetaphone
from g2p_en import G2p
import nltk

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
    return text.lower().strip()


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

    exp_meta = doublemetaphone(expected)[0]
    act_meta = doublemetaphone(actual)[0]

    return exp_meta == act_meta


# ------------------------------------------------
# ERROR CLASSIFICATION
# ------------------------------------------------

def classify_error(similarity, phonetic_match, phoneme_errors):

    if similarity == 1:
        return "correct"

    if phoneme_errors and phonetic_match:
        return "minor_pronunciation_error"

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

def analyze_sentence(expected_sentence, actual_sentence):

    expected_words = normalize_text(expected_sentence).split()
    actual_words = normalize_text(actual_sentence).split()

    results = []

    min_len = min(len(expected_words), len(actual_words))

    for i in range(min_len):

        word_result = analyze_word(
            expected_words[i],
            actual_words[i]
        )

        results.append(word_result)

    correct_count = sum(1 for r in results if r["is_correct"])

    return {
        "word_analysis": results,
        "correct_word_count": correct_count,
        "total_word_count": len(expected_words)
    }


# ------------------------------------------------
# MAIN ENTRY FUNCTION
# ------------------------------------------------

def analyse_pronunciation(expected, actual):

    if len(expected.split()) > 1:

        sentence_analysis = analyze_sentence(expected, actual)

        similarity = sentence_analysis["correct_word_count"] / sentence_analysis["total_word_count"]

        return {
            "is_correct": similarity == 1,
            "similarity_score": round(similarity, 2),
            "word_analysis": sentence_analysis["word_analysis"],
            "correct_word_count": sentence_analysis["correct_word_count"],
            "total_word_count": sentence_analysis["total_word_count"],
            "feedback": "Let's practice the words again."
        }

    else:

        return analyze_word(expected, actual)
