// Node-side mirror of tests/test_live_crdt.py — same convergence proofs,
// run directly against the actual shipped demo/static/js/live.js (no DOM,
// no browser: the CRDT logic in that file is plain data functions, dual-mode
// on purpose so it can be required here exactly like a browser would load it
// as a <script>).
//
// Run:  node --test tests/live/

const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const { LiveCRDT, liveFlatten, liveNormalizeDomain } = require(
  path.join(__dirname, "..", "..", "demo", "static", "js", "live.js"));

function seedFiles() {
  return {
    cuts: {
      video_tracks: [{
        index: 1,
        items: [{
          id: "a", name: "a.mov", media_ref: "m",
          record_start_frame: 0, record_end_frame: 100,
          source_start_frame: 0, source_end_frame: 100,
          track_index: 1, transform: {},
        }],
      }],
    },
    metadata: { frame_rate: 24.0, project_name: "P" },
  };
}

test("local edit wins and increments the Lamport counter", () => {
  const doc = new LiveCRDT("alice");
  doc.loadFromFiles(seedFiles());
  const update = doc.applyLocal(["cuts", "video_tracks", "a", "record_end_frame"], 150);

  assert.equal(update.value, 150);
  assert.deepEqual(update.timestamp, [1, "alice"]);
  assert.equal(doc.snapshot().cuts.video_tracks[0].items[0].record_end_frame, 150);
});

test("stale remote update is a no-op", () => {
  const doc = new LiveCRDT("alice");
  doc.loadFromFiles(seedFiles());
  doc.applyLocal(["cuts", "video_tracks", "a", "record_end_frame"], 150);

  const changed = doc.applyRemote({
    path: ["cuts", "video_tracks", "a", "record_end_frame"], value: 999, timestamp: [0, ""],
  });

  assert.equal(changed, false);
  assert.equal(doc.snapshot().cuts.video_tracks[0].items[0].record_end_frame, 150);
});

test("duplicate remote update is idempotent", () => {
  const doc = new LiveCRDT("alice");
  doc.loadFromFiles(seedFiles());
  const update = { path: ["cuts", "video_tracks", "a", "record_end_frame"], value: 200, timestamp: [5, "bob"] };

  assert.equal(doc.applyRemote(update), true);
  assert.equal(doc.applyRemote(update), false);
  assert.equal(doc.snapshot().cuts.video_tracks[0].items[0].record_end_frame, 200);
});

test("concurrent edits to the same field converge regardless of delivery order", () => {
  const base = seedFiles();
  const alice = new LiveCRDT("alice");
  alice.loadFromFiles(base);
  const bob = new LiveCRDT("bob");
  bob.loadFromFiles(base);

  const aliceUpdate = alice.applyLocal(["cuts", "video_tracks", "a", "record_end_frame"], 111);
  const bobUpdate = bob.applyLocal(["cuts", "video_tracks", "a", "record_end_frame"], 222);

  alice.applyRemote(bobUpdate);
  bob.applyRemote(aliceUpdate);

  assert.deepEqual(alice.snapshot(), bob.snapshot());
  assert.equal(alice.snapshot().cuts.video_tracks[0].items[0].record_end_frame, 222); // "bob" > "alice"
});

test("delete wins over a stale concurrent field edit", () => {
  const doc = new LiveCRDT("alice");
  doc.loadFromFiles(seedFiles());

  doc.deleteItem(["cuts", "video_tracks", "a"]);
  doc.applyRemote({
    path: ["cuts", "video_tracks", "a", "record_end_frame"], value: 999, timestamp: [0, ""],
  });

  const ids = doc.snapshot().cuts.video_tracks[0].items.map((i) => i.id);
  assert.equal(ids.includes("a"), false);
});

test("load_from_files round-trips through snapshot unchanged", () => {
  const files = seedFiles();
  const doc = new LiveCRDT("alice");
  doc.loadFromFiles(files);

  assert.deepEqual(doc.snapshot().cuts, files.cuts);
  assert.equal(doc.snapshot().metadata.project_name, "P");
});

test("liveNormalizeDomain matches vit's own shape (id-keyed clips + track existence)", () => {
  const normalized = liveNormalizeDomain("cuts", seedFiles().cuts);
  assert.deepEqual(Object.keys(normalized.video_tracks), ["a"]);
  assert.deepEqual(normalized._tracks, { "1": true });
});

test("liveFlatten treats an empty object as a leaf, not nothing", () => {
  const pairs = liveFlatten(["x"], { transform: {} });
  assert.deepEqual(pairs, [[["x", "transform"], {}]]);
});

test("cross-language interop: a Python-shaped update message applies identically", () => {
  // The wire format is just JSON — this asserts the JS side interprets an
  // update exactly the way the Python side produces one (list path, list
  // timestamp), i.e. the two implementations actually speak the same protocol.
  const doc = new LiveCRDT("alice");
  doc.loadFromFiles(seedFiles());
  const pythonStyleUpdate = JSON.parse(JSON.stringify({
    path: ["metadata", "project_name"], value: "from python", timestamp: [3, "py-client"],
  }));

  assert.equal(doc.applyRemote(pythonStyleUpdate), true);
  assert.equal(doc.snapshot().metadata.project_name, "from python");
});
