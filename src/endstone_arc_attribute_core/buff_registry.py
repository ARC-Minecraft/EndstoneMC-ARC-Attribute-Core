"""Buff 优先级队列：同一效果按等级维护优先级，高等级先生效，到期回退次高级。

例：请求A 速度1级10秒，请求B 速度2级5秒
  → 生效速度2（剩余 5s）；速度2 到期后回退速度1（剩余 5s）；全部到期 → 无生效。

- push：同一 source 重复请求为覆盖
- active：等级最高者；同等级取剩余时间最长者；确定序保证稳定
- expire：清理到期条目，返回当前生效条目是否变化（供上层决定是否重挂效果）
纯逻辑类，不接触 endstone 对象。
"""

import time


class BuffEntry:
    __slots__ = ("source", "level", "expire_at")

    def __init__(self, source: str, level: int, expire_at: float):
        self.source = str(source)
        self.level = int(level)
        self.expire_at = float(expire_at)

    def remaining(self, now: float) -> float:
        return max(0.0, self.expire_at - now)

    def is_expired(self, now: float) -> bool:
        return now >= self.expire_at


class BuffChannel:
    """单玩家单效果键的 buff 队列。"""

    def __init__(self):
        self._entries: dict[str, BuffEntry] = {}
        self._active_source: str | None = None

    # ---------- 增删 ----------

    def push(self, source: str, level: int, duration: float) -> None:
        key = str(source).strip()
        if not key:
            raise ValueError("buff source must not be empty")
        level = int(level)
        duration = float(duration)
        if level < 1 or duration <= 0:
            # 非法请求视为撤销该来源
            self.remove(key)
            return
        self._entries[key] = BuffEntry(key, level, time.time() + duration)

    def remove(self, source: str) -> bool:
        return self._entries.pop(str(source).strip(), None) is not None

    def clear(self) -> None:
        self._entries.clear()
        self._active_source = None

    # ---------- 查询 ----------

    def entries(self) -> list[BuffEntry]:
        return list(self._entries.values())

    def is_empty(self) -> bool:
        return not self._entries

    def active(self, now: float | None = None) -> BuffEntry | None:
        """等级最高者；同等级取 expire 最晚；source 字典序稳定。"""
        now = time.time() if now is None else now
        best: BuffEntry | None = None
        for entry in self._entries.values():
            if entry.is_expired(now):
                continue
            if best is None:
                best = entry
                continue
            if (entry.level, entry.expire_at, entry.source) > (best.level, best.expire_at, best.source):
                best = entry
        return best

    # ---------- 到期维护 ----------

    def expire(self, now: float | None = None) -> bool:
        """清理到期条目；返回「当前生效条目」是否变化（上层据此重挂效果）。"""
        now = time.time() if now is None else now
        before = self._active_source
        expired = [k for k, e in self._entries.items() if e.is_expired(now)]
        for k in expired:
            self._entries.pop(k, None)
        current = self.active(now)
        self._active_source = current.source if current else None
        return before != self._active_source

    def mark_applied(self, now: float | None = None) -> None:
        """上层把 active() 实际挂到玩家后调用，记录当前生效 source。"""
        current = self.active(now)
        self._active_source = current.source if current else None

    # ---------- 展示 ----------

    def describe(self, now: float | None = None) -> list[str]:
        now = time.time() if now is None else now
        lines = []
        act = self.active(now)
        act_source = act.source if act else None
        for entry in sorted(
            self._entries.values(),
            key=lambda e: (-e.level, -e.expire_at, e.source),
        ):
            if entry.is_expired(now):
                continue
            mark = " ←生效中" if entry.source == act_source else ""
            lines.append(
                f"Lv{entry.level} 剩{entry.remaining(now):.0f}s 来源={entry.source}{mark}"
            )
        return lines
