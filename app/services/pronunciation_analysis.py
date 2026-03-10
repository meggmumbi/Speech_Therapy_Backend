import random
import re
from itertools import zip_longest

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
    - Compound words (passion fruit → passionfruit)
    """

    text = text.lower()

    # First, handle common compound words BEFORE removing spaces
    compound_mappings = {
        r'passion\s+fruit': 'passionfruit',
        r'passion-?fruit': 'passionfruit',
        r'straw\s+berry': 'strawberry',
        r'straw-?berry': 'strawberry',
        r'blue\s+berry': 'blueberry',
        r'blue-?berry': 'blueberry',
        r'pine\s+apple': 'pineapple',
        r'pine-?apple': 'pineapple',
        r'water\s+melon': 'watermelon',
        r'water-?melon': 'watermelon',
    }

    for pattern, replacement in compound_mappings.items():
        text = re.sub(pattern, replacement, text)

    # Remove non-alphabetic characters (but keep spaces for now)
    text = re.sub(r'[^a-z\s-]', '', text)

    # Handle stuttering and partial repetitions
    # Pattern for repeated letters: t-t-tomato
    text = re.sub(r'(\w)[- ]+\1(?:\1[- ]+)*', r'\1', text)

    # Pattern for repeated syllables: to-to-tomato
    text = re.sub(r'(\w{1,3})[- ]+\1(?:[- ]+\1)*', r'\1', text)

    # Handle hyphenated compounds
    text = re.sub(r'-', '', text)

    # Now handle multiple spaces and split
    words = text.split()

    # Take the last attempt if multiple exist (for echolalia/repetition)
    if not words:
        return ""

    # Check if this might be a compound word that wasn't caught
    last_word = words[-1]

    # Common compound words that might be said as two words
    two_word_compounds = {
        'passion fruit': 'passionfruit',
        'straw berry': 'strawberry',
        'blue berry': 'blueberry',
        'pine apple': 'pineapple',
        'water melon': 'watermelon',
        'chocolate cake': 'chocolatecake',
        'ice cream': 'icecream',
    }

    # If we have multiple words, check if they form a compound
    if len(words) >= 2:
        last_two = ' '.join(words[-2:])
        if last_two in two_word_compounds:
            return two_word_compounds[last_two]

    return last_word


def normalize_item_name(name: str) -> str:
    """Normalize item names by removing spaces and handling common variations"""
    # Remove all spaces and convert to lowercase
    normalized = name.lower().replace(" ", "")

    # Add common variations if needed
    variations = {
        "passionfruit": ["passionfruit", "passion fruit"],
        "strawberry": ["strawberry", "straw berry"],
        "blueberry": ["blueberry", "blue berry"],
        "icecream": ["icecream", "ice cream"],
        "firetruck": ["firetruck", "fire truck"],
        "rainbow": ["firetruck", "rain bow"],
        "sunflower": ["sunflower", "sun flower"],

    }

    # Check if this normalized name matches any known variations
    for canonical, variants in variations.items():
        if normalized in variants or name.lower() in variants:
            return canonical

    return normalized


def normalizesentence_disfluencies(text: str) -> str:
    """Normalize ASD speech patterns"""
    # Convert to lowercase and remove punctuation
    text = text.lower()
    text = re.sub(r'[^a-z ]', '', text)

    # Handle stuttering patterns (t-t-tomato → tomato)
    words = []
    for word in text.split():
        # Remove repeated single letters at start
        clean_word = re.sub(r'^(\w)[ -]+\1', r'\1', word)
        # Remove whole word repetitions (tomato tomato → tomato)
        clean_word = re.sub(r'^(\w+)[ -]+\1$', r'\1', clean_word)
        words.append(clean_word)

    return ' '.join(words).strip()

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

    expected = expected.lower().strip()
    actual = actual.lower().strip()
    # Direct match after normalization
    if expected == actual:
        return 1.0

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
    """Comprehensive ASD pronunciation analysis for both words and sentences"""
    # Normalize inputs
    expected_clean = expected.lower().strip()

    # Check if this is a sentence or single word
    is_sentence = len(expected_clean.split()) > 1

    if is_sentence:
        actual_clean = normalizesentence_disfluencies(actual)
        return analyze_sentence_pronunciation(expected_clean, actual_clean)
    else:
        normalize_item_name(actual)
        actual_clean = normalize_disfluencies(actual)
        return analyze_word_pronunciation(expected_clean, actual_clean)


def analyze_word_pronunciation(expected: str, actual: str) -> dict:
    """Analyze pronunciation for single words"""
    expected_clean = re.sub(r'[^a-z]', '', expected.lower())
    actual_clean = normalize_disfluencies(actual)
    original_actual = actual.lower().strip()

    # Handle echolalia for single words
    if is_echolalic(actual):
        return {
            "is_correct": True,
            "similarity_score": 0.95,
            "feedback": "I hear you repeating the word! That's a good start. Now let's try saying it just once together.",
            "phonetic_similarity": 0.95,
            "error_type": "echolalia",
            "substitutions": [],
            "word_analysis": [{
                "word": expected_clean,
                "actual": actual_clean,
                "similarity": 0.95,
                "is_correct": True,
                "error": "echolalia",
                "position": 0
            }],
            "special_case": "echolalia"
        }

    # Calculate similarity and detect errors
    similarity = calculate_asd_similarity(expected_clean, actual_clean)
    error_analysis = detect_pronunciation_errors(expected_clean, actual_clean)
    is_correct = similarity >= 0.7

    # Generate feedback
    feedback = generate_empathetic_feedback(expected_clean, actual_clean, is_correct, similarity, error_analysis)

    return {
        "is_correct": is_correct,
        "similarity_score": similarity,
        "feedback": feedback,
        "phonetic_similarity": similarity,
        "error_type": error_analysis["error_type"],
        "substitutions": error_analysis["substitutions"],
        "word_analysis": [{
            "word": expected_clean,
            "actual": actual_clean,
            "similarity": similarity,
            "is_correct": is_correct,
            "error": error_analysis["error_type"],
            "substitutions": error_analysis["substitutions"],
            "position": 0
        }],
        "special_case": None
    }


def analyze_sentence_pronunciation(expected: str, actual: str) -> dict:
    """Analyze pronunciation for multi-word sentences"""
    expected = normalize_text(expected)
    actual = normalize_text(actual)

    expected_words = expected.split()
    actual_words = actual.split()

    # Handle echolalia for sentences
    if is_echolalic_sentence(expected, actual):
        return {
            "is_correct": True,
            "similarity_score": 0.9,
            "feedback": "Great repeating! You said the whole sentence. Now let's try saying it just once together.",
            "phonetic_similarity": 0.9,
            "error_type": "echolalia",
            "substitutions": [],
            "word_analysis": [],
            "special_case": "echolalia"
        }

    # Analyze each word in the sentence
    word_analyses = []
    total_similarity = 0
    correct_word_count = 0

    for i, (exp_word, act_word) in enumerate(zip_longest(expected_words, actual_words, fillvalue="")):
        if i >= len(actual_words):
            # Missing words
            word_analysis = {
                "word": exp_word,
                "actual": "",
                "similarity": 0,
                "is_correct": False,
                "error": "missing",
                "position": i
            }
        elif i >= len(expected_words):
            # Extra words
            word_analysis = {
                "word": "",
                "actual": act_word,
                "similarity": 0,
                "is_correct": False,
                "error": "extra",
                "position": i
            }
        else:
            # Analyze word pronunciation
            word_similarity = calculate_asd_similarity(exp_word, act_word)
            is_word_correct = word_similarity >= 0.7
            error_analysis = detect_pronunciation_errors(exp_word, act_word)

            word_analysis = {
                "word": exp_word,
                "actual": act_word,
                "similarity": word_similarity,
                "is_correct": is_word_correct,
                "error": error_analysis["error_type"],
                "substitutions": error_analysis["substitutions"],
                "position": i
            }

            if is_word_correct:
                correct_word_count += 1
            total_similarity += word_similarity

    # Calculate overall sentence metrics
    word_count = max(len(expected_words), len(actual_words))
    overall_similarity = total_similarity / word_count if word_count > 0 else 0
    is_sentence_correct = overall_similarity >= 0.7 and correct_word_count >= len(expected_words) * 0.7

    # Generate empathetic feedback for sentences
    feedback = generate_sentence_feedback(expected_words, actual_words, word_analyses, is_sentence_correct,
                                          overall_similarity)

    return {
        "is_correct": is_sentence_correct,
        "similarity_score": overall_similarity,
        "feedback": feedback,
        "phonetic_similarity": overall_similarity,
        "error_type": "sentence_errors",
        "substitutions": get_sentence_substitutions(word_analyses),
        "word_analysis": word_analyses,
        "correct_word_count": correct_word_count,
        "total_word_count": len(expected_words),
        "special_case": None
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


def is_echolalic_sentence(expected: str, actual: str) -> bool:
    """Detect echolalia in sentences"""
    expected_lower = expected.lower().strip()
    actual_lower = actual.lower().strip()

    # Exact match
    if expected_lower == actual_lower:
        return True

    # Repeated phrases
    words = actual_lower.split()
    return len(words) > 3 and len(set(words)) < len(words) * 0.5


def get_sentence_substitutions(word_analyses: list) -> list:
    """Extract all substitutions from word-level analyses"""
    substitutions = []
    for analysis in word_analyses:
        if analysis.get("substitutions"):
            for sub in analysis["substitutions"]:
                substitutions.append({
                    "word": analysis["word"],
                    "position_in_word": sub["position"],
                    "expected": sub["expected"],
                    "actual": sub["actual"],
                    "word_position": analysis["position"]
                })
    return substitutions



def detect_echolalia(expected: str, actual: str) -> bool:
    return expected.strip().lower() == actual.strip().lower()


def detect_pronunciation_errors(expected: str, actual: str) -> dict:
    """Detect specific types of pronunciation errors"""
    substitutions = []
    error_type = "correct"

    # Find sound substitutions
    for i, (exp_char, act_char) in enumerate(zip_longest(expected, actual, fillvalue='')):
        if exp_char != act_char and act_char and exp_char:
            # Check if this is a common substitution pattern
            exp_group = next((g for g in PHONEME_GROUPS if exp_char in g), {exp_char})
            act_group = next((g for g in PHONEME_GROUPS if act_char in g), {act_char})

            if not exp_group.intersection(act_group):
                substitutions.append({
                    "position": i,
                    "expected": exp_char,
                    "actual": act_char,
                    "type": "substitution"
                })

    # Determine primary error type
    if substitutions:
        error_type = "substitution"
    elif len(actual) > len(expected) + 2:  # Likely repetition/stammering in normalized text
        error_type = "repetition"

    return {
        "error_type": error_type,
        "substitutions": substitutions,
        "substitution_count": len(substitutions)
    }


def detect_stuttering(transcription: str) -> dict:
    """Enhanced stuttering detection with repetition counting"""
    words = transcription.lower().split()
    repetition_count = 0
    has_stammering = False

    # Count word repetitions
    for i in range(len(words) - 1):
        if words[i] == words[i + 1]:
            repetition_count += 1
            has_stammering = True

    # Detect sound repetitions within words (stammering)
    for word in words:
        if re.search(r'(\w)\1{2,}', word):  # Triple or more repetition of same character
            has_stammering = True
            break

    return {
        "has_stammering": has_stammering,
        "repetition_count": repetition_count,
        "word_count": len(words)
    }


def generate_empathetic_feedback(expected: str, actual: str, is_correct: bool,
                                 similarity: float, error_analysis: dict) -> str:
    """Generate engaging, empathetic feedback for Pepper to announce"""

    error_type = error_analysis.get("error_type", None)
    print("error_type", error_type)

    if is_correct:
        # Correct responses - 10+ exciting options
        if error_type == "substitution" and error_analysis.get("substitutions"):
            sub = error_analysis["substitutions"][0]
            print("sub", sub)
            options = [
                f"You turned '{sub['actual']}' into '{expected}'. That's magic!",
                f"'{sub['actual']}' became '{expected}'. You fixed it!",
                f"From '{sub['actual']}' to '{expected}'. Perfect fix!",
                f"Wow, '{sub['actual']}' changed into '{expected}'. You're a word wizard!",
                f"You turned that '{sub['actual']}' sound into '{expected}'. Amazing!",
                f"'{sub['actual']}' magically became '{expected}'. Poof!",
                f"You fixed '{sub['actual']}' and said '{expected}'. Super!",
                f"'{sub['actual']}' to '{expected}'. That's how it's done!",
                f"You transformed '{sub['actual']}' into '{expected}'. Brilliant!",
                f"From tricky '{sub['actual']}' to perfect '{expected}'. You rock!",
                f"'{sub['actual']}' disappeared and '{expected}' appeared. Magic!",
                f"You caught that '{sub['actual']}' and said '{expected}'. Excellent catch!",
                f"'{sub['actual']}' tried to hide but you found '{expected}'. Word detective!",
                f"You fixed the sound, '{sub['actual']}' to '{expected}'. High five!",
                f"That '{sub['actual']}' turned into a beautiful '{expected}'. Bravo!"
            ]
            return random.choice(options)

        elif error_type == "repetition":
            options = [
                f"'{expected}' came out smooth and perfect!",
                f"Super smooth '{expected}'. You nailed it!",
                f"'{expected}' rolled off your tongue perfectly!",
                f"No bumps, no stops, just perfect '{expected}'.",
                f"'{expected}' flowed like a river. So smooth!",
                f"Butter smooth '{expected}'. You're a fluency star!",
                f"'{expected}' came out like magic, smooth and easy.",
                f"Smooth operator with '{expected}'. You did it!",
                f"'{expected}' was silky smooth. Fantastic!",
                f"Not a single bump, just beautiful '{expected}'.",
                f"'{expected}' glided out perfectly, like a swan!",
                f"Smooth as glass with '{expected}'. You're amazing!",
                f"'{expected}' came out like a song. So smooth!",
                f"Zero stumbles on '{expected}'. Perfect rhythm!",
                f"'{expected}' was smooth sailing all the way."
            ]
            return random.choice(options)

        # Then handle general correct responses by similarity
        elif similarity >= 0.95:
            options = [
                f"Wow! You said '{expected}' perfectly! I'm so proud of you!",
                f"Amazing job! '{expected}' came out just right. You did it!",
                f"Perfect '{expected}'! Your hard work really paid off!",
                f"Yes! '{expected}' was exactly right. You should be proud!",
                f"Fantastic! You said '{expected}' beautifully. High five!",
                f"Super job! '{expected}' was spot on. You're doing great!",
                f"Excellent! I love how you said '{expected}'. Perfect!",
                f"Way to go! '{expected}' came out wonderful. You're a star!",
                f"Beautiful! '{expected}' sounded just right. Keep it up!",
                f"Great work! You said '{expected}' so clearly. Awesome!",
                f"You did it! '{expected}' was perfect. That's amazing progress!",
                f"Wonderful! '{expected}' came out exactly as it should. Bravo!",
                f"Outstanding! Your '{expected}' was perfect. You're getting so good!",
                f"Perfect pronunciation of '{expected}'! All your practice is working!",
                f"Excellent job with '{expected}'! You said it so clearly and confidently!"
            ]
            return random.choice(options)
        elif similarity >= 0.85:
            options = [
                f"'{actual}' was so close to '{expected}'. Almost there!",
                f"From '{actual}' to '{expected}', you're getting closer!",
                f"'{actual}' to '{expected}'. So close! Keep going!",
                f"'{actual}' almost kissed '{expected}'. Next time!",
                f"You're chasing '{expected}' with that '{actual}'. Good pace!",
                f"'{actual}' is knocking on '{expected}'s door. Open it!",
                f"Just a tiny step from '{actual}' to '{expected}'. You've got this!",
                f"'{actual}' and '{expected}' are becoming best friends!",
                f"'{actual}' whispered '{expected}'. Louder next time!",
                f"You're heating up. '{actual}' to '{expected}' is so close!",
                f"'{actual}' is the cousin of '{expected}'. So close!",
                f"Almost twins, '{actual}' and '{expected}' are nearly identical!",
                f"'{actual}' peeked at '{expected}'. Just a little more!",
                f"One small tweak and '{actual}' becomes '{expected}'. You can do it!",
                f"'{actual}' is hugging '{expected}'. Squeeze a bit tighter!"
            ]
            return random.choice(options)
        else:
            options = [
                f"'{actual}' was a good try. Let's aim for '{expected}' next!",
                f"Warm up with '{actual}'. Now let's try '{expected}'!",
                f"Good attempt at '{actual}'. Now for '{expected}'. Let's go!",
                f"'{actual}' is practice for '{expected}'. Great warm-up!",
                f"You're building up to '{expected}' with '{actual}'. Nice work!",
                f"'{actual}' is your friend. Now meet '{expected}'. Hello there!",
                f"Practice '{actual}' one more time, then let's grab '{expected}'.",
                f"'{actual}' is the appetizer, '{expected}' is the main course. Let's eat!",
                f"First step '{actual}', next step '{expected}'. Climb higher!",
                f"'{actual}' is warming up the stage for '{expected}'. Curtain up!",
                f"You're stretching those muscles with '{actual}'. Now for '{expected}'!",
                f"'{actual}' is good training wheels for '{expected}'. Let's ride!",
                f"Build on '{actual}' to reach '{expected}'. You're getting taller!",
                f"'{actual}' is the seed, '{expected}' is the flower. Grow, grow!",
                f"Keep rolling with '{actual}' until '{expected}' pops out. Here it comes!"
            ]
            return random.choice(options)

    # Incorrect attempts - 10+ encouraging options
    if error_type == "substitution" and error_analysis.get("substitutions"):
        sub = error_analysis["substitutions"][0]
        options = [
            f"I heard '{sub['actual']}'. Let's make '{expected}' together. Watch my mouth!",
            f"Try '{expected}' instead of '{sub['actual']}'. Copy me!",
            f"You said '{sub['actual']}'. Now let's play with '{expected}'. Ready?",
            f"'{sub['actual']}' is tricky. Let's catch '{expected}' together!",
            f"Swap '{sub['actual']}' for '{expected}'. Like magic!",
            f"'{sub['actual']}' stepped aside, now bring in '{expected}'. Come on in!",
            f"Let's replace '{sub['actual']}' with a shiny new '{expected}'.",
            f"'{sub['actual']}' is hiding '{expected}'. Let's find it!",
            f"Instead of '{sub['actual']}', let's try a happy '{expected}'.",
            f"'{sub['actual']}' wants to be '{expected}'. Help it change!",
            f"Cover your '{sub['actual']}' sound and uncover '{expected}'.",
            f"Let's teach '{sub['actual']}' how to become '{expected}'. School time!",
            f"'{sub['actual']}' is sleepy. Wake up '{expected}'. Good morning!",
            f"Shush '{sub['actual']}' and say '{expected}' nice and loud.",
            f"'{sub['actual']}' is the old way. '{expected}' is the new way. Upgrade!"
        ]
        return random.choice(options)

    elif error_type == "repetition":
        options = [
            f"Let's smooth out '{expected}' together. Follow me!",
            f"Say '{expected}' with me, nice and smooth!",
            f"One smooth '{expected}'. Ready? Let's try!",
            f"'{expected}' loves to slide out smoothly. Let's glide!",
            f"No bumps on '{expected}'. Like a calm lake!",
            f"Let's iron out the wrinkles in '{expected}'. Smooth as silk!",
            f"'{expected}' wants to be a smooth roller coaster. Whee!",
            f"Paint '{expected}' with one smooth brush stroke.",
            f"Let's teach '{expected}' to walk without tripping.",
            f"'{expected}' should flow like honey. Sweet and smooth!",
            f"Blow '{expected}' out like a smooth breeze.",
            f"Let's make '{expected}' a skipping stone, skip, skip, skip.",
            f"'{expected}' is a race car on a smooth track. Vroom!",
            f"Squeeze '{expected}' out like toothpaste, nice and smooth.",
            f"Let's zip '{expected}' up like a smooth zipper."
        ]
        return random.choice(options)

    else:
        options = [
            f"You said '{actual}'. Watch me say '{expected}', then you try!",
            f"'{actual}' was close. Let's practice '{expected}' together!",
            f"My turn: '{expected}'. Your turn now. You can do it!",
            f"Echo me: '{expected}'. Then you say it. Like a parrot!",
            f"'{actual}' is knocking. Let's open the door for '{expected}'.",
            f"Follow my lips for '{expected}'. Ready, set, go!",
            f"Copycat time. I say '{expected}', you say '{expected}'.",
            f"Let's build '{expected}' sound by sound. I'll help!",
            f"'{expected}' is hiding in my mouth. Can you find it?",
            f"Mirror me. Watch and say '{expected}'. You've got this!",
            f"Let's catch '{expected}' together. Ready? Catch!",
            f"'{actual}' was warm-up. Now main event: '{expected}'.",
            f"Step by step to '{expected}'. I'll walk with you!",
            f"'{expected}' is a friendly word. Let's be friends!",
            f"One more try for '{expected}'. You're almost there!"
        ]
        return random.choice(options)

def generate_sentence_feedback(expected_words: list, actual_words: list,
                               word_analyses: list, is_correct: bool,
                               similarity: float) -> str:
    """Generate empathetic feedback for sentence responses"""

    correct_count = sum(1 for analysis in word_analyses if analysis.get("is_correct", False))
    total_expected = len(expected_words)

    if is_correct:
        if similarity >= 0.9:
            return "Amazing! You said the whole sentence perfectly! I'm so proud of you! 🌟"
        elif similarity >= 0.8:
            return "Excellent job! You said almost all the words correctly! You're doing wonderful! ✨"
        else:
            return "Good job saying the sentence! You're getting better every time! Let's practice together."

    # Incorrect sentence attempts
    missing_words = [analysis["word"] for analysis in word_analyses if analysis.get("error") == "missing"]
    difficult_words = [analysis["word"] for analysis in word_analyses
                       if not analysis.get("is_correct", True) and analysis.get("error") not in ["missing", "extra"]]

    if missing_words:
        if len(missing_words) == 1:
            return f"You're doing great! Let's try including the word '{missing_words[0]}'. You can do it! 💪"
        else:
            return f"Good attempt! Let's practice including all the words. You're making good progress!"

    elif difficult_words:
        if len(difficult_words) == 1:
            return f"You're working so hard on '{difficult_words[0]}'! Let's try that word together first."
        else:
            return "You're getting closer! Let's practice the tricky words together. I'll help you! 🤝"

    elif len(actual_words) < len(expected_words):
        return "Good start! Let's try saying all the words in the sentence. You're doing amazing!"

    else:
        return "That was a good try! Let me say the sentence first, then we can try together. You're learning so well!"

import re

def normalize_text(text: str) -> str:
    # Remove punctuation but keep apostrophes if needed
    text = re.sub(r"[^\w\s']", "", text)
    return text.lower().strip()
