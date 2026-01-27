from elasticsearch7 import Elasticsearch
from typing import List,Dict,Any
from SourceMergeDection import *


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