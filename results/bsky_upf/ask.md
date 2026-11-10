# Open questions, side by side (6,042 posts)

Same reader (Opus 5.5, medium effort). Ledger = theme view held as a cached system prompt. RAG = BM25 top-k.

| method | mean $ / question | mean cache-read tokens | mean uncached input tokens |
|---|---|---|---|
| ledger | $0.127 | 50,002 | 11,335 |
| rag20 | $0.045 | 529 | 2,873 |
| rag100 | $0.108 | 529 | 9,044 |

Ledger, first question (cache write): $0.520; later questions (cache read): $0.048 each.


## Q1. What are the main health harms people attribute to ultra-processed foods, and how widespread is each claim?

**ledger:** **Main health harms attributed to ultra-processed foods (UPF)**

Overall, 2,396 authors took a clear position on "UPF are harmful": 1,751 agreed and 645 disagreed. Health harms are the largest theme, at 2,128 of 6,042 documents (35.2%). Few authors back any one specific harm, though.

| Harm | Authors | Docs |
|---|---|---|
| Addictive or engineered overeating | 61 | 37 |
| Several chronic diseases, not just obesity | 36 | 33 |
| Higher dementia risk | 31 | 18 |
| Weight loss after cutting UPF | 29 | 22 |
| Obesity | 12 | 7 |
| Heart and blood-vessel events | 27 | 24 |
| Gut microbiome disruption | 21 | 13 |
| Fertility and embryo harm | 18 | 13 |
| Cancer and stroke | 17 | 10 |
| Harm from additives, not just nutrients | 17 | 11 |
| Anxiety, depression, ADHD and similar | 13 | 8 |
| Depression | 12 | 10 |
| Cognitive impairment | 12 | 7 |

Other claims, such as early death (8 authors), inflammation (8) and diabetes (2–5), each have under 10 authors.

**Contested:** 22 authors say total UPF intake isn't linked to colorectal cancer. Another 20 say the harm comes from fat, sugar and salt, not from processing.

**What the data can't show:** whether any of these claims are true or causal, or how many people overall shared posts. It counts authors and documents only.

**rag20:** **Health harms attributed to ultra-processed foods (UPFs)**

These counts come from only the 20 retrieved posts out of 6,042. They show what appears in this sample, not how common each claim is across the full corpus. The material has no author or share data, so I can't count people or measure reach.

- **General disease, disability and premature death: 6 posts.** These include Mozaffarian calling UPFs "the main driver of disease, disability and death," the Lancet review by 43 experts on premature mortality, the NEJM paper, Chartres saying the evidence is "unequivocal," a CME webinar, and one post that also mentions harm to the planet.
- **Engineered for addiction or overeating, compared to nicotine: 2 posts.**
- **Heart disease: 3 posts.** Two of these also name obesity, type 2 diabetes and cancer, but they have identical text, so it's really 1 distinct claim.
- **Additives: 2 posts.** One raises Red Dye 40 and the other seed oils. Neither says these cause specific harm. A third post argues the harm comes from how processing changes food structure, not from additives.
- **Poor nutrition and emotional well-being: 1 post.**

**Pushback:** 3 posts question the framing. One calls it "fear mongering," one says UPF intake is hard to measure, and one points to critics of the Lancet series.

Several other retrieved posts are off-topic, such as one about foodborne illness.

**rag100:** # Health harms people attribute to ultra-processed foods (UPFs)

These counts come only from the 100 posts I was given, out of 6,042 in the corpus. They are approximate counts of posts that name each harm.

**Harms named, most to least common**
- **Addiction or overeating:** about 6 posts. They compare UPFs to cigarettes or nicotine, or say they are "engineered" to make people keep eating. One cites a University of Auckland study, another the Guardian's "one bite and he was hooked."
- **Obesity:** about 7 posts. These include a repeated line about "almost 1 billion" people living with obesity, and one post calling UPFs the "main culprit."
- **Heart disease:** about 7 posts.
- **Type 2 diabetes:** about 4 posts.
- **Cancer:** about 4 posts, including one on colon cancer.
- **Early death:** about 4 posts. Sources include a 43-expert Lancet review and claims that UPFs "kill more people than smoking."
- **Brain or mental health:** about 4 posts.
- **Children's health:** about 3 posts.
- **Male reproductive health:** 2 posts with the same headline.
- **Kidneys and Red Dye 40:** 1 post each.

**Other patterns**
- The most-shared item is the Guardian story about UPF firms suing to block health rules, which appears about 14 times. It's about regulation more than any specific harm.
- About 8 to 10 posts are skeptical. They say "ultra-processed" is poorly defined or the evidence is weak.

**What the material doesn't tell me:** who wrote the posts (so I can't count people), how often they were shared, or what the other 5,942 posts say.


## Q2. Who pushes back on the ultra-processed food narrative, and with what arguments?

**ledger:** **Who:** 645 of the 2,396 authors with a discernible position (about 27%) disagree that ultra-processed foods (UPF) are harmful to health. The material doesn't say who these people are: no professions, affiliations, countries or industry ties.

**Their main arguments, by number of authors (the bracket shows how many of them reject the anchor):**
- **The term has no clear definition:** 121 authors (74). This one is shared across camps, since 16 of them agree UPF is harmful.
- **The panic is overblown and feeds food anxiety and disordered eating:** 61 (58). A related line, that fear is overblown and comfort food should be defended, has 14 (14).
- **The category is too vague to pin down specific harms:** 29 (23). Others say it wrongly groups cheese, tofu and dressings with junk food (25, 23) or tells science and policy nothing useful (15, 15).
- **Not all UPF has a poor nutrient profile:** 26 (19). Others say the harm comes from fat, sugar, salt and calories, not processing (20, 13).
- **Weak evidence:** total UPF isn't linked to colorectal cancer (22, 16), and observational studies can't show cause (7, 6).
- **Class bias:** 11 (9) call it classism, and 10 (10) say the label targets food poor people eat.

The material doesn't show how many shares these posts got.

**rag20:** **Short answer: these 20 posts (out of 6,042) contain almost no direct pushback on the ultra-processed food (UPF) narrative.** Most of them support cutting UPF or simply report on it. The closest things to pushback are:

- **Political hypocrisy (1 post):** One user says the right wing worries about "chemicals in ultra processed food" while pushing to end emissions controls. They call this proof of having "no agenda but whatever they personally like." This questions who is pushing the narrative, not the science.
- **Arguments over the definition (1–2 posts):** One user mocks people "arguing with a straight face that loose leaf tea is an ultra processed food." Another praises a thread that explains "what it is, exactly." Both suggest the label gets stretched or used loosely.
- **Open scientific question (1 post):** A diabetes-meeting interview asks, "Will targeting UPF end the chronic disease epidemic?" It frames this as a debate, but we don't see the answer.

**What the material doesn't show:** who the critics are by name or role, any industry or scientific counterarguments, how many people hold these views, or share and engagement numbers. The other 5,000+ posts might include stronger pushback.

**rag100:** **Who pushes back on the ultra-processed food (UPF) narrative, and how**

The posts only tell me what was said. I can't see who posted them, their follower counts or any share or engagement numbers, so I can't say how many people this is or how far it spread. My counts below come from the 100 posts retrieved, not the full corpus of 6,042.

**1. Critics who say the term is undefined (about 8 posts, the biggest group)**
- One post saying there's "no scientific or medical consensus" on what UPF is appears twice.
- Three posts share The Atlantic's "Nobody Knows What Ultra-Processed Food Is."
- One claims the category comes from an "arbitrary… very Western" paper from around 2009.
- Others argue that linking UPF to disease is "incorrect" without a definition, cite the Maintenance Phase podcast, or call UPF an "indefinable boogeyman" and say regulators should target contaminants instead.

**2. Critics who point to hypocrisy (about 3 posts)**
- Influencers attack UPF while selling supplements.
- People who promote plant-based products ignore that those are processed too.
- One post mocks claims that loose-leaf tea counts as UPF.

**3. Critics who question the science (1 post)**
- It attacks who reviewed a BMJ umbrella review on UPF.

**4. Critics who raise cost and class (about 4 posts)**
- UPF is cheap while protein and organic food cost more.
- One column calls the issue a "class war" of "food snobs."
- One notes restaurant food is often just as ultra-processed.

**5. The food industry (as described by others in about 4 posts)**
- Manufacturers resist a legal definition, sue countries, lobby Congress and oppose Colombia's taxes on these foods.

Two posts push back the other way, saying people should just call it "junk food."


## Q3. Overall, what share of people with a discernible position think ultra-processed foods are harmful?

**ledger:** **About 73% of people with a discernible position think ultra-processed foods are harmful.**

- Of the corpus's 3,846 authors, 2,396 took a discernible position on the statement "Ultra-processed foods are harmful to health." These authors wrote 1,885 posts.
- **1,751 agree (73.1%)** and **645 disagree (26.9%)**.
- The other 1,450 authors (about 38%) took no discernible position, so they aren't counted in either share.

**What "disagree" often means:** Many who disagree seem to be questioning the label itself rather than saying the food is safe. For example:
- "'Ultra-processed' lacks a functional consensus definition": 74 of these authors disagree with the harm statement.
- "The panic is excessive and fuels food anxiety": 58 disagree.
- "The category wrongly lumps cheese and tofu with junk food": 23 disagree.

**What the material doesn't tell you:**
- How strongly people hold their views.
- Who the authors are, or where they're from.
- Whether this social-media sample represents the wider public.
- How the 9.2% noise and 5.4% unplaced posts would change the split.

**rag20:** **I can't give an overall share. I only have 20 of the 6,042 posts, and they were picked for relevance, not at random, so they can't stand in for the whole corpus.**

Here is what the 20 posts show, using my own rough reading of each:

- **About 10 say ultra-processed foods are harmful.** Seven say it outright: the comparison to cigarettes, the Stanford piece on why they're unhealthy, the post asking whether to ban their ads, "damaging to health," "quite bad for you," "garbage," and the South African study on unhealthy school food. Three more imply it: "slop," the trend toward healthier diets, and the UK's "extreme position" in Europe.
- **None clearly says they're harmless.** About five doubt the term or how people use it. That includes the posts mocking calls to regulate something nobody has defined, the one saying the problem is "mostly too much sugar and salt," and the one rejecting the cigarette comparison. They question the label more than the harm.
- **About five take no position.** These are questions or neutral comments on definitions.

Among the posts with a clear view, nearly all lean "harmful," but that's 10 posts, not a measure of opinion. The material has no author names, so I can't count people, and it has no share or engagement numbers.

**rag100:** **Roughly 70% of the posts that take a side treat ultra-processed foods (UPFs) as harmful.** This covers only the 100 posts I was given, out of 6,042 in the corpus, so it is not a figure for the whole corpus.

My own hand-coding of those 100 posts:
- **46 say UPFs are harmful.** They link UPFs to cancer, heart disease, depression, dementia or obesity, or call for regulation, ad bans or labels.
- **19 are sceptical.** Most say there is no clear definition of "ultra-processed," that the category is "idiotic," that the research is "garbage," or that the real problem is just salt and sugar. Few say outright that UPFs are harmless.
- **35 take no clear position.** These are questions, neutral news, or posts defending the category without judging harm.

That gives 46 out of 65, or about 71%.

Limits:
- The 100 posts were picked by how well they matched the search, not at random. Many contain phrases like "people think," which may over-sample debates about definitions.
- The material doesn't show authors, so I can't count people. Some posts are duplicates or reposts of the same news story, such as the bowel-cancer study posted twice.
- There are no share or engagement numbers, so I can't weight posts by reach.
- Borderline posts could be coded either way, so the figure could plausibly be 65–75%.


## Q4. Which claims or themes became prominent only recently, and which faded?

**ledger:** The material can't answer this. The ledger has no dates, posting times or time breakdowns. It only gives totals for authors, posts and agree/disagree splits, gathered across the whole corpus (6,042 posts, 3,846 authors). So I can't tell which claims rose or faded.

Some claims mention dates or events in their wording, but that only shows when the topic was set, not when people posted about it:
- e1939 (4 authors, 4 posts): experts urge release of the federal UPF definition, "held up since August."
- e1644 (8 authors, 8 posts): RFK Jr.'s promised definition "by April" hasn't been delivered.
- e1792 (2 authors): Jason Fung's 2026 book.
- e1798 (3 authors): the Earth Day 2027 theme.
- e1402 (92 authors, 97 posts) and e15 (74 authors, 67 posts): industry lawsuits and San Francisco's lawsuit, which are probably tied to news events.

None of these show a trend. A post-by-post breakdown by date for each theme or claim would be needed to see what rose or faded.

**rag20:** I can't tell from this material which themes rose or faded. The 20 posts shown (out of 6,042) have no dates, share counts or engagement numbers, so I can't compare over time.

What I can say:

- **Themes in the sample:**
  - RFK Jr. and the reversed food pyramid (about 3 posts)
  - Comparing ultra-processed food (UPF) to tobacco and calling health claims "health washing" (2)
  - Arguments that "ultra-processed" is a meaningless or fallacious term (about 4)
  - Corporate blame, such as San Francisco's suit against Kraft Heinz and Mondelez (2)
  - Poverty and cost driving UPF diets (1)
  - Cancer-related claims (1)
- **Partial date hints:** A few links include "2026" (Guardian, Washington Post opinion, an AcademyHealth blog from 2026-05). So the tobacco comparison and the food-justice framing appear in 2026 content, but there's nothing earlier to compare them with.
- **Not in the material:** dates for most posts, how often each theme appears across all 6,042 posts, numbers of authors, and shares.

To answer this properly, I'd need post timestamps and theme counts grouped by month or quarter.

**rag100:** **I can't answer this from the material.** The 100 retrieved posts (of 6,042) have no dates or engagement data, so I can't tell which claims rose recently and which faded. There are also no share counts or author IDs, so I can't count how many people posted.

**What the sample does show (no timing):**
- **Repeated posts:** "The meat industry needed a new weapon… 'Ultra-processed food'… Vague, meaningless, effective" appears 5 times. The "Big Education Ape: Junk Food Industrial Complex" post appears 5 times. "How Ireland got hooked on ultra-processed foods" appears 4 times.
- **Recurring themes:**
  - RFK Jr./MAHA, the upside-down food pyramid and his promised definition of ultra-processed food (roughly 10 posts).
  - The term is vague or meaningless (about 12 posts).
  - Comparisons to tobacco and corporate harm, plus San Francisco's lawsuits against food companies (about 6 posts).
  - Health studies linking these foods to dementia, ADHD, depression and heart disease (4 posts).
  - Cost and access to food (about 5 posts).

**Weak hints only:** Link paths include "2026" (one is dated 2026/09), and one post mentions the 2025–2030 US dietary guidelines. That suggests the RFK Jr. and lawsuit topics are from around 2026, but it doesn't show change over time.

To answer the question properly, I'd need post dates for the full corpus.


## Q5. What policy proposals come up (bans, labels, taxes, school food), and how much support does each get?

**ledger:** **Policy proposals for ultra-processed food (UPF), by number of authors**

| Proposal | Authors | Agree / disagree / neutral |
|---|---|---|
| Tax it, put hazard warnings on it, limit promotion like tobacco | 77 | 44 / 4 / 29 |
| Regulate UPF in school kiosks and canteens | 25 | 17 / 2 / 6 |
| Ban or restrict UPF advertising | 18 | 14 / 1 / 3 |
| New federal definition plus traffic-light front-of-pack labels | 11 | 8 / 0 / 3 |
| Tax modelled on the UK sugar tax | 10 | 8 / 2 / 0 |
| Ban UPF outright | 10 | 8 / 2 / 0 |
| End UPF subsidies | 10 | 9 / 1 / 0 |
| Legally protect children from UPF marketing | 10 | 10 / 0 / 0 |
| California "not ultra-processed" label (AB 2244) | 6 | 4 / 0 / 2 |
| Limit UPF in hospital food | 6 | 5 / 0 / 1 |

A separate post about California's voluntary label bill (7 authors) was almost all neutral reporting.

**Smaller items:**
- More money for school meals: 4 authors.
- Survey showing support from both parties: 4.
- Opposing a state "not UPF" certification: 3.

**Opposition:** 18 authors say "ultra-processed" doesn't belong in legislation. Restricting what food stamps (SNAP) can buy draws mostly neutral news posts (bills in Utah and elsewhere, 3 authors each). A few critics call it fearmongering (3) or harmful to poor people (1 each).

**Gaps:** The material doesn't give share counts or engagement. About 80 other policy claims are grouped together without separate counts, each from at most one author.

**rag20:** Only 20 of the 6,042 posts were retrieved, and none include likes, shares or author counts. So I can't measure support. All I can do is count how many retrieved posts mention each proposal and what stance they take.

- **Labels (4 posts):** This is the most common topic.
  - One asks senators to vote yes on the Childhood Diabetes Reduction Act's warning labels.
  - One argues for front-of-pack scores like Nutri-Score.
  - One cites Dr. Tedros saying companies obstruct front-of-pack labels.
  - One is FDA head Makary talking about food labels.
- **School food (3 posts):**
  - A South Carolina Senate bill would ban the sale of ultra-processed foods at school.
  - Makary discusses what the push could mean for school lunches.
  - A Friends of the Earth report says ultra-processed food makers lobby to get their food into schools.
- **Marketing limits (2 supportive, 1 critical):** Two posts back limits on junk-food ads to kids, including the Tedros post. One critic calls the proposals "incredibly bad."
- **Bans:** Only the South Carolina school bill.
- **Taxes:** Sugar taxes come up once, in the Tedros post, as a target of industry pushback.

**Pushback (3 posts):** Food makers say RFK Jr.'s proposals push up grocery costs. Another post cites a Lancet review saying the harm comes from ingredients, so policy needs rethinking. The third is the "incredibly bad" critic above.

These counts come from a small sample and don't show how widely any of these views are shared.

**rag100:** **Policy proposals in 100 retrieved posts on ultra-processed food (out of 6,042 total)**

These are rough counts from the retrieved posts only. Duplicate reposts are noted.

- **School food (about 12 posts, the most common topic):** Includes South Carolina's bill to ban ultra-processed food sales in schools, H.R. 5753 (backed by a claim that 99% of school nutrition providers need more funding), California's Real Food, Healthy Kids Act, and examples from South Africa, Argentina and Brazil. Three identical posts link a usrtk.org piece on food companies and school meals. All of these posts support the changes. One parent calls school food "ultra processed garbage."
- **Labels (about 8 posts):** Warning labels, front-of-pack labels and Nutri-Score. One cited survey (AJPH) reports broad support from both parties for warning labels, safety testing of additives and required sugar and salt cuts. One Washington Post opinion piece argues that labelling raises costs for low-income families.
- **Ad and marketing limits (about 4 posts):** All of these support restrictions.
- **Taxes and subsidies (about 4 posts):** Only 2 mention sugar or fat taxes. Two criticise farm subsidies.

**Pushback:** At least 6 posts say "ultra-processed" has no clear definition. Industry says RFK Jr.'s proposals raise grocery costs. One post calls the proposals "incredibly bad," and several say healthy food needs to be affordable first.

**What I can't tell you:** The posts include no share or engagement numbers and no author IDs, so I can't count people or measure reach. These 100 posts may not represent the other 5,942.


## Q6. How is the topic tied to politics or specific public figures?

**ledger:** **How the topic ties to politics and public figures**

US federal politics, centred on RFK Jr. and MAHA, is one of 17 themes. It covers 154 assertions and 235 documents, about 3.9% of the 6,042 in the corpus.

- **US dietary guidelines:** 32 authors say the new guidelines tell people to limit ultra-processed food. Of those, 17 agree and 14 are neutral.
- **RFK Jr.:** Opinion is split.
  - Critical: 17 authors find his food plan confusing, 10 say he isn't a credible source, and 7 say he spreads vaccine confusion instead.
  - Positive: 11 authors credit him with "sometimes brilliant ideas." All 11 also agree that ultra-processed food is harmful.
  - 8 note that the federal definition he promised by April hasn't been delivered.
- **White House:** 4 authors report that 70+ experts urged it to release the definition. 3 say food-company CEOs pushed for a delay.
- **Trump:** 6 authors mention his fast-food diet.
- **Sceptics:** 3 authors call ultra-processed food worries a MAHA scam, and all 3 disagree that it's harmful.
- **Lawsuits and lobbying:** 92 authors call industry lawsuits "weaponised delay," and 74 discuss San Francisco suing food makers.
- **Other figures** (2–3 authors each): Chris van Tulleken, Marion Nestle, Michelle Obama and Calley Means.

The data doesn't show authors' party or country, so it can't say whether views split along party lines.

**rag20:** About 7–8 of the 20 retrieved posts (out of 6,042 in the corpus) link ultra-processed food (UPF) to politics or named figures.

**Named figures and government:**
- **RFK Jr. / MAHA:** One post says the effort fits the "MAHA" agenda. It claims RFK Jr. encouraged Republican state attorneys general in September to "pursue this strategy."
- **Trump administration / Kennedy:** One post says the American Journal of Public Health is "laying down a marker" for how the administration should define UPF.
- **Sen. Cassidy:** One post says he "sold himself out for politics" and calls UPF "a meaningless word."

**Policy and industry politics:**
- A talk at the American Public Health Association titled "Dietary Guidelines and Ultra-Processed Foods: The Politics."
- Big Tobacco's role in designing Lunchables.
- A claim that the food industry "shapes the narrative" and targets low-income groups.
- A warning that bans or limits on UPF must come with access to healthy food for poor and disabled people.
- An academic post on plastics and environmental politics.

**Gaps:** The material has no share or engagement numbers and no author counts. These are only the top 20 posts, so I can't say how common political framing is across the full corpus.

**rag100:** **How the topic ties to politics and public figures (based on 100 retrieved posts out of 6,042)**

- **RFK Jr. / MAHA / Trump administration (about 6 posts):** One post says RFK Jr. encouraged Republican state attorneys general to pursue ultra-processed food cases. Another calls the MAHA agenda "failed," citing a report from the Center for American Progress. A third mentions a leaked RFK letter about David Kessler's petition. Others mock Trump's own diet or cover a public health journal (AJPH) pushing the administration on how to define ultra-processed food. A separate post accuses Senator Cassidy of selling out "for politics."
- **WHO Director-General Tedros (about 6 posts):** Four posts repeat his quote about industry interference: "when harm and profit are tied to the same product." Two more cite related lines about lawsuits weakening public health rules.
- **Commentators:** 7 posts link to Marion Nestle's "Food Politics" blog, and 2 feature Chris van Tulleken. Leana Wen and Christina Roberto appear once each.
- **Law and policy:** San Francisco's lawsuit against manufacturers, a California law, US federal labelling, Brazil's food policy and an APHA talk on the politics of the dietary guidelines (1 post each).

**What the material doesn't tell me:** how many distinct people posted, or any share or engagement counts. These posts are also only a small sample of the corpus.

