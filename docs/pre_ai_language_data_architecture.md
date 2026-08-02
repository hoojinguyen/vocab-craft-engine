# Pre-AI Language Data Architecture: Building Massive Dictionaries for Free

## 1. Pre-AI Open Dictionary Databases & Formats

### Wiktionary Parsing
Wiktionary is the ultimate open-source linguistic resource, but raw XML dumps are notoriously difficult to parse due to complex wikitext templates.
- **Wiktionary Dumps:** Available via Wikimedia Downloads, they provide comprehensive multi-lingual data.
- **kaikki.org & Wiktextract:** Tools like `wiktextract` parse the wikitext into highly structured machine-readable JSON formats. `kaikki.org` provides pre-parsed JSON dumps, making it trivially easy to ingest etymology, definitions, IPA transcriptions, and usage examples into a database without building custom parsers.

### StarDict / MDict / Dictd
Before mobile apps dominated, desktop dictionary applications like GoldenDict and StarDict relied on standardized, offline dictionary formats.
- **StarDict Format:** Consists of `.dict` (the actual data), `.idx` (the index), and `.ifo` (metadata).
- **Available Dumps:** Vast repositories of English-Vietnamese dictionaries (e.g., EVDP - English-Vietnamese Dictionary Project, Stardict-AnhViet) are hosted on SourceForge or GitHub. These databases can be reverse-engineered using tools like `PyGlossary` to extract the underlying HTML/text definitions.

### WordNet & Open English WordNet
Developed at Princeton, WordNet is a lexical database of English that groups words into sets of cognitive synonyms (synsets).
- **Usage:** Essential for disambiguating word senses and mapping semantic relationships (hypernyms, hyponyms). Open English WordNet extends this effort as a fully open-source fork.

## 2. Parallel Sentence & Dialogue Corpus Mining

### Tatoeba Project
Tatoeba is a massive, crowdsourced database of translated sentences.
- **Data:** It contains millions of aligned sentence pairs (e.g., English-Vietnamese) alongside community-recorded audio. All data is downloadable as CSV/TSV, making it a perfect seed corpus for flashcards.

### OPUS Corpus
The open parallel corpus (OPUS) aggregates translated texts from the web.
- **Sources:** OpenSubtitles (movie/TV subtitles), TED Talks transcripts, and Europarl (European Parliament proceedings).
- **Application:** By parsing `.tmx` (Translation Memory eXchange) or plain text alignments from OPUS, one can extract highly conversational, context-rich dialogues.

### Rule-based & Statistical Dialogue Extraction
Raw subtitle data often contains noise. Pre-AI extraction relied on heuristics:
- **Utterance Length & Turn Count:** Filtering out one-word lines or overly long monologues to find natural dialogue exchanges.
- **Vocabulary Leveling:** Using frequency lists to score sentences. A sentence containing 90% top-1000 frequency words is tagged as A1/A2 (CEFR), while sentences with rare words are tagged as C1/C2.

## 3. Community & Crowdsourcing Systems

### User Generated Content (UGC)
Platforms like Anki, Memrise, and the original Duolingo Incubator scaled incredibly fast because they didn't create courses—their users did.
- **Duolingo Incubator:** Volunteers built courses using a custom rule-based alignment engine to match sentences and translations.
- **Memrise:** Relied heavily on user-created "mems" (mnemonics) and shared vocabulary lists.

### Anki Shared Decks
Anki is essentially a spaced-repetition frontend for SQLite databases.
- **Under the Hood:** An `.apkg` file is just a ZIP archive containing media files and a SQLite database (`collection.anki2`).
- **Data Extraction:** By unzipping an `.apkg` and querying the `notes` and `cards` tables, developers can trivially harvest thousands of high-quality, pre-curated flashcards, audio clips, and images from shared Anki decks.

## 4. Deterministic NLP & Rule-Based Pipeline

### NLP Toolkits (spaCy, NLTK, Stanza)
Before LLMs, standardizing raw text required deterministic NLP pipelines:
- **Tokenization & Lemmatization:** Using spaCy or NLTK to reduce words to their base forms (e.g., "running" -> "run") so they can be matched against a dictionary.
- **POS Tagging:** Determining if "record" is a noun or verb to fetch the correct definition and pronunciation.

### CEFR Grading via Frequency Rank
Vocabulary difficulty can be statistically estimated:
- **Frequency Lists:** Corpora like the Leipzig Corpora Collection, COCA (Corpus of Contemporary American English), or SUBTLEX (subtitle frequency) rank words by occurrence.
- **Mapping:** Words in the top 1,000 are broadly A1, 1,000-3,000 are A2/B1, etc. A simple dictionary lookup assigns CEFR levels automatically.

### Rule-Based Audio & IPA Alignment
- **IPA Transcription:** Dictionaries provide IPA. For out-of-vocabulary words, rule-based grapheme-to-phoneme (G2P) models like eSpeak NG generate transcriptions.
- **Audio:** Sourcing free audio from Wikimedia Commons, or automating generation using Microsoft Edge-TTS (which exposes Azure neural TTS for free) or Google's free tier.

## 5. Self-Owned Language Data System Architecture

To build a free, zero-dependency linguistic engine, you need a solid offline architecture.

### Data Schema (SQLite/PostgreSQL)
A relational model is perfect for structured linguistic data:
- **Words Table:** `id`, `lemma`, `pos`, `ipa`, `frequency_rank`, `cefr_level`
- **Definitions Table:** `id`, `word_id`, `sense`, `translation`, `source` (e.g., Wiktionary)
- **Sentences Table:** `id`, `text`, `translation`, `audio_path`, `source` (e.g., Tatoeba)
- **Word_Sentence_Map:** Many-to-many table linking lemmas to their occurrence in sentences.

### Architectural Blueprint
1. **Ingestion Layer:** Python scripts download and parse dumps (Kaikki JSON, Tatoeba CSV, OPUS subtitles).
2. **NLP Processing Layer:** A spaCy pipeline processes sentences, lemmatizes words, assigns POS tags, and calculates sentence difficulty based on the `frequency_rank` of its constituent words.
3. **Storage Layer:** Processed data is bulk-inserted into a self-hosted PostgreSQL database for backend use, or exported to a standalone SQLite database for offline mobile consumption.
4. **Media Layer:** A background job fetches Edge-TTS audio or maps local Tatoeba audio files, saving them to object storage (or local disk).
5. **Serving Layer:** A fast API (e.g., FastAPI or Go) queries the SQL database to serve definitions, contextual sentences, and flashcard generation without a single API call to OpenAI.

This architecture ensures you 100% own the data, have zero recurring LLM API costs, and can serve millions of queries locally with millisecond latency.
