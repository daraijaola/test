# Open questions, side by side (6,062 posts)

Same reader (Opus 5.5, medium effort). Ledger = theme view held as a cached system prompt. RAG = BM25 top-k.

| method | mean $ / question | mean cache-read tokens | mean uncached input tokens |
|---|---|---|---|
| ledger | $0.133 | 63,556 | 12,037 |
| rag20 | $0.046 | 976 | 2,958 |
| rag100 | $0.105 | 529 | 8,578 |

Ledger, first question (cache write): $0.549; later questions (cache read): $0.050 each.


## Q1. What are the main arguments made by people who think seed oils are harmful, and roughly how many people make each?

**ledger:** **Arguments that seed oils are harmful, by number of people**

Of the 3,000 authors who took a clear position, 701 (about 23%) disagree that seed oils are safe. Most of them don't give a specific reason. The reasons that do appear, by number of authors agreeing:

- **"Seed oils are toxic":** 159 agree (89 disagree). This is the most common claim.
- **"Avoid them for health":** 86
- **Remove them from food and diets:** 23 (15 disagree)
- **Too much omega-6, throwing the diet out of balance:** 19
- **Tallow or butter is healthier:** 15. Another 8 say coconut oil, olive oil or ghee is healthier.
- **"There's too much seed oil in our diet":** 13
- **The author avoids seed oils personally:** 12
- **Processing harms (chemical residue from extraction, damage from heat, solvent extraction):** 7–8 for each version
- **Processed foods containing them drive chronic disease:** 8–9
- **Refined oils cause cancer or metabolic disease:** 7
- **They lower testosterone:** 7 (5 disagree)
- **They impair brain function:** 6
- **Personal stories of health improving after quitting them:** about 4 each

**What the data doesn't show:** Totals can't be added up, because one person can make several claims. Some people who agree with a harm claim still say seed oils are safe overall. Nothing here shows how widely these posts spread or whether they changed anyone's mind.

**rag20:** The retrieved posts can't answer this directly. None of the 20 posts (out of 6,062 in the corpus) comes from someone who says seed oils are harmful. Every one is written by a critic who mocks or describes the anti-seed-oil side. So the arguments below are how critics summarise that side, not claims made by its believers.

Arguments critics attribute to them:
- Seed oils are toxic, inflammatory or "killing everybody": about 4 posts, using words like "poisonous," "inflammatory," "will kill us all" and "making everyone sick."
- Seed oils are linked to autism: 1 post, plus 1 that ties the worry to the same people who blame Tylenol for autism.
- Beef fat or tallow is better and "liberals" hid that: 2 posts, plus 2 noting RFK Jr.'s or the beef lobby's preference.
- Seed oils make you "effeminate": 1 post.

Most of the posts treat the belief as part of the wider MAHA/RFK Jr. wellness movement, alongside opposition to vaccines, fluoride and food dyes.

The material doesn't tell me:
- what believers actually argue, in their own words
- how many distinct people wrote these posts
- any share or engagement counts
- whether these 20 posts are typical of the full 6,062

**rag100:** **Direct answer: this sample barely shows those arguments.** Almost all of the 100 retrieved posts (out of 6,062) mock or criticise people who are against seed oils. Only about 2–3 posts clearly argue that seed oils are harmful:
- 1 says seed oils are "killing you" because of how they are processed to stay shelf-stable.
- 1 says seed oils, along with meat, sugar and trans fats, "make a person look old and ugly."
- 1 is a chip brand's marketing that rejects seed oils as "modern shortcuts."

A few others are unsure, like "maybe they really ARE bad," or one person whose doctor's assistant told them to stop using seed oils.

**What critics say the claims are** (counts are posts, not people):
- **Inflammation, omega-6 or oxidation:** about 4–5 posts.
- **Poisonous, toxic or "killing everyone":** about 6.
- **Beef tallow, lard or butter is healthier:** about 6–7.
- **Industrial processing:** about 2.
- **Seed oils make people feminine, gay or trans:** about 8. These look like jokes or exaggeration rather than real quotes.
- **Link to autism:** about 1–2.

**What the material doesn't tell me:** who wrote each post, so I can't count individual people. There's also no share or engagement data, and nothing about the other 5,962 posts.


## Q2. How do defenders of seed oils respond, and which of their arguments are most common?

**ledger:** **Seed-oil defenders far outnumber critics.** Of 3,000 authors with a clear position on whether seed oils are safe and healthy, 2,299 say yes and 701 say no. The pro-safety theme covers 2,439 docs, which is 40.2% of the corpus.

**Their most common responses (authors agreeing):**
- **Mockery:** anti-seed-oil claims are absurd and deserve ridicule (211); seed-oil fears are a joke (165).
- **"It's overblown":** harm claims have been stretched too far (170); seed oils get blamed for problems they didn't cause (109).
- **Pointing at the messengers:** the opposition is a conspiracy or wellness fad pushed by MAHA and RFK Jr. (86); RFK Jr. blames seed oils without basis (43).
- **Comparing fats:** beef tallow isn't healthier (79); seed oils beat butter, lard and tallow (58).
- **Healthy and tasty:** they belong in a healthy diet (64); they're delicious (37).
- **Redirecting blame:** the real problem is ultra-processed food (37).

**What's rare:** specific scientific points come up much less. Omega-6 may lower heart-disease and diabetes risk (13 authors), seed oils have been eaten for thousands of years (16), and canola and corn oil don't cause inflammation (9).

**What I can't tell you:** the material has no share or engagement numbers. Authors can also appear on more than one line, so these counts shouldn't be added together.

**rag20:** This is based on only 20 of 6,062 retrieved posts, so I can't say how common these arguments are across the full corpus. About 11 of the 20 push back on anti–seed oil claims in some way. They fall into these groups:

1. **Mocking the critics (most common, about 5 posts).** These attack the critics' credibility rather than the science. Examples are the "clean lifestyle" influencer whose "lips are an inflatable raft", people who "see one post on Facebook" and believe it, a family's list of "health disinfo", and the claim that no one lumps olive oil in with seed oils.
2. **Citing evidence or authorities (about 3).** These point to American Heart Association facts against MAHA's "beef tallow" message. Others argue the harm comes from ultra-processed foods, not the oils themselves, or allow benefits like vitamin E "in moderation".
3. **Calling it a distraction (about 2).** For example, reporters "would rather sit and do research on seed oils" than criticise an official who isn't qualified.
4. **Simply saying they're fine (1).** "Yes, seed oils are fine."

Only a few posts attack seed oils (for example, over chemical processing and hexane). The posts carry no author or share data, so I can't tell how many people are involved or how far these arguments spread.

**rag100:** **Defenders of seed oils mostly ridicule their critics rather than argue about nutrition.** My counts below are rough hand counts from the 100 posts retrieved, out of 6,062 in the corpus.

1. **Mockery and guilt by association (about 35 posts).** This is the most common response by far. Seed-oil fears get lumped with MAHA, RFK Jr., beef tallow, raw milk, being against vaccines, "do your own research" and right-wing gender panic. Several posts call it a fad, like "fat free… gluten free" or "the new 5G."
2. **Pointing to research and experts (about 10–12 posts).** Posts link to the American Heart Association, NPR, Nature, Scientific American, Dr. Matthew Nagra and the Maintenance Phase podcast. They say feeding trials and Mendelian randomization studies don't support the inflammation claims.
3. **Saturated fat is the real risk (about 6 posts).** Seed oils are unsaturated, so swapping them for tallow or lard makes things worse.
4. **The real problem is ultra-processed food, not the oil (about 4 posts).**
5. **The category doesn't hold together (about 5 posts).** Olive oil isn't from a seed, and sesame oil has been used for 5,000 years.
6. **It's a distraction (about 4 posts)** from bigger issues like heavy metals in candy, hunger and drug prices.

A few defenders give some ground: omega-6 balance matters, and moderation is sensible. The material includes no share or engagement numbers and doesn't tell me who the posters are, so I can't say which arguments spread furthest.


## Q3. Overall, what share of people with a discernible position think seed oils are safe?

**ledger:** About three in four (76.6%) of people with a discernible position think seed oils are safe.

Of the 4,139 authors in the corpus, 3,000 took a position that could be identified on the statement "Seed oils (canola, soybean, sunflower etc.) are safe and healthy to eat":
- 2,299 agree (76.6%)
- 701 disagree (23.4%)

That's roughly 3.3 agreeing for every one disagreeing, across 2,227 documents.

Things to keep in mind:
- The other 1,139 authors (27.5% of everyone) showed no position, so they aren't counted. Among all authors, agreement is about 55.5%.
- The statement combines "safe" and "healthy." The material can't separate people who think seed oils are merely harmless from those who think they're actively good for you.
- These are counts of people posting, not a representative survey. The material doesn't say how authors were sampled or how positions were judged.
- Not every disagreement is strong. The related claim "Seed oils are toxic" drew 276 authors, but only 159 agreed with it, and 107 of those still counted as agreeing that seed oils are safe.

**rag20:** I can't give an overall share. I only have 20 of the 6,062 posts, the posts show no author information, and the 20 may not be a random sample. Here is what those 20 show:

- **11 posts clearly say or imply seed oils are safe.** They mock "seed oils bad" claims, call them "RFK brain rot," say "seed oils are great," or share the Johns Hopkins post saying canola, sunflower and soybean oils are safe. Two of the 11 have identical text, which may be a repost.
- **3 more lean that way.** These are the "pouring seed oils into my food" post, the biochemist/TikTok post and the "people skipping seed oils" post.
- **0 posts clearly say seed oils are harmful.**
- **6 posts take no clear position.** These are the Andrew Tate post, the poll, the "what is the story here?" question, the summit ad, the "what is a seed oil" post and the MAHA strategy post.

So in this sample, 11 to 14 of the 14 posts with a position (79–100%) say seed oils are safe, and none say they are harmful. That is a share of posts, not people, because I can't tell who wrote them. The other 6,042 posts could look very different. For example, the mocking posts suggest seed-oil skeptics exist, but none of their posts were retrieved.

**rag100:** **About 9 in 10 of the posts that take a side treat seed oils as safe, but this can't be read as a share of people.**

This comes from my own hand-coding of about 100 retrieved posts out of 6,062:

- **Safe or "the fear is overblown":** about 58 posts. Most of these mock people who fear seed oils ("Tallowban," "RFK brain rot," "TikTok convinced them"). Fewer say directly that the oils are safe, such as the Johns Hopkins link and "seed oils are not bad for you."
- **Harmful:** about 4 posts. These are a tallow-soap ad, an "omega-6" diet tip, "living on sugar, seed oils…," and a retweet saying seed oils keep "millions of people" away from fast food.
- **Left out:** jokes, ads, neutral questions and unclear posts, such as "Maybe seed oils really ARE bad…"

That puts it at roughly 90–95% "safe," with these limits:
- These are only the top 100 search matches, not a random sample, so they may not reflect all 6,062 posts.
- The data has no author information, so I can't count people. At least one post appears twice.
- Most "safe" posts mock the other side rather than state a view on health, so I'm reading their position in.
- One post runs a true/false poll, but its results aren't included.


## Q4. Which claims or themes became prominent only recently, and which faded?

**ledger:** **The ledger can't answer this.** It has no dates or time breakdown. It gives totals of authors, posts and positions for each claim across the whole corpus (6,062 posts, 4,139 authors), so it can't show what rose or faded.

Some claims mention dated events, but that only tells you what the posts talk about, not when attention peaked:
- **2026 US dietary guidelines** (e735, e895, e745, e747): each has 4 or fewer authors.
- **Titans coach Saleh banning seed oils** (e1027: 27 authors; e999: 19 authors; e1207: 9 authors).
- **Dated media pieces:** NPR's July 2025 article (e91, 11 authors) and a Scientific American episode on January 14, 2026 (e685, 4 authors).
- **e797, "Seed oil talk has faded from attention":** only 3 authors and 2 posts. That's one opinion, not a measured trend.

The biggest items are big overall, not recent. The anchor statement that seed oils are safe has 3,000 authors with a position (2,299 agree, 701 disagree), and e251, "Seed oils are toxic," has 276 authors.

To answer your question I'd need post dates, so I could count posts per claim or theme by month.

**rag20:** **The posts can't show which themes rose or faded, because none of them have dates.** The only date anywhere is in the Range Products press release (8 Sep 2026). Without timestamps I can't measure how often a theme appeared over time. Also, I only have 20 of the 6,062 posts, and they seem to have been picked because they contain the words "became" and "only," not because they're recent.

**What the posts themselves say about timing:**
- **Recent rise tied to RFK Jr. / MAHA:** One poster says they had never heard of "seed oils" or "ferments" before RFK Jr. took office. They call it "DHS Sec," but his post is HHS. Six posts link seed-oil and beef-tallow claims to RFK Jr. or MAHA.
- **Older origins:** One post traces the switch from animal fats to plant oils back to 1990s diet culture. Another says seed oils showed up in neo-Nazi "goyslop" talk before AI content became common.
- **Pushback:** Several posts cite debunking, including a Harvard study and a Guardian piece on paid posts.

None of the posts say any theme has faded. Answering this properly would need post dates or counts per time period.

**rag100:** **The posts can't show which themes rose or faded recently.** I have 100 of 6,062 posts, and none has a timestamp, so I can't compare periods or count trends over time. The retrieval also seems to have matched the question's own words ("only," "became," "claims"), so the sample is skewed.

What the posts themselves say about change:

- **Seed oils moved into government policy.** One poster had never heard of "seed oils" before RFK Jr. took office, and another says the idea became "official US policy." A STAT link dated January 2026 describes Kennedy dropping 421 pages of scientific recommendations.
- **Legal disputes over avocado oil.** Two posts describe class actions (Chosen Foods; PepsiCo/Utz) as snack brands "pivot from seed oils."
- **Diet fads replacing each other.** One post suggests people who went vegan for health have moved to carnivore or no-seed-oil diets. Another says "data centers are the new 5G, which was the new seed oils, which were the new saturated fats." That hints seed-oil worry may be giving way to other scares, but it's one person's opinion.
- **Older history.** One post says plant oils caught on through 1990s diet culture.

Getting real trends would need dated posts for the whole set of 6,062.


## Q5. Is there evidence of coordinated or bot-like amplification of any claim?

**ledger:** **Short answer: the ledger shows uneven posting, but nothing in it shows coordination or bots.** It records how many authors and posts each claim has. It has no account ages, post timing, shared wording or network links, which are what you'd need to show coordination.

**The one flagged case:**
- **e411**, "Pumpkin seed and other plant oils are great for skincare": 17 authors and 52 posts. The ledger warns that 5 accounts wrote 77% of those posts. This looks like promotional or commercial posting, and it has almost nothing to do with the anchor (1 author agrees, 0 disagree).

**Smaller cases where a few authors posted a lot:**
- e725 (RFK Jr. reshaped positions on seed oils, fluoride and Tylenol): 3 authors, 14 posts.
- e1289 (Chosen Foods avocado-oil class action): 2 authors, 9 posts.
- e1261 (Siete chips contain undisclosed seed oils): 2 authors, 6 posts.
- e618 (fries as harmful as cigarettes): 1 author, 4 posts.

**Links shared once per author, mostly without taking a position:** the NPR article (11 authors, 11 posts), product ads (e663, 11 and 11) and the Lionheart Clinic blog (e917, 8 and 8). This could be ordinary sharing or a campaign. The ledger can't tell which.

The biggest claims, such as the anchor (3,000 authors) and e251 "toxic" (276 authors), don't show this pattern. The ledger also classes 7.6% of the corpus as noise, without saying what that noise contains.

**rag20:** **No. These 20 posts don't show any coordinated or bot-like amplification, but they also can't rule it out.**

**What the posts show:**
- **No repeated text.** Each of the 20 posts is worded differently. Copy-paste wording is the most common sign of coordination, and it's absent here.
- **Most posts push back on seed-oil fears.** About 10 of the 20 dispute claims that seed oils are harmful, some citing STAT News, FactCheck.org, a review paper or the Washington Post.
- **Only a few posts promote the claims.** About 3 do, including the "5 things damaging your health" list (which could be a joke) and a personal story about cutting out processed foods. A few posts say influencers and algorithms spread the claims, but that's an opinion, not evidence of coordination.

**What the material doesn't include:**
- Who posted each item, account ages, or posting times
- Share, repost or like counts
- Whether links or hashtags were posted in bursts or by connected accounts
- The other 6,042 posts in the corpus

Checking for coordination would need account and timing data, plus a search of all 6,062 posts for repeated text or links.

**rag100:** **Not really. These 100 posts (out of 6,062) don't show coordinated or bot-like amplification, and they don't include the data needed to check for it properly.**

**Possible signs in the sample:**
- **Exact duplicates:** "Seed oils show no convincing evidence of harm in normal dietary amounts and are generally linked to cardiovascular benefits" appears twice, word for word.
- **Near-duplicates:** "Free-From Pestos : Besto" appears twice from diningandcooking.com, with the same text but different URLs (…/2159946/ and …/2160315/…-2/).
- **Automated-looking posts:** diningandcooking.com links make up 4 posts, all in the same headline + link + excerpt format. That looks like an automated news-aggregator feed, not a campaign pushing a claim. Its posts are mostly product or news items, though one uses a "no seed oils" hook.

**What's missing:**
- No account names, timestamps, follower counts, or share or repost numbers. Without these I can't tell whether the duplicates came from one account or several, or whether they were posted in bursts.
- I can't see the other 5,962 posts.

**Overall:** Most posts read as individual, varied opinions. Most push back on anti-seed-oil claims, and a few support them, such as "industrial seed oils. I avoid them." To test for coordination, you'd need account IDs, posting times, and repost data for the whole corpus.


## Q6. What do people say about beef tallow specifically, and is that mostly praise or criticism?

**ledger:** **Beef tallow talk in this corpus is mostly criticism.** Most of it sits in the theme "Saturated fats and beef tallow vs seed oils" (212 posts, 3.5% of the corpus).

**Criticism (the largest lines):**
- Tallow isn't healthier than seed oils, and MAHA's tallow claims make no real difference: 82 authors, 46 posts.
- Seed oils are healthier than butter, lard and tallow: 59 authors.
- RFK Jr. promoting tallow is unscientific: 9 authors. The tallow push is about beef-industry profits: 9 authors.
- Tallow is linked to heart disease: 8 authors. Tallow fries are no healthier: 6 authors.
- Steak 'n Shake's switch to tallow is stupid and deserves a boycott: 9 authors.

**Praise (much smaller):**
- Tallow and butter are healthier than seed oils: 18 authors (15 agree, 3 disagree).
- Food cooked in animal fat tastes better: 11 authors (7 agree, 4 disagree).
- Beef lard is the healthier cooking fat: 7 authors (4 agree, 3 disagree).

**Neutral reporting:** 33 authors note that restaurants advertise tallow and "no seed oils," and 13 describe a national move to tallow frying. Almost all of them take no stance.

**Limits:** Authors can appear on several lines, so these counts can't be added up. The material also doesn't give a single total for everyone who mentions tallow.

**rag20:** **Answer:** In these 20 posts, beef tallow is almost all criticized or mocked. No post praises it in its own voice.

**What the posts say:** 11 of the 20 posts mention beef tallow.
- **Critical (6):** People say it's being pushed politically, as "a right wing conspiracy" from RFK and HHS and part of the "MAHAsphere's war on seed oils." They say the studies HHS posted don't show tallow is healthier. Other posts mock the idea that tallow is better than seed oils, joking that it can still cause heart failure and diabetes, or groan at Instagram claims that frying in tallow is healthier.
- **Mocking or bemused (2):** One jokes that tallow fixes everything. One describes a shopper whose son heard about tallow from Joe Rogan.
- **Neutral or informational (3):** These are article-style headlines, such as what dietitians or cardiologists say about tallow. Only the headline or lead is shown, so their conclusions aren't visible.

**Praise:** Support for tallow appears only secondhand, as claims by "influencers," Instagram users and Rogan listeners that critics are pushing back on.

**Limits:** This covers only the top 20 of 6,062 posts. There are no share or engagement numbers, and I can't tell whether different people wrote these posts. So I can't say how common praise is in the full set of posts.

**rag100:** **People mostly criticise or mock beef tallow. Praise is rare, and it's usually about taste rather than health.**

About 60 of the 100 retrieved posts mention tallow. My sorting is approximate:

- **Critical (about 35–40):** These say tallow is high in saturated fat and bad for the heart ("Beef tallow is natural. So is atherosclerosis"). They say the cited studies don't support RFK Jr.'s claims, and they frame tallow as a MAHA or right-wing culture-war symbol ("seed oils are fem, beef tallow is masc"). The ABC headline saying tallow "may not be healthier, some cardiologists say" appears 4 times.
- **Neutral news or explainers (about 7):** Dietitian and cardiologist Q&As, plus a story about Steak 'n Shake's tallow-fried fries.
- **Taste praise mixed with health doubts (about 5):** For example, "silly, but… beef tallow fries are so stinkin good" and "delicious, but… no healthier."
- **Praising its health (about 3):** One says it "doesn't oxidise" under heat. One cites a "2026 meta-analysis" and halal tallow. One is a retweet urging McDonald's to go back to its original fries.

**What the material doesn't tell me:** shares, likes, or how many separate people posted. It also doesn't cover the other 5,962 posts, so the balance across the whole corpus could be different.

