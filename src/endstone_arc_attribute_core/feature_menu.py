"""OP 功能菜单：弧光核心主菜单入口（仅 OP 可见）→ 属性列表 → 单属性调整面板。

面板支持：查看引擎实时值/因子合成值、按自定义幅度添加或覆盖因子（multiply/add、
可选时长）、按来源移除因子、清空该属性全部因子。因子为内存态，玩家退出即清。
"""

import json

from endstone.form import ActionForm, Dropdown, Label, MessageForm, ModalForm, TextInput

from .attribute_keys import ATTRIBUTE_KEYS, DIRECT_PROPS, FALLBACK_DIRECT_PROPS
from .factor_registry import OP_ADD, OP_MULTIPLY


class FeatureMenu:
    MENU_BUTTON_ID = "arc_attribute_core:feature_menu"
    MENU_BUTTON_TEXT = "属性管理器"
    MENU_BUTTON_PRIORITY = 4
    DEFAULT_SOURCE = "menu:manual"

    KEY_LABELS = {
        "walk_speed": "行走速度",
        "fly_speed": "飞行速度",
        "health": "生命上限",
        "absorption": "吸收护盾",
        "attack_damage": "攻击伤害",
        "knockback_resistance": "击退抗性",
        "luck": "幸运",
        "movement_speed": "引擎移动速度",
        "underwater_movement_speed": "水下移动速度",
        "lava_movement_speed": "熔岩移动速度",
        "jump_strength": "跳跃力度",
        "follow_range": "索敌范围",
        "player_hunger": "饥饿值",
        "player_saturation": "饱和度",
        "player_exhaustion": "饥饿消耗",
        "player_experience": "经验点",
        "player_level": "经验等级",
    }

    def __init__(self, plugin):
        self._plugin = plugin

    # ---------- 主菜单按钮 ----------

    def register_into(self, core) -> bool:
        """向弧光核心注册主菜单按钮；仅 OP 可见（走核心 _put 的 visible 回调）。"""
        visible = lambda p: bool(getattr(p, "is_op", False))  # noqa: E731
        put = getattr(core, "_put_main_menu_button", None)
        if callable(put):
            try:
                return bool(put(
                    self.MENU_BUTTON_ID,
                    self.MENU_BUTTON_TEXT,
                    self._guarded_open,
                    priority=self.MENU_BUTTON_PRIORITY,
                    visible=visible,
                ))
            except Exception:
                pass
        api = getattr(core, "api_register_main_menu_button", None)
        if callable(api):
            # 旧版核心不支持 visible：退化为全员可见，点击时再校验 OP
            return bool(api(
                self.MENU_BUTTON_ID,
                self.MENU_BUTTON_TEXT,
                self._guarded_open,
                priority=self.MENU_BUTTON_PRIORITY,
            ))
        return False

    def unregister_from(self, core) -> bool:
        api = getattr(core, "api_unregister_main_menu_button", None)
        if not callable(api):
            return False
        try:
            return bool(api(self.MENU_BUTTON_ID))
        except Exception:
            return False

    def _guarded_open(self, sender) -> None:
        if not bool(getattr(sender, "is_op", False)):
            try:
                sender.send_message("[ARCAttributeCore] 功能菜单仅 OP 可用")
            except Exception:
                pass
            return
        self.open_menu(sender)

    # ---------- 面板 ----------

    def open_menu(self, player) -> None:
        p = self._plugin
        try:
            form = ActionForm(title="属性管理器 · 属性调整", content="选择要查看/调整的属性：")
            for key in self._ordered_keys():
                live, _mods = self._live_value(player, key)
                info = f"因子 {len(self._factor_lines(player, key))}"
                if live is not None:
                    info += f" · 引擎 {live:.4f}"
                form.add_button(
                    f"{self._label(key)} {key}\n{info}",
                    on_click=lambda s, k=key: self.open_attribute(s, k),
                )
            player.send_form(form)
        except Exception as e:
            p.logger.error(f"[ARCAttributeCore] open feature menu error: {e}")

    def open_attribute(self, player, key: str) -> None:
        p = self._plugin
        key = str(key or "").strip()
        if key not in DIRECT_PROPS and key not in ATTRIBUTE_KEYS:
            return
        try:
            is_direct = key in DIRECT_PROPS
            final = p.api_get_factor_value(player, key)
            live, mods = self._live_value(player, key)
            lines = self._factor_lines(player, key)
            kind = (
                "独占直写（引擎唯一值，连乘后直接写回玩家）"
                if is_direct
                else "AttributeModifier（挂在引擎属性上，与原版效果共存）"
            )
            content = [
                f"类型：{kind}",
                self._landing_desc(player, key),
                f"引擎实时值：{'%.4f' % live if live is not None else '未知'}"
                + (f"（{mods} 个修饰符）" if mods is not None else ""),
                f"因子合成值：{final:.4f}",
                "公式：最终值 = (base + Σadd) × Π(1+mul)",
                "",
                "因子明细：" if lines else "因子明细：（无）",
            ]
            content.extend(f"  {line}" for line in lines)
            content.append("")
            content.append("注意：因子为内存态，玩家退出服务器后自动清空。")
            form = ActionForm(title=f"属性管理器 · {self._label(key)}", content="\n".join(content))
            form.add_button(
                "添加 / 覆盖因子（自定义幅度）",
                on_click=lambda s, k=key: self.open_add_factor(s, k),
            )
            if lines:
                form.add_button("移除指定来源因子", on_click=lambda s, k=key: self.open_remove_source(s, k))
                form.add_button("清空该属性全部因子", on_click=lambda s, k=key: self._confirm_clear(s, k))
            form.add_button("刷新", on_click=lambda s, k=key: self.open_attribute(s, k))
            form.add_button("返回", on_click=lambda s: self.open_menu(s))
            player.send_form(form)
        except Exception as e:
            p.logger.error(f"[ARCAttributeCore] open attribute panel {key} error: {e}")

    def open_add_factor(self, player, key: str) -> None:
        p = self._plugin
        key = str(key or "").strip()
        if key not in DIRECT_PROPS and key not in ATTRIBUTE_KEYS:
            return
        try:
            live, _mods = self._live_value(player, key)
            final = p.api_get_factor_value(player, key)
            header = Label(text="\n".join([
                f"{self._label(key)}（{key}）",
                self._landing_desc(player, key),
                f"引擎实时值：{'%.4f' % live if live is not None else '未知'}",
                f"因子合成值：{final:.4f}",
                "",
                "multiply：连乘，幅度为相对量（-0.5 → ×0.5）",
                "add：直接加减数值（attribute 系挂在基础值上）",
            ]))
            source_input = TextInput(
                label="来源 source",
                placeholder="标识调整来源；同源重复添加=覆盖",
                default_value=self.DEFAULT_SOURCE,
            )
            op_dropdown = Dropdown(
                label="操作类型",
                options=["multiply（连乘 ×(1+幅度)）", "add（基础值直接加减）"],
                default_index=0,
            )
            amount_input = TextInput(
                label="幅度 amount",
                placeholder="如 -0.5（减半）、0.25、5",
                default_value="",
            )
            duration_input = TextInput(
                label="时长（秒，可选）",
                placeholder="留空 = 永久（退出服务器自动清除）",
                default_value="",
            )

            def on_submit(s, data):
                # 提交数据与 controls 顺序一致且 Label 也占一位（首位为空值，与 ARS 配置面板一致）；
                # 兼容个别版本不含 Label 的情况（长度少 1）
                try:
                    values = json.loads(data) if isinstance(data, str) else list(data or [])
                except Exception:
                    values = []
                if len(values) >= 5:
                    values = values[1:]

                def field(i: int) -> str:
                    if len(values) <= i or values[i] is None:
                        return ""
                    return str(values[i]).strip()

                source = field(0) or self.DEFAULT_SOURCE
                raw_op = field(1)
                op = OP_ADD if (raw_op in ("1", "1.0") or "add" in raw_op.lower()) else OP_MULTIPLY
                try:
                    amount = float(field(2))
                except ValueError:
                    s.send_message(f"[ARCAttributeCore] 幅度无效：{field(2) or '（空）'}")
                    return self.open_add_factor(s, key)
                if amount == 0:
                    s.send_message("[ARCAttributeCore] 幅度不能为 0；撤销因子请用「移除指定来源因子」")
                    return self.open_add_factor(s, key)
                raw_duration = field(3)
                if raw_duration:
                    try:
                        duration = float(raw_duration)
                    except ValueError:
                        s.send_message(f"[ARCAttributeCore] 时长无效：{raw_duration}")
                        return self.open_add_factor(s, key)
                    if duration <= 0:
                        s.send_message("[ARCAttributeCore] 时长必须大于 0 秒（永久请留空）")
                        return self.open_add_factor(s, key)
                else:
                    duration = None
                if not p.api_add_factor(s, key, source=source, amount=amount,
                                        duration=duration, operation=op):
                    s.send_message(f"[ARCAttributeCore] 因子添加失败（参数非法）：{key} {source}")
                    return self.open_add_factor(s, key)
                live_now, _m = self._live_value(s, key)
                landing = self._landing_desc(s, key)
                s.send_message(
                    f"[ARCAttributeCore] 已应用 {key} ← {source}: {amount:+g} "
                    f"[{op}{'' if duration is None else f', {duration:g}s'}]，"
                    f"合成值 {p.api_get_factor_value(s, key):.4f}"
                    + (f"，引擎值 {live_now:.4f}" if live_now is not None else "")
                    + ("；⚠ 该属性当前无法落地，仅登记" if landing.startswith("⚠") else "")
                )
                self.open_attribute(s, key)

            form = ModalForm(
                title=f"调整 · {self._label(key)}",
                controls=[header, source_input, op_dropdown, amount_input, duration_input],
                on_close=lambda s: None,
                on_submit=on_submit,
            )
            player.send_form(form)
        except Exception as e:
            p.logger.error(f"[ARCAttributeCore] open add factor form {key} error: {e}")

    def open_remove_source(self, player, key: str) -> None:
        p = self._plugin
        key = str(key or "").strip()
        try:
            sources = p._factor_sources(player, key)
            if not sources:
                return self.open_attribute(player, key)
            form = ActionForm(
                title=f"移除因子 · {self._label(key)}",
                content="点击要移除的来源（撤销后自动重算落地）：",
            )
            for src in sources:
                form.add_button(
                    f"{src}",
                    on_click=lambda s, k=key, src=src: self._remove_source(s, k, src),
                )
            form.add_button("返回", on_click=lambda s, k=key: self.open_attribute(s, k))
            player.send_form(form)
        except Exception as e:
            p.logger.error(f"[ARCAttributeCore] open remove source {key} error: {e}")

    def _remove_source(self, player, key: str, source: str) -> None:
        p = self._plugin
        try:
            ok = p.api_remove_factor(player, key, source)
            live, _m = self._live_value(player, key)
            player.send_message(
                f"[ARCAttributeCore] {'已移除' if ok else '移除失败（不存在）'} {key} ← {source}"
                + (f"，引擎值 {live:.4f}" if live is not None else "")
            )
        except Exception as e:
            p.logger.error(f"[ARCAttributeCore] remove factor {key} {source} error: {e}")
        self.open_attribute(player, key)

    def _confirm_clear(self, player, key: str) -> None:
        p = self._plugin
        try:
            form = MessageForm(
                title="清空确认",
                text=f"清空 {self._label(key)}（{key}）的全部因子？",
            )
            form.button1 = "确认清空"
            form.button2 = "再想想"

            def on_submit(s, choice):
                if not choice:
                    return self.open_attribute(s, key)
                removed = p.api_clear_factors(s, key)
                live, _m = self._live_value(s, key)
                s.send_message(
                    f"[ARCAttributeCore] 已清空 {key} 的 {removed} 个因子"
                    + (f"，引擎值 {live:.4f}" if live is not None else "")
                )
                self.open_attribute(s, key)

            form.on_submit = on_submit
            player.send_form(form)
        except Exception as e:
            p.logger.error(f"[ARCAttributeCore] confirm clear {key} error: {e}")

    # ---------- 数据辅助 ----------

    def _ordered_keys(self) -> list[str]:
        return list(DIRECT_PROPS) + list(ATTRIBUTE_KEYS)

    def _label(self, key: str) -> str:
        return self.KEY_LABELS.get(key, key)

    def _factor_lines(self, player, key: str) -> list[str]:
        try:
            return self._plugin.api_list_factors(player, key).get(key, [])
        except Exception:
            return []

    def _live_value(self, player, key: str):
        """引擎实时值：(值, attribute 系修饰符个数)；直写系第二个为 None；未知为 (None, None)。"""
        try:
            if key in DIRECT_PROPS:
                return float(getattr(player, key)), None
        except Exception:
            pass
        try:
            if key in FALLBACK_DIRECT_PROPS:
                prop, _base = FALLBACK_DIRECT_PROPS[key]
                return float(getattr(player, prop)), None
        except Exception:
            pass
        try:
            from endstone.attribute import Attribute

            attr = getattr(Attribute, ATTRIBUTE_KEYS[key], None)
            if attr is None:
                return None, None
            instance = player.get_attribute(attr)
            if instance is None:
                return None, None
            mods = len(list(getattr(instance, "modifiers", None) or []))
            return float(instance.value), mods
        except Exception:
            return None, None

    def _landing_desc(self, player, key: str) -> str:
        """该属性因子在当前引擎上的落地方式（如实呈现，避免"写了没生效"的困惑）。"""
        if key in DIRECT_PROPS:
            return f"落地方式：独占直写 player.{key}"
        p = self._plugin
        if p._get_attribute(player, key) is not None:
            return "落地方式：AttributeModifier"
        if key in FALLBACK_DIRECT_PROPS:
            prop, _base = FALLBACK_DIRECT_PROPS[key]
            return (
                f"落地方式：直写 player.{prop}"
                "（当前 endstone 未暴露 get_attribute，走替代直写通道）"
            )
        return "⚠ 无法落地：当前 endstone 未向 Python 暴露 get_attribute，因子仅登记、暂不写入玩家"
