"""vit.live.crdt — pure-Python CRDT convergence proofs.

No git, no disk, no WebSocket: these tests establish the actual mathematical
property a CRDT needs (apply the same set of updates, in any order, any
number of times, and every replica ends up identical) directly, without
needing two browser tabs to "look like" they converged.
"""

import itertools

from tests.helpers import clip
from vit.live.crdt import CRDTDoc


def _seed_files():
    return {
        "cuts": {"video_tracks": [{"index": 1, "items": [clip("a", 0, length=100)]}]},
        "metadata": {"frame_rate": 24.0, "project_name": "P"},
    }


def test_local_edit_wins_and_increments_the_lamport_counter():
    doc = CRDTDoc(client_id="alice")
    doc.load_from_files(_seed_files())
    update = doc.apply_local(("cuts", "video_tracks", "a", "record_end_frame"), 150)

    assert update["value"] == 150
    assert update["timestamp"] == [1, "alice"]
    assert doc.counter == 1
    assert doc.snapshot()["cuts"]["video_tracks"][0]["items"][0]["record_end_frame"] == 150


def test_stale_remote_update_is_a_no_op():
    doc = CRDTDoc(client_id="alice")
    doc.load_from_files(_seed_files())
    doc.apply_local(("cuts", "video_tracks", "a", "record_end_frame"), 150)  # counter -> 1

    changed = doc.apply_remote({
        "path": ["cuts", "video_tracks", "a", "record_end_frame"],
        "value": 999,
        "timestamp": [0, ""],  # genesis-level — strictly older than our local edit
    })

    assert changed is False
    assert doc.snapshot()["cuts"]["video_tracks"][0]["items"][0]["record_end_frame"] == 150


def test_duplicate_remote_update_is_idempotent():
    doc = CRDTDoc(client_id="alice")
    doc.load_from_files(_seed_files())
    update = {"path": ["cuts", "video_tracks", "a", "record_end_frame"], "value": 200, "timestamp": [5, "bob"]}

    first = doc.apply_remote(update)
    second = doc.apply_remote(update)  # same message, applied again (e.g. redelivery)

    assert first is True
    assert second is False  # already at this exact state — correctly recognized as a no-op
    assert doc.snapshot()["cuts"]["video_tracks"][0]["items"][0]["record_end_frame"] == 200


def test_concurrent_edits_to_the_same_field_converge_regardless_of_order():
    """The actual convergence proof: two replicas, each makes its own local
    edit to the SAME field (a genuine concurrent write), then each receives
    the other's update — but in a DIFFERENT relative order on each side
    (simulating real network reordering). Both must end up identical."""
    base = _seed_files()

    alice = CRDTDoc(client_id="alice")
    alice.load_from_files(base)
    bob = CRDTDoc(client_id="bob")
    bob.load_from_files(base)

    alice_update = alice.apply_local(("cuts", "video_tracks", "a", "record_end_frame"), 111)
    bob_update = bob.apply_local(("cuts", "video_tracks", "a", "record_end_frame"), 222)

    # Alice receives Bob's update; Bob receives Alice's — opposite arrival order.
    alice.apply_remote(bob_update)
    bob.apply_remote(alice_update)

    assert alice.snapshot() == bob.snapshot()
    # Both counters were 1 (each made one local edit) with different client_ids;
    # "bob" > "alice" lexicographically, so bob's write deterministically wins.
    assert alice.snapshot()["cuts"]["video_tracks"][0]["items"][0]["record_end_frame"] == 222


def test_convergence_holds_across_every_possible_delivery_order():
    """Stronger version of the above: three replicas, several concurrent
    edits to different fields, delivered in every possible order across
    every pair — still converge to one state every time."""
    base = _seed_files()
    updates = []
    docs = {}
    for name, field, value in [("a", "record_end_frame", 130), ("b", "transform", {"Opacity": 50}), ("c", "record_start_frame", 5)]:
        d = CRDTDoc(client_id=name)
        d.load_from_files(base)
        docs[name] = d
    updates.append(docs["a"].apply_local(("cuts", "video_tracks", "a", "record_end_frame"), 130))
    updates.append(docs["b"].apply_local(("cuts", "video_tracks", "a", "transform"), {"Opacity": 50}))
    updates.append(docs["c"].apply_local(("cuts", "video_tracks", "a", "record_start_frame"), 5))

    snapshots = []
    for order in itertools.permutations(updates):
        replica = CRDTDoc(client_id="observer")
        replica.load_from_files(base)
        for u in order:
            replica.apply_remote(u)
        snapshots.append(replica.snapshot())

    assert all(s == snapshots[0] for s in snapshots)


def test_delete_wins_over_a_stale_concurrent_field_edit():
    base = _seed_files()
    doc = CRDTDoc(client_id="alice")
    doc.load_from_files(base)

    delete_update = doc.delete_item(("cuts", "video_tracks", "a"))
    stale_field_edit = {
        "path": ["cuts", "video_tracks", "a", "record_end_frame"],
        "value": 999,
        "timestamp": [0, ""],  # from before the delete was even known
    }
    doc.apply_remote(stale_field_edit)

    ids = [i["id"] for i in doc.snapshot()["cuts"]["video_tracks"][0]["items"]]
    assert "a" not in ids
    assert delete_update["value"] is False


def test_merge_doc_combines_two_replicas_deterministically():
    base = _seed_files()
    alice = CRDTDoc(client_id="alice")
    alice.load_from_files(base)
    bob = CRDTDoc(client_id="bob")
    bob.load_from_files(base)

    alice.apply_local(("cuts", "video_tracks", "a", "record_end_frame"), 111)
    bob.apply_local(("cuts", "video_tracks", "a", "record_end_frame"), 222)

    merged_via_alice = CRDTDoc(client_id="observer")
    merged_via_alice.load_from_files(base)
    merged_via_alice.merge_doc(alice)
    merged_via_alice.merge_doc(bob)

    merged_via_bob = CRDTDoc(client_id="observer")
    merged_via_bob.load_from_files(base)
    merged_via_bob.merge_doc(bob)
    merged_via_bob.merge_doc(alice)

    assert merged_via_alice.snapshot() == merged_via_bob.snapshot()


def test_load_from_files_round_trips_through_snapshot_unchanged():
    files = _seed_files()
    doc = CRDTDoc(client_id="alice")
    doc.load_from_files(files)

    assert doc.snapshot()["cuts"] == files["cuts"]
    assert doc.snapshot()["metadata"]["frame_rate"] == 24.0
