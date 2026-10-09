"""Macro part “raid / defense”: start or join, gear menu (Auto Retry, Auto Leave + wave), farm until the end
condition, steps inside the raid, leave only before a different raid. Without Qt."""

from __future__ import annotations

import ctypes
import re
import time
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from . import vision
from .i18n import tr
from .macro_base import _ACTIVE, Stop, UserStop, task_label

RAID_KINDS = ("raid",)                                    # tasks that lead into a raid/mode
IN_RAID_KINDS = ("autoroll", "progression")      # quick menu tasks that also work inside a raid (owner 09.10.2026)
RAID_GEAR = Path(__file__).with_name("uimap_static") / "raid_gear.png"   # gear at the top right in a raid (fixed, not from the map)
GEAR_REGION = [0.4, 0.0, 0.9, 0.16]
LEAVE_REGION = [0.35, 0.0, 0.75, 0.2]
GEAR_HIT = 0.75
# raid settings layout (measured 09.10.2026), in widths of the “Auto Leave” label: Auto Retry this far above, the
# field “Wave N” centered this far right/below, half width/height of the field
RAID_LAYOUT = {"dy": 0.464, "field_dx": 1.058, "field_dy": 0.363, "field_hw": 0.45, "field_hh": 0.09}
TOGGLE_TRIES = 24          # looks at the switch color (cheap) – messages pass within a few seconds
GEAR_TRIES = 6            # click the gear again if the menu doesn't open (loading screen swallows clicks)
GEAR_WAIT = 2.0           # wait this long for the menu after each click


def raid_side_steps(tasks: list[dict], index: int) -> list[int]:
    """Steps right after the raid step tasks[index] that run INSIDE the raid, once its settings are set: Auto Roll
    and Progressions up to the next raid or pause (owner 09.10.2026: “Farm … until stopped” never ended, so the
    gachas/pets after it never started)."""
    if tasks[index].get("kind") != "raid":
        return []
    out = []
    for j in range(index + 1, len(tasks)):
        if tasks[j].get("kind") not in IN_RAID_KINDS:
            break
        out.append(j)
    return out


def leave_before(task: dict, following: Optional[dict]) -> bool:
    """Leave the raid before continuing? Only if a DIFFERENT raid/mode comes next (owner 08.10.2026) –
    for Auto Roll, gigs, guild … you stay in (Auto Retry keeps farming)."""
    if following is None or following.get("kind") not in RAID_KINDS:
        return False
    return following.get("target") != task.get("target")


def complete_raid_labels(out: dict, aspect: float) -> dict:
    """The raid settings always have the same layout: “Auto Retry” above “Auto Leave”, the field “Wave N” below.
    “Wave cleared!” messages often cover part of it (owner 09.10.2026: 4–6 at once) – from one readable label the
    others follow (RAID_LAYOUT, in widths of the “Auto Leave” label; aspect = image width / height). The grey
    field text “Wave 12” is often not read at all: its position is calculated."""
    out = dict(out)
    ref = out.get("leave") or out.get("retry")
    if ref is None:
        return out
    w = ref[2] - ref[0]
    dy = RAID_LAYOUT["dy"] * w * aspect                  # x and y fractions have different scales
    if "leave" not in out:
        r = out["retry"]
        out["leave"] = [r[0], r[1] + dy, r[2], r[3] + dy]
    if "retry" not in out:
        lv = out["leave"]
        out["retry"] = [lv[0], lv[1] - dy, lv[2], lv[3] - dy]
    if "wave" not in out:
        lv = out["leave"]
        cx = lv[0] + RAID_LAYOUT["field_dx"] * w
        cy = (lv[1] + lv[3]) / 2 + RAID_LAYOUT["field_dy"] * w * aspect
        hw, hh = RAID_LAYOUT["field_hw"] * w, RAID_LAYOUT["field_hh"] * w * aspect
        out["wave"] = [cx - hw, cy - hh, cx + hw, cy + hh]
    return out


class RaidMixin:
    """Part of the Navigator (automation.Navigator) – uses its input, image and log methods."""

    def _raid(self, window: dict, join: bool) -> None:
        """Open the raid window and press “Create”/“Start” (own raid, costs a key) or “Join”.
        What comes afterwards (lobby, teleport) is logged and saved as an image for troubleshooting."""
        self._open(window)
        if join:
            self._press(window, ("join",))
        else:
            self._press(window, ("create",), ("start",))
        time.sleep(3.0)
        frame = self._frame()
        kind, st = self._screen(frame)
        self.log(tr("Afterwards: {state}", state=(st[1] if kind == "menu" else kind) or "?"))
        try:
            from .app_paths import debug_dir
            path = debug_dir() / f"makro_raid_{time.strftime('%H%M%S')}.jpg"
            small = cv2.resize(frame, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
            cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tofile(str(path))
        except Exception:  # noqa: BLE001 – only a debugging aid
            pass

    def _gear(self, frame: np.ndarray) -> Optional[list[float]]:
        """Gear at the top right next to wave/timer – only visible in a raid."""
        if not hasattr(self, "_gear_tpl"):
            self._gear_tpl = cv2.imdecode(np.fromfile(str(RAID_GEAR), dtype=np.uint8), cv2.IMREAD_COLOR)
        score, box = vision.find_multiscale(frame, self._gear_tpl, GEAR_REGION)
        return box if score >= GEAR_HIT else None

    def _stable_gear(self, timeout: float = 12.0) -> Optional[list[float]]:
        """Only click the gear once the raid is really running: “Starting defense …” darkens the image and swallows
        clicks. It waits until the monitoring reads a wave (if connected) and the gear is at the same spot twice."""
        end = time.monotonic() + timeout
        last = None
        while time.monotonic() < end:
            self._check()
            gear = self._gear(self._frame())
            wave_ok = self.wave_visible is None or self.wave_visible()
            if gear is not None and wave_ok and last is not None and abs(gear[0] - last[0]) < 0.004                     and abs(gear[1] - last[1]) < 0.004:
                return gear
            last = gear
            time.sleep(0.5)
        return last

    def _labels(self, frame: np.ndarray) -> dict:
        """Labels in the gear menu: {"retry": position, "leave": position, "wave": position of the wave field}."""
        words = vision.words_in(frame, [0.2, 0.1, 0.8, 0.9], self._ocr)
        norm = [(re.sub(r"[^a-z0-9]", "", w.lower()), b) for w, b in words]
        out = {}
        for key, second in (("retry", "retry"), ("leave", "leave")):
            for w, b in norm:
                if w != "auto":
                    continue
                nxt = next((b2 for w2, b2 in norm if w2 == second and 0 <= b2[0] - b[2] < 0.03
                            and abs((b2[1] + b2[3]) / 2 - (b[1] + b[3]) / 2) < 0.015), None)
                if nxt is not None:
                    out[key] = [b[0], min(b[1], nxt[1]), nxt[2], max(b[3], nxt[3])]
                    break
        if "leave" in out:                                # field “Wave 85” right below “Auto Leave”
            lv = out["leave"]
            field = next((b for w, b in norm if w == "wave" and 0 < b[1] - lv[3] < 0.08
                          and abs(b[0] - lv[0]) < 0.12), None)
            if field is not None:
                out["wave"] = field
        return complete_raid_labels(out, frame.shape[1] / frame.shape[0])

    def _open_raid_settings(self) -> dict:
        """Open the gear menu and remember where its parts are (self._raid_labels) – the menu doesn't move, so the
        following steps don't need to read it again (fast, and messages covering it don't matter)."""
        self._raid_labels = {}
        frame = self._frame()
        labels = self._labels(frame)
        if "retry" in labels or "leave" in labels:
            self._raid_labels = labels
            return labels
        gear = self._stable_gear()
        if gear is None:
            raise Stop(tr("No raid gear found – are you in a raid?"))
        self.log(tr("Opening the raid settings (gear)."))
        for attempt in range(GEAR_TRIES):
            if attempt:                                   # loading screen (“Starting defense …”) swallowed the click
                self.log(tr("Gear: no reaction yet (loading screen?) – clicking again."))
                gear = self._gear(self._frame()) or gear
            self._click(((gear[0] + gear[2]) / 2, (gear[1] + gear[3]) / 2))
            end = time.monotonic() + GEAR_WAIT
            while time.monotonic() < end:
                time.sleep(0.3)
                labels = self._labels(self._frame())
                if "retry" in labels or "leave" in labels:   # one readable label is enough (complete_raid_labels)
                    self._raid_labels = labels
                    return labels
        raise Stop(tr("The raid settings did not open."))

    def _set_toggle(self, key: str, on: bool) -> None:
        """Set the switch “Auto Retry”/“Auto Leave” and verify it. Uses the remembered position of the open menu
        and only looks at the switch color – while a message covers it, wait briefly and look again."""
        name = "Auto Retry" if key == "retry" else "Auto Leave"
        clicks = 0
        for _ in range(TOGGLE_TRIES):
            frame = self._frame()
            label = (getattr(self, "_raid_labels", {}) or {}).get(key) or self._labels(frame).get(key)
            if label is None:
                time.sleep(0.3)
                continue
            state = vision.toggle_state(frame, label)
            if state is None:                             # covered by “Wave cleared!”: look again shortly
                time.sleep(0.25)
                continue
            if state == on:
                self.log(tr("{name}: {state}", name=name, state=tr("on") if on else tr("off")))
                return
            if clicks >= 3:
                break
            cy = (label[1] + label[3]) / 2
            self._click((label[2] + 0.05, cy))           # switch to the right of the label
            clicks += 1
            time.sleep(0.5)
        raise Stop(tr("Couldn't switch “{name}” reliably.", name=name))

    def _set_leave_wave(self, wave: int) -> None:
        field = (getattr(self, "_raid_labels", {}) or {}).get("wave") or self._labels(self._frame()).get("wave")
        if field is None:
            raise Stop(tr("Wave field (auto leave) not found."))
        from .antiafk import _key
        self._click_roi(field)
        time.sleep(0.3)
        for _ in range(6):                                # delete the old number
            _key(0x08, True, 0x0E)
            _key(0x08, False, 0x0E)
            time.sleep(0.04)
        scans = {"1": 0x02, "2": 0x03, "3": 0x04, "4": 0x05, "5": 0x06, "6": 0x07, "7": 0x08, "8": 0x09, "9": 0x0A,
                 "0": 0x0B}
        for ch in str(int(wave)):
            _key(ord(ch), True, scans[ch])
            _key(ord(ch), False, scans[ch])
            time.sleep(0.05)
        _key(0x0D, True, 0x1C)                            # Enter
        _key(0x0D, False, 0x1C)
        self.log(tr("Auto leave from wave {wave}.", wave=wave))
        time.sleep(0.4)

    def _close_raid_settings(self) -> None:
        frame = self._frame()
        labels = self._labels(frame) or (getattr(self, "_raid_labels", {}) or {})   # covered: remembered position
        self._raid_labels = {}
        if not labels:
            return
        anchor = labels.get("retry") or labels.get("leave")
        region = [anchor[0], max(0.0, anchor[1] - 0.2), min(1.0, anchor[2] + 0.25), anchor[1]]
        score, box = vision.find_multiscale(frame, self._menu.x_tpl, region, (0.4, 0.5, 0.6, 0.7, 0.8, 1.0))
        if score >= 0.6 and box is not None:
            self._click_roi(box)                          # pink X at the top right of the menu
        else:
            gear = self._gear(frame)
            if gear is not None:
                self._click_roi(gear)                     # the gear closes it again
        time.sleep(0.6)

    def _leave_raid(self) -> None:
        """Leave the raid: first Auto Retry off (otherwise you are thrown back in), then LEAVE!."""
        self._open_raid_settings()
        self._set_toggle("retry", False)
        self._close_raid_settings()
        box = vision.find_word(self._frame(), LEAVE_REGION, self._ocr, "leave", "leave!")
        if box is None:
            raise Stop(tr("“LEAVE!” not found."))
        self.log(tr("Clicking “{button}”.", button="LEAVE!"))
        # The raid “LEAVE!” at the top middle is wanted (leave the raid). No-go zones only apply while the guild or
        # a window is open while exploring – none is active here (guild “Leave” at the bottom left of the guild window).
        self._click_roi(box)
        time.sleep(3.0)

    def _ensure_monitoring(self) -> None:
        if self.monitoring is None or self.raid_count is None:
            raise Stop(tr("Raids need monitoring to run (it counts the raids)."))
        if self.monitoring():
            return
        if self.start_monitoring is None:
            raise Stop(tr("Raids need monitoring to run (it counts the raids)."))
        self.log(tr("Starting monitoring (it counts the raids)."))
        self.start_monitoring()
        end = time.monotonic() + 15
        while not self.monitoring():
            if time.monotonic() > end:
                raise Stop(tr("Monitoring could not be started."))
            self._check()
            time.sleep(0.3)

    def _raid_task(self, task: dict, following: Optional[dict]) -> None:
        """Start/join a raid (unless you are already farming exactly this one), set Auto Retry + Auto Leave, farm to
        the
                end (N raids, M minutes or without end), then only leave if a different raid/mode follows."""
        target = task.get("target", "")
        self._ensure_monitoring()
        if self.set_raid is not None:
            self.set_raid(target)
        leave_wave = int(task.get("leave_wave", 0))
        if self._in_raid == target and self._gear(self._frame()) is not None:
            self.log(tr("Already in raid “{name}” – farming on.", name=target))
        else:
            if self._gear(self._frame()) is not None:     # still in another raid
                self._leave_raid()
            self._in_raid = None
            self._raid(self._window(target), bool(task.get("join")))
            end = time.monotonic() + 120                  # until you are in the raid (teleport, lobby)
            while self._gear(self._frame()) is None:
                if time.monotonic() > end:
                    raise Stop(tr("Did not arrive in the raid."))
                time.sleep(1.0)
            self._in_raid = target
        self._open_raid_settings()
        self._set_toggle("retry", True)
        if leave_wave > 0:                                # wave first, then the switch: the game's default is 5 –
            self._set_leave_wave(leave_wave)              # switched on first it could leave too early (owner 09.10.2026)
        self._set_toggle("leave", leave_wave > 0)
        self._close_raid_settings()
        self._run_side_steps()
        until = task.get("until", "runs")
        runs, minutes = int(task.get("runs", 1)), float(task.get("minutes", 30))
        start, t0 = self.raid_count(), time.monotonic()
        self.log({"runs": tr("Farming {runs} raids …", runs=runs),
                  "minutes": tr("Farming {minutes} min …", minutes=int(minutes))}.get(until, tr("Farming until you stop …")))
        _ACTIVE.clear()                                   # Anti-AFK may run while waiting
        try:
            last = 0
            while True:
                done = self.raid_count() - start
                if until == "runs" and done >= runs:
                    break
                if until == "minutes" and time.monotonic() - t0 >= minutes * 60:
                    break
                if done != last:
                    last = done
                    self.log(tr("{done} raids done", done=done))
                self._extras_while_waiting()
                if self._halt.wait(2.0):
                    raise UserStop(tr("Stopped."))
                if ctypes.windll.user32.GetAsyncKeyState(0x1B) & 0x8000:
                    raise UserStop(tr("Cancelled (Esc)."))
        finally:
            _ACTIVE.set()
        self._focus()
        if leave_before(task, following):
            self.log(tr("A different raid is next – leaving this one."))
            self._leave_raid()
            self._in_raid = None
        else:
            self.log(tr("Staying in the raid (Auto Retry keeps farming)."))

    def _run_side_steps(self) -> None:
        """Auto Roll & co. placed after the raid step: run them now, inside the raid (raid_side_steps)."""
        steps, self._side_steps = getattr(self, "_side_steps", []), []
        for j, side, count in steps:
            self.queue_pos = j
            self.log(tr("In the raid – step {n}/{count}: {task}", n=j + 1, count=count, task=task_label(side)))
            for attempt in (1, 2):
                try:
                    self._task(side)
                    break
                except UserStop:
                    raise
                except Stop as exc:
                    if attempt == 2:
                        self.log("⚠ " + tr("Skipped: {reason}", reason=exc))
                    else:
                        self.log("⚠ " + tr("{reason} – trying once more.", reason=exc))
                        self._close_any_quiet()
            time.sleep(0.6)
        if steps:
            self.queue_pos = steps[0][0] - 1                  # back to the raid step for the display
