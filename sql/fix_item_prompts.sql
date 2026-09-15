-- Corrections to activity_item prompts that teach the wrong pronunciation.
--
-- These are STUDY MATERIALS, not code. Read every statement before running it:
-- each one changes what the robot says to a participant, and therefore what
-- the participant produces and what the scorer is then judging.
--
-- Every UPDATE matches on the exact current text, so it is idempotent and
-- cannot touch the duplicate rows that carry only the bare word as their
-- description. Run inside the transaction and check the row counts.
--
-- Found while investigating attempts that the pipeline scored wrong. In each
-- case below the scorer was right and the prompt was wrong: a participant who
-- does what the robot asks produces a form that is not the word.

BEGIN;

-- 1. Colonel is /'k3:n@l/, "KER-nul" -- two syllables, no "lo".
--    The prompt taught a three-syllable spelling pronunciation.
UPDATE activity_items SET description =
  'This is a high ranking army officer. The word is colonel. Listen: KER-nul. Now you try saying colonel.'
WHERE description =
  'This is a high ranking army officer. The word is colonel. Listen CO-LO-NEL. Now you try saying CO-LO-NEL';

-- 2. "DRA-UGHT" is the spelling read out, not a pronunciation. Draught is
--    "DRAHFT" -- the whole point of the item is that spelling misleads.
UPDATE activity_items SET description =
  'This word describes cool air moving in a room. The word is draught. Listen: DRAHFT. Now you try saying draught.'
WHERE description =
  'This word describes cool air moving in a room. The word is draught. Listen: DRA-UGHT. Now you try saying draught.';

-- 3. Mauve is /m@Uv/, "mohv". The prompt modelled "mowv" and then asked for
--    "mawve" -- two different vowels, neither of them the word. Both study
--    attempts came back as "M AW TH"/"M OW TH": the participant said what the
--    robot asked for, and was marked wrong for it.
UPDATE activity_items SET description =
  'Look at the color in the picture. The word is mauve. Listen: mohv. Now say mauve.'
WHERE description =
  'Look at the color in the picture. The word is mauve. Listen: mowv. Now say mawve.';

-- 4. gaucherie had the word and the model form swapped, so "Listen:" was
--    followed by the spelling and the participant was asked to repeat the
--    phonetic respelling.
UPDATE activity_items SET description =
  'This word describes a social mistake. The word is gaucherie. Listen: goh-shuh-REE. Now try saying gaucherie.'
WHERE description =
  'This word describes a social mistake. The word is goh-shuh-REE. Listen: gaucherie. Now try saying goh-shuh-REE.';

-- 5. Onomatopoeia never modelled the word at all -- "List carefully" is a typo
--    for "Listen carefully", and nothing followed it. The participant heard
--    the word once, at prompt speed, with no slow form. Both attempts came
--    back missing whole syllables.
UPDATE activity_items SET description =
  'Some words sound like the noise they describe. The word is onomatopoeia. Listen carefully: on-uh-mat-uh-PEE-uh. Now try saying onomatopoeia.'
WHERE description =
  'Some words sound like the noise they describe. The word Onomatopoeia. List carefully. Now try saying Onomatopoeia.';

-- 6. parallelogram also modelled no slow form. Unlike the others it scored
--    correctly anyway, so this is consistency rather than a bug fix: every
--    other advanced item gives a syllable-by-syllable model and this one asks
--    the participant to "try your best".
UPDATE activity_items SET description =
  'This is a very long word! The word is parallelogram. Listen carefully: pa-ruh-LEL-uh-gram. Now try saying parallelogram.'
WHERE description =
  'This is a very long word!. The word is parallelogram. Listen carefully and try your best to repeat it. Parallelogram';

-- Expect 6 rows changed. If any statement reports 0 the text has already been
-- fixed or has drifted -- check before committing.
COMMIT;
