from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Optional, Tuple

from elasticsearch7 import Elasticsearch


# -----------------------------
# Helpers: normalization
# -----------------------------

_HANDLE_RE = re.compile(r"^@+", re.IGNORECASE)
_WS_RE = re.compile(r"\s+")

def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def norm_handle(handle: Optional[str]) -> str:
    if not handle:
        return ""
    h = handle.strip()
    h = _HANDLE_RE.sub("", h)
    return h.lower()

def norm_text(s: Optional[str]) -> str:
    if not s:
        return ""
    s = s.strip().lower()
    s = _WS_RE.sub(" ", s)
    return s

def norm_domain(domain: str) -> str:
    d = domain.strip().lower()
    d = d.replace("https://", "").replace("http://", "")
    d = d.split("/")[0]
    if d.startswith("www."):
        d = d[4:]
    return d

def stable_hash_id(*parts: str, length: int = 32) -> str:
    """
    Deterministic id for link documents.
    """
    h = hashlib.sha256("||".join(parts).encode("utf-8")).hexdigest()
    return h[:length]


# -----------------------------
# Scoring components
# -----------------------------

def ratio(a: str, b: str) -> float:
    """
    Deterministic similarity 0..1 using stdlib difflib.
    """
    a = norm_text(a)
    b = norm_text(b)
    if not a or not b:
        return 0.0
    return SequenceMatcher(a=a, b=b).ratio()

def weighted_overlap(a: Iterable[str], b: Iterable[str]) -> float:
    """
    Deterministic overlap score 0..1:
      |A ∩ B| / |A ∪ B|  (Jaccard)
    """
    sa = {x for x in a if x}
    sb = {x for x in b if x}
    if not sa and not sb:
        return 0.0
    return len(sa & sb) / max(1, len(sa | sb))


@dataclass(frozen=True)
class ScoreWeights:
    external_links: float = 0.45
    handle: float = 0.20
    bio: float = 0.15
    display_name: float = 0.10
    content: float = 0.10  # optional placeholder if you add content similarity later


@dataclass
class ScoreResult:
    confidence: float
    evidence: Dict[str, Any]
    matched_signals: List[Dict[str, Any]]  # for tiktok-source-links.signals[]


def compute_confidence(
    src: Dict[str, Any],
    cand: Dict[str, Any],
    *,
    weights: ScoreWeights = ScoreWeights(),
) -> ScoreResult:
    """
    Deterministic confidence score and evidence.

    Expected doc shape (from your `tiktok-sources` mapping):
      - handle, display_name
      - signals.website_domains, youtube_channel_ids, instagram_usernames, twitter_usernames, emails
      - (optional) bio field if you store it (not in your mapping currently)
    """

    src_signals = (src.get("signals") or {})
    cand_signals = (cand.get("signals") or {})

    # Durable signal buckets (normalize!)
    src_domains = [norm_domain(x) for x in (src_signals.get("website_domains") or [])]
    cand_domains = [norm_domain(x) for x in (cand_signals.get("website_domains") or [])]

    src_yt = [norm_text(x) for x in (src_signals.get("youtube_channel_ids") or [])]
    cand_yt = [norm_text(x) for x in (cand_signals.get("youtube_channel_ids") or [])]

    src_ig = [norm_handle(x) for x in (src_signals.get("instagram_usernames") or [])]
    cand_ig = [norm_handle(x) for x in (cand_signals.get("instagram_usernames") or [])]

    src_tw = [norm_handle(x) for x in (src_signals.get("twitter_usernames") or [])]
    cand_tw = [norm_handle(x) for x in (cand_signals.get("twitter_usernames") or [])]

    src_em = [norm_text(x) for x in (src_signals.get("emails") or [])]
    cand_em = [norm_text(x) for x in (cand_signals.get("emails") or [])]

    # Strong “external links” score: average of Jaccards across buckets, with a bit more weight for email/yt.
    # (Still deterministic; tune as you like.)
    j_domains = weighted_overlap(src_domains, cand_domains)
    j_yt = weighted_overlap(src_yt, cand_yt)
    j_ig = weighted_overlap(src_ig, cand_ig)
    j_tw = weighted_overlap(src_tw, cand_tw)
    j_em = weighted_overlap(src_em, cand_em)

    external_links_score = (
        0.20 * j_domains +
        0.35 * j_yt +
        0.20 * j_ig +
        0.15 * j_tw +
        0.10 * j_em
    )

    # Name-ish similarities
    handle_score = ratio(norm_handle(src.get("handle")), norm_handle(cand.get("handle")))
    display_name_score = ratio(src.get("display_name") or "", cand.get("display_name") or "")

    # Bio similarity if you store it (you currently don’t in mapping; safe default 0)
    bio_score = ratio(src.get("bio") or "", cand.get("bio") or "")

    # Placeholder for future content similarity (keep deterministic; default 0)
    content_score = 0.0

    confidence = (
        weights.external_links * external_links_score +
        weights.handle * handle_score +
        weights.bio * bio_score +
        weights.display_name * display_name_score +
        weights.content * content_score
    )

    # Build matched signals list for tiktok-source-links.signals (nested)
    matched_signals: List[Dict[str, Any]] = []

    def add_matches(sig_type: str, src_vals: List[str], cand_vals: List[str], weight: float) -> None:
        inter = sorted(set(src_vals) & set(cand_vals))
        for v in inter:
            matched_signals.append({"type": sig_type, "value": v, "weight": float(weight)})

    # weights here are “evidence weights”, not final score weights
    add_matches("website_domain", src_domains, cand_domains, 0.20)
    add_matches("youtube_channel_id", src_yt, cand_yt, 0.35)
    add_matches("instagram_username", src_ig, cand_ig, 0.20)
    add_matches("twitter_username", src_tw, cand_tw, 0.15)
    add_matches("email", src_em, cand_em, 0.10)

    evidence = {
        "matched_domains": sorted(set(src_domains) & set(cand_domains)),
        "matched_youtube_channel_ids": sorted(set(src_yt) & set(cand_yt)),
        "bio_similarity": round(bio_score, 4),
        "handle_similarity": round(handle_score, 4),
        "display_name_similarity": round(display_name_score, 4),
        "external_links_score": round(external_links_score, 4),
    }

    return ScoreResult(
        confidence=round(float(confidence), 6),
        evidence=evidence,
        matched_signals=matched_signals,
    )


# -----------------------------
# Elasticsearch candidate queries
# -----------------------------

def build_candidates_query(src: Dict[str, Any], *, size: int = 50) -> Dict[str, Any]:
    """
    High-recall deterministic candidate query:
    - SHOULD matches on durable signals
    - optional SHOULD on handle/display_name keywords if present
    - minimum_should_match=1 keeps it practical
    """
    sig = (src.get("signals") or {})
    website_domains = [norm_domain(x) for x in (sig.get("website_domains") or [])]
    youtube_channel_ids = [norm_text(x) for x in (sig.get("youtube_channel_ids") or [])]
    instagram_usernames = [norm_handle(x) for x in (sig.get("instagram_usernames") or [])]
    twitter_usernames = [norm_handle(x) for x in (sig.get("twitter_usernames") or [])]
    emails = [norm_text(x) for x in (sig.get("emails") or [])]

    should: List[Dict[str, Any]] = []

    if website_domains:
        should.append({"terms": {"signals.website_domains": website_domains}})
    if youtube_channel_ids:
        should.append({"terms": {"signals.youtube_channel_ids": youtube_channel_ids}})
    if instagram_usernames:
        should.append({"terms": {"signals.instagram_usernames": instagram_usernames}})
    if twitter_usernames:
        should.append({"terms": {"signals.twitter_usernames": twitter_usernames}})
    if emails:
        should.append({"terms": {"signals.emails": emails}})

    # Lightweight extra recall: exact keyword handle/display_name match (if those fields exist)
    # (Your mapping has handle/display_name as keyword, so this is fine.)
    h = norm_handle(src.get("handle"))
    if h:
        should.append({"term": {"handle": h}})

    dn = norm_text(src.get("display_name"))
    if dn:
        should.append({"term": {"display_name": dn}})

    # If we have no signals at all, fall back to handle-only (still deterministic)
    if not should and h:
        should = [{"term": {"handle": h}}]

    return {
        "size": size,
        "_source": True,
        "query": {
            "bool": {
                "should": should,
                "minimum_should_match": 1 if should else 0
            }
        }
    }


def search_candidate_accounts(
    es: Elasticsearch,
    *,
    creator_accounts_index: str,
    src_account_doc: Dict[str, Any],
    exclude_account_id: Optional[str] = None,
    size: int = 50,
) -> List[Dict[str, Any]]:
    body = build_candidates_query(src_account_doc, size=size)

    # Exclude the same account_id (so you don't match yourself)
    if exclude_account_id:
        body["query"]["bool"].setdefault("must_not", [])
        body["query"]["bool"]["must_not"].append({"term": {"account_id": exclude_account_id}})

    resp = es.search(index=creator_accounts_index, body=body)
    hits = (resp.get("hits") or {}).get("hits") or []
    return [h.get("_source") or {} for h in hits]


# -----------------------------
# Write proposals to tiktok-source-links
# -----------------------------

def upsert_link_proposal(
    es: Elasticsearch,
    *,
    creator_account_links_index: str,
    creator_id: str,
    src_account_id: str,
    cand_account_id: str,
    score: ScoreResult,
    approved: bool = False,
    status: str = "proposed",
    link_id_len: int = 32,
) -> str:
    """
    Deterministically create link_id from (creator_id, src_account_id, cand_account_id).
    """
    # canonicalize order so link_id is stable regardless of which side is "src"
    a, b = sorted([src_account_id, cand_account_id])
    link_id = stable_hash_id("link", creator_id, a, b, length=link_id_len)

    doc = {
        "link_id": link_id,
        "creator_id": creator_id,
        "account_id": cand_account_id,          # the candidate account
        "confidence": float(score.confidence),
        "status": status,
        "signals": score.matched_signals,
        "evidence": {
            "matched_domains": score.evidence.get("matched_domains", []),
            "matched_youtube_channel_ids": score.evidence.get("matched_youtube_channel_ids", []),
            "bio_similarity": float(score.evidence.get("bio_similarity", 0.0)),
            "handle_similarity": float(score.evidence.get("handle_similarity", 0.0)),
        },
        "updated_at": now_utc_iso(),
        "approved": bool(approved),
    }

    # Upsert (deterministic doc id)
    es.update(
        index=creator_account_links_index,
        id=link_id,
        doc=doc,
        doc_as_upsert=True,
        refresh=False,
    )
    return link_id


# -----------------------------
# Orchestrator: resolve candidates + propose merges
# -----------------------------

def propose_creator_merges_for_account(
    es: Elasticsearch,
    *,
    creator_accounts_index: str = "tiktok-sources",
    creator_account_links_index: str = "tiktok-source-links",
    creator_id: str,
    src_account_doc: Dict[str, Any],
    min_confidence: float = 0.70,
    auto_link_confidence: float = 0.85,
    max_candidates: int = 50,
) -> List[Dict[str, Any]]:
    """
    Deterministic end-to-end:
      - find candidates via ES query
      - score each
      - write proposals >= min_confidence
      - auto-approve >= auto_link_confidence (optional)
    Returns list of proposal summaries.
    """
    src_account_id = src_account_doc.get("account_id") or ""
    if not src_account_id:
        raise ValueError("src_account_doc must include account_id")

    candidates = search_candidate_accounts(
        es,
        creator_accounts_index=creator_accounts_index,
        src_account_doc=src_account_doc,
        exclude_account_id=src_account_id,
        size=max_candidates,
    )

    out: List[Dict[str, Any]] = []

    for cand in candidates:
        cand_account_id = cand.get("account_id") or ""
        if not cand_account_id:
            continue

        score = compute_confidence(src_account_doc, cand)

        if score.confidence < min_confidence:
            continue

        approved = score.confidence >= auto_link_confidence
        link_id = upsert_link_proposal(
            es,
            creator_account_links_index=creator_account_links_index,
            creator_id=creator_id,
            src_account_id=src_account_id,
            cand_account_id=cand_account_id,
            score=score,
            approved=approved,
            status="approved" if approved else "proposed",
        )

        out.append({
            "link_id": link_id,
            "src_account_id": src_account_id,
            "cand_account_id": cand_account_id,
            "confidence": score.confidence,
            "approved": approved,
            "evidence": score.evidence,
            "matched_signals": score.matched_signals,
        })

    # deterministic sort for stable output
    out.sort(key=lambda x: (-x["confidence"], x["cand_account_id"]))
    return out
