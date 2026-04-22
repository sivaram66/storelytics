# CHOICES.md — Technical Decisions

Before I wrote a single line of code, I watched all five video clips carefully to understand what I was actually dealing with and note down them in a notebook with timestamps Here is what I observed :

CAM 1 runs from 20:10:28 to 20:12:47. I can see one female employee checking products while looking at her phone I think she is checking the product details from phone, and one man standing nearby wearing earphones he is clearly a customer on a phone call, not staff. His face is blurred in the footage. There are also two more female employees in black outfits moving around the floor and one female customer being helped by a staff member to try products.

CAM 2 runs from 20:10:03 to 20:12:07. This is the opposite side of the same floor CAM 1. The same people are visible the female customer who is trying the products the man on the phone,  the employee checking her phone and checking the products(stock) on racks, one employee arranging stock on racks, one helping the customer try products, one standing at the billing counter, and one standing next to it doing nothing.

CAM 3 shows the store entrance from outside. The timestamp is blurred but the clip is around 2 minutes 28 seconds. No customer entered the store during this entire clip.

CAM 4 shows what looks like an upstairs stockroom from 20:09:46 to 20:12:11. It is completely empty throughout. I can see stairs, water cans, bags, and small packages. Nobody came into this room.

CAM 5 shows the billing counter from 20:09:28 to 20:12:06. Two employees are present the whole time. One is taking products from a package and placing shelves. The other is scanning products at the counter and putting them back. No customer came to billing at any point through whole video.

So the ground truth is: 5 female employees in black uniforms, 1 female customer trying products, 1 male customer on a phone call. Total 7 people. Zero customer transactions at billing.

I made all my technical decisions based on this observation first, then used AI to evaluate the options.

---

## Decision 1 — Detection Model: YOLOv8n

**Options I considered:** YOLOv8n, YOLOv9, RT-DETR These are the models I though to use but

The most important constraint I had was my system -- Nvidia GTX 1650 Ti with 4GB VRAM and 8GB RAM. These resources are shared across everything: the model, the tracker, the analytics code, and the operating system itself.
So these are specs and I cant run the heavy model on my system if I write to run heavy model sytem may get slow and cant even evaluate the videos they stop in the middle 

So then I looked at the official Ultralytics documentation(https://docs.ultralytics.com/models/yolov8/#performance-metrics) and found that YOLOv8n has only 3.2M parameters and 8.7 GFLOPs, with a mAP of 37.3 on COCO. It runs comfortably within my 4GB VRAM budget, leaving room for everything else to run simultaneously.

YOLOv9 and RT-DETR are more accurate but significantly heavier. If I try to use them they wil take a whole VRAM and RAM  When I thought about what would happen if I ran them on my system — the model alone would eat most of the VRAM, leaving no space for the ByteTrack style tracker, the dwell time calculations, or the staff detection logic. On larger clips, RAM usage would spike and processing would stop midway. I have seen this happen on my machine before with other heavy models.


**What AI suggested:** Claude suggested starting with YOLOv8n and confirmed the resource reasoning. I agreed with this because it matched what I already knew from my own experience with my machine.

**What I chose and why:** YOLOv8n. The accuracy trade-off is real a larger model would catch more detections — but a model that crashes halfway through processing five video clips is useless. I set confidence threshold at 0.45 after testing, which reduced false positives from reflections and partial occlusions without missing real detections.

One thing I noticed from watching the videos: the man on the phone has his face blurred, which means YOLO cannot use face features to detect him. It relies purely on body shape and clothing. YOLOv8n handled this correctly in most frames.

---

## Decision 2 — Event Schema: Single Table with JSONB

**Options I considered:** One events table with JSONB metadata, or separate tables per event type (entry_events, zone_dwell_events, billing_events, etc.)

When I thought about separate tables, the first problem I saw was how hard it would be to add new event types. If tomorrow the business wants to add a new event type like PRODUCT_PICKUP, with separate tables I would need to create a new table, update the schema, modify the backend ingestion logic, and update every query that touches events.That's a lot of effort for something that should be simple.

With one events table, I just start sending the new event type and it gets stored. The metadata JSONB column handles any event-specific fields that do not fit the common structure. The core fields that every event shares — event_id, store_id, camera_id, visitor_id, event_type, timestamp, zone_id, is_staff, confidence — are proper columns with indexes on them.



Another reason I preferred a single events table is that it avoids joins entirely. Since all event types are stored in one place, I don’t need to join or union multiple tables to compute analytics. This keeps queries simpler and also improves performance, especially for things like reconstructing a visitor’s journey or calculating dwell time.

The second problem with separate tables is querying. If I want to see all the events of visitor VIS_AE08F5 — when they entered, which zones they visited, how long they stayed — I would need to write UNION queries across multiple tables. With one table it is a single SELECT with a WHERE clause on visitor_id. Clean and fast.

I do lose strict database-level type checking on the metadata fields. To handle this I validate everything at the ingestion layer using Pydantic before it touches the database. Invalid confidence scores, unknown event types, malformed timestamps — all rejected before the INSERT.


**What AI suggested:** Claude suggested using a single events table, which I agreed with. One place I thought about differently was how to store fields like queue_depth. The suggestion was to keep it inside the metadata JSON, but I initially felt it might be important enough to store as a separate column since it’s something we might query often

**What I chose and why:** After thinking it through, I decided to keep it in JSONB. PostgreSQL handles JSONB queries quite efficiently, and adding a separate column would complicate the schema for a relatively small benefit. So I kept it in metadata, but I do see it as a trade-off.

For timestamps, I decided to store everything in IST (+05:30) since the store is in Mumbai. Initially, AI suggested using UTC, which is the standard for APIs, but when I looked at the actual video footage, all the timestamps there were in IST.

During debugging, I realized it would be much easier if the timestamps in the database matched what I was seeing in the video directly. Otherwise, I'd constantly have to convert between UTC and IST in my head.
So I chose to stick with IST throughout. It made debugging and validation much more straightforward, even though it’s slightly different from the usual convention.
---

## Decision 3 — API Architecture: No Caching

**Options I considered:** Direct database queries on every request OR an in-memory cache with a TTL (time-to-live) of 5 minutes.

I choose to skip the caching one because this is a live retail analytics system. The whole point is that a store manager can look at the dashboard and see what is happening right now not what was happening 5 minutes ago. Events are constantly being ingested as cameras send new data. If I cache the metrics response and a store manager opens the dashboard right after a batch of events comes in, they will see stale numbers. That defeats the purpose.

At our current scale around 380 events total for one store the database queries return in under 100 milliseconds. There is no performance problem to solve. Caching would add complexity without any real benefit at this scale.

I also thought about what happens if the cache and the database get out of sync during a deployment or a pipeline restart. Debugging stale cache issues in a production retail system where accuracy matters is painful. Removing the cache entirely removes that whole class of bugs.

**What AI suggested:** Claude also agreed with the no-cache approach for this use case and scale. One thing it suggested, which I did think about seriously, was using materialized views in PostgreSQL to pre-aggregate metrics.
That's actually a solid approach for a production system handling millions of events. But in this case, we’re only dealing with a few hundred events, so it felt like over-engineering.
I decided to keep things simple with direct queries for now, and just note that materialized views would be the right next step if the system scales.

**What I chose and why:** No caching. Every request hits the database directly. This gives the store manager accurate real-time data. If event volume grows to millions of records, the correct path is pre-aggregated materialized views updated by a background job — not an application-level cache.

---

## Note on Staff Detection

One thing I want to be honest about: the staff detection using clothing brightness thresholds works but is not perfect. I set brightness < 70 and color variation < 40 to classify someone as staff wearing a black uniform.

When I watched the videos I could clearly identify all 5 employees — they all wear identical black shirt and black pants. But the model flickered on some of them, sometimes classifying the same person as staff in one frame and customer in the next, because the store lighting changes as people move.

AI suggested this brightness-based approach and I implemented it. In hindsight, a better approach would be training a small binary classifier specifically on crops from this store's footage — staff versus customer. But that requires labeled training data which I did not have. So I used the brightness threshold as a practical approximation and documented the limitation honestly.

The man on the phone with earphones and blurred face was correctly identified as a non-staff customer in most frames, which matched my observation from watching the video.
