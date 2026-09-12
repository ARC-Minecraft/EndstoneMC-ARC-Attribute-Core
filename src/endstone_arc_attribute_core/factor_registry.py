"""属性因子表：多来源增删调整因子，get 时按公式计算最终值。

公式（与 AttributeModifier.MULTIPLY 的引擎语义一致）：

    最终值 = (base + Σ add因子) × Π (1 + multiply因子)

例：base=1，加入 multiply 因子 0.25、-0.05、-0.10、0.15
  → 1 × 1.25 × 0.95 × 0.90 × 1.15

因子支持 duration（秒，None=无限期）：compute 时懒剔除已过期因子，
expire() 主动清理并返回被移除的 source（供定时器触发落地重算）。
同一 source 重复 add 为覆盖。
"""

import time

OP_MULTIPLY = "multiply"
OP_ADD = "add"
_VALID_OPS = (OP_MULTIPLY, OP_ADD)


class Factor:
    __slots__ = ("amount", "operation", "expire_at")

    def __init__(self, amount: float, operation: str, expire_at: float | None):
        self.amount = float(amount)
        self.operation = operation
        self.expire_at = expire_at

    def is_expired(self, now: float) -> bool:
        return self.expire_at is not None and now >= self.expire_at

    def remaining(self, now: float) -> float | None:
        if self.expire_at is None:
            return None
        return max(0.0, self.expire_at - now)


class FactorRegistry:
    """单玩家单属性键的因子表。纯逻辑类，不接触 endstone 对象。"""

    def __init__(self, base: float = 0.0):
        self.base = float(base)
        self._factors: dict[str, Factor] = {}

    # ---------- 增删 ----------

    def add(
        self,
        source: str,
        amount: float,
        duration: float | None = None,
        operation: str = OP_MULTIPLY,
    ) -> None:
        key = str(source).strip()
        if not key:
            raise ValueError("factor source must not be empty")
        op = str(operation).strip().lower()
        if op not in _VALID_OPS:
            raise ValueError(f"operation must be one of {_VALID_OPS}")
        expire_at = None
        if duration is not None:
            duration = float(duration)
            if duration <= 0:
                # 非法时长视为立即过期：直接移除，不留因子
                self._factors.pop(key, None)
                return
            expire_at = time.time() + duration
        self._factors[key] = Factor(amount, op, expire_at)

    def remove(self, source: str) -> bool:
        return self._factors.pop(str(source).strip(), None) is not None

    def clear(self) -> None:
        self._factors.clear()

    # ---------- 查询 ----------

    def get(self, source: str) -> Factor | None:
        return self._factors.get(str(source).strip())

    def sources(self) -> list[str]:
        return list(self._factors.keys())

    def is_empty(self) -> bool:
        return not self._factors

    def compute(self, now: float | None = None) -> float:
        """最终值 = (base + Σadd) × Π(1+mul)；已过期因子在此懒剔除。"""
        now = time.time() if now is None else now
        total_add = 0.0
        product = 1.0
        expired = [k for k, f in self._factors.items() if f.is_expired(now)]
        for k in expired:
            self._factors.pop(k, None)
        for f in self._factors.values():
            if f.operation == OP_ADD:
                total_add += f.amount
            else:
                product *= 1.0 + f.amount
        return (self.base + total_add) * product

    def expire(self, now: float | None = None) -> list[str]:
        """主动清理到期因子，返回被移除的 source 列表（供上层重算落地）。"""
        now = time.time() if now is None else now
        expired = [k for k, f in self._factors.items() if f.is_expired(now)]
        for k in expired:
            self._factors.pop(k, None)
        return expired

    # ---------- 展示 ----------

    def describe(self, now: float | None = None) -> list[str]:
        now = time.time() if now is None else now
        lines = []
        for source, f in sorted(self._factors.items()):
            remain = f.remaining(now)
            time_part = "永久" if remain is None else f"{remain:.0f}s"
            sign = f"{f.amount:+g}"
            if f.operation == OP_ADD:
                lines.append(f"{source}: {sign} [add, {time_part}]")
            else:
                lines.append(f"{source}: {sign} [mul→x{1.0 + f.amount:.3f}, {time_part}]")
        return lines
