from __future__ import annotations

from datetime import datetime, time, timedelta

from .model import Action, Rule, Session, Snapshot
from .storage import Store


class Engine:
    """Deterministic accounting. The OS adapter alone can terminate processes."""

    MAX_GAP = 2.5

    def __init__(self, store: Store):
        self.store = store
        self.previous: tuple[float, datetime, Snapshot, dict[int, Rule]] | None = None

    @staticmethod
    def matches(rule: Rule, snapshot: Snapshot):
        return tuple(p for p in snapshot.processes if p.path in rule.paths)

    @staticmethod
    def portions(start: datetime, end: datetime, duration: float):
        """Split a measured monotonic interval at local calendar midnight."""
        wall = (end - start).total_seconds()
        if duration <= 0 or wall <= 0:
            return []
        result = []
        cursor = start
        while cursor < end:
            boundary = datetime.combine(cursor.date() + timedelta(days=1), time.min)
            stop = min(end, boundary)
            result.append((cursor.date().isoformat(), duration * (stop - cursor).total_seconds() / wall))
            cursor = stop
        return result

    def tick(self, mono: float, now: datetime, snapshot: Snapshot) -> list[Action]:
        rules = self.store.rules()
        previous = self.previous
        actions = []
        day = now.date().isoformat()
        duration = 0.0
        if previous:
            elapsed = mono - previous[0]
            wall = (now - previous[1]).total_seconds()
            # Suspend, clock jumps and stale sampling are not active usage.
            if 0 < elapsed <= self.MAX_GAP and abs(wall - elapsed) < 1.0:
                duration = elapsed
        with self.store.transaction():
            for rule in rules:
                live = self.matches(rule, snapshot)
                tokens = {p.token for p in live}
                session = self.store.session(rule.id)
                if snapshot.complete:
                    if not tokens or not session.tokens.intersection(tokens):
                        session = Session(warnings={w for w in session.warnings if w.startswith(f"daily:{day}:")})
                    session.tokens = tokens
                elif tokens:
                    # An inaccessible scan must not silently erase a live session.
                    session.tokens.update(tokens)
                old_rule = previous[3].get(rule.id) if previous else None
                active = (rule.enabled and old_rule == rule and duration > 0 and previous is not None
                          and snapshot.complete and previous[2].complete
                          and snapshot.foreground_pid is not None
                          and snapshot.foreground_pid == previous[2].foreground_pid)
                if active:
                    fg = next((p for p in live if p.pid == snapshot.foreground_pid), None)
                    old_live = self.matches(rule, previous[2])
                    if fg and any(p.token == fg.token for p in old_live):
                        # A boundary sample can overshoot by at most one polling interval.
                        # Credit only up to the first limit, then enforce after commit.
                        remaining_single = max(0.0, rule.single_seconds - session.seconds)
                        for part_day, amount in self.portions(previous[1], now, duration):
                            remaining_daily = max(0.0, rule.daily_seconds - self.store.used(rule.id, part_day))
                            credit = min(amount, remaining_single, remaining_daily)
                            session.seconds += credit
                            remaining_single -= credit
                            self.store.add_usage(rule.id, part_day, credit)
                used = self.store.used(rule.id, day)
                reason = None
                if rule.enabled:
                    if used >= rule.daily_seconds:
                        reason = "daily"
                    elif session.seconds >= rule.single_seconds:
                        reason = "single"
                if reason and live:
                    actions.append(Action(rule.id, rule.name, reason, live))
                elif rule.enabled and live:
                    for kind, remaining in (("single", rule.single_seconds - session.seconds),
                                            ("daily", rule.daily_seconds - used)):
                        for threshold in (300, 60):
                            key = f"{kind}:{day if kind == 'daily' else 'session'}:{threshold}"
                            if 0 < remaining <= threshold and key not in session.warnings:
                                session.warnings.add(key)
                                minutes = threshold // 60
                                label = "今日累计" if kind == "daily" else "本次使用"
                                self.store.event(now.isoformat(), rule.id, "warning",
                                                 f"{rule.name}：{label}剩余不足 {minutes} 分钟")
                self.store.save_session(rule.id, session)
                state = ("已暂停" if not rule.enabled else "今日已达上限" if used >= rule.daily_seconds else
                         "本次已达上限" if session.seconds >= rule.single_seconds else
                         "前台计时中" if any(p.pid == snapshot.foreground_pid for p in live) else
                         "后台已暂停计时" if live else "等待启动")
                self.store.set_status(f"rule:{rule.id}", state)
            self.store.set_status("heartbeat", now.isoformat())
        self.previous = (mono, now, snapshot, {r.id: r for r in rules})
        return actions
