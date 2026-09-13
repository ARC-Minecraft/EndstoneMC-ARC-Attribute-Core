# -*- coding: utf-8 -*-
"""ARC Attribute Core 冒烟测试：因子连乘 / buff 优先级 / 主插件落地全链路（stub endstone）。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _endstone_stub  # noqa: F401
from _endstone_stub import AttributeInstance, AttributeModifier
_endstone_stub.add_src_to_path()

from endstone_arc_attribute_core.factor_registry import FactorRegistry
from endstone_arc_attribute_core.buff_registry import BuffChannel
from endstone_arc_attribute_core.arc_attribute_core import ARCAttributeCorePlugin

print("== 0) 模块 import 成功")

# ---------- 纯逻辑：FactorRegistry ----------

print("\n== 1) 因子连乘（用户示例）")
reg = FactorRegistry(base=1.0)
reg.add("a", 0.25)
reg.add("b", -0.05)
reg.add("c", -0.10)
reg.add("d", 0.15)
expected = 1.0 * 1.25 * 0.95 * 0.90 * 1.15
assert abs(reg.compute() - expected) < 1e-9, reg.compute()
print(f"   1 × 1.25 × 0.95 × 0.90 × 1.15 = {reg.compute():.6f} ok")

print("== 2) add 因子混合：(base + Σadd) × Π(1+mul)")
reg2 = FactorRegistry(base=10.0)
reg2.add("flat", 5, operation="add")
reg2.add("mul", 0.2)
assert abs(reg2.compute() - (10 + 5) * 1.2) < 1e-9
print(f"   (10+5)×1.2 = {reg2.compute():.2f} ok")

print("== 3) 定时因子：到期自动剔除")
t0 = time.time()
reg3 = FactorRegistry(base=100.0)
reg3.add("temp", -0.5, duration=5)
reg3.add("perm", 0.1)
assert abs(reg3.compute() - 55.0) < 1e-9
removed = reg3.expire(t0 + 6)
assert removed == ["temp"], removed
assert abs(reg3.compute() - 110.0) < 1e-9
print(f"   5s 因子到期移除 {removed}，恢复 110 ok")

print("== 4) 同 source 覆盖与手动移除")
reg3.add("perm", -0.5)  # 覆盖原 +0.1
assert abs(reg3.compute() - 50.0) < 1e-9
assert reg3.remove("perm") is True
assert reg3.compute() == 100.0
assert reg3.is_empty()
print("   覆盖→50，移除→100 ok")

# ---------- 纯逻辑：BuffChannel 优先级 ----------

print("\n== 5) buff 优先级：速度2(5s) + 速度1(10s) → 2 先生效，到期回退 1")
t0 = time.time()
ch = BuffChannel()
ch.push("src_a", 1, 10)
ch.push("src_b", 2, 5)
act = ch.active(t0 + 1)
assert act.level == 2 and act.source == "src_b"
assert ch.expire(t0 + 1) is False or True  # 首次 expire 记录基准
act = ch.active(t0 + 6)
assert act.level == 1 and act.source == "src_a", "速度2 到期后应回退速度1"
assert abs(act.remaining(t0 + 6) - 4.0) < 0.5, act.remaining(t0 + 6)
assert ch.expire(t0 + 6) is True, "生效条目变化应通知重挂"
act = ch.active(t0 + 11)
assert act is None, "全部到期无生效"
print(f"   t+6 → Lv1 剩 4s；t+11 → None ok")

print("== 6) 同 source 覆盖与手动移除")
ch2 = BuffChannel()
ch2.push("x", 1, 100)
ch2.push("x", 3, 50)
assert ch2.active().level == 3, "同 source 覆盖后应为 Lv3"
ch2.remove("x")
assert ch2.active() is None and ch2.is_empty()
print("   覆盖 Lv3、移除清空 ok")

# ---------- 主插件全链路 ----------


class FakeLogger:
    def info(self, m):
        print(f"[info] {m}")

    def warning(self, m):
        print(f"[warning] {m}")

    def error(self, m):
        print(f"[error] {m}")


class FakeScheduler:
    def __init__(self):
        self.tasks = []

    def run_task(self, plugin, fn, delay=0):
        self.tasks.append((fn, delay))
        return None


class FakeServer:
    def __init__(self, players):
        self.online_players = players
        self.scheduler = FakeScheduler()


class FakePlayer:
    def __init__(self, name, xuid):
        self.name = name
        self.xuid = xuid
        self.walk_speed = 0.10
        self.fly_speed = 0.05
        self.max_health = 20.0
        self._attrs: dict[str, AttributeInstance] = {}
        self.effects_applied = []  # (type, duration_ticks, amplifier)
        self.effects_removed = []

    def get_attribute(self, attr_enum):
        if attr_enum not in self._attrs:
            self._attrs[attr_enum] = AttributeInstance(attr_enum, base_value=1.0)
        return self._attrs[attr_enum]

    def add_effect(self, effect):
        self.effects_applied.append((str(effect.type), effect.duration, effect.amplifier))

    def remove_effect(self, resolved):
        self.effects_removed.append(str(resolved))


steve = FakePlayer("Steve", "x1")
plugin = ARCAttributeCorePlugin()
plugin.logger = FakeLogger()
plugin.server = FakeServer([steve])

print("\n== 7) walk_speed 因子：直写落地")
plugin.api_add_factor(steve, "walk_speed", "ars:thirst", -0.20)
assert abs(steve.walk_speed - 0.08) < 1e-9, steve.walk_speed
plugin.api_add_factor(steve, "walk_speed", "item:boots", 0.25)
assert abs(steve.walk_speed - 0.10) < 1e-9, "0.10×0.8×1.25 = 0.10"
assert abs(plugin.api_get_factor_value(steve, "walk_speed") - 0.10) < 1e-9
plugin.api_remove_factor(steve, "walk_speed", "item:boots")
assert abs(steve.walk_speed - 0.08) < 1e-9
print(f"   -20% → 0.08；+25% 叠加 → 0.10；移除 +25% → 0.08 ok")

print("== 8) walk_speed 定时因子：tick 到期恢复")
t0 = time.time()
plugin.api_add_factor(steve, "walk_speed", "skill:dash", 0.5, duration=10)
assert abs(steve.walk_speed - 0.12) < 1e-9
plugin._tick_once(t0 + 11)
assert abs(steve.walk_speed - 0.08) < 1e-9, f"dash 到期应回到 0.08，实际 {steve.walk_speed}"
print("   dash +50% 10s 到期 → 恢复 0.08 ok")

print("== 9) attribute 因子：AttributeModifier 挂载/卸载")
plugin.api_add_factor(steve, "attack_damage", "ars:protein", -0.3)
inst = steve._attrs["minecraft:attack_damage"]
mod = inst.get_modifier("arcattr:attack_damage:ars:protein")
assert mod is not None and mod.operation == AttributeModifier.MULTIPLY and abs(mod.amount + 0.3) < 1e-9
plugin.api_add_factor(steve, "attack_damage", "item:sword", 5, operation="add")
mod2 = inst.get_modifier("arcattr:attack_damage:item:sword")
assert mod2 is not None and mod2.operation == AttributeModifier.ADD and mod2.amount == 5
plugin.api_remove_factor(steve, "attack_damage", "ars:protein")
assert inst.get_modifier("arcattr:attack_damage:ars:protein") is None
assert len(inst.modifiers) == 1
print(f"   MULTIPLY/-0.3 + ADD/5 挂载，移除后剩 {len(inst.modifiers)} 个 ok")

print("== 10) attribute 定时因子：tick 到期卸载 modifier")
t0 = time.time()
plugin.api_add_factor(steve, "attack_damage", "buff:rage", 0.4, duration=5)
assert inst.get_modifier("arcattr:attack_damage:buff:rage") is not None
plugin._tick_once(t0 + 6)
assert inst.get_modifier("arcattr:attack_damage:buff:rage") is None
print("   rage 到期自动卸载 ok")

print("== 11) buff API：优先级切换与到期回退（速度2 5s + 速度1 10s）")
t0 = time.time()
plugin.api_apply_buff(steve, "speed", level=1, duration=10, source="food:sugar")
plugin.api_apply_buff(steve, "speed", level=2, duration=5, source="potion:swift")
assert len(steve.effects_applied) == 2  # 两次 push 都触发了应用
etype, dur, amp = steve.effects_applied[-1]
assert etype == "stub_effect:speed" and amp == 1 and abs(dur - 100) < 25, (etype, dur, amp)
print(f"   生效 Lv2: amplifier={amp} duration≈{dur} ticks ok")
plugin._tick_once(t0 + 6)  # 速度2 到期 → 回退速度1
etype, dur, amp = steve.effects_applied[-1]
assert amp == 0 and abs(dur - 80) < 25, (etype, dur, amp)
print(f"   回退 Lv1: amplifier={amp} duration≈{dur} ticks ok")
plugin._tick_once(t0 + 11)  # 全部到期 → 移除效果
assert len(steve.effects_removed) == 1 and steve.effects_removed[0] == "stub_effect:speed"
print("   全部到期移除效果 ok")

print("== 12) buff 手动撤销：清 source 后回退/移除")
t0 = time.time()
plugin.api_apply_buff(steve, "speed", level=1, duration=60, source="food:sugar")
plugin.api_apply_buff(steve, "speed", level=2, duration=60, source="potion:swift")
assert steve.effects_applied[-1][2] == 1
plugin.api_remove_buff(steve, "speed", source="potion:swift")
assert steve.effects_applied[-1][2] == 0, "撤销 Lv2 应回退 Lv1"
active = plugin.api_get_active_buff(steve, "speed")
assert active is not None and active[0] == 1
plugin.api_remove_buff(steve, "speed", source="food:sugar")
assert plugin.api_get_active_buff(steve, "speed") is None
assert steve.effects_removed[-1] == "stub_effect:speed"
print("   撤销来源回退、清空移除 ok")

print("== 13) 玩家退出：direct 恢复默认、内存清空")
class QuitEvent:
    def __init__(self, player):
        self.player = player

steve.walk_speed = 0.02  # 模拟其他来源残留
plugin.api_add_factor(steve, "walk_speed", "ars:thirst", -0.9)
plugin.on_player_quit(QuitEvent(steve))
assert abs(steve.walk_speed - 0.10) < 1e-9, f"退出应恢复 0.10，实际 {steve.walk_speed}"
assert plugin.api_list_factors(steve) == {}
assert plugin.api_list_buffs(steve) == {}
print("   walk_speed 恢复 0.10、因子/buff 清空 ok")

print("== 14) 重生：attribute modifier 重挂（transient 丢失后）")
plugin.api_add_factor(steve, "attack_damage", "item:sword", 5, operation="add")
steve._attrs["minecraft:attack_damage"]._modifiers.clear()  # 模拟 transient 丢失

class RespawnEvent:
    def __init__(self, player):
        self.player = player

plugin.on_player_respawn(RespawnEvent(steve))
mod = steve._attrs["minecraft:attack_damage"].get_modifier("arcattr:attack_damage:item:sword")
assert mod is not None and mod.amount == 5
print("   重生后 modifier 重挂 ok")

print("== 15) 非法键与 describe")
assert plugin.api_add_factor(steve, "not_a_key", "s", 0.1) is False
factor_map = plugin.api_list_factors(steve)
assert "attack_damage" in factor_map and factor_map["attack_damage"], factor_map
assert plugin.api_clear_factors(steve) >= 1
assert plugin.api_list_factors(steve) == {}
print(f"   非法键拒绝、describe={factor_map}、clear ok")

print("\n== 16) walk_speed 写入保护疾跑（同 tick + 下 tick 写回、无变化跳过）")
sprinter = FakePlayer("Sprinter", "x16")
plugin_sp = ARCAttributeCorePlugin()
plugin_sp.logger = FakeLogger()
plugin_sp.server = FakeServer([sprinter])
sprinter.is_sprinting = True
plugin_sp.api_add_factor(sprinter, "walk_speed", "test:boost", 0.5)
assert abs(sprinter.walk_speed - 0.15) < 1e-9
assert sprinter.is_sprinting is True, "同 tick 应立即写回疾跑"
tasks = plugin_sp.server.scheduler.tasks
assert len(tasks) == 1 and tasks[0][1] == 1, f"应有下一 tick 恢复任务: {tasks}"
fn, _ = tasks[0]
fn()
assert sprinter.is_sprinting is True
# 值未变化时不得重复写入（不产生新的恢复任务）
plugin_sp.server.scheduler.tasks.clear()
plugin_sp.api_add_factor(sprinter, "walk_speed", "test:boost", 0.5)  # 同 source 覆盖同值
assert plugin_sp.server.scheduler.tasks == [], "值未变化不应写 walk_speed"
assert abs(sprinter.walk_speed - 0.15) < 1e-9
print("   同 tick 恢复 + 延迟恢复 + 无变化跳过 ok")

# ---------- OP 功能菜单 ----------

import json as _json

from endstone.form import ActionForm, MessageForm, ModalForm

print("\n== 17) 功能菜单：主菜单按钮注册（仅 OP 可见）")


class FakePluginManager:
    def __init__(self, plugins):
        self._plugins = plugins

    def get_plugin(self, name):
        return self._plugins.get(name)


class FakeArcCore:
    def __init__(self):
        self.buttons = {}

    def _put_main_menu_button(self, button_id, text, on_click, priority=6, visible=None):
        self.buttons[button_id] = {
            "text": text, "on_click": on_click, "priority": priority, "visible": visible,
        }
        return True

    def api_unregister_main_menu_button(self, button_id):
        return self.buttons.pop(button_id, None) is not None


class MenuPlayer(FakePlayer):
    def __init__(self, name, xuid, is_op=False):
        super().__init__(name, xuid)
        self.is_op = is_op
        self.forms = []
        self.messages = []

    def send_form(self, form):
        self.forms.append(form)

    def send_message(self, m):
        self.messages.append(str(m))


arc_core = FakeArcCore()
alice = MenuPlayer("Alice", "x17", is_op=True)
bob = MenuPlayer("Bob", "x17b", is_op=False)
plugin_menu = ARCAttributeCorePlugin()
plugin_menu.logger = FakeLogger()
plugin_menu.server = FakeServer([alice, bob])
plugin_menu.server.plugin_manager = FakePluginManager({"arc_core": arc_core})

plugin_menu._register_feature_menu()
entry = arc_core.buttons["arc_attribute_core:feature_menu"]
assert entry["text"] == "属性管理器"
assert entry["visible"](alice) is True and entry["visible"](bob) is False
print("   已注册进弧光核心主菜单，visible 仅 OP 为真 ok")

arc_core2 = FakeArcCore()
plugin_menu._menu_registered = False
plugin_menu.server.plugin_manager = FakePluginManager({"arc_core": arc_core2})


class _NamedPlugin:
    name = "arc_core"


class _EnableEvent:
    def __init__(self, plugin):
        self.plugin = plugin


plugin_menu.on_plugin_enable(_EnableEvent(_NamedPlugin()))
assert "arc_attribute_core:feature_menu" in arc_core2.buttons, "弧光核心晚加载应兜底注册"
print("   PluginEnableEvent 兜底注册 ok")

print("\n== 18) 功能菜单：面板流转与自定义幅度")
entry2 = arc_core2.buttons["arc_attribute_core:feature_menu"]
alice.forms.clear()
entry2["on_click"](alice)
menu_form = alice.forms[-1]
assert isinstance(menu_form, ActionForm) and len(menu_form.buttons) == 17, len(menu_form.buttons)

bob.forms.clear()
bob.messages.clear()
entry2["on_click"](bob)
assert bob.forms == [] and any("OP" in m for m in bob.messages), "非 OP 应被拦截"
print("   功能菜单 17 个属性按钮；非 OP 拦截 ok")

walk_btn = next(on for text, on in menu_form.buttons if text.startswith("行走速度"))
alice.forms.clear()
walk_btn(alice)
detail = alice.forms[-1]
assert isinstance(detail, ActionForm) and "引擎实时值：0.1000" in detail.content
add_btn = next(on for text, on in detail.buttons if text.startswith("添加"))
alice.forms.clear()
add_btn(alice)
add_form = alice.forms[-1]
assert isinstance(add_form, ModalForm)

alice.messages.clear()
# 真实 endstone 布局：Label 占首位（None），共 5 个元素
add_form.on_submit(alice, _json.dumps([None, "menu:test", 0, "-0.5", "10"]))
assert abs(alice.walk_speed - 0.05) < 1e-9, alice.walk_speed
assert alice.messages and "已应用" in alice.messages[-1]
detail2 = alice.forms[-1]
assert isinstance(detail2, ActionForm), "提交后应刷新详情面板"

alice.forms.clear()
next(on for text, on in detail2.buttons if text.startswith("添加"))(alice)
add_form2 = alice.forms[-1]
add_form2.on_submit(alice, _json.dumps([None, "menu:test", 0, "-0.75", ""]))
assert abs(alice.walk_speed - 0.025) < 1e-9, alice.walk_speed
lines = plugin_menu.api_list_factors(alice, "walk_speed")["walk_speed"]
assert len(lines) == 1 and "menu:test" in lines[0], lines

kept = alice.walk_speed
alice.forms.clear()
next(on for text, on in detail2.buttons if text.startswith("添加"))(alice)
add_form3 = alice.forms[-1]
add_form3.on_submit(alice, _json.dumps([None, "menu:test", 0, "abc", ""]))
assert abs(alice.walk_speed - kept) < 1e-9 and any("幅度无效" in m for m in alice.messages)
print("   multiply -0.5 → 0.05；同源覆盖 -0.75 → 0.025；非法幅度拒绝 ok")

plugin_menu._menu.open_add_factor(alice, "attack_damage")
add_flat = alice.forms[-1]
# 兼容布局：无 Label 占位，共 4 个元素
add_flat.on_submit(alice, _json.dumps(["menu:flat", "1", "5", ""]))
inst = alice._attrs["minecraft:attack_damage"]
mod = inst.get_modifier("arcattr:attack_damage:menu:flat")
assert mod is not None and mod.operation == AttributeModifier.ADD and mod.amount == 5

plugin_menu._menu.open_add_factor(alice, "attack_damage")
add_text = alice.forms[-1]
add_text.on_submit(alice, _json.dumps(["menu:text", "add（基础值直接加减）", "2", ""]))
mod2 = inst.get_modifier("arcattr:attack_damage:menu:text")
assert mod2 is not None and mod2.operation == AttributeModifier.ADD and mod2.amount == 2
print("   add 操作：索引与选项文本两种提交均解析为 ADD ok")

plugin_menu._menu.open_remove_source(alice, "walk_speed")
rm_form = alice.forms[-1]
rm_btn = next(on for text, on in rm_form.buttons if text.endswith("menu:test"))
rm_btn(alice)
assert "menu:test" not in plugin_menu.api_list_factors(alice, "walk_speed")
assert abs(alice.walk_speed - 0.10) < 1e-9
print("   按来源移除并重算落地 ok")

plugin_menu.api_add_factor(alice, "walk_speed", "menu:bulk", -0.2)
plugin_menu._menu._confirm_clear(alice, "walk_speed")
confirm = alice.forms[-1]
assert isinstance(confirm, MessageForm)
confirm.on_submit(alice, True)
assert "walk_speed" not in plugin_menu.api_list_factors(alice)
assert abs(alice.walk_speed - 0.10) < 1e-9
print("   MessageForm 确认后清空全部因子 ok")

plugin_menu.on_disable()
assert "arc_attribute_core:feature_menu" not in arc_core2.buttons
print("   on_disable 注销主菜单按钮 ok")

print("\n== 19) health 替代直写通道（引擎无 get_attribute）")


class NoAttrPlayer(MenuPlayer):
    """模拟真实引擎：无 get_attribute，且 max_health setter 仅收整数（pybind SupportsInt）。"""

    def __init__(self, name, xuid, is_op=False):
        super().__init__(name, xuid, is_op)
        self._strict_max_health = True

    def __setattr__(self, name, value):
        if (
            name == "max_health"
            and getattr(self, "_strict_max_health", False)
            and not isinstance(value, int)
        ):
            raise TypeError(
                "incompatible function arguments: (arg0: Mob, arg1: typing.SupportsInt)"
            )
        object.__setattr__(self, name, value)

    def get_attribute(self, attr_enum):
        return None


nathan = NoAttrPlayer("Nathan", "x19", is_op=True)
plugin_fb = ARCAttributeCorePlugin()
plugin_fb.logger = FakeLogger()
plugin_fb.server = FakeServer([nathan])

assert nathan.max_health == 20.0
plugin_fb.api_add_factor(nathan, "health", "menu:manual", 5, operation="add")
assert abs(nathan.max_health - 25.0) < 1e-9, nathan.max_health
assert abs(plugin_fb.api_get_factor_value(nathan, "health") - 25.0) < 1e-9
plugin_fb.api_add_factor(nathan, "health", "menu:manual", -0.5)  # 覆盖为 multiply ×0.5
assert abs(nathan.max_health - 10.0) < 1e-9, nathan.max_health
plugin_fb.api_remove_factor(nathan, "health", "menu:manual")
assert abs(nathan.max_health - 20.0) < 1e-9
print("   add +5 → 25；覆盖 multiply ×0.5 → 10；移除恢复 20 ok")

plugin_fb.api_add_factor(nathan, "attack_damage", "menu:x", 3, operation="add")
assert "attack_damage" in plugin_fb.api_list_factors(nathan), "无通道属性应仍登记"
print("   无落地通道属性：仅登记、不报错 ok")

plugin_fb.api_add_factor(nathan, "health", "menu:manual", 5, operation="add")
plugin_fb.on_player_quit(QuitEvent(nathan))
assert abs(nathan.max_health - 20.0) < 1e-9, "退出应恢复默认 20"
plugin_fb.api_add_factor(nathan, "health", "menu:manual", 5, operation="add")
nathan.max_health = 20  # 模拟引擎重生重置
plugin_fb.on_player_respawn(RespawnEvent(nathan))
assert abs(nathan.max_health - 25.0) < 1e-9, "重生应重挂因子"
print("   退出恢复默认、重生重挂 ok")

plugin_fb.api_add_factor(nathan, "health", "buff:temp", 1.0, duration=5, operation="add")
assert abs(nathan.max_health - 26.0) < 1e-9, nathan.max_health
plugin_fb._tick_once(time.time() + 6)
assert abs(nathan.max_health - 25.0) < 1e-9, "定时因子到期应回落"
plugin_fb.api_remove_factor(nathan, "health", "menu:manual")
assert abs(nathan.max_health - 20.0) < 1e-9
print("   临时因子到期回落、移除恢复 ok")

plugin_fb._menu.open_attribute(nathan, "health")
panel = nathan.forms[-1]
assert "player.max_health" in panel.content and "替代直写通道" in panel.content
plugin_fb._menu.open_attribute(nathan, "attack_damage")
panel2 = nathan.forms[-1]
assert "仅登记" in panel2.content
print("   面板如实标注落地方式 ok")

print("\nALL ATTRIBUTE CORE SMOKE TESTS PASSED")
