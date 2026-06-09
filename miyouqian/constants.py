# -*- coding: utf-8 -*-
"""接口常量与业务映射。"""

BBS_VERSION = "2.106.2"
QR_LOGIN_VERSION = "2.102.1"
PASSPORT_APP_VERSION = "2.90.1"

BBS_SALT = "idMMaGYmVgPzh3wxmWudUXKUPGidO7GM"
BBS_WEB_SALT = "G1ktdwFL4IyGkHuuWSmz0wUe9Db9scyK"
BBS_X6_SALT = "t0qEgfub6cvueAPgR5m9aQWWVciEer7v"
PASSPORT_X4_SALT = "xV8v4Qu54lUKrEYFZkJhB8cuOh9Asafs"
PASSPORT_APP_SALT = "dDIQHbKOdaPaLuvQKVzUzqdeCaxjtaPV"

PASSPORT_APP_ID = "bll8iq97cem8"
QRCODE_APP_APP_ID = "ddxf5dufpuyo"

TAKUMI_API = "https://api-takumi.mihoyo.com"
BBS_API = "https://bbs-api.miyoushe.com"
PASSPORT_API = "https://passport-api.mihoyo.com"
ZZZ_ACT_API = "https://act-nap-api.mihoyo.com"

ACCOUNT_ROLES_URL = f"{TAKUMI_API}/binding/api/getUserGameRolesByCookie"

GAME_HOME_URL = f"{TAKUMI_API}/event/luna/home?lang=zh-cn"
GAME_INFO_URL = f"{TAKUMI_API}/event/luna/info?lang=zh-cn"
GAME_SIGN_URL = f"{TAKUMI_API}/event/luna/sign"

ZZZ_HOME_URL = f"{ZZZ_ACT_API}/event/luna/zzz/home?lang=zh-cn"
ZZZ_INFO_URL = f"{ZZZ_ACT_API}/event/luna/zzz/info?lang=zh-cn"
ZZZ_SIGN_URL = f"{ZZZ_ACT_API}/event/luna/zzz/sign"

BBS_TASKS_URL = f"{BBS_API}/apihub/wapi/getUserMissionsState"
BBS_SIGN_URL = f"{BBS_API}/apihub/app/api/signIn"
BBS_POST_LIST_URL = f"{BBS_API}/post/api/getForumPostList"
BBS_DETAIL_URL = f"{BBS_API}/post/api/getPostFull"
BBS_SHARE_URL = f"{BBS_API}/apihub/api/getShareConf"
BBS_LIKE_URL = f"{BBS_API}/apihub/sapi/upvotePost"
BBS_CREATE_VERIFICATION_URL = f"{BBS_API}/misc/api/createVerification?is_high=true"
BBS_VERIFY_VERIFICATION_URL = f"{BBS_API}/misc/api/verifyVerification"

MALL_POINT_URL = f"{TAKUMI_API}/common/homutreasure/v1/web/user/point"
MALL_GOODS_LIST_URL = f"{TAKUMI_API}/mall/v1/web/goods/list"
MALL_GOOD_DETAIL_URL = f"{TAKUMI_API}/mall/v1/web/goods/detail"
MALL_EXCHANGE_URL = "https://api-takumi.miyoushe.com/mall/v1/web/goods/exchange"
MALL_ADDRESS_URL = f"{TAKUMI_API}/account/address/list"
DEVICE_FP_URL = "https://public-data-api.mihoyo.com/device-fp/api/getFp"

QRCODE_FETCH_URL = f"{PASSPORT_API}/account/ma-cn-passport/app/createQRLogin"
QRCODE_QUERY_URL = f"{PASSPORT_API}/account/ma-cn-passport/app/queryQRLoginStatus"
LOGIN_CAPTCHA_URL = f"{PASSPORT_API}/account/ma-cn-verifier/verifier/createLoginCaptcha"
LOGIN_BY_MOBILE_CAPTCHA_URL = f"{PASSPORT_API}/account/ma-cn-passport/app/loginByMobileCaptcha"
LTOKEN_BY_STOKEN_URL = f"{PASSPORT_API}/account/auth/api/getLTokenBySToken"
COOKIE_TOKEN_BY_STOKEN_URL = (
    f"{PASSPORT_API}/account/auth/api/getCookieAccountInfoBySToken"
)
COOKIE_TOKEN_REFRESH_URL = f"{TAKUMI_API}/auth/api/getCookieAccountInfoBySToken"

DEFAULT_MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 12; Unspecified Device) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
    f"Chrome/103.0.5060.129 Mobile Safari/537.36 miHoYoBBS/{BBS_VERSION}"
)

QR_MOBILE_UA = (
    f"Mozilla/5.0 (Linux; Android 12) Mobile miHoYoBBS/{QR_LOGIN_VERSION}"
)

PASSPORT_APP_UA = f"Mozilla/5.0 miHoYoBBS/{PASSPORT_APP_VERSION} Capture/2.2.0"

GAMES = {
    "genshin": {
        "name": "原神",
        "role": "旅行者",
        "game_biz": "hk4e_cn",
        "act_id": "e202311201442471",
        "home_url": GAME_HOME_URL,
        "info_url": GAME_INFO_URL,
        "sign_url": GAME_SIGN_URL,
        "extra_headers": {"x-rpc-signgame": "hk4e"},
    },
    "starrail": {
        "name": "崩坏：星穹铁道",
        "role": "开拓者",
        "game_biz": "hkrpg_cn",
        "act_id": "e202304121516551",
        "home_url": GAME_HOME_URL,
        "info_url": GAME_INFO_URL,
        "sign_url": GAME_SIGN_URL,
        "extra_headers": {},
    },
    "zzz": {
        "name": "绝区零",
        "role": "绳匠",
        "game_biz": "nap_cn",
        "act_id": "e202406242138391",
        "home_url": ZZZ_HOME_URL,
        "info_url": ZZZ_INFO_URL,
        "sign_url": ZZZ_SIGN_URL,
        "extra_headers": {"x-rpc-signgame": "zzz"},
    },
    "honkai3rd": {
        "name": "崩坏3",
        "role": "舰长",
        "game_biz": "bh3_cn",
        "act_id": "e202306201626331",
        "home_url": GAME_HOME_URL,
        "info_url": GAME_INFO_URL,
        "sign_url": GAME_SIGN_URL,
        "extra_headers": {},
    },
    "tears": {
        "name": "未定事件簿",
        "role": "律师",
        "game_biz": "nxx_cn",
        "act_id": "e202202251749321",
        "home_url": GAME_HOME_URL,
        "info_url": GAME_INFO_URL,
        "sign_url": GAME_SIGN_URL,
        "extra_headers": {},
    },
    "honkai2": {
        "name": "崩坏学园2",
        "role": "玩家",
        "game_biz": "bh2_cn",
        "act_id": "e202203291431091",
        "home_url": GAME_HOME_URL,
        "info_url": GAME_INFO_URL,
        "sign_url": GAME_SIGN_URL,
        "extra_headers": {},
    },
}

CLOUD_GAMES = {
    "genshin": {
        "name": "云原神",
        "coin_name": "米云币",
        "sign_url": "https://api-cloudgame.mihoyo.com/hk4e_cg_cn/wallet/wallet/get",
        "host": "api-cloudgame.mihoyo.com",
        "referer": "https://app.mihoyo.com",
    },
    "zzz": {
        "name": "云绝区零",
        "coin_name": "邦邦点",
        "sign_url": "https://cg-nap-api.mihoyo.com/nap_cn/cg/wallet/wallet/get",
        "host": "cg-nap-api.mihoyo.com",
        "referer": "",
    },
}

CLOUD_GAME_DISABLED_REASONS = {
    "starrail": "云星穹铁道是版本更新赠送 600 分钟，不需要每日签到获取时长",
}

BBS_FORUMS = {
    1: {"id": "1", "forum_id": "1", "name": "崩坏3"},
    2: {"id": "2", "forum_id": "26", "name": "原神"},
    3: {"id": "3", "forum_id": "30", "name": "崩坏2"},
    4: {"id": "4", "forum_id": "37", "name": "未定事件簿"},
    5: {"id": "5", "forum_id": "34", "name": "大别野"},
    6: {"id": "6", "forum_id": "52", "name": "崩坏：星穹铁道"},
    8: {"id": "8", "forum_id": "57", "name": "绝区零"},
}
