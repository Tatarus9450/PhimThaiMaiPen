#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(realpath "$0")")" && pwd)"
source "$SCRIPT_DIR/config.env"

TXT_FILE="${1:-/tmp/voice_agent.txt}"
TEXT="$(cat "$TXT_FILE" 2>/dev/null || true)"
PREVIOUS_CLIPBOARD_FILE=""
PREVIOUS_CLIPBOARD_TYPE=""
KLIPPER_STATE_FILE=""
RESTORE_DELAY="${CLIPBOARD_RESTORE_DELAY:-0.15}"
SESSION_TYPE="$(printf '%s' "${XDG_SESSION_TYPE:-x11}" | tr '[:upper:]' '[:lower:]')"
QDBUS_BIN=""
for candidate in qdbus qdbus6 qdbus-qt6; do
  if command -v "$candidate" >/dev/null 2>&1; then
    QDBUS_BIN="$candidate"
    break
  fi
done

if [[ -z "$TEXT" ]]; then
  notify-send "Phim Thai Mai Pen" "No text recognized."
  exit 0
fi

cleanup_previous_clipboard_file() {
  if [[ -n "$PREVIOUS_CLIPBOARD_FILE" && -f "$PREVIOUS_CLIPBOARD_FILE" ]]; then
    rm -f "$PREVIOUS_CLIPBOARD_FILE"
  fi
  if [[ -n "$KLIPPER_STATE_FILE" && -f "$KLIPPER_STATE_FILE" ]]; then
    rm -f "$KLIPPER_STATE_FILE"
  fi
}

has_klipper() {
  [[ -n "$QDBUS_BIN" ]] && "$QDBUS_BIN" org.kde.klipper /klipper >/dev/null 2>&1
}

use_wayland_clipboard() {
  [[ "$SESSION_TYPE" == "wayland" ]] && command -v wl-copy >/dev/null 2>&1 && command -v wl-paste >/dev/null 2>&1
}

use_private_clipboard() {
  use_wayland_clipboard && wl-copy --help 2>&1 | grep -q -- '--sensitive'
}

read_clipboard_to_file() {
  local target="$1"
  if use_wayland_clipboard; then
    PREVIOUS_CLIPBOARD_TYPE="$(wl-paste --list-types 2>/dev/null | sed -n '1p')" || return 1
    [[ -n "$PREVIOUS_CLIPBOARD_TYPE" ]] || return 1
    wl-paste --no-newline --type "$PREVIOUS_CLIPBOARD_TYPE" >"$target" 2>/dev/null
  else
    xclip -selection clipboard -o >"$target" 2>/dev/null
  fi
}

write_clipboard() {
  local mime_type="${1:-text/plain;charset=utf-8}"
  if use_wayland_clipboard; then
    if use_private_clipboard; then
      wl-copy --sensitive --type "$mime_type"
    else
      wl-copy --type "$mime_type"
    fi
  else
    xclip -selection clipboard
  fi
}

clear_clipboard() {
  if use_wayland_clipboard; then
    wl-copy --clear 2>/dev/null || true
  else
    printf '' | xclip -selection clipboard 2>/dev/null || true
  fi
}

snapshot_clipboard() {
  # KDE ignores the sensitive offer in history. Preserve its existing history
  # untouched instead of clearing and reconstructing it for temporary pastes.
  if ! use_private_clipboard && has_klipper; then
    KLIPPER_STATE_FILE="$(mktemp)"
    python3 - "$KLIPPER_STATE_FILE" "$QDBUS_BIN" <<'PY'
import json
import subprocess
import sys

state_path = sys.argv[1]
qdbus = sys.argv[2]

def qdbus_call(method: str, *args: str) -> str:
    proc = subprocess.run(
        [qdbus, "org.kde.klipper", "/klipper", method, *args],
        text=True,
        capture_output=True,
        check=False,
    )
    return proc.stdout

history: list[str] = []
for index in range(200):
    item = qdbus_call("org.kde.klipper.klipper.getClipboardHistoryItem", str(index))
    if item in {"", "\n"}:
        break
    history.append(item[:-1] if item.endswith("\n") else item)

with open(state_path, "w", encoding="utf-8") as handle:
    json.dump({"history": history}, handle, ensure_ascii=False)
PY
    return
  fi

  PREVIOUS_CLIPBOARD_FILE="$(mktemp)"
  if ! read_clipboard_to_file "$PREVIOUS_CLIPBOARD_FILE"; then
    rm -f "$PREVIOUS_CLIPBOARD_FILE"
    PREVIOUS_CLIPBOARD_FILE=""
  fi
}

restore_clipboard() {
  sleep "$RESTORE_DELAY"

  if [[ -n "$KLIPPER_STATE_FILE" && -f "$KLIPPER_STATE_FILE" ]]; then
    python3 - "$KLIPPER_STATE_FILE" "$QDBUS_BIN" <<'PY'
import json
import subprocess
import sys

state_path = sys.argv[1]
qdbus = sys.argv[2]

with open(state_path, encoding="utf-8") as handle:
    state = json.load(handle)

history = state.get("history") or []

subprocess.run(
    [qdbus, "org.kde.klipper", "/klipper", "org.kde.klipper.klipper.clearClipboardHistory"],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    check=False,
)

if history:
    for item in reversed(history):
        subprocess.run(
            [qdbus, "org.kde.klipper", "/klipper", "org.kde.klipper.klipper.setClipboardContents", item],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
PY
    cleanup_previous_clipboard_file
    return
  fi

  if [[ -n "$PREVIOUS_CLIPBOARD_FILE" && -f "$PREVIOUS_CLIPBOARD_FILE" ]]; then
    if use_wayland_clipboard; then
      write_clipboard "$PREVIOUS_CLIPBOARD_TYPE" <"$PREVIOUS_CLIPBOARD_FILE" 2>/dev/null || true
    else
      xclip -selection clipboard <"$PREVIOUS_CLIPBOARD_FILE" 2>/dev/null || true
    fi
    cleanup_previous_clipboard_file
    return
  fi

  clear_clipboard
}

ensure_ydotoold() {
  if ! command -v ydotool >/dev/null 2>&1 || ! command -v ydotoold >/dev/null 2>&1; then
    return 1
  fi

  # Fedora runs ydotoold as a system service. Prefer its protected socket when
  # it is available to the current user instead of starting a second daemon.
  if [[ -S /run/ydotoold/socket && -r /run/ydotoold/socket && -w /run/ydotoold/socket ]]; then
    export YDOTOOL_SOCKET="/run/ydotoold/socket"
    return 0
  fi

  if pgrep -u "$USER" -x ydotoold >/dev/null 2>&1; then
    return 0
  fi

  if command -v systemctl >/dev/null 2>&1; then
    systemctl --user start ydotool.service >/dev/null 2>&1 || true
    systemctl --user start ydotoold.service >/dev/null 2>&1 || true
  fi

  if ! pgrep -u "$USER" -x ydotoold >/dev/null 2>&1; then
    (ydotoold >/dev/null 2>&1 &)
    sleep 0.5
  fi

  pgrep -u "$USER" -x ydotoold >/dev/null 2>&1
}

paste_via_wayland() {
  if command -v wtype >/dev/null 2>&1; then
    wtype -M ctrl -k v -m ctrl >/dev/null 2>&1 && return 0
  fi

  if ensure_ydotoold; then
    # KEY_LEFTCTRL=29, KEY_V=47 from linux/input-event-codes.h
    ydotool key 29:1 47:1 47:0 29:0 >/dev/null 2>&1 && return 0
  fi

  return 1
}

notify_manual_paste() {
  notify-send "Phim Thai Mai Pen" "Copied text to clipboard. Paste manually."
}

trap cleanup_previous_clipboard_file EXIT

snapshot_clipboard
printf "%s" "$TEXT" | write_clipboard

if use_wayland_clipboard; then
  if paste_via_wayland; then
    restore_clipboard
    exit 0
  fi

  notify_manual_paste
  exit 0
fi

if xdotool key --clearmodifiers ctrl+v; then
  restore_clipboard
  exit 0
fi

if xdotool type --delay "$TYPE_DELAY" -- "$TEXT" 2>/dev/null; then
  restore_clipboard
  exit 0
fi

notify_manual_paste
