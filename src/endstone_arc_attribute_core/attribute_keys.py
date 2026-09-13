"""可管理属性键定义：direct 直写属性与 AttributeModifier 属性。"""

# 独占直写属性：引擎只有一个值，所有插件统一经本 API 管理
DIRECT_PROPS = {
    "walk_speed": 0.10,
    "fly_speed": 0.05,
}

# Attribute 体系属性：因子映射为 AttributeModifier，多插件原生 modifier 仍可共存
ATTRIBUTE_KEYS = {
    "health": "HEALTH",
    "absorption": "ABSORPTION",
    "attack_damage": "ATTACK_DAMAGE",
    "knockback_resistance": "KNOCKBACK_RESISTANCE",
    "luck": "LUCK",
    "movement_speed": "MOVEMENT_SPEED",
    "underwater_movement_speed": "UNDERWATER_MOVEMENT_SPEED",
    "lava_movement_speed": "LAVA_MOVEMENT_SPEED",
    "jump_strength": "JUMP_STRENGTH",
    "follow_range": "FOLLOW_RANGE",
    "player_hunger": "PLAYER_HUNGER",
    "player_saturation": "PLAYER_SATURATION",
    "player_exhaustion": "PLAYER_EXHAUSTION",
    "player_experience": "PLAYER_EXPERIENCE",
    "player_level": "PLAYER_LEVEL",
}

# 引擎未向 Python 暴露 get_attribute 时的替代直写通道：
# {属性键: (player 属性名, 引擎默认值)}；此通道下该键按 direct 语义落地（base 连乘直写）
FALLBACK_DIRECT_PROPS = {
    "health": ("max_health", 20.0),
}

# setter 仅接受整数的 player 属性（pybind SupportsInt，写浮点会直接报类型错误）
FALLBACK_INT_PROPS = {"max_health"}
