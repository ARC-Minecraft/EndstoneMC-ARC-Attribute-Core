import time

from endstone.command import Command, CommandSender
from endstone.event import event_handler, PlayerJoinEvent, PlayerQuitEvent, PlayerRespawnEvent, PluginEnableEvent
from endstone.plugin import Plugin

from .attribute_keys import ATTRIBUTE_KEYS, DIRECT_PROPS, FALLBACK_DIRECT_PROPS, FALLBACK_INT_PROPS
from .buff_registry import BuffChannel
from .effect_compat import apply_mob_effect, remove_mob_effect, resolve_effect_type
from .factor_registry import FactorRegistry, OP_ADD, OP_MULTIPLY
from .feature_menu import FeatureMenu

DIRECT_MIN = 0.01
DIRECT_MAX = 1.0


class ARCAttributeCorePlugin(Plugin):
    """多插件共享的玩家属性因子 / buff 优先级管理器。

    属性因子：最终值 = (base + Σadd) × Π(1+mul)；Attribute 系挂 AttributeModifier
    （multiply→MULTIPLY 逐个连乘，add→ADD），walk_speed/fly_speed 直写。
    Buff：同效果按等级排队，高等级先生效，到期回退次高级剩余时长。
    """

    prefix = "ARCAttributeCore"
    api_version = "0.10"
    load = "POSTWORLD"

    commands = {
        "arcattr": {
            "description": "查看玩家属性因子与 buff（OP 可查他人、reload）",
            "usages": ["/arcattr", "/arcattr <player>", "/arcattr reload"],
            "permissions": ["arc_attribute_core.command.common"],
        },
    }

    permissions = {
        "arc_attribute_core.command.common": {
            "description": "全员查看自己的因子与 buff",
            "default": True,
        },
        "arc_attribute_core.command.admin": {
            "description": "查看任意玩家、reload",
            "default": "op",
        },
    }

    def __init__(self):
        super().__init__()
        # (xuid, key) -> FactorRegistry
        self._factors: dict[tuple[str, str], FactorRegistry] = {}
        # (xuid, effect_key) -> BuffChannel
        self._buffs: dict[tuple[str, str], BuffChannel] = {}
        self._task = None
        # OP 功能菜单（注册进弧光核心主菜单）
        self._menu = FeatureMenu(self)
        self._menu_registered = False
        # 已告警过不可用的属性键（避免刷屏）
        self._unsupported_keys: set[str] = set()

    # ---------- 生命周期 ----------

    def on_load(self) -> None:
        self.logger.info("[ARCAttributeCore] on_load is called!")

    def on_enable(self) -> None:
        self.logger.info("[ARCAttributeCore] on_enable is called!")
        self.register_events(self)
        self._start_timer()
        self._register_feature_menu()

    def on_disable(self) -> None:
        self.logger.info("[ARCAttributeCore] on_disable is called!")
        if self._task is not None:
            try:
                self._task.cancel()
            except Exception:
                pass
            self._task = None
        try:
            core = self.server.plugin_manager.get_plugin("arc_core")
            if core is not None and self._menu.unregister_from(core):
                self._menu_registered = False
        except Exception:
            pass

    def _register_feature_menu(self) -> None:
        """向弧光核心注册主菜单「功能菜单」按钮；核心晚加载时由 PluginEnableEvent 兜底。"""
        if self._menu_registered:
            return
        try:
            core = self.server.plugin_manager.get_plugin("arc_core")
        except Exception:
            return
        if core is None:
            return
        try:
            if self._menu.register_into(core):
                self._menu_registered = True
                self.logger.info("[ARCAttributeCore] 已注册弧光核心主菜单「属性管理器」按钮（仅 OP 可见）")
        except Exception as e:
            self.logger.warning(f"[ARCAttributeCore] 注册功能菜单按钮失败: {e}")

    def _start_timer(self) -> None:
        """统一 20-tick（1 秒）定时器：清理过期因子与 buff 并重算落地。"""
        try:
            if self._task is not None:
                try:
                    self._task.cancel()
                except Exception:
                    pass
                self._task = None

            def tick():
                try:
                    self._tick_once(time.time())
                except Exception as e:
                    self.logger.error(f"[ARCAttributeCore] timer error: {e}")

            self._task = self.server.scheduler.run_task(self, tick, 20, 20)
        except Exception as e:
            self.logger.error(f"[ARCAttributeCore] start timer error: {e}")

    def _tick_once(self, now: float) -> None:
        """清理过期因子与 buff 并重算落地（now 可注入便于测试）。"""
        for (xuid, key), registry in list(self._factors.items()):
            expired = registry.expire(now)
            if not expired:
                continue
            player = self._player_by_xuid(xuid)
            if player is None:
                continue
            if key in DIRECT_PROPS:
                self._apply_direct(player, key)
            else:
                self._land_attribute_key(player, key, expired, remove=True)
        for (xuid, effect_key), channel in list(self._buffs.items()):
            if not channel.expire(now):
                continue
            player = self._player_by_xuid(xuid)
            if player is not None:
                self._apply_active_buff(player, effect_key, now)

    # ---------- 对外 API：属性因子 ----------

    def api_add_factor(
        self,
        player,
        key: str,
        source: str,
        amount: float,
        duration: float | None = None,
        operation: str = OP_MULTIPLY,
    ) -> bool:
        """注册一个调整因子。duration 秒后自动移除；None=无限期。

        operation: "multiply"（默认，最终值连乘 (1+amount)）或 "add"（base 上加减数值）。
        """
        key = self._normalize_key(key)
        if key is None:
            return False
        xuid = self._get_xuid(player)
        registry = self._factors.get((xuid, key))
        if registry is None:
            registry = FactorRegistry(base=self._key_base(key))
            self._factors[(xuid, key)] = registry
        registry.add(source, amount, duration, operation)
        self._land_factor(player, key, source=source)
        return True

    def api_remove_factor(self, player, key: str, source: str) -> bool:
        key = self._normalize_key(key)
        if key is None:
            return False
        xuid = self._get_xuid(player)
        registry = self._factors.get((xuid, key))
        if registry is None or not registry.remove(source):
            return False
        if registry.is_empty():
            self._factors.pop((xuid, key), None)
        self._land_factor(player, key, source=source, remove=True)
        return True

    def api_clear_factors(self, player, key: str | None = None) -> int:
        """清除玩家的因子（key=None 清全部）。返回清除的因子数量。"""
        xuid = self._get_xuid(player)
        targets = []
        if key is None:
            targets = [k for k in self._factors if k[0] == xuid]
        else:
            norm = self._normalize_key(key)
            if norm is not None and (xuid, norm) in self._factors:
                targets = [(xuid, norm)]
        removed = 0
        for slot in targets:
            registry = self._factors.pop(slot, None)
            if registry is None:
                continue
            removed += len(registry.sources())
            src_key = slot[1]
            if src_key in DIRECT_PROPS:
                self._apply_direct(player, src_key)
            else:
                self._land_attribute_key(player, src_key, registry.sources(), remove=True)
        return removed

    def _key_base(self, key: str) -> float:
        """属性键的注册表 base：direct / 替代直写键用引擎默认值，其余为 0。"""
        base = DIRECT_PROPS.get(key)
        if base is not None:
            return base
        return FALLBACK_DIRECT_PROPS.get(key, ("", 0.0))[1]

    def _land_factor(self, player, key: str, source: str | None = None, remove: bool = False) -> None:
        """单因子落地：direct 键直写；attribute 键优先 modifier，引擎不可用时走替代直写通道。"""
        if key in DIRECT_PROPS:
            self._apply_direct(player, key)
            return
        self._land_attribute_key(player, key, [source] if source else [], remove=remove)

    def _land_attribute_key(self, player, key: str, sources, remove: bool = False) -> None:
        """attribute 键落地：引擎支持 get_attribute 时逐个同步/撤销 modifier，
        否则若配置了替代直写通道（如 health→max_health）则整键重算直写；再无通道仅登记。"""
        attr = self._get_attribute(player, key)
        if attr is not None:
            for src in sources:
                if remove:
                    self._remove_modifier(player, key, src)
                else:
                    self._sync_modifier(player, key, src)
        elif key in FALLBACK_DIRECT_PROPS:
            self._apply_direct(player, key)

    def api_get_factor_value(self, player, key: str) -> float | None:
        """查询最终值：direct / 替代直写属性返回钳制后的实际写入值；attribute 系返回因子合成值。"""
        key = self._normalize_key(key)
        if key is None:
            return None
        registry = self._factors.get((self._get_xuid(player), key))
        if registry is None:
            return float(self._key_base(key))
        value = registry.compute()
        if key in DIRECT_PROPS:
            return max(DIRECT_MIN, min(DIRECT_MAX, value))
        if key in FALLBACK_DIRECT_PROPS:
            return max(1.0, min(1024.0, value))
        return value

    def api_list_factors(self, player, key: str | None = None) -> dict[str, list[str]]:
        """调试/面板用：{属性键: [因子描述行]}。"""
        xuid = self._get_xuid(player)
        result: dict[str, list[str]] = {}
        for (uid, k), registry in sorted(self._factors.items()):
            if uid != xuid:
                continue
            if key is not None and k != self._normalize_key(key):
                continue
            lines = registry.describe()
            if lines:
                result[k] = lines
        return result

    def _factor_sources(self, player, key: str) -> list[str]:
        """指定属性的来源列表（功能菜单移除面板用）。"""
        key = self._normalize_key(key)
        if key is None:
            return []
        registry = self._factors.get((self._get_xuid(player), key))
        return registry.sources() if registry is not None else []

    # ---------- 对外 API：buff ----------

    def api_apply_buff(self, player, effect: str, level: int, duration: float, source: str) -> bool:
        """挂 buff：等级=显示等级（速度1 → amplifier 0）；同效果高等级先生效。

        duration 秒；同一 source 重复请求为覆盖。
        """
        effect_key = self._normalize_effect(effect)
        if effect_key is None:
            return False
        resolved = resolve_effect_type(effect_key)
        if resolved is None:
            self.logger.warning(f"[ARCAttributeCore] 未知效果: {effect}")
            return False
        slot = (self._get_xuid(player), effect_key)
        channel = self._buffs.get(slot)
        if channel is None:
            channel = BuffChannel()
            self._buffs[slot] = channel
        channel.push(source, level, duration)
        self._apply_active_buff(player, effect_key)
        return True

    def api_remove_buff(self, player, effect: str, source: str | None = None) -> bool:
        """撤销 buff：source=None 清空该效果全部条目并移除效果。"""
        effect_key = self._normalize_effect(effect)
        if effect_key is None:
            return False
        slot = (self._get_xuid(player), effect_key)
        channel = self._buffs.get(slot)
        if channel is None:
            return False
        if source is None:
            channel.clear()
            self._buffs.pop(slot, None)
        elif not channel.remove(source):
            return False
        if channel.is_empty():
            self._buffs.pop(slot, None)
        self._apply_active_buff(player, effect_key)
        return True

    def api_get_active_buff(self, player, effect: str) -> tuple[int, float] | None:
        """当前生效的 (等级, 剩余秒)；无则 None。"""
        effect_key = self._normalize_effect(effect)
        if effect_key is None:
            return None
        channel = self._buffs.get((self._get_xuid(player), effect_key))
        if channel is None:
            return None
        entry = channel.active()
        if entry is None:
            return None
        return entry.level, entry.remaining(time.time())

    def api_list_buffs(self, player) -> dict[str, list[str]]:
        """调试/面板用：{效果键: [队列描述行]}。"""
        xuid = self._get_xuid(player)
        result: dict[str, list[str]] = {}
        for (uid, effect_key), channel in sorted(self._buffs.items()):
            if uid != xuid:
                continue
            lines = channel.describe()
            if lines:
                result[effect_key] = lines
        return result

    # ---------- 落地 ----------

    def _apply_direct(self, player, key: str) -> None:
        """direct / 替代直写键：base × 因子连乘后写回玩家属性（钳制 0.01~1.0 / health 1~1024）。"""
        try:
            registry = self._factors.get((self._get_xuid(player), key))
            base = DIRECT_PROPS.get(key)
            prop = key
            if base is None:
                fallback = FALLBACK_DIRECT_PROPS.get(key)
                if fallback is None:
                    return
                prop, base = fallback
            value = registry.compute() if registry is not None else base
            if key in DIRECT_PROPS:
                value = max(DIRECT_MIN, min(DIRECT_MAX, value))
            else:
                value = max(1.0, min(1024.0, value))
            if prop in FALLBACK_INT_PROPS:
                value = int(round(value))  # max_health 等 setter 仅收整数
            try:
                current = float(getattr(player, prop))
            except Exception:
                current = None
            if current is not None and abs(current - value) < 1e-9:
                return  # 值未变化不写入，避免无谓打断疾跑
            was_sprinting = bool(getattr(player, "is_sprinting", False))
            setattr(player, prop, value)
            if was_sprinting and key == "walk_speed":
                self._restore_sprint(player)
        except Exception as e:
            self.logger.error(f"[ARCAttributeCore] apply direct {key} error: {e}")

    def _restore_sprint(self, player) -> None:
        """改 walk_speed 会打断疾跑：同 tick 写回一次，下一 tick 再写回一次。"""
        try:
            player.is_sprinting = True
        except Exception:
            return
        try:
            xuid = self._get_xuid(player)

            def _restore():
                p = self._player_by_xuid(xuid)
                if p is not None:
                    try:
                        p.is_sprinting = True
                    except Exception:
                        pass

            self.server.scheduler.run_task(self, _restore, delay=1)
        except Exception:
            pass

    def _modifier_id(self, key: str, source: str) -> str:
        return f"arcattr:{key}:{source}"

    def _sync_modifier(self, player, key: str, source: str) -> None:
        """把单因子同步为 AttributeModifier：multiply→MULTIPLY（逐个连乘），add→ADD。"""
        from endstone.attribute import Attribute, AttributeModifier

        attr = self._get_attribute(player, key)
        if attr is None:
            return
        registry = self._factors.get((self._get_xuid(player), key))
        factor = registry.get(source) if registry is not None else None
        modifier_id = self._modifier_id(key, source)
        self._safe_remove_modifier(attr, modifier_id)
        if factor is None:
            return
        try:
            operation = (
                AttributeModifier.MULTIPLY
                if factor.operation == OP_MULTIPLY
                else AttributeModifier.ADD
            )
            modifier = AttributeModifier(modifier_id, factor.amount, operation)
            if hasattr(attr, "add_transient_modifier"):
                attr.add_transient_modifier(modifier)
            else:
                attr.add_modifier(modifier)
        except Exception as e:
            self.logger.error(f"[ARCAttributeCore] add modifier {modifier_id} error: {e}")

    def _remove_modifier(self, player, key: str, source: str) -> None:
        attr = self._get_attribute(player, key)
        if attr is None:
            return
        self._safe_remove_modifier(attr, self._modifier_id(key, source))

    def _safe_remove_modifier(self, attr_instance, modifier_id: str) -> None:
        try:
            attr_instance.remove_modifier(modifier_id)
        except Exception:
            try:
                for existing in list(getattr(attr_instance, "modifiers", []) or []):
                    # 0.11+ 的 AttributeModifier 无 .id，以 name（构造时的 modifier_id）匹配
                    if (
                        getattr(existing, "id", None) == modifier_id
                        or getattr(existing, "name", None) == modifier_id
                    ):
                        attr_instance.remove_modifier(existing)
                        break
            except Exception:
                pass

    def _get_attribute(self, player, key: str):
        """取 AttributeInstance；键不存在于该玩家实体则告警一次并返回 None。"""
        if key in self._unsupported_keys:
            return None
        try:
            from endstone.attribute import Attribute

            attr_enum = getattr(Attribute, ATTRIBUTE_KEYS[key], None)
            if attr_enum is None:
                raise KeyError(key)
            get_attr = getattr(player, "get_attribute", None)
            if get_attr is None:
                self._unsupported_keys.add(key)
                if key in FALLBACK_DIRECT_PROPS:
                    self.logger.warning(
                        f"[ARCAttributeCore] 当前 endstone 未暴露 get_attribute，属性 {key} 走直写替代通道"
                    )
                else:
                    self.logger.warning(
                        f"[ARCAttributeCore] 当前 endstone 未暴露 get_attribute，属性 {key} 仅登记、无法落地"
                    )
                return None
            instance = get_attr(attr_enum)
            if instance is None:
                self._unsupported_keys.add(key)
                self.logger.warning(f"[ARCAttributeCore] 玩家实体不支持属性 {key}，已忽略")
                return None
            return instance
        except Exception as e:
            self._unsupported_keys.add(key)
            self.logger.warning(f"[ARCAttributeCore] 获取属性 {key} 失败，已忽略: {e}")
            return None

    def _apply_active_buff(self, player, effect_key: str, now: float | None = None) -> None:
        """把 channel 当前生效条目挂到玩家（或移除效果）。"""
        try:
            now = time.time() if now is None else now
            resolved = resolve_effect_type(effect_key)
            channel = self._buffs.get((self._get_xuid(player), effect_key))
            if resolved is None:
                return
            entry = channel.active(now) if channel is not None else None
            if entry is None:
                remove_mob_effect(player, resolved)
                if channel is not None:
                    channel.mark_applied()
                return
            remaining = max(0.2, entry.remaining(now))
            apply_mob_effect(
                player,
                resolved,
                int(remaining * 20),
                max(0, entry.level - 1),
                ambient=True,
                particles=False,
                icon=True,
            )
            channel.mark_applied()
        except Exception as e:
            self.logger.error(f"[ARCAttributeCore] apply buff {effect_key} error: {e}")

    # ---------- 键规范化 ----------

    @staticmethod
    def _normalize_key(key: str) -> str | None:
        norm = str(key or "").strip().lower()
        if norm in DIRECT_PROPS or norm in ATTRIBUTE_KEYS:
            return norm
        return None

    @staticmethod
    def _normalize_effect(effect: str) -> str | None:
        norm = str(effect or "").strip().lower()
        return norm or None

    @staticmethod
    def _get_xuid(player) -> str:
        try:
            return str(
                getattr(player, "xuid", None)
                or getattr(player, "uuid", None)
                or getattr(player, "name", "")
            )
        except Exception:
            return ""

    def _player_by_xuid(self, xuid: str):
        try:
            for p in self.server.online_players or []:
                if self._get_xuid(p) == xuid:
                    return p
        except Exception:
            return None
        return None

    # ---------- 事件 ----------

    @event_handler()
    def on_player_join(self, event: PlayerJoinEvent):
        # direct / 替代直写属性在重进后由引擎恢复默认；若有残留内存态则重算落地
        player = event.player
        xuid = self._get_xuid(player)
        for (uid, key) in self._factors:
            if uid == xuid and (key in DIRECT_PROPS or key in FALLBACK_DIRECT_PROPS):
                self._apply_direct(player, key)

    @event_handler()
    def on_player_quit(self, event: PlayerQuitEvent):
        player = event.player
        xuid = self._get_xuid(player)
        # direct / 替代直写属性恢复默认（引擎不持久，双保险）；因子内存清空
        for (uid, key) in list(self._factors):
            if uid != xuid:
                continue
            if key in DIRECT_PROPS:
                try:
                    setattr(player, key, DIRECT_PROPS[key])
                except Exception:
                    pass
            elif key in FALLBACK_DIRECT_PROPS:
                prop, base = FALLBACK_DIRECT_PROPS[key]
                if prop in FALLBACK_INT_PROPS:
                    base = int(round(base))
                try:
                    setattr(player, prop, base)
                except Exception:
                    pass
        self._factors = {k: v for k, v in self._factors.items() if k[0] != xuid}
        # buff：效果本身带时长自然到期，内存队列清空
        self._buffs = {k: v for k, v in self._buffs.items() if k[0] != xuid}

    @event_handler()
    def on_player_respawn(self, event: PlayerRespawnEvent):
        """transient modifier 与效果在死亡/重生时丢失：重挂该玩家全部因子与生效 buff。"""
        player = event.player
        xuid = self._get_xuid(player)
        for (uid, key), registry in self._factors.items():
            if uid != xuid:
                continue
            if key in DIRECT_PROPS:
                self._apply_direct(player, key)
            else:
                self._land_attribute_key(player, key, registry.sources())
        for (uid, effect_key), channel in self._buffs.items():
            if uid == xuid:
                self._apply_active_buff(player, effect_key)

    @event_handler()
    def on_plugin_enable(self, event: PluginEnableEvent):
        """弧光核心晚于本插件加载时，补注册功能菜单按钮。"""
        try:
            if str(getattr(getattr(event, "plugin", None), "name", "")) == "arc_core":
                self._register_feature_menu()
        except Exception:
            pass

    # ---------- 命令 ----------

    def on_command(self, sender: CommandSender, command: Command, args: list[str]) -> bool:
        if command.name != "arcattr":
            return True
        if args and str(args[0]).lower() == "reload":
            if not getattr(sender, "is_op", False):
                sender.send_message("No permission")
                return True
            self._start_timer()
            sender.send_message("[ARCAttributeCore] 已重载（因子与 buff 状态保留）")
            return True
        target = None
        if args:
            if not getattr(sender, "is_op", False):
                sender.send_message("No permission")
                return True
            try:
                target = self.server.get_player(args[0])
            except Exception:
                target = None
            if target is None:
                sender.send_message(f"[ARCAttributeCore] 找不到玩家: {args[0]}")
                return True
        elif hasattr(sender, "send_form") or hasattr(sender, "xuid"):
            target = sender
        else:
            sender.send_message("[ARCAttributeCore] 用法: /arcattr <玩家>（控制台）")
            return True
        if target is None:
            return True

        lines = [f"=== {target.name} 属性因子 ==="]
        factors = self.api_list_factors(target)
        if factors:
            for key, desc in factors.items():
                value = self.api_get_factor_value(target, key)
                lines.append(f"[{key}] 最终值={value:.4f}")
                lines.extend(f"  {d}" for d in desc)
        else:
            lines.append("（无）")
        lines.append(f"=== {target.name} Buff 队列 ===")
        buffs = self.api_list_buffs(target)
        if buffs:
            for effect_key, desc in buffs.items():
                lines.append(f"[{effect_key}]")
                lines.extend(f"  {d}" for d in desc)
        else:
            lines.append("（无）")
        sender.send_message("\n".join(lines))
        return True
