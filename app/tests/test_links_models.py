from app.links import (
    ApproveProposalRequest,
    ProposalListResponse,
    ProposalResponse,
    RejectProposalRequest,
)
from app.matching import ConfidenceBand


def test_proposal_response_stores_expected_fields() -> None:
    proposal = ProposalResponse(
        id=4,
        local_track_id=8,
        local_file_path="Artist/Track.mp3",
        local_title="Track",
        local_artist="Artist",
        local_album="Album",
        streaming_track_id=12,
        streaming_title="Track",
        streaming_artist="Artist",
        streaming_album="Album",
        match_method="tags",
        score=0.82,
        status="pending",
        confidence_band=ConfidenceBand.MEDIUM,
        rejected_at=None,
    )

    assert proposal.id == 4
    assert proposal.local_track_id == 8
    assert proposal.local_file_path == "Artist/Track.mp3"
    assert proposal.local_title == "Track"
    assert proposal.local_artist == "Artist"
    assert proposal.local_album == "Album"
    assert proposal.streaming_track_id == 12
    assert proposal.streaming_title == "Track"
    assert proposal.streaming_artist == "Artist"
    assert proposal.streaming_album == "Album"
    assert proposal.match_method == "tags"
    assert proposal.score == 0.82
    assert proposal.status == "pending"
    assert proposal.confidence_band is ConfidenceBand.MEDIUM
    assert proposal.rejected_at is None


def test_proposal_list_response_wraps_proposals() -> None:
    payload = ProposalListResponse(
        proposals=[
            ProposalResponse(
                id=1,
                local_track_id=2,
                local_file_path="Artist/Track.mp3",
                local_title=None,
                local_artist=None,
                local_album=None,
                streaming_track_id=3,
                streaming_title="Track",
                streaming_artist="Artist",
                streaming_album=None,
                match_method="isrc",
                score=1.0,
                status="approved",
                confidence_band=ConfidenceBand.HIGH,
                rejected_at=None,
            )
        ]
    )

    assert len(payload.proposals) == 1
    assert payload.proposals[0].confidence_band is ConfidenceBand.HIGH


def test_approve_and_reject_requests_accept_empty_payloads() -> None:
    assert ApproveProposalRequest().model_dump() == {}
    assert RejectProposalRequest().model_dump() == {}
