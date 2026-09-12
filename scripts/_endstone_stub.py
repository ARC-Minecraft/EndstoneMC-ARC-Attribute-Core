# -*- coding: utf-8 -*-
"""ARC Attribute Core 离线测试共享的 endstone stub。"""
import sys
import types

endstone = types.ModuleType("endstone")
endstone.__path__ = []


class GameMode:
    SURVIVAL = "SURVIVAL"
    ADVENTURE = "ADVENTURE"
    CREATIVE = "CREATIVE"
    SPECTATOR = "SPECTATOR"


endstone.GameMode = GameMode


def _mod(name):
    m = types.ModuleType(name)
    sys.modules[name] = m
    setattr(endstone, name.split(".", 1)[1], m)
    return m


cmd_mod = _mod("endstone.command")
cmd_mod.Command = type("Command", (), {})
cmd_mod.CommandSender = type("CommandSender", (), {})

evt_mod = _mod("endstone.event")


def event_handler(*a, **k):
    def deco(fn):
        return fn
    return deco


evt_mod.event_handler = event_handler
for cls_name in (
    "PlayerJoinEvent", "PlayerQuitEvent", "PlayerRespawnEvent",
    "PlayerItemConsumeEvent", "PlayerMoveEvent", "ActorDamageEvent",
    "PlayerDeathEvent", "PlayerGameModeChangeEvent",
):
    setattr(evt_mod, cls_name, type(cls_name, (), {}))

plugin_mod = _mod("endstone.plugin")
plugin_mod.Plugin = type("Plugin", (), {})

# ---- endstone.attribute ----
attr_mod = _mod("endstone.attribute")

ATTR_NAMES = [
    "ABSORPTION", "ATTACK_DAMAGE", "FOLLOW_RANGE", "HEALTH", "JUMP_STRENGTH",
    "KNOCKBACK_RESISTANCE", "LAVA_MOVEMENT_SPEED", "LUCK", "MOVEMENT_SPEED",
    "PLAYER_EXHAUSTION", "PLAYER_EXPERIENCE", "PLAYER_HUNGER", "PLAYER_LEVEL",
    "PLAYER_SATURATION", "UNDERWATER_MOVEMENT_SPEED", "ZOMBIE_SPAWN_REINFORCEMENTS",
]


class Attribute:
    for _n in ATTR_NAMES:
        locals()[_n] = f"minecraft:{_n.lower()}"
    del _n


attr_mod.Attribute = Attribute


class AttributeModifier:
    ADD = 0
    MULTIPLY_BASE = 1
    MULTIPLY = 2
    CAP = 3

    def __init__(self, modifier_id, amount, operation):
        self.id = modifier_id
        self.amount = float(amount)
        self.operation = operation


attr_mod.AttributeModifier = AttributeModifier


class AttributeInstance:
    """stub：记录 add/remove 的 modifier 调用。"""

    def __init__(self, attr_type, base_value=0.0):
        self.type = attr_type
        self.base_value = base_value
        self._modifiers: dict[str, AttributeModifier] = {}

    @property
    def modifiers(self):
        return list(self._modifiers.values())

    def add_modifier(self, mod):
        self._modifiers[mod.id] = mod

    def add_transient_modifier(self, mod):
        self._modifiers[mod.id] = mod

    def get_modifier(self, key):
        return self._modifiers.get(str(key))

    def remove_modifier(self, key):
        if isinstance(key, AttributeModifier):
            self._modifiers.pop(key.id, None)
            return
        self._modifiers.pop(str(key), None)


attr_mod.AttributeInstance = AttributeInstance

# ---- endstone.potion ----
potion_mod = _mod("endstone.potion")


class Effect:
    def __init__(self, effect_type, duration, amplifier=0, ambient=False,
                 particles=True, icon=True):
        self.type = effect_type
        self.duration = duration
        self.amplifier = amplifier
        self.ambient = ambient
        self.particles = particles
        self.icon = icon


potion_mod.Effect = Effect


class _EffectTypeMeta(type):
    def __getattr__(cls, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return f"stub_effect:{name.lower()}"


class EffectType(metaclass=_EffectTypeMeta):
    @staticmethod
    def get(key):
        return f"stub_effect:{str(key).split(':')[-1]}"


potion_mod.EffectType = EffectType
sys.modules["endstone"] = endstone


def add_src_to_path():
    from pathlib import Path
    src = Path(__file__).resolve().parent.parent / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
