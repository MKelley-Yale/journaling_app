# Journal — a private, self-hosted journaling app

A private journaling app that runs on a desktop and reaches phone or laptop via Tailscale. Every few days it prompts at a random time with quick and reflective questions about the day. Long-form collections can be triggered on demand for major milestones. Past entries resurface at random for reflection. Captures weather and locks behind a PIN.

---

## Overview

**Goal.** Journal is a private journaling app built for a single person, run on their own computer. Rather than facing a blank page, the writer is nudged every few days with a rotating set of quick and reflective questions, building an ongoing record of daily life that can be revisited and added to over time.

**What makes it different.** Most journaling apps are cloud services: they need an account and keep entries on a company's servers. Journal is self-hosted and single-user — it runs on the owner's desktop, the data never leaves that machine, and by default there is no account,
no company, and no third party involved. Two further differences shape how it feels to use.
It is *prompt-driven* rather than a blank page: it actively probes with semi-random questions and brings old entries back for fresh reflection. And *privacy is the default, not a setting*: optional AI follow-ups send nothing anywhere unless an API key is deliberately added, and phone access runs over a private Tailscale network instead of the public internet.

**Features at a glance.** Semi-random daily prompts (quick and reflective), themed collections for deep dives, opt-in AI "go deeper" follow-ups, resurfacing of old entries, a searchable history and a calendar, photo attachments, a 48-hour editing window, weather captured from location, push reminders, PIN lock, and a dark theme. Each is detailed below.

---

## What's in the box

- **Daily collection** — semi-random prompts (half quick/factual, half reflective). Before
  noon it asks about *yesterday*; later in the day, about *today*. Buttons pull more factual
  or more reflective prompts, swap an unwanted prompt, or switch to free-writing.
- **Themed collections** — self-contained question sets worked through at any pace, separate
  from the daily rhythm. Ships with **Labor & Delivery** and a reusable **Deep Dive: An Event**
  template; new collections can be created anytime.
- **Go deeper (opt-in AI)** — any answer can get one AI follow-up question. With no API key it
  uses built-in templates and nothing leaves the machine; adding a key in `.env` enables
  smarter, tailored follow-ups.
- **Look Back** — browse and search past entries; open one to add dated reflections later.
- **Calendar** — a month grid marking which days have entries. Selecting a day shows that
  day's entries and opens any of them; arrows move between months.
- **Editing (48-hour window)** — for 48 hours after an entry is created, its answers can be
  edited, photos added or removed, or the entry deleted. After that it is fixed, keeping the
  record honest. Reflections can still be added to old entries anytime.
- **Resurface** — "From the past" surfaces an old answer (favoring roughly a year ago) and
  invites a follow-up thought.
- **Reminders** — a push notification every 3–4 days at a random time within a set window
  (8am–10pm by default), with one follow-up that day if ignored, then it lets go.
- **Photos** — one or more photos can be attached to any entry, from camera or library,
  viewed full-size, and removed later.
- **PIN lock**, automatic timestamps, and weather captured from location on save.
- **Dark theme** throughout, easy on the eyes for evening writing.

Everything is configurable on the **Settings** screen.

---

## One-time setup (desktop)

Requires **Python 3.11+** (from python.org — during install, tick *"Add Python to PATH"*).

1. Place the `journal-app` folder somewhere permanent.
2. Double-click **`run.bat`**. The first run creates a private environment, installs
   dependencies, and starts the server (a couple of minutes the first time).
3. Once `Starting journal on http://localhost:8000` appears, opening that address in a
   browser on the desktop confirms it loads. A PIN is set on first launch.

After that, double-clicking `run.bat` starts it again.

> Entries live in a single file, `journal.db`, alongside a `photos/` folder for attached
> images. Both sit in the **parent** folder, one level up from this code folder — so the data
> isn't mixed in with the app's source and survives replacing or reinstalling `journal-app/`.
> **Backing up means copying `journal.db` and the `photos/` folder** together somewhere safe
> (external drive, etc.); restoring is just putting them back.
>
> To store the data elsewhere, set `JOURNAL_DATA_DIR` (or the individual `JOURNAL_DB` /
> `JOURNAL_PHOTOS_DIR`) before launching.

---

## Reaching it from a phone (and laptop) over Tailscale

The desktop is the server; Tailscale gives the phone a secure HTTPS address for it.

1. In the **Tailscale admin console**, enable **MagicDNS** and **HTTPS Certificates**
   (Settings → Features). This lets Tailscale issue the `https://…ts.net` address that iPhone
   push notifications and "Add to Home Screen" require.
2. With `run.bat` running, open a second terminal in this folder and run:

   ```
   tailscale serve --bg https / http://localhost:8000
   ```

   Tailscale prints the app's address, something like `https://desktop-name.tailXXXX.ts.net`.
   (To stop sharing later: `tailscale serve reset`.)
3. That address can be added to `.env` as `PUBLIC_ORIGIN=` (copy `.env.example` to `.env`
   first). Optional but recommended.
4. On the **iPhone** (with the Tailscale app installed and connected):
   - Open the `https://…ts.net` address in **Safari**.
   - Share → **Add to Home Screen**, then open the app from that icon (this step is what lets
     iOS allow notifications).
   - Enter the PIN, then go to **Settings → Enable reminders on this device** and allow
     notifications; **Send test** confirms one arrives.
   - Allowing **location** on the first saved entry enables weather capture.
5. On a **laptop**, the same `https://…ts.net` address opens in any browser.

---

## Keeping reminders working

Reminders fire only while the desktop is awake and `run.bat` is running. For random daytime
reminders, the desktop should not sleep during the day:

- Windows → Settings → System → Power → set *Sleep* to *Never* while plugged in, or long
  enough to cover the day.

Push notifications are delivered by Apple, so they arrive even if Tailscale is off — but
opening and using the app requires Tailscale connected on the phone.

---

## Optional: smarter AI follow-ups

"Go deeper" works with zero setup (template questions, fully local). For tailored follow-ups,
copy `.env.example` to `.env` and add **one** key:

- `ANTHROPIC_API_KEY=...` (optionally `ANTHROPIC_MODEL=`), or
- `OPENAI_API_KEY=...` (optionally `OPENAI_MODEL=`)

With a key set, the text of the answer being expanded is sent to that provider to generate
the follow-up — nothing else, and only on request. Restart `run.bat` after editing `.env`.

---

## Good to know

- **Editing window:** entries lock 48 hours after creation. To change it, edit the
  `EDIT_WINDOW_HOURS` constant near the top of the edit section in `server.py`.
- **Push timing** is best-effort — Apple controls delivery, so notifications are generally
  reliable once enabled but not precise to the minute.
- **Unlocking** uses a PIN.

