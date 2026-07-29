"""Seed content: the daily prompt pools and themed collections.

Re-running the app never deletes your entries. Seed prompts are only inserted
once per collection (on first creation). You can add/edit/disable prompts later
from the Settings screen or directly in the database.
"""

# ---------------------------------------------------------------------------
# DAILY collection — the semi-random pool that drives the every-few-days rhythm.
# kind is "factual" (quick, concrete) or "reflective" (longer, open).
# ---------------------------------------------------------------------------

DAILY_FACTUAL = [
    "What did you do today, in three or four quick lines?",
    "What did you eat today that you actually noticed?",
    "Who did you talk to today, and about what?",
    "Where did you spend most of your time today?",
    "What did you read, watch, or listen to today?",
    "What was the high point of the day, factually — what happened and when?",
    "What was the low point of the day?",
    "What did you make, finish, or fix today?",
    "What did you spend money on today?",
    "What's one small thing you noticed today that you'd otherwise forget?",
    "What did your body feel like today — energy, sleep, aches, appetite?",
    "What's currently on your mind that you haven't written down yet?",
    "What did the weather do today, and did it change anything for you?",
    "What's one thing you said yes to, and one you said no to, today?",
    "What's a number from today worth recording (steps, hours, count of anything)?",
]

DAILY_MORNING_FACTUAL = [
    "What did you do yesterday, in three or four quick lines?",
    "What did you eat yesterday that you actually noticed?",
    "Who did you talk to yesterday, and about what?",
    "What did you read, watch, or listen to yesterday?",
    "What was the high point of yesterday — what happened and when?",
    "What was the low point of yesterday?",
    "What did you make, finish, or fix yesterday?",
    "How did you sleep last night, and how do you feel this morning?",
    "What's one small thing from yesterday you'd otherwise forget?",
    "What's already on your mind for today?",
]

DAILY_REFLECTIVE = [
    "What's a thought you've been circling lately? Try to put it into words and push it one step further than usual.",
    "What's something you changed your mind about recently, even a little?",
    "What are you reading or watching right now, and what is it doing to your thinking?",
    "Describe your mood right now without using the word 'fine'. Where do you feel it?",
    "What's something you're looking forward to, and what's underneath that feeling?",
    "What's been quietly bothering you that you haven't said out loud?",
    "What did someone say recently that stuck with you, and why?",
    "What's a small decision you're sitting with? Lay out how you're actually weighing it.",
    "What's a topic you keep coming back to? What draws you to it?",
    "Write about something you noticed this week that most people would walk past.",
    "What would you do with an unexpected free afternoon right now, and what does that say about what you need?",
    "What's a tension you're holding between two things you both want?",
    "Who have you been thinking about lately, and what's the thought?",
    "What's a belief you hold that you'd have a hard time defending? Try anyway.",
    "What felt meaningful recently, even if it was small or hard to explain?",
    "What's draining you right now, and what's restoring you?",
    "If you reread this entry in a year, what would you want it to remind you of?",
    "What's a question you don't have an answer to yet, but want to keep thinking about?",
    "What's something you're proud of that you haven't told anyone?",
    "Describe a moment from the last few days in as much sensory detail as you can.",
]

# ---------------------------------------------------------------------------
# Labor & Delivery — imported as a themed collection (worked through at your
# own pace, separate from the daily rhythm).
# ---------------------------------------------------------------------------

LABOR_DELIVERY = [
    ("factual", "Date of birth:"),
    ("factual", "Time of birth:"),
    ("factual", "Day of the week:"),
    ("factual", "Where you gave birth (hospital, birth center, home, etc.):"),
    ("factual", "How many weeks pregnant you were; was the baby early, late, or on time?"),
    ("factual", "Baby's name (and any name story worth noting):"),
    ("factual", "Weight and length at birth:"),
    ("factual", "Who delivered the baby (name, role):"),
    ("factual", "Who else was present (partner, family, doula, friend, photographer):"),
    ("factual", "Total length of labor, type of birth, and pain management used:"),
    ("reflective", "What was the very first sign that something was different? When did you first think 'this might be it'?"),
    ("reflective", "How were you feeling, physically and emotionally, in the days leading up?"),
    ("reflective", "How did early labor unfold, and how did you pass the time before it got serious?"),
    ("reflective", "Describe the room you labored in — what you saw, smelled, heard, the lighting, the temperature."),
    ("reflective", "How would you describe what contractions felt like at their hardest? Reach for images, comparisons, sounds."),
    ("reflective", "Who was the most helpful person in the room, and what specifically did they do?"),
    ("reflective", "What did the shift into transition or pushing feel like? How did you know things were changing?"),
    ("reflective", "What do you remember about the moment the baby was born — sensations, sounds, what people said?"),
    ("reflective", "What did the baby look like the first time you saw them? Be honest; don't smooth it."),
    ("reflective", "What was your first emotion when you held them? It doesn't have to be the one you're 'supposed' to feel."),
    ("reflective", "What were the first minutes and hours like — the fog, the adrenaline, who came and went?"),
    ("reflective", "What decisions were made during labor — by you or for you — that you want to remember the details of?"),
    ("reflective", "Was there a moment of fear, of dissociation, of surrender, or of unexpected tenderness? Describe it."),
    ("reflective", "What's something you've never said out loud about this birth that you want written down?"),
    ("reflective", "What is the single image, sound, or sensation that comes to mind first when you think about the birth now?"),
    ("reflective", "What surprised you most — about labor, your body, yourself, or the people around you?"),
    ("reflective", "If this birth could be remembered for one thing, what would you want it to be?"),
]

# ---------------------------------------------------------------------------
# A starter template for ad-hoc deep journaling about a one-off event.
# ---------------------------------------------------------------------------

EVENT_TEMPLATE = [
    ("factual", "What happened, and when? Date, time, place."),
    ("factual", "Who was there?"),
    ("reflective", "Walk through it from the beginning, in whatever order it comes."),
    ("reflective", "What's the sharpest detail you remember right now?"),
    ("reflective", "What were you feeling as it happened? And now?"),
    ("reflective", "What did you notice that someone else there might have missed?"),
    ("reflective", "What do you want to make sure you never forget about this?"),
    ("reflective", "How do you think you'll feel about this in a year?"),
]


def seed_collections():
    """Returns the collections to create on first run.

    Each: (name, description, kind, is_daily, prompts)
    where prompts is a list of (kind, text). For DAILY we combine the pools.
    """
    daily_prompts = (
        [("factual", t) for t in DAILY_FACTUAL]
        + [("reflective", t) for t in DAILY_REFLECTIVE]
    )
    return [
        ("Daily", "Your ongoing life journal — semi-random prompts every few days.",
         "daily", 1, daily_prompts),
        ("Labor & Delivery", "A guided record of your birth, in your own words.",
         "themed", 0, LABOR_DELIVERY),
        ("Deep Dive: An Event", "A reusable template for journaling a specific event in depth.",
         "template", 0, EVENT_TEMPLATE),
    ]
