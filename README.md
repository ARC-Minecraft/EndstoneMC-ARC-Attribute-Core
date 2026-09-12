# ARC Attribute Core - 玩家属性与 Buff 管理器
[![Version](https://img.shields.io/badge/version-v0.1.0-blue)]()

一个为 Endstone 服务器打造的**多插件共享玩家属性管理器**：任何插件都可以发一个「属性调整请求」或「buff 请求」，由本插件统一叠加、优先级维护和到期回收，避免多个插件各自直写玩家属性互相覆盖。

## ✨ 核心概念

### 1. 属性调整因子

每个属性键维护一份**因子表**，其他插件按 `source`（来源标识）增删因子：

```
最终值 = (base + Σ add因子) × Π (1 + multiply因子)

例：base=1.0，加入 multiply 因子 0.25、-0.05、-0.10、0.15
  → 1 × 1.25 × 0.95 × 0.90 × 1.15 = 1.229
```

- `amount` 为**相对量**：multiply 因子 `0.25` 表示 ×1.25（+25%），`-0.20` 表示 ×0.80（-20%）
- 因子支持 `duration`（秒）：到期自动移除并重算；`duration=None` 为无限期，由来源插件手动移除
- 同一 `source` 重复添加为**覆盖**（先移除旧因子再加新因子）；`amount=0` 的因子不会挂载（自动移除）
- 按 `source` 撤销即恢复该来源之前的叠加状态，无需关心其他插件

### 2. Buff 优先级队列

同一效果按等级维护优先级，高等级先生效，到期自动回退次高级的**剩余时长**：

```
请求A：速度 1 级，持续 10 秒
请求B：速度 2 级，持续 5 秒
→ 先生效速度2（5 秒），结束后自动回退速度1（剩余 5 秒），全部到期移除
```

- 等级即显示等级（速度 1 → `amplifier 0`，速度 2 → `amplifier 1`）
- 同级取剩余时间最长者；同一 `source` 重复请求为覆盖；`api_remove_buff` 手动撤销

## 🎛️ 可管理的属性

### 独占直写（direct）

引擎只提供一个最终值、无法挂 modifier 的属性。**所有插件必须统一经本 API 管理**，本插件按上式连乘后直接写入玩家，并保护疾跑不被打断（无变化不写入；写入后同 tick + 下一 tick 写回疾跑状态）：

| 键 | 引擎默认值 | 说明 |
|------|-----------|------|
| `walk_speed` | `0.10` | 行走速度。最终写入值 = `0.10 × Π(1+因子)`，钳制在 [0.01, 1.0] |
| `fly_speed` | `0.05` | 飞行速度。最终写入值 = `0.05 × Π(1+因子)`，钳制在 [0.01, 1.0] |

### AttributeModifier（可共存）

映射为引擎 `AttributeModifier`，与原版效果、其他插件的原生 modifier **天然共存**：

- `multiply` 因子 → `Operation.MULTIPLY`（每个修饰符各乘 `1+amount`，引擎原生连乘）
- `add` 因子 → `Operation.ADD`（在 base 值上加减数值）
- 使用 `add_transient_modifier`（不写 NBT），死亡/重生丢失时插件自动重挂

| 键 | 引擎属性 | 说明 |
|------|----------|------|
| `health` | `minecraft:health` | 生命上限 |
| `absorption` | `minecraft:absorption` | 黄色吸收伤害 |
| `attack_damage` | `minecraft:attack_damage` | 近战攻击伤害 |
| `knockback_resistance` | `minecraft:knockback_resistance` | 击退抗性 |
| `luck` | `minecraft:luck` | 幸运（影响战利品表） |
| `movement_speed` | `minecraft:movement` | 引擎层移动速度属性 |
| `underwater_movement_speed` | `minecraft:underwater_movement` | 水下移动速度 |
| `lava_movement_speed` | `minecraft:lava_movement` | 熔岩中移动速度 |
| `jump_strength` | `minecraft:jump_strength` | 跳跃力度 |
| `follow_range` | `minecraft:follow_range` | 生物索敌范围 |
| `player_hunger` | `minecraft:player.hunger` | 饥饿值 |
| `player_saturation` | `minecraft:player.saturation` | 饱和度 |
| `player_exhaustion` | `minecraft:player.exhaustion` | 饥饿消耗度 |
| `player_experience` | `minecraft:player.experience` | 经验点 |
| `player_level` | `minecraft:player.level` | 经验等级 |

> 玩家实体不支持的键（如部分属性不存在于玩家）会在首次使用时告警一次并忽略，不影响其他属性。

## 🔌 插件对接 API

通过 `server.plugin_manager.get_plugin("arc_attribute_core")` 拿到插件实例后调用：

### 属性因子

```python
arc = server.plugin_manager.get_plugin("arc_attribute_core")

# 移速 -20%，10 秒后自动恢复（无 duration 为无限期，需手动移除）
arc.api_add_factor(player, "walk_speed", source="my_plugin:slow",
                   amount=-0.20, duration=10)

# add 语义：攻击力 base 上 +5（不随其他因子连乘）
arc.api_add_factor(player, "attack_damage", source="my_plugin:buff",
                   amount=5, operation="add")

# 手动撤销（只撤自己来源的，不影响别人）
arc.api_remove_factor(player, "walk_speed", source="my_plugin:slow")

# 清空玩家的因子（key=None 清全部），返回清除数量
arc.api_clear_factors(player)

# 查询最终值（walk_speed 返回钳制后的实际写入值）
arc.api_get_factor_value(player, "walk_speed")

# 调试/面板：{属性键: ["来源: 因子 [类型, 剩余时间]", ...]}
arc.api_list_factors(player)
```

**函数签名**：

| 函数 | 返回 | 说明 |
|------|------|------|
| `api_add_factor(player, key, source, amount, duration=None, operation="multiply")` | `bool` | 注册因子；非法 key 返回 False；同 source 覆盖 |
| `api_remove_factor(player, key, source)` | `bool` | 撤销指定来源因子 |
| `api_clear_factors(player, key=None)` | `int` | 清空因子，返回数量 |
| `api_get_factor_value(player, key)` | `float \| None` | 最终合成值；未知键 None |
| `api_list_factors(player, key=None)` | `dict[str, list[str]]` | 因子明细（面板用） |

### Buff

```python
# 速度 2 级持续 5 秒（等级=显示等级，内部 amplifier = level-1）
arc.api_apply_buff(player, "speed", level=2, duration=5, source="my_plugin:dart")

# 撤销该来源 → 自动回退队列中的次高级；source=None 清空该效果全部来源
arc.api_remove_buff(player, "speed", source="my_plugin:dart")

# 当前生效的 (等级, 剩余秒)；无生效返回 None
arc.api_get_active_buff(player, "speed")

# 调试/面板：{效果键: ["Lv2 剩5s 来源=... ←生效中", ...]}
arc.api_list_buffs(player)
```

**函数签名**：

| 函数 | 返回 | 说明 |
|------|------|------|
| `api_apply_buff(player, effect, level, duration, source)` | `bool` | 挂 buff；效果名支持任意 `EffectType` 名（speed/haste/strength/regeneration/fire_resistance/night_vision…） |
| `api_remove_buff(player, effect, source=None)` | `bool` | 撤销来源或整条队列 |
| `api_get_active_buff(player, effect)` | `tuple[int, float] \| None` | (生效等级, 剩余秒) |
| `api_list_buffs(player)` | `dict[str, list[str]]` | 队列明细（面板用） |

### 实战示例：ARC Realistic Survival 的接入方式

ARS 把口渴移速、基速倍率、腿伤减速拆成三路因子，互不干扰、随状态自动挂撤：

```python
arc.api_add_factor(player, "walk_speed", source="ars:base",   amount=0.5)    # 基速倍率 1.5
arc.api_add_factor(player, "walk_speed", source="ars:thirst", amount=0.2)    # 口渴 >80 → +20%
arc.api_add_factor(player, "walk_speed", source="ars:leg",    amount=-0.25)  # 骨裂 -25%
# 痊愈/创造旁路时对应 api_remove_factor(player, "walk_speed", source=...)
# 最终 walk_speed = 0.10 × 1.5 × 1.2 × 0.75
```

## ⚙️ 行为细节

- **不持久化**：因子与 buff 均为内存态，玩家退出即清（direct 属性恢复引擎默认）；长期效果请来源插件在玩家进服时重挂
- **重生恢复**：transient modifier 与效果在死亡/重生时丢失，插件在重生事件自动重挂该玩家全部因子与生效 buff
- **到期处理**：统一 20-tick（1 秒）定时器清理过期因子与 buff 并重算落地
- **疾跑保护**：写入 `walk_speed` 前记录疾跑状态，同 tick 与下一 tick 各写回一次；值未变化不写入
- **热重载**：`/arcattr reload` 重启定时器，因子与 buff 状态保留

## 🎮 命令

| 命令 | 权限 | 描述 |
|------|------|------|
| `/arcattr` | 全员 | 查看自己当前的属性因子与 buff 队列 |
| `/arcattr <玩家>` | OP | 查看指定玩家 |
| `/arcattr reload` | OP | 重载配置（保留因子状态） |

## 📦 安装

```bash
pip install build
python -m build
cp dist/*.whl /path/to/server/plugins/
```

依赖本插件的插件需在 Plugin 类声明 `depend = ["arc_attribute_core"]` 保证加载顺序。

## 🗄️ 开发

```
src/endstone_arc_attribute_core/
├── __init__.py              # 插件入口
├── arc_attribute_core.py    # 主插件：API / 定时器 / 事件 / 命令 / 属性落地
├── factor_registry.py       # 属性因子表（增删/连乘/到期，纯逻辑）
├── buff_registry.py         # buff 优先级队列（等级/时长/回退，纯逻辑）
└── effect_compat.py         # 药水效果 API 兼容层（0.10/0.11）

scripts/
├── _endstone_stub.py        # 离线测试 endstone stub
└── smoke_test_attribute_core.py  # 冒烟测试（python scripts/smoke_test_attribute_core.py）
```
