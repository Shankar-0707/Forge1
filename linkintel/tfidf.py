"""
tfidf.py - Lightweight TF-IDF + cosine similarity module.

Zero external dependencies (standard library only: math, collections, re).
Fully independent — does NOT import from analyzer.py.

Used by analyzer.py to:
  - Build TF-IDF vectors per page
  - Compute cosine similarity for relatedness scoring
  - Cluster pages by topical similarity
  - Extract bigram phrases
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Stop words — same set used in analyzer.py for consistency
# ---------------------------------------------------------------------------
STOPWORDS: frozenset = frozenset("""
a an the and or but if then else for to of in on at by with from as is are
was were be been being this that these those it its we you they he she them
our your their i me my mine ours us not no yes do does did doing have has
had having will would can could should may might must shall about into over
under again further once here there all any both each few more most other
some such only own same so than too very s t can just don now get got also
out up down off above below between through during before after each who what
when where why how which while until unless since though although because
whether both either neither nor so yet also just either need used like well
""".split())


# ---------------------------------------------------------------------------
# 1. tokenize
# ---------------------------------------------------------------------------
def tokenize(text: str) -> List[str]:
    """Tokenize text into meaningful words, filtering stopwords.

    Args:
        text: Raw input text (any case).

    Returns:
        List of lowercase tokens (3+ chars, not in STOPWORDS).
    """
    if not text:
        return []
    tokens = re.findall(r"[a-z][a-z0-9\-]{2,}", text.lower())
    return [t for t in tokens if t not in STOPWORDS]


# ---------------------------------------------------------------------------
# 2. compute_tf
# ---------------------------------------------------------------------------
def compute_tf(tokens: List[str]) -> Dict[str, float]:
    """Compute term frequency for a list of tokens.

    TF(term) = count(term) / total_tokens

    Args:
        tokens: List of tokens from a single document.

    Returns:
        Dict mapping term -> TF score (0.0 to 1.0).
    """
    if not tokens:
        return {}
    total = len(tokens)
    counts = Counter(tokens)
    return {term: count / total for term, count in counts.items()}


# ---------------------------------------------------------------------------
# 3. compute_idf
# ---------------------------------------------------------------------------
def compute_idf(documents: List[List[str]]) -> Dict[str, float]:
    """Compute inverse document frequency across a corpus.

    IDF(term) = log(N / df(term))  where df = # documents containing the term.
    Uses +1 smoothing on the denominator to avoid division by zero.

    Args:
        documents: List of token lists, one per document.

    Returns:
        Dict mapping term -> IDF score.
    """
    n = len(documents)
    if n == 0:
        return {}
    df: Dict[str, int] = defaultdict(int)
    for doc in documents:
        for term in set(doc):
            df[term] += 1
    return {term: math.log(n / (count + 1)) for term, count in df.items()}


# ---------------------------------------------------------------------------
# 4. tfidf_vectors
# ---------------------------------------------------------------------------
def tfidf_vectors(
    pages_text: Dict[str, str],
) -> Tuple[Dict[str, Dict[str, float]], Dict[str, float]]:
    """Build TF-IDF vectors for a collection of pages.

    Args:
        pages_text: Dict mapping URL -> combined page text
                    (typically Title + H1 + H2 + body).

    Returns:
        Tuple of:
          - vectors: {url: {term: tfidf_score}}
          - idf:     {term: idf_score}  (the shared IDF table)
    """
    urls = list(pages_text.keys())
    tokenized: Dict[str, List[str]] = {u: tokenize(pages_text[u]) for u in urls}

    idf = compute_idf(list(tokenized.values()))

    vectors: Dict[str, Dict[str, float]] = {}
    for url in urls:
        tokens = tokenized[url]
        tf = compute_tf(tokens)
        vectors[url] = {
            term: tf_score * idf.get(term, 0.0)
            for term, tf_score in tf.items()
        }
    return vectors, idf


# ---------------------------------------------------------------------------
# 5. cosine_similarity
# ---------------------------------------------------------------------------
def cosine_similarity(v1: Dict[str, float], v2: Dict[str, float]) -> float:
    """Compute cosine similarity between two sparse TF-IDF vectors.

    Args:
        v1: First vector {term: score}.
        v2: Second vector {term: score}.

    Returns:
        Cosine similarity in range [0.0, 1.0].
    """
    if not v1 or not v2:
        return 0.0

    # Dot product over shared terms only (sparse efficiency)
    shared_terms = set(v1.keys()) & set(v2.keys())
    dot = sum(v1[t] * v2[t] for t in shared_terms)
    if dot == 0.0:
        return 0.0

    mag1 = math.sqrt(sum(s * s for s in v1.values()))
    mag2 = math.sqrt(sum(s * s for s in v2.values()))
    if mag1 == 0.0 or mag2 == 0.0:
        return 0.0

    return round(dot / (mag1 * mag2), 4)


# ---------------------------------------------------------------------------
# 6. extract_bigrams
# ---------------------------------------------------------------------------
def extract_bigrams(tokens: List[str], top_n: int = 10) -> List[str]:
    """Extract the most common meaningful 2-word phrases from a token list.

    Skips bigrams where either word is a number or shorter than 3 chars.

    Args:
        tokens: Token list (already stopword-filtered).
        top_n:  How many top bigrams to return.

    Returns:
        List of bigram strings (e.g. ["mobile app", "web development"]).
    """
    if len(tokens) < 2:
        return []
    bigrams = [
        f"{tokens[i]} {tokens[i + 1]}"
        for i in range(len(tokens) - 1)
        if len(tokens[i]) >= 3 and len(tokens[i + 1]) >= 3
    ]
    counts = Counter(bigrams)
    return [bg for bg, _ in counts.most_common(top_n)]


# ---------------------------------------------------------------------------
# 7. cluster_by_similarity
# ---------------------------------------------------------------------------
def cluster_by_similarity(
    vectors: Dict[str, Dict[str, float]],
    threshold: float = 0.12,
    idf: Optional[Dict[str, float]] = None,  # reserved for future weighted variant
) -> List[List[str]]:
    """Group URLs into topical clusters using greedy similarity merging.

    Algorithm:
      1. Start with each URL as its own cluster.
      2. Repeatedly find the most similar pair of clusters (centroid cosine sim).
      3. Merge if similarity >= threshold.
      4. Stop when no pair exceeds the threshold.

    Args:
        vectors:   {url: {term: tfidf_score}} from tfidf_vectors().
        threshold: Minimum cosine similarity to merge two clusters (0–1).
        idf:       Unused; kept for API compatibility with weighted variants.

    Returns:
        List of URL groups, e.g. [["url1", "url2"], ["url3"], ...].
        Each URL appears in exactly one cluster.
    """
    urls = list(vectors.keys())
    if not urls:
        return []

    # Start: each URL is its own cluster
    clusters: List[List[str]] = [[u] for u in urls]

    def centroid(cluster: List[str]) -> Dict[str, float]:
        """Average TF-IDF vector for a list of URLs."""
        n = len(cluster)
        merged: Dict[str, float] = defaultdict(float)
        for u in cluster:
            for term, score in vectors.get(u, {}).items():
                merged[term] += score
        return {t: s / n for t, s in merged.items()}

    while True:
        best_sim = 0.0
        best_pair = (-1, -1)

        # Find the most similar cluster pair
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                sim = cosine_similarity(centroid(clusters[i]), centroid(clusters[j]))
                if sim > best_sim:
                    best_sim = sim
                    best_pair = (i, j)

        if best_sim < threshold:
            break  # No more merges above threshold

        # Merge the best pair
        i, j = best_pair
        merged_cluster = clusters[i] + clusters[j]
        # Remove j first (higher index), then i
        clusters = [c for idx, c in enumerate(clusters) if idx not in (i, j)]
        clusters.append(merged_cluster)

    return clusters


# ---------------------------------------------------------------------------
# Utility: top_keywords_from_vector
# ---------------------------------------------------------------------------
def top_keywords_from_vector(
    vector: Dict[str, float], top_n: int = 10
) -> List[str]:
    """Return the top-N terms from a TF-IDF vector by score.

    Args:
        vector: {term: tfidf_score}
        top_n:  Number of terms to return.

    Returns:
        List of term strings, highest-scoring first.
    """
    return [term for term, _ in sorted(vector.items(), key=lambda x: -x[1])[:top_n]]


# ---------------------------------------------------------------------------
# __main__ demo / test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 60)
    print("TF-IDF Module — self-test")
    print("=" * 60)

    # Sample pages
    sample_pages = {
        "https://example.com/mobile-app-development": (
            "Mobile App Development Services | Build iOS Android Apps "
            "We build custom mobile applications for iOS and Android. "
            "Our mobile development team uses React Native and Flutter. "
            "Enterprise mobile app development with agile methodology."
        ),
        "https://example.com/web-development": (
            "Web Development Services | Custom Websites and Web Apps "
            "Professional web development using React, Next.js, Django. "
            "Full stack web development for startups and enterprises. "
            "Responsive website design and web application development."
        ),
        "https://example.com/seo-services": (
            "SEO Services | Search Engine Optimization Company "
            "Search engine optimization and digital marketing solutions. "
            "Technical SEO, content SEO, and link building services. "
            "Improve your Google rankings with our SEO experts."
        ),
        "https://example.com/react-native-development": (
            "React Native App Development | Cross Platform Mobile Apps "
            "Build cross-platform mobile apps with React Native framework. "
            "React Native development for iOS and Android simultaneously. "
            "Experienced React Native developers for enterprise apps."
        ),
    }

    # 1. Tokenize test
    tokens = tokenize(sample_pages["https://example.com/mobile-app-development"])
    print(f"\n1. tokenize() → {len(tokens)} tokens")
    print(f"   First 10: {tokens[:10]}")

    # 2. TF
    tf = compute_tf(tokens)
    top_tf = sorted(tf.items(), key=lambda x: -x[1])[:5]
    print(f"\n2. compute_tf() → top 5: {top_tf}")

    # 3. TF-IDF vectors
    vectors, idf = tfidf_vectors(sample_pages)
    print(f"\n3. tfidf_vectors() → {len(vectors)} vectors built")
    for url, vec in vectors.items():
        top = top_keywords_from_vector(vec, 5)
        print(f"   {url.split('/')[-1]:35s} → {top}")

    # 4. Cosine similarity
    urls = list(vectors.keys())
    sim_mobile_react = cosine_similarity(vectors[urls[0]], vectors[urls[3]])
    sim_mobile_seo = cosine_similarity(vectors[urls[0]], vectors[urls[2]])
    print(f"\n4. cosine_similarity()")
    print(f"   mobile-app vs react-native : {sim_mobile_react} (should be HIGH)")
    print(f"   mobile-app vs seo-services : {sim_mobile_seo}  (should be LOW)")

    # 5. Bigrams
    bigrams = extract_bigrams(tokens, top_n=5)
    print(f"\n5. extract_bigrams() → {bigrams}")

    # 6. Clustering
    clusters = cluster_by_similarity(vectors, threshold=0.10)
    print(f"\n6. cluster_by_similarity(threshold=0.10) → {len(clusters)} clusters")
    for i, cluster in enumerate(clusters):
        names = [u.split("/")[-1] for u in cluster]
        print(f"   Cluster {i + 1}: {names}")

    print("\n✅ All tests passed.")
