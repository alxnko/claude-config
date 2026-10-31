"""Tests for scripts/subagent-usage.py. Stdlib only; synthetic transcripts under a fake HOME.

Set USAGE_SCRIPT=<path> to run the suite against another copy of the script (e.g. the old one).
"""
import json, os, re, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.environ.get("USAGE_SCRIPT") or os.path.join(HERE, "..", "subagent-usage.py")
PRICES = os.path.join(HERE, "fixtures", "usage", "prices.json")
M = "claude-sonnet-5-5"


def rec(mid, usage=None, stop="end_turn", ts="2026-10-20T10:00:00.000Z", model=M, sidechain=False, extra=None):
    u = {"input_tokens": 1000, "output_tokens": 500, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    u.update(usage or {})
    msg = {"model": model, "usage": u, "stop_reason": stop, "content": [{"type": "text", "text": "x"}]}
    if mid:
        msg["id"] = mid
    r = {"type": "assistant", "timestamp": ts, "message": msg}
    if sidechain:
        r["isSidechain"] = True
    r.update(extra or {})
    return r


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = self.tmp.name
        self.root = os.path.join(self.home, ".claude", "projects")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, records):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            for r in records:
                fh.write(json.dumps(r) + "\n")
        return path

    def run_script(self, *args, project_dir=None):
        cmd = [sys.executable, SCRIPT]
        cmd += [project_dir] if project_dir else ["--all-projects"]
        cmd += ["--since", "2026-10-01", "--prices", PRICES, *args]
        p = subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, "HOME": self.home})
        return p

    def total(self, p):
        return float(re.search(r"TOTAL API-equivalent[^$]*\$([\d,.]+)", p.stdout).group(1).replace(",", ""))

    def cov(self, p, name):
        return int(re.search(rf"^\s*{name}:\s+(\d+)", p.stdout, re.M).group(1))


class TestDedupe(Base):
    # cost of the default usage: 1000 in * $2/M + 500 out * $10/M = $0.007

    def test_block_records_counted_once(self):
        d = self.write("-p/s1.jsonl", [rec("msg_1"), rec("msg_1"), rec("msg_1")]) and os.path.join(self.root, "-p")
        p = self.run_script(project_dir=d)
        main = p.stdout.split("main session (orchestrator) by model:")[1].split("subagents by model:")[0]
        self.assertEqual(int(re.search(r"calls=\s*(\d+)", main).group(1)), 1, p.stdout)

    def test_block_records_exact_dollars(self):
        self.write("-p/s1.jsonl", [rec("msg_1")] * 3)
        p = self.run_script()
        self.assertAlmostEqual(self.total(p), 0.007, places=6)
        self.assertEqual((self.cov(p, "raw usage records"), self.cov(p, "unique responses"), self.cov(p, "duplicates collapsed")), (3, 1, 2))

    def test_same_id_in_duplicate_project_dirs(self):
        self.write("-home-x-proj/s1.jsonl", [rec("msg_1")])
        self.write("-home-x-home-x-proj/s1.jsonl", [rec("msg_1")])
        self.assertAlmostEqual(self.total(self.run_script()), 0.007, places=6)

    def test_same_id_in_fork_session(self):
        self.write("-p/s1.jsonl", [rec("msg_1"), rec("msg_2")])
        self.write("-p/s2-fork.jsonl", [rec("msg_1"), rec("msg_2"), rec("msg_3")])
        self.assertAlmostEqual(self.total(self.run_script()), 0.021, places=6)

    def test_subagent_copy_wins_over_main_sidechain(self):
        self.write("-p/s1.jsonl", [rec("msg_1", sidechain=True, extra={"attributionAgent": "main"})])
        self.write("-p/s1/subagents/agent-a.jsonl", [rec("msg_1", extra={"attributionAgent": "sonnet-worker"})])
        p = self.run_script()
        self.assertAlmostEqual(self.total(p), 0.007, places=6)
        self.assertRegex(p.stdout.split("subagents by role:")[1], r"sonnet-worker\s+agents=\s*1 calls=\s*1")

    def test_final_beats_partial_regardless_of_order(self):
        self.write("-p/s1.jsonl", [rec("msg_1", {"output_tokens": 500}), rec("msg_1", {"output_tokens": 10}, stop=None)])
        p = self.run_script()
        self.assertAlmostEqual(self.total(p), 0.007, places=6)
        self.assertEqual(self.cov(p, "partial"), 0)

    def test_only_partial_copies_flagged(self):
        self.write("-p/s1.jsonl", [rec("msg_1", {"output_tokens": 10}, stop=None), rec("msg_1", {"output_tokens": 20}, stop=None)])
        p = self.run_script()
        self.assertAlmostEqual(self.total(p), 0.0022, places=6)  # 1000*2/M + 20*10/M
        self.assertEqual((self.cov(p, "partial"), self.cov(p, "unique responses")), (1, 1))

    def test_conflicting_finals(self):
        self.write("-p/s1.jsonl", [rec("msg_1"), rec("msg_1", {"output_tokens": 600})])
        p = self.run_script()
        self.assertEqual(p.returncode, 0)
        self.assertEqual(self.cov(p, "conflicts"), 1)
        self.assertAlmostEqual(self.total(p), 0.008, places=6)  # keeps max-output copy
        self.assertEqual(self.run_script("--strict").returncode, 2)

    def test_identical_finals_are_not_a_conflict(self):
        self.write("-p/s1.jsonl", [rec("msg_1"), rec("msg_1")])
        p = self.run_script("--strict")
        self.assertEqual((p.returncode, self.cov(p, "conflicts")), (0, 0))

    def test_record_without_id_counted_and_flagged(self):
        self.write("-p/s1.jsonl", [rec(None), rec(None)])
        p = self.run_script()
        self.assertEqual(self.cov(p, "unidentified"), 2)
        self.assertAlmostEqual(self.total(p), 0.014, places=6)


class TestPricing(Base):
    def test_unknown_model_unpriced_not_zero(self):
        self.write("-p/s1.jsonl", [rec("msg_1"), rec("msg_2", model="claude-mystery-9", usage={"input_tokens": 123, "output_tokens": 45})])
        p = self.run_script()
        self.assertEqual(p.returncode, 0)
        self.assertAlmostEqual(self.total(p), 0.007, places=6)
        self.assertRegex(p.stdout, r"UNPRICED[^\n]*\n\s+claude-mystery-9\s+responses=1 in=123 cache_r=0 cache_w=0 out=45")
        self.assertIn("unpriced models:         claude-mystery-9", p.stdout)
        self.assertEqual(self.run_script("--strict").returncode, 2)

    def cw(self, cc):
        u = {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 1_000_000}
        if cc is not None:
            u["cache_creation"] = cc
        self.write("-p/s1.jsonl", [rec("msg_1", u)])
        return self.run_script()

    def test_1h_write_is_2x_input(self):
        p = self.cw({"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 1_000_000})
        self.assertAlmostEqual(self.total(p), 4.0, places=6)
        self.assertEqual(self.cov(p, "assumed_ttl"), 0)

    def test_5m_write_is_1_25x_input(self):
        p = self.cw({"ephemeral_5m_input_tokens": 1_000_000, "ephemeral_1h_input_tokens": 0})
        self.assertAlmostEqual(self.total(p), 2.5, places=6)

    def test_mixed_write_split(self):
        p = self.cw({"ephemeral_5m_input_tokens": 400_000, "ephemeral_1h_input_tokens": 600_000})
        self.assertAlmostEqual(self.total(p), 0.4 * 2.5 + 0.6 * 4.0, places=6)

    def test_missing_breakdown_priced_5m_and_counted(self):
        p = self.cw(None)
        self.assertAlmostEqual(self.total(p), 2.5, places=6)
        self.assertEqual(self.cov(p, "assumed_ttl"), 1)


class TestRewrites(Base):
    LABEL = "large cache rewrites after a >5 min gap (consistent with TTL expiry; cause not proven)"
    BIG = {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 40_000}

    def run_gap(self, second_ts, usage=None):
        self.write("-p/s1.jsonl", [rec("msg_1", {"input_tokens": 0, "output_tokens": 0}, ts="2026-10-20T10:00:00.000Z"),
                                   rec("msg_2", usage or self.BIG, ts=second_ts)])
        return self.run_script()

    def test_gap_6_min_counts(self):
        p = self.run_gap("2026-10-20T10:06:00.000Z")
        self.assertIn(self.LABEL + ": 1 responses, $0.10 total response cost, $0.10 of it cache writes", p.stdout)

    def test_gap_1_min_does_not(self):
        p = self.run_gap("2026-10-20T10:01:00.000Z")
        self.assertIn(self.LABEL + ": 0 responses, $0.00", p.stdout)

    def test_cache_read_larger_than_write_does_not(self):
        p = self.run_gap("2026-10-20T10:06:00.000Z", {**self.BIG, "cache_read_input_tokens": 50_000})
        self.assertIn(self.LABEL + ": 0 responses", p.stdout)


if __name__ == "__main__":
    unittest.main()
