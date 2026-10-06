"""Auto-Rejoin: Protokollzeilen einordnen, neue Zeilen lesen, Ablauf bei Abbruch/Absturz/Verlassen."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import _env  # noqa: F401
from astral_monitor import rejoin
from astral_monitor.rejoin import AutoRejoin, LogTail, classify

PRE = "2026-10-06T14:02:36.565Z,689.565613,1bd8,6 "
JOIN = PRE + "[FLog::Output] ! Joining game '8db9f1b7-ad28-4088-a590-33b5a3451fce' place 102072869879193 at 10.0.0.1"
LEFT = PRE + "[FLog::Network] Sending disconnect with reason: 285"
LOST = PRE + "[FLog::Network] Disconnection Notification. Reason: 277"
PEER = PRE + "[FLog::Network] Connection lost: connectMode: Peer Disconnected, timeMS:1, connectionTime 1"
OTHER = PRE + "[FLog::Network] Disconnection Notification. Reason: 276"
LINK = "https://www.roblox.com/share?code=0123456789abcdef0123456789abcdef&type=Server"


class FakeTail:
    def __init__(self):
        self.lines = []

    def poll(self):
        out, self.lines = self.lines, []
        return out


class Rig:
    def __init__(self, link=LINK):
        self.s = SimpleNamespace(auto_rejoin_enabled=True, private_server_link=link)
        self.tail, self.alive, self.started, self.kills = FakeTail(), True, [], 0
        self.events, self.notes = [], []
        self.now = 0.0

        def kill():
            self.kills += 1
            return 1
        self.r = AutoRejoin(lambda: self.s, lambda t, lvl: self.events.append((t, lvl)),
                            lambda kind, title, *a, **k: self.notes.append((kind, title)),
                            tail=self.tail, alive=lambda: self.alive, kill=kill,
                            start=self.started.append, clock=lambda: self.now, sleep=lambda _s: None)

    def step(self, seconds, *lines):
        self.tail.lines += lines
        end = self.now + seconds
        while True:
            self.r.tick(self.now)
            if self.now >= end:
                break
            self.now = min(end, self.now + 1.0)


class ClassifyTests(unittest.TestCase):
    def test_lines(self):
        self.assertEqual(classify(JOIN), ("join", 102072869879193))
        self.assertEqual(classify(LEFT), ("left", 285))
        self.assertEqual(classify(LOST), ("lost", 277))
        self.assertEqual(classify(OTHER), ("left", 276))
        self.assertEqual(classify(PEER), ("lost", 0))
        self.assertEqual(classify(PRE + "[FLog::Network] Lost connection with reason : This game has been "
                                        "disconnected because you have joined a game from another device"), ("left", 0))
        self.assertIsNone(classify(PRE + "[FLog::Graphics] Adapter[0] info"))
        self.assertIsNone(classify(PRE + "[DFLog::NetworkClient] Client:Disconnect"))


class TailTests(unittest.TestCase):
    def test_reads_only_new_lines(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "0.1_20261006T1_Player_AAAA_last.log"
            f.write_bytes((JOIN + "\n").encode())
            (Path(d) / "0.1_20261006T1_Player_BBBB_CrashHandler_last.log").write_bytes(b"x Joining game\n")
            tail = LogTail(Path(d))
            self.assertEqual([classify(x) for x in tail.poll()], [("join", 102072869879193)])   # Stand beim Start
            self.assertEqual(tail.poll(), [])
            with open(f, "ab") as fh:
                fh.write((LOST + "\n" + "halbe Zei").encode())
            self.assertEqual([classify(x) for x in tail.poll()], [("lost", 277)])
            with open(f, "ab") as fh:
                fh.write(b"le\n")
            self.assertEqual(tail.poll(), ["halbe Zeile"])
            g = Path(d) / "0.1_20261006T2_Player_CCCC_last.log"                       # neuer Client: von vorn
            g.write_bytes((JOIN + "\n").encode())
            self.assertEqual(len(tail.poll()), 1)


class FlowTests(unittest.TestCase):
    def test_disconnect_rejoins_private_server(self):
        rig = Rig()
        rig.step(1, JOIN)
        self.assertEqual(rig.r.status, "in_game")
        rig.step(5, LOST)
        self.assertEqual(rig.r.status, "lost")
        self.assertEqual(rig.started, [])                          # Wartezeit (Teleport/Serverwechsel)
        rig.step(rejoin.GRACE + 4)
        self.assertEqual(rig.started, ["roblox://navigation/share_links?code=0123456789abcdef0123456789abcdef&type=Server"])
        self.assertEqual(rig.kills, 1)
        self.assertEqual(rig.r.status, "rejoining")
        rig.step(30, JOIN)
        self.assertEqual(rig.r.status, "in_game")
        self.assertEqual([n[0] for n in rig.notes], ["rejoin", "rejoin"])

    def test_leaving_yourself_does_not_rejoin(self):
        rig = Rig()
        rig.step(1, JOIN)
        rig.step(2, PEER, OTHER)                                   # auf anderem Gerät beigetreten
        rig.alive = False
        rig.step(60)
        self.assertEqual(rig.started, [])
        rig.step(1, JOIN)
        rig.step(1, LEFT)
        rig.step(60)
        self.assertEqual(rig.started, [])
        self.assertEqual(rig.r.status, "left")

    def test_teleport_within_grace_is_ignored(self):
        rig = Rig()
        rig.step(1, JOIN)
        rig.step(3, LOST)
        rig.step(3, JOIN)
        rig.step(30)
        self.assertEqual(rig.started, [])
        self.assertEqual(rig.r.status, "in_game")

    def test_crash_rejoins_public_without_link(self):
        rig = Rig(link="")
        rig.step(1, JOIN)
        rig.alive = False
        rig.step(rejoin.CRASH_AFTER + rejoin.POLL_PROCESS_EVERY + 3)
        self.assertEqual(rig.started, ["roblox://experiences/start?placeId=102072869879193"])

    def test_gives_up_after_max_attempts(self):
        rig = Rig()
        rig.step(1, JOIN)
        rig.step(1, LOST)
        rig.step(sum(rejoin.BACKOFF) + rejoin.GRACE + rejoin.MAX_ATTEMPTS * rejoin.JOIN_TIMEOUT + 30)
        self.assertEqual(len(rig.started), rejoin.MAX_ATTEMPTS)
        self.assertEqual(rig.r.status, "gave_up")
        self.assertIn("aufgegeben", rig.r.info())
        rig.step(1, JOIN)                                          # nächster Beitritt setzt zurück
        self.assertEqual((rig.r.status, rig.r.attempt), ("in_game", 0))

    def test_ocr_signal_and_switch_off(self):
        rig = Rig()
        rig.step(1, JOIN)
        rig.r.external_lost()
        rig.step(1)
        self.assertEqual(rig.r.status, "lost")
        rig.s.auto_rejoin_enabled = False
        rig.step(30)
        self.assertEqual((rig.r.status, rig.started), ("off", []))


if __name__ == "__main__":
    unittest.main()
