"""Từ điển alias cứng: ánh xạ ngôn ngữ tự nhiên tiếng Việt sang filter của DB.

QUAN TRỌNG: mọi slug ở đây được COPY NGUYÊN VĂN từ Phụ lục A của
``plan_md/CHATBOT_AI_PLAN.md``. Tuyệt đối không tự suy luận slug từ tiếng Việt,
vì ``slugify`` của Django xoá ký tự ``Đ/đ`` (``Đen`` -> ``en``, ``Đỏ`` -> ``o``,
``Đối xứng`` -> ``oi-xung``).

Test ``test_all_alias_slugs_exist_in_db`` sẽ phát hiện alias chết khi dữ liệu đổi.
"""

# --- Danh mục -----------------------------------------------------------------

CATEGORY_ALIASES = {
    'ban-phim': [
        'ban phim co', 'phim co', 'ban phim', 'keyboard', 'keycap', 'kb',
    ],
    'chuot': [
        'chuot gaming', 'chuot', 'mouse',
    ],
    'tai-nghe': [
        'tai nghe', 'headphone', 'headset', 'earbud', 'earphone', 'tai phone',
    ],
    'microphone': [
        'microphone', 'micro', 'mic',
    ],
    'tay-cam': [
        'tay cam', 'gamepad', 'controller', 'joystick', 'vo lang',
        'steering wheel', 'arcade stick',
    ],
}

# --- Thuộc tính EAV -----------------------------------------------------------
# Mỗi entry: keywords (đã viết dạng không dấu HOẶC có dấu, resolver tự normalize)
#            attributes = {group_slug: [value_slug, ...]}

ATTRIBUTE_ALIASES = {
    'wireless': {
        'keywords': ['khong day', 'wireless', 'bluetooth', '2.4ghz', '24ghz', 'khong can day'],
        'attributes': {'ket-noi': ['wireless', '24ghz', '24ghz-wireless', 'bluetooth']},
    },
    'wired': {
        'keywords': ['co day', 'wired', 'cam day', 'usb'],
        'attributes': {'ket-noi': ['usb', 'type-c']},
    },
    'jack_35': {
        'keywords': ['jack 3.5', '3.5mm', '35mm', 'cam jack'],
        'attributes': {'ket-noi': ['35mm']},
    },
    'compact': {
        'keywords': ['nho gon', 'compact', 'tkl', 'mini', '75%', '65%', 'tenkeyless'],
        'attributes': {'layout': ['tkl', '65', '75']},
    },
    'fullsize': {
        'keywords': ['fullsize', 'full size', 'day du', '104 phim', 'co so'],
        'attributes': {'layout': ['fullsize', '96']},
    },
    'switch_linear': {
        'keywords': ['switch em', 'em ai', 'silent', 'yen tinh', 'linear', 'red switch', 'switch do'],
        'attributes': {'switch': ['linear', 'red', 'red-switch', 'kailh-linear-40-8g']},
    },
    'switch_tactile': {
        'keywords': ['tactile', 'brown', 'switch nau', 'co khac'],
        'attributes': {'switch': ['tactile', 'brown', 'kailh-tactile-50-10g', 'gl-low-profile-tactile']},
    },
    'switch_clicky': {
        'keywords': ['clicky', 'switch xanh', 'blue switch', 'tieng click'],
        'attributes': {'switch': ['blue', 'gl-low-profile-clicky']},
    },
    'rgb': {
        'keywords': ['rgb', 'led', 'den led', 'chroma', 'nhieu mau', 'phat sang'],
        'attributes': {'den-led': ['rgb', 'led-rgb', '6-zone-razer-chroma-rgb', 'yes']},
    },
    'anc': {
        'keywords': ['chong on', 'anc', 'khu on', 'noise cancel'],
        'attributes': {'chong-on': ['co']},
    },
    'has_mic': {
        'keywords': ['co mic', 'kem mic', 'mic dam thoai', 'co microphone'],
        'attributes': {'microphone': ['co']},
    },
    'over_ear': {
        'keywords': ['over ear', 'on ear', 'trum tai', 'full tai', 'om tai'],
        'attributes': {'loai-tai-nghe': ['over-ear', 'on-ear']},
    },
    'in_ear': {
        'keywords': ['in ear', 'nhet tai', 'true wireless', 'tws'],
        'attributes': {'loai-tai-nghe': ['in-ear']},
    },
    'ergonomic': {
        'keywords': ['ergonomic', 'om tay', 'thuan tay phai', 'cong thai hoc'],
        'attributes': {'form-chuot': ['ergonomic']},
    },
    'symmetric': {
        # 'Đối xứng' -> slug 'oi-xung' (slugify xoá Đ)
        'keywords': ['doi xung', 'ambidextrous', 'hai tay'],
        'attributes': {'form-chuot': ['oi-xung']},
    },
    'haptic': {
        'keywords': ['co rung', 'haptic', 'phan hoi rung', 'rung tay'],
        'attributes': {'rung': ['co']},
    },
    'condenser': {
        'keywords': ['condenser', 'thu am phong', 'studio', 'phong thu'],
        'attributes': {'loai-micro': ['condenser']},
    },
    'dynamic_mic': {
        'keywords': ['dynamic', 'mic dong'],
        'attributes': {'loai-micro': ['dynamic']},
    },
    'cardioid': {
        'keywords': ['cardioid', 'thu 1 huong', 'mot huong', 'unidirectional'],
        'attributes': {'huong-thu-am': ['cardioid', 'unidirectional']},
    },
    'omnidirectional': {
        'keywords': ['omnidirectional', 'da huong', 'thu moi huong'],
        'attributes': {'huong-thu-am': ['omnidirectional']},
    },
    'with_stand': {
        'keywords': ['kem chan de', 'co chan de', 'arm', 'gia do mic'],
        'attributes': {'chan-de': ['co']},
    },
    'color_black': {
        'keywords': ['mau den', 'black'],
        'attributes': {'mau-sac': ['en']},
    },
    'color_white': {
        'keywords': ['mau trang', 'white'],
        'attributes': {'mau-sac': ['trang']},
    },
    'color_pink': {
        'keywords': ['mau hong', 'pink'],
        'attributes': {'mau-sac': ['hong']},
    },
    'color_red': {
        'keywords': ['mau do'],
        'attributes': {'mau-sac': ['o']},
    },
    'platform_playstation': {
        'keywords': ['ps5', 'ps4', 'playstation'],
        'attributes': {'tuong-thich': ['ps5', 'ps4']},
    },
    'platform_xbox': {
        'keywords': ['xbox'],
        'attributes': {'tuong-thich': ['xbox']},
    },
    'platform_switch': {
        'keywords': ['nintendo', 'nintendo switch'],
        'attributes': {'tuong-thich': ['nintendo-switch']},
    },
    'platform_mac': {
        'keywords': ['macos', 'macbook', 'mac'],
        'attributes': {'tuong-thich': ['macos', 'macos-105-tro-len']},
    },
}

# --- Ý định KHÔNG map được sang EAV (không tồn tại group 'usage' trong DB) ----
# Các ý này chỉ được đẩy vào keyword search trên name/description.

KEYWORD_ALIASES = {
    'gaming': ['gaming', 'chien game', 'choi game', 'esport', 'fps', 'moba', 'game'],
    'office': ['van phong', 'office', 'lam viec', 'hoc tap', 'code', 'lap trinh'],
    'stream': ['stream', 'livestream', 'youtube', 'podcast', 'thu am'],
    'battery': ['pin trau', 'pin lau', 'pin khoe', 'pin ben'],
    'lightweight': ['sieu nhe', 'nhe', 'lightweight'],
}

# --- Sắp xếp ------------------------------------------------------------------

SORT_ALIASES = {
    'price_asc': ['re nhat', 'gia re', 'tiet kiem', 'sinh vien', 'binh dan', 'gia thap'],
    'price_desc': ['cao cap', 'dat nhat', 'flagship', 'xin nhat', 'cao nhat'],
    'rating': ['danh gia cao', 'tot nhat', 'review tot', 'nhieu sao'],
    'popular': ['ban chay', 'pho bien', 'nhieu nguoi mua', 'hot', 'xu huong'],
}

# --- Phân loại chất lượng dữ liệu của 29 AttributeGroup (cạm bẫy T12/T13) ----
# Mọi group trong DB PHẢI thuộc đúng một trong bốn tập dưới đây.
# Command `chatbot_check_aliases` sẽ báo lỗi nếu có group chưa phân loại.

# 1. Sạch: value hữu hạn, đúng nghĩa -> luôn gợi ý cho LLM.
CLEAN_GROUPS = {
    'ket-noi',
    'layout',
    'switch',
    'den-led',
    'mau-sac',
    'form-chuot',
    'loai-tai-nghe',
    'loai-micro',
    'loai-tay-cam',
    'huong-thu-am',
    'trong-luong',
    'tuong-thich',
}

# 2. Dùng được nhưng value là text tự do / trùng lặp -> chỉ đưa cho LLM khi
#    người dùng hỏi trực tiếp về thông số đó, không gợi ý mặc định.
USABLE_GROUPS = {
    'cam-bien',
    'dpi',
    'keycap',
    'kich-thuoc',
    'polling-rate',
    'so-nut',
    'thoi-gian-bao-hanh',
}

# 3. Khai báo boolean nhưng DB chứa cả text rác -> chỉ cho phép co/khong (T13).
BOOLEAN_LIKE_GROUPS = {
    'chong-on': ['co', 'khong'],
    'microphone': ['co', 'khong'],
    'rung': ['co', 'khong'],
    'chan-de': ['co', 'khong'],
}

# 4. Bẩn: chứa rác thực sự (vd thoi-luong-pin có "Gasket Mount giờ")
#    -> KHÔNG bao giờ gợi ý cho LLM, không dùng làm filter.
DIRTY_GROUPS = {
    'thoi-luong-pin',
    'pin',
    'do-nhay',
    'snr',
    'dai-tan',
    'tro-khang',
}

# Tập group được phép xuất hiện trong gợi ý filter gửi cho LLM.
SUGGESTABLE_GROUPS = CLEAN_GROUPS | set(BOOLEAN_LIKE_GROUPS)

# Tập group được phép dùng làm filter (kể cả khi không gợi ý).
FILTERABLE_GROUPS = SUGGESTABLE_GROUPS | USABLE_GROUPS
