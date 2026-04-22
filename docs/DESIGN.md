# DESIGN.md — System Design

## How I Started

Before designing anything I watched all five video clips completely. I needed to understand what the cameras actually see before writing any detection logic.

CAM 1 covers the main floor skincare section from 20:10:28 to 20:12:47. I can see one female employee checking products on her phone, a male customer wearing earphones and talking on a call with his face blurred, two more female employees in black uniforms moving around, and one female customer being helped by a staff member to try products.

CAM 2 covers the opposite side of the same floor from 20:10:03 to 20:12:07. Same people visible from a different angle — the female customer trying products, the man on the phone, the employee checking her phone, one employee arranging stock on racks, one helping the customer, one at the billing counter, and one standing next to it.

CAM 3 shows the store entrance from outside. No customer entered the store during the entire clip.

CAM 4 shows an upstairs stockroom. Completely empty throughout. Stairs visible, water cans, bags, small packages. Nobody entered this room.

CAM 5 shows the billing counter from 20:10:28 to 20:12:47. Two employees only. One stocking shelves from a package, one scanning products at the counter. No customer came to billing at any point.

Ground truth: 5 female employees in identical black shirt and black pants, 1 female customer trying products, 1 male customer on a phone call. Seven people total. Zero customer transactions at billing.

This observation shaped every design decision I made.

---

## System Architecture

The system has three layers that work independently of each other.

**Layer 1 - Detection Pipeline**

The pipeline reads each video clip frame by frame using OpenCV. Every second frame is passed to YOLOv8n for person detection. YOLOv8n returns bounding boxes with track IDs — each person gets a persistent ID that follows them across frames.

For each tracked person I do three things. First I classify which zone they are in based on which camera is watching them and where they are in the frame. Second I check if they are staff based on their clothing color. Third I calculate how long they have been in that zone and emit dwell events at regular intervals.

All detections get converted into structured events and saved to a JSONL file. Each line is one event — one thing that happened in the store at a specific timestamp.

**Layer 2 - Ingestion and Storage**

The JSONL file gets sent to a FastAPI endpoint in batches of up to 500 events. Each event is validated by Pydantic before touching the database. Invalid events are rejected individually — one bad event does not kill the whole batch. Valid events go into a single PostgreSQL table on Neon.

The ingest endpoint is idempotent by event_id. If the pipeline runs twice, the second run produces duplicate event_ids and they get silently ignored. This means re-running the pipeline is always safe.

**Layer 3 - Analytics API and Dashboard**

Six REST endpoints query the database and return business metrics. No caching — every request hits the database directly so the store manager always sees current data. A Rich terminal dashboard polls the API every 3 seconds and displays live metrics.

The complete data flow:

CAM 1 through CAM 5 videos go into YOLOv8n detection, then tracker.py builds events, then emit.py saves to detected_events.jsonl, then POST /ingest sends to Neon PostgreSQL, then the API endpoints serve the dashboard.

---

## Zone Classification

Zone classification is how the system knows which part of the store a person is in.

My first approach was to use the camera itself as the zone. Since each camera covers a fixed area of the store, whoever appears in CAM 1 is in the SKINCARE section, whoever appears in CAM 5 is at the BILLING counter. This works perfectly for CAM 1, CAM 3, CAM 4, and CAM 5.

CAM 2 is the only camera that covers two zones — MAKEUP on the left side of the frame and ACCESSORIES on the right side. I asked AI to help me think through the zone boundary logic for this camera.

**Prompt I gave to Claude:**

"CAM 2 covers two zones — MAKEUP on the left side of the store and ACCESSORIES on the right side. The frame is 1280x720. How should I split the frame to classify which zone a detected person is in? Should I use a fixed pixel boundary, relative position, or something else? The camera angle is fixed and the zones do not overlap physically."

**What AI suggested:**

Claude suggested using a relative boundary at 60% of frame width rather than a fixed pixel value. The reason was that relative boundaries are resolution-independent — if the video resolution changes, the boundary automatically scales. A fixed pixel value like 768px would break if the clip was recorded at a different resolution.

**What I implemented:**

I used the horizontal center of each person's bounding box. If it is less than 60% of frame width, the person is in MAKEUP. If it is 60% or more, they are in ACCESSORIES. This worked correctly in testing.

**Did it work?**

Mostly yes. The boundary held up well for people clearly on one side. The edge case is someone standing exactly at the boundary — they could flicker between MAKEUP and ACCESSORIES across frames. I handled this with a 5-second debounce on ZONE_ENTER events, so a person has to stay on one side for at least 5 seconds before a new zone enter is recorded.

---

## Staff Detection

After watching the videos I knew exactly what staff looks like — all five employees wear identical black shirts and black pants. The male customer wears different clothing and the female customer also wears different colors.

I designed a two-signal staff detection approach.

**Signal 1 - Camera role override**

Anyone detected in CAM 4 (stockroom) or CAM 5 (billing counter) is automatically classified as staff. No customer should be in the stockroom. And from watching CAM 5, I confirmed no customer came to billing during the entire clip. This camera-based override is 100% reliable for these two cameras.

**Signal 2 - Clothing brightness for floor cameras**

For CAM 1 and CAM 2 I crop the bounding box of each detected person and analyze the RGB values of the clothing area — specifically the middle 60% of the crop to avoid background noise. Black uniforms have low brightness below 70 and low color variation with standard deviation below 40.

**What AI suggested:**

Claude initially suggested HSV color space analysis for better color discrimination. I tested this but found it added complexity without meaningful improvement on this specific footage because the store lighting is consistent enough that simple RGB brightness works reliably.

**Limitation I observed:**

The same person sometimes flickers between staff and customer classification across frames because store lighting changes slightly as people move. The man on the phone was correctly classified as non-staff in most frames, which matched my observation from watching the video. But some staff members with slightly lighter black clothing in certain lighting conditions got misclassified occasionally. A production system would solve this with a trained binary classifier on store-specific data.

---

## Entry Detection - Virtual Tripwire

CAM 3 faces the store entrance. The problem I noticed when watching it is that you can see people outside the store through the glass door. Without special handling, the model would count window shoppers as store visitors.

I solved this with a virtual tripwire — an invisible horizontal line drawn at 60% of the frame height. A person is only counted as entering when their bounding box center crosses from above this line to below it. Crossing from below to above counts as an exit.

This means a person visible through the glass door but standing still outside never crosses the tripwire and never gets counted. Only someone physically walking through the door and moving toward the camera triggers an ENTRY event.

From the footage I confirmed this worked — CAM 3 detected 0 customer entries because no customer walked through the door during the clip. Only staff movements near the entrance generated EXIT and ENTRY events.

---

## Edge Cases I Handled

**Glass door false positives:** Solved with the virtual tripwire on CAM 3.

**Empty stockroom:** CAM 4 correctly produced 0 events because no one entered the room.

**All-staff billing counter:** CAM 5 correctly flagged all detections as staff because of the camera role override.

**Ghost tracks:** Short-lived detections from reflections or partial occlusions. Solved by requiring a minimum of 8 frames before a track is considered real. CAM 3 requires 12 frames because the entrance area has more visual noise from outside light.

**Duplicate zone events:** A person detected in 300 consecutive frames would generate 300 ZONE_ENTER events without debouncing. Solved with a 5-second debounce per visitor per zone. CAM 2 uses 8 seconds because it has more people in frame simultaneously.

**Re-entry:** If a visitor exits and comes back, the SessionTracker increments their session count and emits a REENTRY event instead of a second ENTRY.

**Mixed database ingest:** If the pipeline runs twice, duplicate event_ids are detected and silently rejected. The database always contains exactly one copy of each event.

---

## Validation Against Ground Truth

After running the full pipeline I compared the output against what I personally observed in the videos.

CAM 4 produced 0 events — correct, the stockroom was empty.
CAM 3 produced 4 events — 2 exits and 2 staff entries — correct, no customers entered.
CAM 5 produced 78 events all marked is_staff true — correct, only staff at billing.
CAM 1 produced 114 events covering the skincare section.
CAM 2 produced 185 events covering makeup and accessories.

The main limitation is staff detection flickering on the floor cameras due to lighting variation. The unique visitor count is higher than the actual 7 people because the same physical person gets a different visitor ID on each camera — cross-camera re-identification is not implemented. This is a known limitation.

Conversion rate shows 0% which is correct — no customer reached the billing counter during the footage window, and the POS transaction timestamps predate the footage window. The correlation logic is correct and will work properly with real overlapping POS data.
