#!/usr/bin/env bash
set -euo pipefail

# ── Colors ──
G='\033[0;32m'  Y='\033[1;33m'  R='\033[0;31m'  B='\033[1;34m'  NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
HF_HOME_DIR="$SCRIPT_DIR/.cache/huggingface"
AUTOSTART_SCRIPT="$SCRIPT_DIR/autostart.sh"
AUTOSTART_DESKTOP_FILE="$HOME/.config/autostart/linux-voice-typing.desktop"
TOTAL_STEPS=0
MODE=""

bi() {
    local thai="${1:-}"
    local english="${2:-}"

    if [ -n "$thai" ] && [ -n "$english" ]; then
        printf '%s / %s' "$thai" "$english"
    elif [ -n "$thai" ]; then
        printf '%s' "$thai"
    else
        printf '%s' "$english"
    fi
}

step() { echo -e "\n${B}[$1/$TOTAL_STEPS]${NC} ${Y}$(bi "$2" "$3")${NC}"; }
ok()   { echo -e "  ${G}✓ $(bi "$1" "$2")${NC}"; }
fail() { echo -e "  ${R}✗ $(bi "$1" "$2")${NC}"; exit 1; }
skip() { echo -e "  ${G}⏭ $(bi "$1" "$2")${NC}"; }
warn() { echo -e "  ${Y}⚠ $(bi "$1" "$2")${NC}"; }
note() { echo -e "  ${B}• $(bi "$1" "$2")${NC}"; }

need_cmd() {
    command -v "$1" >/dev/null 2>&1 || fail "ไม่พบคำสั่งที่ต้องใช้: $1" "Missing required command: $1"
}

lower() {
    printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

escape_sed() {
    printf '%s' "$1" | sed 's/[\/&]/\\&/g'
}

upsert_env_key() {
    local key="$1"
    local value="$2"
    local file="$3"
    local escaped
    escaped="$(escape_sed "$value")"
    if grep -q "^${key}=" "$file"; then
        sed -i "s|^${key}=.*|${key}=\"${escaped}\"|" "$file"
    else
        printf '%s="%s"\n' "$key" "$value" >> "$file"
    fi
}

replace_managed_block() {
    local file="$1"
    local begin="$2"
    local end="$3"
    local content="$4"
    local tmp
    tmp="$(mktemp)"

    if [ -f "$file" ]; then
        awk -v begin="$begin" -v end="$end" '
            $0 == begin { skip = 1; next }
            $0 == end { skip = 0; next }
            !skip { print }
        ' "$file" > "$tmp"
    else
        : > "$tmp"
    fi

    printf '\n%s\n%s\n%s\n' "$begin" "$content" "$end" >> "$tmp"
    mv "$tmp" "$file"
}

remove_managed_block() {
    local file="$1"
    local begin="$2"
    local end="$3"
    local tmp

    [ -f "$file" ] || return 0
    tmp="$(mktemp)"

    awk -v begin="$begin" -v end="$end" '
        $0 == begin { skip = 1; next }
        $0 == end { skip = 0; next }
        !skip { print }
    ' "$file" > "$tmp"

    mv "$tmp" "$file"
}

strip_legacy_xbindkeys_entries() {
    local file="$1"
    local agent_command="$2"
    local toggle_command="$3"

    [ -f "$file" ] || return 0

    python3 - "$file" "$agent_command" "$toggle_command" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
agent_command = sys.argv[2]
toggle_command = sys.argv[3]

text = path.read_text(encoding="utf-8", errors="ignore")
blocks = [
    (
        "# Phim Thai Mai Pen Shortcut\n"
        f"\"{agent_command}\"\n"
        "  m:0x50 + c:43\n"
        "  Mod4+h\n"
    ),
    (
        "# Phim Thai Mai Pen Language Toggle\n"
        f"\"{toggle_command}\"\n"
        "  m:0x50 + c:43 + Shift\n"
        "  Mod4+Shift+h\n"
    ),
]

for block in blocks:
    text = text.replace(block + "\n", "")
    text = text.replace(block, "")

while "\n\n\n" in text:
    text = text.replace("\n\n\n", "\n\n")

path.write_text(text.rstrip() + "\n", encoding="utf-8")
PY
}

version_at_least() {
    local current="$1"
    local minimum="$2"
    python3 - "$current" "$minimum" <<'PY'
import sys

def parse(value: str) -> tuple[int, ...]:
    out = []
    for chunk in value.split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        if not digits:
            break
        out.append(int(digits))
    return tuple(out)

current = parse(sys.argv[1])
minimum = parse(sys.argv[2])
width = max(len(current), len(minimum))
current += (0,) * (width - len(current))
minimum += (0,) * (width - len(minimum))
raise SystemExit(0 if current >= minimum else 1)
PY
}

detect_distro_family() {
    local ids
    ids="$(lower "${ID:-}") $(lower "${ID_LIKE:-}")"
    case " $ids " in
        *" arch "*|*" manjaro "*|*" endeavouros "*)
            echo "arch"
            ;;
        *" opensuse "*|*" suse "*|*" sles "*)
            echo "suse"
            ;;
        *" fedora "*|*" rhel "*|*" centos "*|*" rocky "*|*" almalinux "*)
            echo "rhel"
            ;;
        *" debian "*|*" ubuntu "*|*" linuxmint "*)
            echo "debian"
            ;;
        *)
            echo "unknown"
            ;;
    esac
}

detect_desktop_environment() {
    local raw
    raw="$(lower "${XDG_CURRENT_DESKTOP:-${DESKTOP_SESSION:-${GDMSESSION:-}}}")"
    case "$raw" in
        *plasma*|*kde*)
            echo "plasma"
            ;;
        *gnome*)
            echo "gnome"
            ;;
        *xfce*)
            echo "xfce"
            ;;
        *cinnamon*)
            echo "cinnamon"
            ;;
        *mate*)
            echo "mate"
            ;;
        *)
            echo "unknown"
            ;;
    esac
}

desktop_display_name() {
    case "$1" in
        plasma) echo "KDE Plasma" ;;
        gnome) echo "GNOME" ;;
        xfce) echo "XFCE" ;;
        cinnamon) echo "Cinnamon" ;;
        mate) echo "MATE" ;;
        *) echo "Unknown" ;;
    esac
}

family_display_name() {
    case "$1" in
        debian) echo "Debian Base" ;;
        arch) echo "Arch Base" ;;
        suse) echo "SUSE Base" ;;
        rhel) echo "Red Hat (RHEL) Base" ;;
        *) echo "Unknown" ;;
    esac
}

setup_root_runner() {
    if [ "${EUID:-$(id -u)}" -eq 0 ]; then
        SUDO=()
        return
    fi

    need_cmd sudo
    SUDO=(sudo)
    "${SUDO[@]}" -v || fail "ยืนยันสิทธิ์ sudo ไม่สำเร็จ" "sudo authentication failed."
}

run_root() {
    "${SUDO[@]}" "$@"
}

choose_package_manager() {
    case "$DISTRO_FAMILY" in
        debian)
            command -v apt-get >/dev/null 2>&1 && echo "apt" && return 0
            ;;
        arch)
            command -v pacman >/dev/null 2>&1 && echo "pacman" && return 0
            ;;
        suse)
            command -v zypper >/dev/null 2>&1 && echo "zypper" && return 0
            ;;
        rhel)
            if command -v dnf >/dev/null 2>&1; then
                echo "dnf"
                return 0
            fi
            command -v yum >/dev/null 2>&1 && echo "yum" && return 0
            ;;
    esac

    fail "ไม่พบตัวจัดการแพ็กเกจที่รองรับสำหรับดิสโทรนี้" "Could not find a supported package manager for this distro."
}

pkg_refresh() {
    case "$PACKAGE_MANAGER" in
        apt)
            run_root apt-get update -qq
            ;;
        pacman)
            run_root pacman -Sy --noconfirm
            ;;
        zypper)
            run_root zypper --gpg-auto-import-keys --non-interactive refresh
            ;;
        dnf)
            run_root dnf -y makecache
            ;;
        yum)
            run_root yum -y makecache
            ;;
    esac
}

pkg_exists() {
    local pkg="$1"
    case "$PACKAGE_MANAGER" in
        apt)
            apt-cache show "$pkg" >/dev/null 2>&1
            ;;
        pacman)
            pacman -Si "$pkg" >/dev/null 2>&1
            ;;
        zypper)
            zypper --non-interactive info "$pkg" >/dev/null 2>&1
            ;;
        dnf)
            dnf -q info "$pkg" >/dev/null 2>&1
            ;;
        yum)
            yum -q info "$pkg" >/dev/null 2>&1
            ;;
    esac
}

pkg_install() {
    case "$PACKAGE_MANAGER" in
        apt)
            run_root apt-get install -y -qq "$@"
            ;;
        pacman)
            run_root pacman -S --noconfirm --needed "$@"
            ;;
        zypper)
            run_root zypper --non-interactive install -y "$@"
            ;;
        dnf)
            run_root dnf install -y "$@"
            ;;
        yum)
            run_root yum install -y "$@"
            ;;
    esac
}

install_first_available() {
    local label="$1"
    shift
    local pkg
    for pkg in "$@"; do
        [ -n "$pkg" ] || continue
        if pkg_exists "$pkg"; then
            pkg_install "$pkg"
            ok "ติดตั้งแพ็กเกจสำหรับ $label แล้ว: $pkg" "Installed package for $label: $pkg"
            return 0
        fi
    done
    warn "ไม่พบชื่อแพ็กเกจที่ใช้ได้สำหรับ $label" "Could not find a package candidate for $label"
    return 1
}

python_tk_candidates() {
    local short
    short="$(python3 -c 'import sys; print(f"{sys.version_info.major}{sys.version_info.minor}")')"
    printf '%s\n' \
        "python3-tk" \
        "python3-tkinter" \
        "python${short}-tk" \
        "python${short}-tkinter" \
        "python-tk" \
        "tk"
}

install_python_tk_support() {
    if python3 - <<'PY' >/dev/null 2>&1
import tkinter
PY
    then
        skip "รองรับ tkinter พร้อมใช้งานอยู่แล้ว" "python tkinter support is already available"
        return 0
    fi

    mapfile -t tk_candidates < <(python_tk_candidates)
    install_first_available "Tkinter bindings" "${tk_candidates[@]}" || true

    if python3 - <<'PY' >/dev/null 2>&1
import tkinter
PY
    then
        ok "นำเข้า tkinter ได้สำเร็จ" "tkinter import succeeded"
    else
        warn "ยังไม่สามารถใช้ tkinter ได้; popup UI อาจยังไม่ทำงานบนดิสโทรนี้หากไม่มีแพ็กเกจเสริม" "tkinter is still unavailable; the popup UI may not work on this distro without an extra package"
    fi
}

ensure_python_venv_support() {
    if python3 -m venv --help >/dev/null 2>&1; then
        skip "รองรับ python venv พร้อมใช้งานอยู่แล้ว" "python venv support is already available"
        return 0
    fi

    install_first_available "Python venv support" python3-venv python-virtualenv python3-virtualenv || true
    python3 -m venv --help >/dev/null 2>&1 || fail "ระบบนี้ยังใช้ python3 -m venv ไม่ได้" "python3 -m venv is unavailable on this system"
    ok "รองรับ python venv แล้ว" "python venv support is available"
}

enable_epel_if_needed() {
    if [ "$DISTRO_FAMILY" != "rhel" ] || [ "${ID:-}" = "fedora" ]; then
        return 0
    fi

    if pkg_exists epel-release; then
        pkg_install epel-release >/dev/null 2>&1 || true
        ok "พร้อมใช้งาน EPEL repository แล้ว" "EPEL repository is available"
    else
        warn "ไม่พบ epel-release; แพ็กเกจเดสก์ท็อปเสริมบางตัวอาจยังหายไปบนระบบตระกูล RHEL นี้" "epel-release was not found; some optional desktop packages may be missing on this RHEL-family system"
    fi
}

opensuse_repo_target() {
    local id_lower
    id_lower="$(lower "${ID:-}")"
    case "$id_lower" in
        opensuse-tumbleweed)
            echo "openSUSE_Tumbleweed"
            ;;
        opensuse-slowroll)
            echo "openSUSE_Slowroll"
            ;;
        *)
            if [ -n "${VERSION_ID:-}" ]; then
                echo "${VERSION_ID}"
            fi
            ;;
    esac
}

ensure_opensuse_repo() {
    local alias="$1"
    local project="$2"
    local target
    local project_path

    [ "$DISTRO_FAMILY" = "suse" ] || return 0
    target="$(opensuse_repo_target)"
    [ -n "$target" ] || return 0
    project_path="${project//:/:/}"

    if zypper lr -u 2>/dev/null | grep -Fq "$alias"; then
        return 0
    fi

    run_root zypper --non-interactive addrepo \
        "https://download.opensuse.org/repositories/${project_path}/${target}/${project}.repo" \
        "$alias" >/dev/null 2>&1 || true
}

ensure_suse_support_repos() {
    [ "$DISTRO_FAMILY" = "suse" ] || return 0
    ensure_opensuse_repo "LinuxVoiceTyping-X11-Wayland" "X11:Wayland"
    ensure_opensuse_repo "LinuxVoiceTyping-X11-Utilities" "X11:Utilities"
    pkg_refresh
}

append_gsettings_path() {
    local raw_list="$1"
    local new_path="$2"
    python3 - "$raw_list" "$new_path" <<'PY'
import ast
import sys

raw = sys.argv[1]
new_path = sys.argv[2]
try:
    values = list(ast.literal_eval(raw))
except Exception:
    values = []
if new_path not in values:
    values.append(new_path)
print("[" + ", ".join(repr(value) for value in values) + "]")
PY
}

append_gsettings_token() {
    local raw_list="$1"
    local token="$2"
    python3 - "$raw_list" "$token" <<'PY'
import ast
import sys

raw = sys.argv[1]
token = sys.argv[2]
try:
    values = list(ast.literal_eval(raw))
except Exception:
    values = []
if token not in values:
    values.append(token)
print("[" + ", ".join(repr(value) for value in values) + "]")
PY
}

remove_gsettings_path() {
    local raw_list="$1"
    local remove_path="$2"
    python3 - "$raw_list" "$remove_path" <<'PY'
import ast
import sys

raw = sys.argv[1]
remove_path = sys.argv[2]
try:
    values = list(ast.literal_eval(raw))
except Exception:
    values = []
values = [value for value in values if value != remove_path]
print("[" + ", ".join(repr(value) for value in values) + "]")
PY
}

remove_gsettings_token() {
    local raw_list="$1"
    local token="$2"
    python3 - "$raw_list" "$token" <<'PY'
import ast
import sys

raw = sys.argv[1]
token = sys.argv[2]
try:
    values = list(ast.literal_eval(raw))
except Exception:
    values = []
values = [value for value in values if value != token]
print("[" + ", ".join(repr(value) for value in values) + "]")
PY
}

configure_x11_shortcuts() {
    local xb_file="$HOME/.xbindkeysrc"
    local xb_begin="# >>> LinuxVoiceTyping >>>"
    local xb_end="# <<< LinuxVoiceTyping <<<"
    local agent_cmd="$SCRIPT_DIR/agent.py"
    local toggle_cmd="$SCRIPT_DIR/toggle_lang.sh"
    local xb_block

    read -r -d '' xb_block <<EOF || true
# Meta+H = Start/Stop Recording for Phim Thai Mai Pen
"$agent_cmd"
  Mod4+h

# Meta+Shift+H = Cycle dictation profile (Smart Mix / Raw / TH to ENG)
"$toggle_cmd"
  Mod4+Shift+h
EOF

    strip_legacy_xbindkeys_entries "$xb_file" "$agent_cmd" "$toggle_cmd"
    replace_managed_block "$xb_file" "$xb_begin" "$xb_end" "$xb_block"
    ok "ตั้ง global shortcuts บน X11 ด้วย xbindkeys แล้ว" "Configured X11 global shortcuts with xbindkeys"
}

configure_gnome_shortcuts() {
    local schema="org.gnome.settings-daemon.plugins.media-keys"
    local base="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings"
    local record_path="${base}/linux-voice-typing-record/"
    local toggle_path="${base}/linux-voice-typing-profile/"
    local record_schema="${schema}.custom-keybinding:${record_path}"
    local toggle_schema="${schema}.custom-keybinding:${toggle_path}"
    local existing updated

    command -v gsettings >/dev/null 2>&1 || { warn "ไม่พบ gsettings; ข้ามการตั้ง shortcut ของ GNOME" "gsettings was not found; skipping GNOME shortcut setup"; return 1; }

    existing="$(gsettings get "$schema" custom-keybindings)"
    updated="$(append_gsettings_path "$existing" "$record_path")"
    updated="$(append_gsettings_path "$updated" "$toggle_path")"
    gsettings set "$schema" custom-keybindings "$updated"

    gsettings set "$record_schema" name "Phim Thai Mai Pen"
    gsettings set "$record_schema" command "$SCRIPT_DIR/agent.py"
    gsettings set "$record_schema" binding "<Super>h"

    gsettings set "$toggle_schema" name "Phim Thai Mai Pen Profile"
    gsettings set "$toggle_schema" command "$SCRIPT_DIR/toggle_lang.sh"
    gsettings set "$toggle_schema" binding "<Super><Shift>h"
    ok "ตั้ง shortcuts ของ GNOME สำหรับ session ปัจจุบันแล้ว" "Configured GNOME shortcuts for the current session"
}

configure_cinnamon_shortcuts() {
    local list_schema="org.cinnamon.desktop.keybindings"
    local record_id="linux-voice-typing-record"
    local toggle_id="linux-voice-typing-profile"
    local record_path="/org/cinnamon/desktop/keybindings/custom-keybindings/${record_id}/"
    local toggle_path="/org/cinnamon/desktop/keybindings/custom-keybindings/${toggle_id}/"
    local record_schema="org.cinnamon.desktop.keybindings.custom-keybinding:${record_path}"
    local toggle_schema="org.cinnamon.desktop.keybindings.custom-keybinding:${toggle_path}"
    local existing updated

    command -v gsettings >/dev/null 2>&1 || { warn "ไม่พบ gsettings; ข้ามการตั้ง shortcut ของ Cinnamon" "gsettings was not found; skipping Cinnamon shortcut setup"; return 1; }

    existing="$(gsettings get "$list_schema" custom-list)"
    updated="$(append_gsettings_token "$existing" "$record_id")"
    updated="$(append_gsettings_token "$updated" "$toggle_id")"
    gsettings set "$list_schema" custom-list "$updated"

    gsettings set "$record_schema" name "Phim Thai Mai Pen"
    gsettings set "$record_schema" command "$SCRIPT_DIR/agent.py"
    gsettings set "$record_schema" binding "<Super>h"

    gsettings set "$toggle_schema" name "Phim Thai Mai Pen Profile"
    gsettings set "$toggle_schema" command "$SCRIPT_DIR/toggle_lang.sh"
    gsettings set "$toggle_schema" binding "<Super><Shift>h"
    ok "ตั้ง shortcuts ของ Cinnamon สำหรับ session ปัจจุบันแล้ว" "Configured Cinnamon shortcuts for the current session"
}

configure_mate_shortcuts() {
    command -v dconf >/dev/null 2>&1 || { warn "ไม่พบ dconf; ข้ามการตั้ง shortcut ของ MATE" "dconf was not found; skipping MATE shortcut setup"; return 1; }

    dconf write /org/mate/desktop/keybindings/custom0/name "'Phim Thai Mai Pen'"
    dconf write /org/mate/desktop/keybindings/custom0/action "'$SCRIPT_DIR/agent.py'"
    dconf write /org/mate/desktop/keybindings/custom0/binding "'<Super>h'"

    dconf write /org/mate/desktop/keybindings/custom1/name "'Phim Thai Mai Pen Profile'"
    dconf write /org/mate/desktop/keybindings/custom1/action "'$SCRIPT_DIR/toggle_lang.sh'"
    dconf write /org/mate/desktop/keybindings/custom1/binding "'<Super><Shift>h'"
    ok "ตั้ง shortcuts ของ MATE สำหรับ session ปัจจุบันแล้ว" "Configured MATE shortcuts for the current session"
}

configure_xfce_shortcuts() {
    command -v xfconf-query >/dev/null 2>&1 || { warn "ไม่พบ xfconf-query; ข้ามการตั้ง shortcut ของ XFCE" "xfconf-query was not found; skipping XFCE shortcut setup"; return 1; }

    xfconf-query -c xfce4-keyboard-shortcuts -p '/commands/custom/<Super>h' -n -t string -s "$SCRIPT_DIR/agent.py" >/dev/null 2>&1 \
        || xfconf-query -c xfce4-keyboard-shortcuts -p '/commands/custom/<Super>h' -t string -s "$SCRIPT_DIR/agent.py" >/dev/null
    xfconf-query -c xfce4-keyboard-shortcuts -p '/commands/custom/<Super><Shift>h' -n -t string -s "$SCRIPT_DIR/toggle_lang.sh" >/dev/null 2>&1 \
        || xfconf-query -c xfce4-keyboard-shortcuts -p '/commands/custom/<Super><Shift>h' -t string -s "$SCRIPT_DIR/toggle_lang.sh" >/dev/null
    ok "ตั้ง shortcuts ของ XFCE สำหรับ session ปัจจุบันแล้ว" "Configured XFCE shortcuts for the current session"
}

configure_plasma_shortcuts() {
    local applications_dir="$HOME/.local/share/applications"
    local accel_dir="$HOME/.local/share/kglobalaccel"
    local record_file="$applications_dir/linux-voice-typing-record.desktop"
    local toggle_file="$applications_dir/linux-voice-typing-profile.desktop"
    local kwriteconfig=""

    mkdir -p "$applications_dir" "$accel_dir"

    cat > "$record_file" <<EOF
[Desktop Entry]
Type=Application
Name=Phim Thai Mai Pen
Exec=$SCRIPT_DIR/agent.py
NoDisplay=true
StartupNotify=false
X-KDE-Shortcuts=Meta+H
X-KDE-GlobalAccel-CommandShortcut=true
EOF

    cat > "$toggle_file" <<EOF
[Desktop Entry]
Type=Application
Name=Phim Thai Mai Pen Profile
Exec=$SCRIPT_DIR/toggle_lang.sh
NoDisplay=true
StartupNotify=false
X-KDE-Shortcuts=Meta+Shift+H
X-KDE-GlobalAccel-CommandShortcut=true
EOF

    ln -sf "$record_file" "$accel_dir/linux-voice-typing-record.desktop"
    ln -sf "$toggle_file" "$accel_dir/linux-voice-typing-profile.desktop"

    if command -v kwriteconfig6 >/dev/null 2>&1; then
        kwriteconfig="kwriteconfig6"
    elif command -v kwriteconfig5 >/dev/null 2>&1; then
        kwriteconfig="kwriteconfig5"
    fi

    if [ -n "$kwriteconfig" ]; then
        "$kwriteconfig" --file kglobalshortcutsrc --group services --group linux-voice-typing-record.desktop \
            --key _launch "Meta+H,none,Start / Stop Voice Typing"
        "$kwriteconfig" --file kglobalshortcutsrc --group services --group linux-voice-typing-profile.desktop \
            --key _launch "Meta+Shift+H,none,Cycle Voice Typing Profile"
    fi

    command -v kbuildsycoca6 >/dev/null 2>&1 && kbuildsycoca6 >/dev/null 2>&1 || true
    command -v kbuildsycoca5 >/dev/null 2>&1 && kbuildsycoca5 >/dev/null 2>&1 || true
    command -v qdbus6 >/dev/null 2>&1 && qdbus6 org.kde.KWin /KWin reconfigure >/dev/null 2>&1 || true
    command -v qdbus >/dev/null 2>&1 && qdbus org.kde.KWin /KWin reconfigure >/dev/null 2>&1 || true

    ok "ตั้ง shortcuts ของ KDE Plasma สำหรับ session ปัจจุบันแล้ว" "Configured KDE Plasma shortcuts for the current session"
}

configure_wayland_shortcuts() {
    case "$DESKTOP_ENVIRONMENT" in
        plasma) configure_plasma_shortcuts ;;
        gnome) configure_gnome_shortcuts ;;
        xfce) configure_xfce_shortcuts ;;
        cinnamon) configure_cinnamon_shortcuts ;;
        mate) configure_mate_shortcuts ;;
        *)
            warn "desktop environment นี้ยังไม่รองรับการตั้ง Wayland shortcuts อัตโนมัติ: $DESKTOP_ENVIRONMENT" "Unsupported desktop environment for automatic Wayland shortcut setup: $DESKTOP_ENVIRONMENT"
            return 1
            ;;
    esac
}

remove_gnome_shortcuts() {
    local schema="org.gnome.settings-daemon.plugins.media-keys"
    local base="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings"
    local record_path="${base}/linux-voice-typing-record/"
    local toggle_path="${base}/linux-voice-typing-profile/"
    local existing updated

    command -v gsettings >/dev/null 2>&1 || return 0

    existing="$(gsettings get "$schema" custom-keybindings 2>/dev/null || printf '[]')"
    updated="$(remove_gsettings_path "$existing" "$record_path")"
    updated="$(remove_gsettings_path "$updated" "$toggle_path")"
    gsettings set "$schema" custom-keybindings "$updated" >/dev/null 2>&1 || true

    if command -v dconf >/dev/null 2>&1; then
        dconf reset -f "$record_path" >/dev/null 2>&1 || true
        dconf reset -f "$toggle_path" >/dev/null 2>&1 || true
    fi
}

remove_cinnamon_shortcuts() {
    local list_schema="org.cinnamon.desktop.keybindings"
    local record_id="linux-voice-typing-record"
    local toggle_id="linux-voice-typing-profile"
    local record_path="/org/cinnamon/desktop/keybindings/custom-keybindings/${record_id}/"
    local toggle_path="/org/cinnamon/desktop/keybindings/custom-keybindings/${toggle_id}/"
    local existing updated

    command -v gsettings >/dev/null 2>&1 || return 0

    existing="$(gsettings get "$list_schema" custom-list 2>/dev/null || printf '[]')"
    updated="$(remove_gsettings_token "$existing" "$record_id")"
    updated="$(remove_gsettings_token "$updated" "$toggle_id")"
    gsettings set "$list_schema" custom-list "$updated" >/dev/null 2>&1 || true

    if command -v dconf >/dev/null 2>&1; then
        dconf reset -f "$record_path" >/dev/null 2>&1 || true
        dconf reset -f "$toggle_path" >/dev/null 2>&1 || true
    fi
}

remove_mate_shortcuts() {
    command -v dconf >/dev/null 2>&1 || return 0
    dconf reset -f /org/mate/desktop/keybindings/custom0/ >/dev/null 2>&1 || true
    dconf reset -f /org/mate/desktop/keybindings/custom1/ >/dev/null 2>&1 || true
}

remove_xfce_shortcuts() {
    command -v xfconf-query >/dev/null 2>&1 || return 0
    xfconf-query -c xfce4-keyboard-shortcuts -p '/commands/custom/<Super>h' -r >/dev/null 2>&1 || true
    xfconf-query -c xfce4-keyboard-shortcuts -p '/commands/custom/<Super><Shift>h' -r >/dev/null 2>&1 || true
}

remove_plasma_shortcuts() {
    local applications_dir="$HOME/.local/share/applications"
    local accel_dir="$HOME/.local/share/kglobalaccel"
    local shortcuts_file="$HOME/.config/kglobalshortcutsrc"
    local tmp

    rm -f \
        "$applications_dir/linux-voice-typing-record.desktop" \
        "$applications_dir/linux-voice-typing-profile.desktop" \
        "$accel_dir/linux-voice-typing-record.desktop" \
        "$accel_dir/linux-voice-typing-profile.desktop"

    if [ -f "$shortcuts_file" ]; then
        tmp="$(mktemp)"
        awk '
            /^\[/ {
                drop = ($0 ~ /linux-voice-typing-record\.desktop/ || $0 ~ /linux-voice-typing-profile\.desktop/)
            }
            !drop { print }
        ' "$shortcuts_file" > "$tmp"
        mv "$tmp" "$shortcuts_file"
    fi

    command -v kbuildsycoca6 >/dev/null 2>&1 && kbuildsycoca6 >/dev/null 2>&1 || true
    command -v kbuildsycoca5 >/dev/null 2>&1 && kbuildsycoca5 >/dev/null 2>&1 || true
    command -v qdbus6 >/dev/null 2>&1 && qdbus6 org.kde.KWin /KWin reconfigure >/dev/null 2>&1 || true
    command -v qdbus >/dev/null 2>&1 && qdbus org.kde.KWin /KWin reconfigure >/dev/null 2>&1 || true
}

remove_all_shortcuts() {
    local xb_file="$HOME/.xbindkeysrc"

    if command -v python3 >/dev/null 2>&1; then
        strip_legacy_xbindkeys_entries "$xb_file" "$SCRIPT_DIR/agent.py" "$SCRIPT_DIR/toggle_lang.sh"
    fi
    remove_managed_block "$xb_file" "# >>> LinuxVoiceTyping >>>" "# <<< LinuxVoiceTyping <<<"

    remove_gnome_shortcuts
    remove_cinnamon_shortcuts
    remove_mate_shortcuts
    remove_xfce_shortcuts
    remove_plasma_shortcuts

    if command -v xbindkeys >/dev/null 2>&1; then
        pkill -x xbindkeys >/dev/null 2>&1 || true
        if [ -f "$xb_file" ]; then
            xbindkeys -f "$xb_file" >/dev/null 2>&1 || true
        fi
    fi
}

stop_runtime_processes() {
    if [ -x "$VENV_DIR/bin/python" ] && [ -f "$SCRIPT_DIR/typhoon_client.py" ]; then
        "$VENV_DIR/bin/python" "$SCRIPT_DIR/typhoon_client.py" --stop-service >/dev/null 2>&1 || true
    elif command -v python3 >/dev/null 2>&1 && [ -f "$SCRIPT_DIR/typhoon_client.py" ]; then
        python3 "$SCRIPT_DIR/typhoon_client.py" --stop-service >/dev/null 2>&1 || true
    fi

    pkill -f "$SCRIPT_DIR/agent.py" >/dev/null 2>&1 || true
    pkill -f "$SCRIPT_DIR/popup.py" >/dev/null 2>&1 || true
    pkill -f "$SCRIPT_DIR/typhoon_service.py" >/dev/null 2>&1 || true
    pkill -f "$SCRIPT_DIR/transcribe.sh" >/dev/null 2>&1 || true
    pkill -f "$SCRIPT_DIR/type.sh" >/dev/null 2>&1 || true
    pkill -x xbindkeys >/dev/null 2>&1 || true

    if command -v systemctl >/dev/null 2>&1; then
        systemctl --user stop ydotool.service >/dev/null 2>&1 || true
        systemctl --user stop ydotoold.service >/dev/null 2>&1 || true
    fi
}

remove_runtime_state() {
    rm -f \
        "$AUTOSTART_DESKTOP_FILE" \
        /tmp/agent_debug.log \
        /tmp/voice_agent_arecord.log \
        /tmp/voice_agent_arecord.pid \
        /tmp/voice_agent_last_trigger \
        /tmp/voice_agent_trigger.lock \
        /tmp/voice_agent_popup.pid \
        /tmp/voice_agent_profile \
        /tmp/voice_agent_status \
        /tmp/voice_agent.txt \
        /tmp/voice_agent.wav \
        /tmp/voice_agent_typhoon.sock \
        /tmp/voice_agent_typhoon.pid \
        /tmp/voice_agent_typhoon.log
}

remove_project_artifacts() {
    rm -rf \
        "$VENV_DIR" \
        "$SCRIPT_DIR/.cache" \
        "$SCRIPT_DIR/__pycache__" \
        "$SCRIPT_DIR/.pytest_cache"
    rm -f \
        "$SCRIPT_DIR/config.env" \
        "$SCRIPT_DIR/notification.wav"
}

schedule_project_directory_removal() {
    local target="$1"

    if [ -z "$target" ] || [ "$target" = "/" ] || [ "$target" = "$HOME" ] || [ ! -f "$target/install.sh" ]; then
        warn "ข้ามการลบโฟลเดอร์โปรแกรมเพราะ path ไม่ปลอดภัย: $target" "Skipped project directory removal because the path is not safe: $target"
        return 1
    fi

    (cd / && sleep 1 && rm -rf "$target") >/dev/null 2>&1 &
}

run_uninstall() {
    TOTAL_STEPS=5

    step 1 "เตรียมการถอนการติดตั้ง..." "Preparing uninstallation..."
    need_cmd rm
    need_cmd pkill
    ok "เริ่มถอนการติดตั้งจาก $SCRIPT_DIR" "Starting uninstall from $SCRIPT_DIR"

    step 2 "หยุด service และ process ที่กำลังทำงาน..." "Stopping running services and processes..."
    stop_runtime_processes
    ok "หยุด process ที่เกี่ยวข้องแล้ว" "Stopped related processes"

    step 3 "ลบ hotkeys และ autostart..." "Removing hotkeys and autostart..."
    remove_all_shortcuts
    remove_runtime_state
    ok "ลบการเชื่อมต่อกับระบบเดสก์ท็อปแล้ว" "Removed desktop integration"

    step 4 "ลบไฟล์ runtime และ cache ของโปรแกรม..." "Removing project runtime files and caches..."
    remove_project_artifacts
    ok "ลบ virtualenv, cache, config และไฟล์ชั่วคราวแล้ว" "Removed the virtualenv, caches, config, and temporary files"

    step 5 "ลบโฟลเดอร์โปรแกรม..." "Removing the project directory..."
    schedule_project_directory_removal "$SCRIPT_DIR"
    ok "ตั้งเวลาลบโฟลเดอร์โปรแกรมหลังสคริปต์ปิดตัวแล้ว" "Scheduled project directory removal after the script exits"

    echo ""
    echo -e "${G}╔══════════════════════════════════════╗${NC}"
    echo -e "${G}║    ถอนการติดตั้งเสร็จสมบูรณ์แล้ว     ║${NC}"
    echo -e "${G}║     Uninstall Complete Successfully  ║${NC}"
    echo -e "${G}╚══════════════════════════════════════╝${NC}"
    echo ""
    note "ลบไฟล์และการตั้งค่าของโปรแกรมแล้ว รวมถึงโฟลเดอร์นี้ด้วย" "Project files and local integration have been removed, including this project directory"
    note "แพ็กเกจระบบที่อาจถูกใช้ร่วมกับโปรแกรมอื่นจะไม่ถูกถอนออกอัตโนมัติ" "Shared system packages are not removed automatically because other applications may still depend on them"
    echo ""
}

prompt_mode_selection() {
    echo -e "${Y}เลือกโหมดการทำงาน / Choose an action${NC}"
    echo "  1. ติดตั้งหรือซ่อมโปรแกรมนี้ / Install or repair this project"
    echo "  2. ถอนการติดตั้งและลบข้อมูลของโปรแกรมนี้ / Uninstall and remove this project's data"
    echo ""

    while true; do
        printf "%b" "${B}กรุณาพิมพ์ 1 หรือ 2 / Enter 1 or 2: ${NC}"
        read -r MODE_SELECTION
        case "$MODE_SELECTION" in
            1)
                MODE="install"
                TOTAL_STEPS=9
                return 0
                ;;
            2)
                MODE="uninstall"
                return 0
                ;;
            *)
                warn "กรุณาเลือกเฉพาะ 1 หรือ 2" "Please choose only 1 or 2"
                ;;
        esac
    done
}

verify_backend_commands() {
    local base_cmd
    for base_cmd in ffmpeg sox arecord aplay notify-send python3 pgrep pkill killall; do
        need_cmd "$base_cmd"
    done

    if [ "$SESSION_TYPE" = "wayland" ]; then
        need_cmd wl-copy
        need_cmd wl-paste
        if ! command -v wtype >/dev/null 2>&1 && ! command -v ydotool >/dev/null 2>&1; then
            fail "การรองรับ Wayland ต้องมี wtype หรือ ydotool อย่างน้อยหนึ่งตัว" "Wayland support requires either wtype or ydotool."
        fi
    else
        need_cmd xclip
        need_cmd xdotool
        need_cmd xbindkeys
    fi
}

# ── Header ──
echo ""
echo -e "${G}╔══════════════════════════════════════════╗${NC}"
echo -e "${G}║  Phim Thai Mai Pen — Install / Uninstall ║${NC}"
echo -e "${G}╚══════════════════════════════════════════╝${NC}"
echo -e "  โปรแกรม / Project: ${Y}$SCRIPT_DIR${NC}"
echo ""

if [ -f /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
fi

prompt_mode_selection
if [ "$MODE" = "uninstall" ]; then
    run_uninstall
    exit 0
fi

DISTRO_FAMILY="$(detect_distro_family)"
DESKTOP_ENVIRONMENT="$(detect_desktop_environment)"
SESSION_TYPE="$(lower "${XDG_SESSION_TYPE:-x11}")"
DISTRO_LABEL="${PRETTY_NAME:-Linux}"

# ── 1. Pre-flight check ──
step 1 "ตรวจสอบระบบ..." "Checking the system..."

need_cmd uname
need_cmd python3

setup_root_runner
PACKAGE_MANAGER="$(choose_package_manager)"

ARCH="$(uname -m)"
if [[ "$ARCH" != "x86_64" ]]; then
    warn "สถาปัตยกรรม: $ARCH (ยังไม่ได้ทดสอบ แต่อาจใช้งานได้)" "Architecture: $ARCH (untested, but it may still work)"
else
    ok "สถาปัตยกรรม: x86_64" "Architecture: x86_64"
fi

ok "ระบบปฏิบัติการ: $DISTRO_LABEL" "OS: $DISTRO_LABEL"
if [ "$DISTRO_FAMILY" = "unknown" ]; then
    fail "distro family นี้ยังไม่รองรับ รองรับเฉพาะ Debian Base, Arch Base, SUSE Base และ Red Hat (RHEL) Base" "Unsupported distro family. Supported families: Debian Base, Arch Base, SUSE Base, and Red Hat (RHEL) Base."
fi
ok "ตระกูลดิสโทร: $(family_display_name "$DISTRO_FAMILY") ผ่าน $PACKAGE_MANAGER" "Distro family: $(family_display_name "$DISTRO_FAMILY") via $PACKAGE_MANAGER"

if [ "$DESKTOP_ENVIRONMENT" = "unknown" ]; then
    fail "desktop environment นี้ยังไม่รองรับ รองรับเฉพาะ KDE Plasma, GNOME, XFCE, Cinnamon และ MATE" "Unsupported desktop environment. Supported DEs: KDE Plasma, GNOME, XFCE, Cinnamon, and MATE."
fi
ok "เดสก์ท็อป: $(desktop_display_name "$DESKTOP_ENVIRONMENT")" "Desktop environment: $(desktop_display_name "$DESKTOP_ENVIRONMENT")"

if [[ "$SESSION_TYPE" != "x11" && "$SESSION_TYPE" != "wayland" ]]; then
    warn "ไม่รู้จัก session type '${SESSION_TYPE:-unknown}' จึง fallback ไปใช้สมมติฐานแบบ X11" "Unknown session type '${SESSION_TYPE:-unknown}'. Falling back to X11 assumptions."
    SESSION_TYPE="x11"
fi
ok "ชนิด session: $SESSION_TYPE" "Session type: $SESSION_TYPE"

PYTHON_VERSION="$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
version_at_least "$PYTHON_VERSION" "3.10" || fail "ต้องใช้ Python 3.10 ขึ้นไป (พบ $PYTHON_VERSION)" "Python 3.10+ is required (found $PYTHON_VERSION)"
ok "Python: $PYTHON_VERSION" "Python: $PYTHON_VERSION"

AVAILABLE_GB="$(df -BG "$SCRIPT_DIR" | awk 'NR==2 {gsub(/G/, "", $4); print $4}')"
if [[ -n "$AVAILABLE_GB" ]] && (( AVAILABLE_GB < 8 )); then
    fail "ควรมีพื้นที่ว่างอย่างน้อย 8 GB แต่ตอนนี้มีเพียง ${AVAILABLE_GB}G" "At least 8 GB of free disk space is recommended; only ${AVAILABLE_GB}G is available."
fi
ok "พื้นที่ว่าง: ${AVAILABLE_GB:-unknown}G" "Disk available: ${AVAILABLE_GB:-unknown}G"

if [ "$SESSION_TYPE" = "wayland" ]; then
    ok "จะตั้งค่าการรองรับ Wayland สำหรับ $(desktop_display_name "$DESKTOP_ENVIRONMENT")" "Wayland support will be configured for $(desktop_display_name "$DESKTOP_ENVIRONMENT")"
else
    ok "จะตั้งค่าการรองรับ X11 ด้วย xbindkeys" "X11 support will be configured with xbindkeys"
fi

# ── 2. System Dependencies ──
step 2 "ติดตั้งแพ็กเกจของระบบ..." "Installing system packages..."

enable_epel_if_needed
pkg_refresh
[ "$DISTRO_FAMILY" = "suse" ] && ensure_suse_support_repos

install_first_available "Git" git
install_first_available "FFmpeg" ffmpeg ffmpeg-free ffmpeg-4
install_first_available "SoX" sox
install_first_available "ALSA utilities" alsa-utils
install_first_available "Desktop notifications" libnotify-bin libnotify-tools libnotify
install_first_available "Process tools" procps procps-ng
install_first_available "killall utilities" psmisc
install_first_available "Python runtime" python3 python
install_first_available "Python pip" python3-pip python-pip
ensure_python_venv_support
install_python_tk_support

# X11 backend
install_first_available "X11 clipboard backend" xclip
install_first_available "X11 typing backend" xdotool
install_first_available "X11 global hotkeys" xbindkeys

# Wayland backend
install_first_available "Wayland clipboard backend" wl-clipboard
install_first_available "Wayland typing backend" wtype
install_first_available "Wayland fallback typing backend" ydotool || true
if [ "$DISTRO_FAMILY" = "debian" ]; then
    install_first_available "Wayland fallback daemon" ydotoold || true
fi

if [ "$DESKTOP_ENVIRONMENT" = "xfce" ]; then
    install_first_available "XFCE shortcut tooling" xfconf || true
fi

verify_backend_commands
ok "ติดตั้ง dependency ของระบบสำหรับ $SESSION_TYPE บน $(desktop_display_name "$DESKTOP_ENVIRONMENT") แล้ว" "System dependencies are installed for $SESSION_TYPE on $(desktop_display_name "$DESKTOP_ENVIRONMENT")"

# ── 3. Configuration ──
step 3 "เตรียมสถานะของโปรแกรม..." "Preparing project state..."

if [ ! -f "$SCRIPT_DIR/config.env" ]; then
    [ -f "$SCRIPT_DIR/config.env.example" ] || fail "ไม่พบไฟล์ config.env.example" "config.env.example is missing!"
    cp "$SCRIPT_DIR/config.env.example" "$SCRIPT_DIR/config.env"
    ok "สร้าง config.env แล้ว" "Created config.env"
else
    skip "มี config.env อยู่แล้ว" "config.env already exists"
fi

mkdir -p "$SCRIPT_DIR/.cache" "$HF_HOME_DIR"
ok "สร้างโฟลเดอร์ cache แล้ว" "Created cache directories"

if [ ! -f "$SCRIPT_DIR/notification.wav" ]; then
    sox -n -r 16000 -c 1 "$SCRIPT_DIR/notification.wav" \
        synth 0.14 sine 880 fade q 0.005 0.14 0.05 gain -12
    ok "สร้าง notification.wav แล้ว" "Created notification.wav"
else
    skip "มี notification.wav อยู่แล้ว" "notification.wav already exists"
fi

if grep -q 'ARECORD_DEVICE=""' "$SCRIPT_DIR/config.env"; then
    ok "จะใช้ไมโครโฟนค่าเริ่มต้นของระบบ" "Using the system default microphone"
fi

NPROC="$(nproc 2>/dev/null || echo 4)"
THREADS="$NPROC"

if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then
    TORCH_CHANNEL="cuda"
    ok "ตรวจพบ NVIDIA GPU; จะใช้ PyTorch ที่รองรับ CUDA" "NVIDIA GPU detected; the installer will use CUDA-enabled PyTorch"
else
    TORCH_CHANNEL="cpu"
    ok "ไม่พบ NVIDIA GPU; จะใช้ PyTorch ที่เหมาะกับ CPU" "No NVIDIA GPU detected; the installer will use CPU-optimized PyTorch"
fi

upsert_env_key "TYPHOON_MODEL" "Qwen/Qwen3-ASR-0.6B" "$SCRIPT_DIR/config.env"
upsert_env_key "TYPHOON_ASR_BACKEND" "auto" "$SCRIPT_DIR/config.env"
upsert_env_key "TYPHOON_ASR_LANGUAGE" "auto" "$SCRIPT_DIR/config.env"
upsert_env_key "TYPHOON_TRANSLATE_MODEL" "Helsinki-NLP/opus-mt-th-en" "$SCRIPT_DIR/config.env"
upsert_env_key "TYPHOON_DEVICE" "auto" "$SCRIPT_DIR/config.env"
upsert_env_key "TYPHOON_CPU_THREADS" "$THREADS" "$SCRIPT_DIR/config.env"
upsert_env_key "TYPHOON_VENV" "$VENV_DIR" "$SCRIPT_DIR/config.env"
upsert_env_key "TYPHOON_HF_HOME" "$HF_HOME_DIR" "$SCRIPT_DIR/config.env"
upsert_env_key "TYPHOON_PROFILE_DEFAULT" "smart" "$SCRIPT_DIR/config.env"
upsert_env_key "TYPHOON_REQUEST_TIMEOUT" "300" "$SCRIPT_DIR/config.env"
upsert_env_key "TYPHOON_STARTUP_TIMEOUT" "600" "$SCRIPT_DIR/config.env"
upsert_env_key "TYPHOON_FFMPEG_TIMEOUT" "30" "$SCRIPT_DIR/config.env"
upsert_env_key "TYPHOON_REPLACEMENTS_FILE" "$SCRIPT_DIR/typhoon_replacements.tsv" "$SCRIPT_DIR/config.env"
upsert_env_key "ARECORD_FORMAT" "S16_LE" "$SCRIPT_DIR/config.env"
upsert_env_key "ARECORD_CHANNELS" "1" "$SCRIPT_DIR/config.env"
upsert_env_key "ARECORD_RATE" "16000" "$SCRIPT_DIR/config.env"
ok "ตั้งค่า ASR ให้ใช้ CPU threads จำนวน $THREADS แล้ว" "Configured ASR with $THREADS CPU threads"

# ── 4. Python Environment ──
step 4 "สร้าง Python environment..." "Creating the Python environment..."

if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    ok "สร้าง .venv แล้ว" "Created .venv"
else
    skip "มี Python virtual environment อยู่แล้ว" "The Python virtual environment already exists"
fi

"$VENV_DIR/bin/python" -m pip install --upgrade pip wheel 'setuptools>=79,<82' >/dev/null
ok "อัปเกรดเครื่องมือ pip แล้ว" "Upgraded pip tooling"

# ── 5. Install Qwen3 ASR ──
step 5 "ติดตั้ง Python dependencies..." "Installing Python dependencies..."

if [[ "$TORCH_CHANNEL" == "cuda" ]]; then
    "$VENV_DIR/bin/pip" install --upgrade torch==2.11.0 torchaudio==2.11.0
else
    "$VENV_DIR/bin/pip" install --upgrade \
        --index-url https://download.pytorch.org/whl/cpu \
        --extra-index-url https://pypi.org/simple \
        torch==2.11.0 torchaudio==2.11.0
fi
"$VENV_DIR/bin/pip" install --upgrade qwen-asr==0.0.6
"$VENV_DIR/bin/pip" install --upgrade 'transformers==4.57.6' 'sentencepiece>=0.2,<1'
ok "ติดตั้ง Qwen3-ASR และ dependency สำหรับแปลภาษาแล้ว" "Installed Qwen3-ASR and translation dependencies"

# ── 6. Download Model ──
step 6 "ดาวน์โหลดและวอร์มโมเดล Qwen3-ASR กับโมเดลแปลภาษา..." "Downloading and warming the Qwen3-ASR and translation models..."

python3 "$SCRIPT_DIR/typhoon_client.py" --stop-service >/dev/null 2>&1 || true
"$VENV_DIR/bin/python" "$SCRIPT_DIR/typhoon_service.py" --preload-only --preload-translation
ok "cache และวอร์มโมเดล Qwen3-ASR กับโมเดลแปลภาษาแล้ว" "Qwen3-ASR and translation models have been cached and warmed"

# ── 7. Validation ──
step 7 "ตรวจสอบ runtime ภายในเครื่อง..." "Validating the local runtime..."

python3 "$SCRIPT_DIR/self_check.py"
ok "self-check และ smoke test ผ่านแล้ว" "The self-check and smoke tests passed"

# ── 8. Permissions ──
step 8 "ตั้งค่าสิทธิ์ไฟล์..." "Setting file permissions..."

chmod +x "$SCRIPT_DIR/agent.py"
chmod +x "$AUTOSTART_SCRIPT"
chmod +x "$SCRIPT_DIR/self_check.py"
chmod +x "$SCRIPT_DIR/typhoon_backend.py"
chmod +x "$SCRIPT_DIR/typhoon_client.py"
chmod +x "$SCRIPT_DIR/typhoon_service.py"
chmod +x "$SCRIPT_DIR/transcribe.sh"
chmod +x "$SCRIPT_DIR/type.sh"
chmod +x "$SCRIPT_DIR/toggle_lang.sh"
ok "สคริปต์ทั้งหมดเรียกใช้งานได้แล้ว" "All scripts are executable"

# ── 9. Hotkeys & Autostart ──
step 9 "ตั้งค่า shortcuts และ autostart..." "Configuring shortcuts and autostart..."

if [ "$SESSION_TYPE" = "wayland" ]; then
    configure_wayland_shortcuts || warn "การตั้ง Wayland shortcuts สำเร็จเพียงบางส่วน" "Wayland shortcut setup was only partially configured"
else
    configure_x11_shortcuts
fi

AUTOSTART_DIR="$HOME/.config/autostart"
mkdir -p "$AUTOSTART_DIR"
cat > "$AUTOSTART_DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=Phim Thai Mai Pen
Exec=$AUTOSTART_SCRIPT
Comment=Linux Thai Voice Typing HotKey
X-GNOME-Autostart-enabled=true
EOF
ok "ตั้งค่า autostart แล้ว" "Autostart has been configured"

if [ "$SESSION_TYPE" = "x11" ]; then
    killall xbindkeys 2>/dev/null || true
    if xbindkeys -f "$HOME/.xbindkeysrc" 2>/dev/null; then
        ok "โหลด xbindkeys ใหม่แล้ว" "Reloaded xbindkeys"
    else
        warn "ยังไม่สามารถเริ่ม xbindkeys ได้ตอนนี้ (อาจใช้งานได้หลัง login ใหม่)" "Could not start xbindkeys right now (it may work after you log in again)"
    fi
else
    command -v systemctl >/dev/null 2>&1 && systemctl --user start ydotool.service >/dev/null 2>&1 || true
    ok "ตั้งค่า Wayland backend สำหรับ $(desktop_display_name "$DESKTOP_ENVIRONMENT") แล้ว" "Configured the Wayland backend for $(desktop_display_name "$DESKTOP_ENVIRONMENT")"
fi

"$VENV_DIR/bin/python" "$SCRIPT_DIR/typhoon_client.py" --ensure-service --no-wait || true

# ── Done ──
echo ""
echo -e "${G}╔══════════════════════════════════════╗${NC}"
echo -e "${G}║           ติดตั้ง / ซ่อมเสร็จแล้ว           ║${NC}"
echo -e "${G}║      Install / Repair Complete!      ║${NC}"
echo -e "${G}╚══════════════════════════════════════╝${NC}"
echo ""
echo -e "  Session / เซสชัน: ${Y}$SESSION_TYPE${NC}"
echo -e "  Distro / ดิสโทร:  ${Y}$(family_display_name "$DISTRO_FAMILY")${NC}"
echo -e "  Desktop / เดสก์ท็อป: ${Y}$(desktop_display_name "$DESKTOP_ENVIRONMENT")${NC}"
echo -e "  ${Y}Meta + H${NC}           เริ่ม / หยุดการอัดเสียง | Start / Stop Recording"
echo -e "  ${Y}Meta + Shift + H${NC}   วน Smart Mix / Raw / TH to ENG | Cycle Smart Mix / Raw / TH to ENG"
echo ""
echo -e "  Config / คอนฟิก: ${Y}$SCRIPT_DIR/config.env${NC}"
echo -e "  Model cache / แคชโมเดล: ${Y}$HF_HOME_DIR${NC}"
echo -e "  Logs / ล็อก: ${Y}/tmp/agent_debug.log${NC}"
echo -e "  ASR log / ล็อก ASR: ${Y}/tmp/voice_agent_typhoon.log${NC}"
echo ""
echo -e "  ${G}คำแนะนำ / Tip:${NC} รัน ./install.sh ซ้ำหลังสลับระหว่าง X11 กับ Wayland หรือหลังเปลี่ยน DE เพื่อให้ระบบตั้ง shortcuts ให้ตรงกับ session ปัจจุบัน / Re-run ./install.sh after switching between X11 and Wayland, or after changing DEs, so shortcuts are reconfigured for the active session."
echo ""
