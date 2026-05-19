"""配置 I/O：纯逻辑。读 / 写 / 注入到 ``sys.modules['config']``。

使用 ``GuiState`` 作为单一可变状态容器，便于序列化和验证。
"""
from __future__ import annotations

import os
import sys
import types
from dataclasses import dataclass, field


MAX_ACCOUNTS = 2


@dataclass
class AccountState:
    account: str = ""
    password: str = ""
    start: str = ""
    end: str = ""

# 校区 → 自习室
ROOM_DATA = {
    "蒲河校区图书馆": [
        "三楼走廊", "4楼阅览室", "四楼走廊", "5楼阅览室", "五楼走廊",
        "6楼阅览室", "六楼走廊", "704", "706", "707", "708", "七楼走廊",
        "智慧空间",
    ],
    "崇山校区图书馆": [
        "二楼书库北", "二楼书库南", "二楼背诵长廊", "三楼智慧研修空间",
        "三楼理科书库", "四楼北自习室", "四楼南自习室", "四楼自习室406",
    ],
}


@dataclass
class GuiState:
    campus: str = "崇山校区图书馆"
    room: str = "三楼智慧研修空间"
    seats: list[str] = field(default_factory=list)

    account1: str = ""
    password1: str = ""
    start1: str = ""
    end1: str = ""

    use_account2: bool = False
    account2: str = ""
    password2: str = ""
    start2: str = ""
    end2: str = ""
    accounts: list[AccountState] = field(default_factory=lambda: [AccountState()])

    email: str = ""
    mode: str = "scheduled"  # "now" | "scheduled"
    sched_hour: int = 6
    sched_min: int = 30

    def sync_legacy_fields(self) -> None:
        """Keep the old account1/account2 fields in sync for older UI code."""
        entries = account_entries(self, include_empty=True)
        first = entries[0] if entries else AccountState()
        second = entries[1] if len(entries) > 1 else AccountState()
        self.account1 = first.account
        self.password1 = first.password
        self.start1 = first.start
        self.end1 = first.end
        self.use_account2 = bool(second.account or second.password or second.start or second.end)
        self.account2 = second.account
        self.password2 = second.password
        self.start2 = second.start
        self.end2 = second.end


def account_entries(state: GuiState, include_empty: bool = False) -> list[AccountState]:
    entries = list(getattr(state, "accounts", []) or [])
    entries_are_empty = not any(
        entry.account or entry.password or entry.start or entry.end
        for entry in entries
    )
    legacy_has_values = any(
        (
            state.account1,
            state.password1,
            state.start1,
            state.end1,
            state.account2,
            state.password2,
            state.start2,
            state.end2,
        )
    )
    if not entries or (entries_are_empty and legacy_has_values):
        entries = [
            AccountState(state.account1, state.password1, state.start1, state.end1)
        ]
        if state.use_account2:
            entries.append(AccountState(state.account2, state.password2, state.start2, state.end2))

    normalized: list[AccountState] = []
    for entry in entries:
        item = AccountState(
            str(entry.account or "").strip(),
            str(entry.password or ""),
            str(entry.start or "").strip(),
            str(entry.end or "").strip(),
        )
        if include_empty or item.account or item.password or item.start or item.end:
            normalized.append(item)

    if include_empty and not normalized:
        normalized.append(AccountState())
    return normalized


# ── 加载 ──
def load_state(config_path: str) -> GuiState:
    """从 ``config.py`` 解析；不存在或异常时返回全默认。"""
    state = GuiState()
    if not os.path.exists(config_path):
        return state
    try:
        ns: dict = {}
        with open(config_path, "r", encoding="utf-8") as f:
            exec(compile(f.read(), config_path, "exec"), ns)

        users = ns.get("USERS", {})
        accounts = list(users.items())
        state.accounts = []
        for account, info in accounts[:MAX_ACCOUNTS]:
            if account in ("你的学号", "第二个学号", ""):
                continue
            info = info or {}
            tc = info.get("time", {})
            state.accounts.append(
                AccountState(
                    account=str(account),
                    password=info.get("password", ""),
                    start=tc.get("start", ""),
                    end=tc.get("end", ""),
                )
            )
        if not state.accounts:
            state.accounts = [AccountState()]
        state.sync_legacy_fields()

        if v := ns.get("TARGET_CAMPUS"):
            state.campus = v
        if v := ns.get("TARGET_ROOM"):
            state.room = v
        if v := ns.get("RECEIVER_EMAIL"):
            state.email = v

        state.seats = list(ns.get("PREFER_SEATS", []) or [])
        state.mode = "scheduled" if ns.get("WAIT_FOR_0630", True) else "now"

        if (h := ns.get("SCHEDULE_HOUR")) is not None:
            state.sched_hour = int(h)
        if (m := ns.get("SCHEDULE_MINUTE")) is not None:
            state.sched_min = int(m)

    except Exception:
        # 配置损坏则退回默认
        return GuiState()
    return state


# ── 验证 ──
def validate(state: GuiState) -> tuple[bool, str]:
    accounts = account_entries(state)
    if not accounts:
        return False, "请至少填写 1 个账号"
    if len(accounts) > MAX_ACCOUNTS:
        return False, f"最多只支持 {MAX_ACCOUNTS} 个账号"
    seen: set[str] = set()
    for idx, account in enumerate(accounts, start=1):
        if not account.account:
            return False, f"请填写账号 {idx} 的学号"
        if not account.password.strip():
            return False, f"请填写账号 {idx} 的密码"
        if account.account in seen:
            return False, f"账号重复: {account.account}"
        seen.add(account.account)
    if not state.room.strip():
        return False, "请选择自习室"
    if not state.seats:
        return False, "请至少填写一个优先座位号"
    if state.mode == "scheduled":
        h, m = state.sched_hour, state.sched_min
        if not (0 <= h <= 23 and 0 <= m <= 59):
            return False, "定时时间必须在 00:00 ~ 23:59"
    return True, ""


# ── 写盘 ──
def save_state_to_file(state: GuiState, config_path: str) -> None:
    seats_str = ", ".join(f'"{s}"' for s in state.seats)
    esc = lambda s: (s or "").replace("\\", "\\\\").replace('"', '\\"')
    is_sched = state.mode == "scheduled"

    user_block = ""
    for entry in account_entries(state)[:MAX_ACCOUNTS]:
        if not entry.account:
            continue
        user_block += (
            f'    "{esc(entry.account)}": {{\n'
            f'        "password": "{esc(entry.password)}",\n'
            f'        "time": {{"start": "{esc(entry.start)}", '
            f'"end": "{esc(entry.end)}"}}\n    }},\n'
        )

    content = (
        "# ===================================================================\n"
        "# LNU-LibSeat-Automation 配置文件 (由 GUI 自动保存)\n"
        "# ===================================================================\n\n"
        f"USERS = {{\n{user_block}}}\n\n"
        f'TARGET_CAMPUS = "{esc(state.campus)}"\n'
        f'TARGET_ROOM = "{esc(state.room)}"\n'
        f"PREFER_SEATS = [{seats_str}]\n\n"
        f"WAIT_FOR_0630 = {is_sched}\n"
        f"MAX_ACCOUNTS = {MAX_ACCOUNTS}\n"
        '\nBROWSER = "edge"\nDRIVER_PATH = ""\nWEBDRIVER_CACHE = ""\n\n'
        f'RECEIVER_EMAIL = "{esc(state.email)}"\n'
        'SMTP_USER = ""\nSMTP_PASS = ""\n\n'
        'LOG_LEVEL = "INFO"\nLOG_DIR = "logs"\n'
    )
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(content)


# ── 注入 ──
def inject_into_sys_modules(state: GuiState) -> None:
    """把 state 转成动态 ``config`` 模块塞进 ``sys.modules``。
    ``main.py`` 内的 ``import config`` 会立刻拿到这份。
    """
    is_sched = state.mode == "scheduled"

    users: dict = {}
    for entry in account_entries(state)[:MAX_ACCOUNTS]:
        if not entry.account:
            continue
        users[entry.account] = {
            "password": entry.password,
            "time": {"start": entry.start, "end": entry.end},
        }

    cfg = types.ModuleType("config")
    cfg.USERS = users
    cfg.TARGET_CAMPUS = state.campus
    cfg.TARGET_ROOM = state.room.strip()
    cfg.PREFER_SEATS = list(state.seats)
    cfg.WAIT_FOR_0630 = is_sched
    cfg.MAX_ACCOUNTS = MAX_ACCOUNTS
    cfg.BROWSER = "edge"
    cfg.DRIVER_PATH = ""
    cfg.WEBDRIVER_CACHE = ""
    cfg.RECEIVER_EMAIL = state.email.strip()
    cfg.SMTP_USER = ""
    cfg.SMTP_PASS = ""
    cfg.LOG_LEVEL = "INFO"

    # LOG_DIR 用绝对路径，确保打包后定位正确
    log_dir = "logs"
    try:
        if getattr(sys, "frozen", False):
            log_dir = os.path.join(os.path.dirname(sys.executable), "logs")
        else:
            log_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "logs",
            )
    except Exception:
        pass
    cfg.LOG_DIR = log_dir

    if is_sched:
        cfg.SCHEDULE_HOUR = int(state.sched_hour)
        cfg.SCHEDULE_MINUTE = int(state.sched_min)

    sys.modules["config"] = cfg
