"""User-visible text for the main window (Thai first; English only for technical terms).

Error messages say what happened and what to do next. Values containing
``{name}`` placeholders are formatted by the caller with ``str.format``.
"""

APP_TITLE = "PhimThaiMaiPen · พิมพ์ไทยไม่เป็น"
STATUS_BAR = "PhimThaiMaiPen {version}  ·  ประมวลผลในเครื่อง"
BETA_WARNING = ("GPU / NPU · Beta\nฟีเจอร์นี้อยู่ในขั้นตอนพัฒนา หากเปิดแล้วจะมีผลลัพธ์ไม่แน่นอน\n"
                "แนะนำให้ใช้ CPU สำหรับการถอดเสียงทั่วไป")
ERROR_PREFIX = "ข้อผิดพลาด: "

# Settings file
SETTINGS_LOAD_FAILED = ("เปิดไฟล์ตั้งค่าไม่ได้: {error} · ไฟล์เดิมยังไม่ถูกเขียนทับ "
                        "อัปเดตแอปให้เป็นรุ่นล่าสุด หรือย้ายไฟล์ settings.json ออกแล้วเปิดแอปใหม่")
SETTINGS_REPAIRED = "ซ่อมไฟล์ตั้งค่าแล้ว: {warnings} · ตรวจค่าในหน้าตั้งค่าอีกครั้ง"
SETTINGS_REPAIR_SAVE_FAILED = "ซ่อมไฟล์ตั้งค่าแล้วแต่บันทึกไม่สำเร็จ: {error} · ตรวจพื้นที่ดิสก์แล้วกดบันทึกการตั้งค่า"
SETTINGS_SAVED = "บันทึกการตั้งค่าแล้ว"
SETTINGS_UNSAVED = "● ยังไม่ได้บันทึก"
SETUP_SAVE_FAILED = "บันทึกสถานะการเริ่มต้นไม่สำเร็จ: {error} · ตรวจพื้นที่ดิสก์แล้วลองใหม่"
MODE_SAVE_FAILED = "เปลี่ยนโหมดไม่สำเร็จ: {error} · ตรวจพื้นที่ดิสก์แล้วลองใหม่"

# Main status lines
STATUS_IDLE = "พร้อม"
STATUS_READY = "พร้อมแล้ว กดเริ่มพูด เมื่อพูดจบให้กดอีกครั้ง"
STATUS_NEED_MODEL = "เลือกและดาวน์โหลดโมเดลก่อนเริ่มพูด"
STATUS_CANCELLED = "ยกเลิกแล้ว"
STATUS_PROCESSING = "กำลังประมวลผลเสียง…"
STATUS_LISTENING = "กำลังฟัง… พูดจบแล้วกดหยุดพูดหรือปุ่มลัดอีกครั้ง"
STATUS_LISTENING_TICK = "กำลังฟัง…  {minutes:02d}:{seconds:02d}  ·  กดอีกครั้งเมื่อพูดจบ"
STATUS_LISTENING_QUEUED = "กำลังฟัง… งานก่อนหน้ายังประมวลผลอยู่ ครั้งนี้จะต่อคิวให้"
STATUS_PREPARING = "กำลังเตรียมโมเดล… พูดได้เลย ระบบจะถอดเสียงเมื่อโมเดลพร้อม"
STATUS_MODEL_READY = "โมเดลพร้อมแล้ว"
STATUS_QUEUED = "ต่อคิวแล้ว · รอ {count} งานก่อนหน้า"
STATUS_TRANSCRIPT_READY = "ข้อความพร้อมแล้ว · แก้ไข คัดลอก หรือวางได้เลย"
STATUS_MIC_TEST_DONE = "ทดสอบไมค์เสร็จแล้ว · ได้ยินเสียงชัดเจน"
STATUS_MIC_TEST_SILENT = "ทดสอบไมค์เสร็จแล้วแต่ไม่ได้ยินเสียง · ตรวจว่าเลือกไมค์ถูกตัวและไม่ได้ปิดเสียงไว้"
STATUS_MODE = "โหมด {name}"
STATUS_MODE_NEXT = " · ใช้กับการพูดครั้งถัดไป"
STATUS_MODE_NEEDS_TRANSLATION = " · ต้องดาวน์โหลดโมเดลแปลภาษาในหน้าโมเดล"
STATUS_CLEARED = "ล้างข้อความและเสียงชั่วคราวแล้ว"
STATUS_HISTORY_CLEARED = "ลบประวัติข้อความและเสียงที่บันทึกไว้แล้ว"
STATUS_REPORT_COPIED = "คัดลอกรายงานปัญหาแล้ว · วางในอีเมลหรือ issue เพื่อแจ้งผู้พัฒนา (ไม่มีข้อความที่ถอดเสียง)"

# Dictation errors (what happened + what to do)
ERR_MODEL_DOWNLOADING = "กำลังเตรียมโมเดล รอให้ดาวน์โหลดเสร็จก่อน แล้วกด Meta+H เพื่อเริ่มพูด"
ERR_NO_MODEL = "ยังไม่มีโมเดลพร้อมใช้ กดโหลดโมเดลต่อ หรือนำเข้าโมเดลในหน้าโมเดล"
ERR_NO_AUDIO = "ไม่ได้รับเสียงจากไมโครโฟน · ตรวจว่าเลือกไมค์ถูกตัวในหน้าตั้งค่า แล้วลองพูดใหม่"
ERR_NO_SPEECH = "ไม่พบเสียงพูด · พูดใกล้ไมค์ขึ้น หรือปิดการตัดความเงียบในหน้าตั้งค่า"
HUD_NO_SPEECH = "ไม่พบเสียงพูด ลองตรวจไมโครโฟน"
ERR_QUEUE_FULL = "มีงานรอคิวเต็มแล้ว · รอให้งานก่อนหน้าเสร็จ หรือกดยกเลิก แล้วค่อยพูดใหม่"
ERR_BUSY_TEST_MIC = "กำลังมีงานอยู่ · รอให้เสร็จหรือกดยกเลิกก่อนทดสอบไมค์"
ERR_BUSY_RECORDING = "กำลังฟังอยู่ · กดหยุดพูดหรือยกเลิกก่อน แล้วลองใหม่"
ERR_WAIT_MODEL_DOWNLOAD = "กำลังดาวน์โหลดหรือซ่อมโมเดลที่เลือก · รอให้เสร็จแล้วลองใหม่"
ERR_WAIT_TRANSLATION_DOWNLOAD = "กำลังดาวน์โหลดหรือซ่อมโมเดลแปลภาษา · รอให้เสร็จแล้วลองใหม่"
ERR_NOTHING_TO_RETRY = "ยังไม่มีเสียงให้ถอดใหม่ · อัดเสียงหรือเปิดไฟล์เสียงก่อน"
ERR_SHORTCUT_BUSY = "รอตรวจปุ่มลัดเสร็จสักครู่ แล้วลองใหม่"
ERR_SHORTCUT_CHECK_FAILED = "ตรวจปุ่มลัดไม่สำเร็จ ลองเปิดใช้ปุ่มลัดอีกครั้ง"
ERR_SHORTCUT_FAILED = "เปิดใช้ปุ่มลัดไม่สำเร็จ · ลองกดเปิดใช้ปุ่มลัดอีกครั้ง หรือตั้งเองใน System Settings"
SHORTCUT_READY = "ปุ่มลัด {trigger} พร้อมใช้งาน"
SHORTCUT_PORTAL = "ปุ่มลัดทั้งระบบ: {trigger}"
SHORTCUT_BY_DESKTOP = "ตั้งโดยเดสก์ท็อป"
SHORTCUT_NONE = "ยังไม่มีปุ่มลัดที่ใช้งานได้ · กดเปิดใช้ปุ่มลัดในหน้าตั้งค่า"
DESKTOP_START_FAILED = "เชื่อมต่อกับเดสก์ท็อปไม่ได้ · ลองใหม่อีกครั้ง หรือใช้ปุ่มคัดลอกแทน"
HISTORY_CLEAR_FAILED = "ลบประวัติบางส่วนไม่สำเร็จ: {error} · ปิดโปรแกรมที่เปิดไฟล์นั้นอยู่แล้วลองใหม่"

# Paste / clipboard
PASTE_WAIT_PREVIOUS = "รอการวางครั้งก่อนจบ แล้วลองวางอีกครั้ง"
COPY_WAIT_PREVIOUS = "รอการวางครั้งก่อนจบ แล้วลองคัดลอกอีกครั้ง"
PASTE_PERMISSION_PENDING = "รอให้หน้าขอสิทธิ์ของเดสก์ท็อปเสร็จก่อน แล้วลองวางอีกครั้ง"
PASTING = "กำลังวางข้อความ…"
PASTE_COUNTDOWN = "จะวางใน {seconds}… · สลับไปช่องข้อความปลายทาง · กด Esc หรือยกเลิกเพื่อหยุด"
PASTE_SENT = "ส่งคำสั่งวางแล้ว ตรวจสอบแอปปลายทางได้เลย · ระบบจะคืน clipboard ให้ภายหลัง"
PASTE_DONE = "วางข้อความแล้ว · คืน clipboard เรียบร้อย"
COPIED = "คัดลอกแล้ว · clipboard เก็บข้อความไว้ให้วางเอง"
COPIED_FALLBACK = "คัดลอกไว้แล้ว กด Ctrl+V เพื่อวาง"
COPIED_FALLBACK_NO_PERMISSION = "คัดลอกไว้แล้ว กด Ctrl+V เพื่อวาง · อนุญาตวางข้อความในหน้าตั้งค่าเพื่อให้วางอัตโนมัติ"
PASTE_CANCELLED = "ยกเลิกการวางแล้ว · ข้อความยังอยู่ในช่องแก้ไข"
PASTE_ABORT_PERMISSION_PENDING = "ยกเลิกการวางเพราะกำลังตั้งค่าสิทธิ์ของเดสก์ท็อป · ข้อความยังอยู่ในช่องแก้ไข ลองวางใหม่เมื่อเสร็จ"
PASTE_ABORT_PERMISSION_ENDED = "ยกเลิกการวางเพราะสิทธิ์วางข้อความหมดอายุ · ข้อความยังอยู่ในช่องแก้ไข อนุญาตใหม่ในหน้าตั้งค่า"
PASTE_ABORT_CLIPBOARD_CHANGED = "ยกเลิกการวางเพราะ clipboard ถูกเปลี่ยน · ข้อความยังอยู่ในช่องแก้ไข กดวางในแอปอีกครั้ง"
PASTE_ABORT_BRIDGE_CLOSED = "ยกเลิกการวางเพราะการเชื่อมต่อกับเดสก์ท็อปปิดไป · ข้อความยังอยู่ในช่องแก้ไข ลองวางใหม่"
PERMISSION_PENDING = "หน้าขอสิทธิ์ของเดสก์ท็อปยังเปิดอยู่ · ตอบหน้านั้นก่อนแล้วลองใหม่"
PERMISSION_WAIT_PASTE = "รอการวางข้อความให้เสร็จก่อน แล้วค่อยตั้งค่าสิทธิ์"
PASTE_ENABLED = "อนุญาตวางข้อความแล้ว"
PASTE_ENABLED_PERSISTENT = " · ระบบจะจำสิทธิ์นี้ไว้เมื่อเปิดแอปครั้งถัดไป"
PASTE_ENABLED_SESSION = " สำหรับเซสชันนี้"

# Transcript persistence warnings (keep the technical clause for logs/tests)
WARN_SETUP_STATE = "ข้อความพร้อมแล้ว แต่บันทึกสถานะการตั้งค่าไม่ได้: {error}"
WARN_HISTORY = "ข้อความพร้อมแล้ว แต่บันทึกประวัติไม่ได้ (history could not be saved): {error}"
WARN_AUDIO_HISTORY = "ข้อความพร้อมแล้ว แต่บันทึกประวัติเสียงไม่ได้ (audio history could not be saved): {error}"
WARN_TEMP_AUDIO = "ลบไฟล์เสียงชั่วคราวไม่ได้: {error}"

# Job controller messages (English from jobs.py → Thai). Matched by prefix.
JOB_STATUS = {
    "Ready": STATUS_IDLE,
    "Cancelled": STATUS_CANCELLED,
    "Queue is full": ERR_QUEUE_FULL,
    "Could not start the speech worker": "เริ่มตัวถอดเสียงไม่ได้ · ลองใหม่ หรือดูรายงานในหน้าตรวจสอบระบบ",
    "Speech worker stopped unexpectedly": "ตัวถอดเสียงหยุดทำงานกะทันหัน · กดถอดใหม่เพื่อลองอีกครั้ง",
    "Speech processing timed out": "ถอดเสียงนานเกินกำหนด · ลองอัดให้สั้นลง หรือเลือกโมเดลที่เล็กกว่า",
    "Worker failed": "ถอดเสียงไม่สำเร็จ · กดถอดใหม่ หรือดูรายงานในหน้าตรวจสอบระบบ",
}

# Navigation and layout
NAV_PAGES = ("พิมพ์ด้วยเสียง", "โมเดล", "ตั้งค่า", "ตรวจสอบระบบ")
NAV_TOOLTIPS = ("Transcript", "Models", "Settings", "Diagnostics")
NAV_ACCESSIBLE = "หน้าหลักของแอป"
MASCOT_ACCESSIBLE = "เพนกวินถือไมค์ · PhimThaiMaiPen"
BRAND = "PhimThai\nMaiPen"
SHORTCUT_HINT_TOOLTIP = "ปุ่มลัดเริ่มและหยุดพูด · ตั้งค่าได้ในหน้าตั้งค่า"
MODE_TOOLTIP = "สลับโหมด · Smart Mix → Raw → TH → ENG"
SIDEBAR_FOOTER = "ไทย + English\nเสียงอยู่ในเครื่องคุณ"
PROFILE_NAMES = {"smart": "Smart Mix", "raw": "Raw", "th_to_eng": "TH → ENG"}

# Transcript page
TRANSCRIPT_TITLE = "พิมพ์ด้วยเสียง"
TRANSCRIPT_SUBTITLE = "พูดไทย อังกฤษ หรือสลับภาษาได้ในประโยคเดียว"
SETUP_INTRO = ("เริ่มต้นครั้งแรก · ระบบจะดาวน์โหลด Typhoon ASR Realtime ประมาณ 462 MB ให้อัตโนมัติ\n"
               "ดาวน์โหลดเสร็จแล้วใช้แบบออฟไลน์ได้ เลือกโหลด Qwen เพิ่มได้ในหน้าโมเดล")
SETUP_PROGRESS_ACCESSIBLE = "ความคืบหน้าการเตรียมโมเดล"
SETUP_DESKTOP_INTRO = "ระบบจะเตรียม Meta+H และ Meta+Shift+H ให้ · อนุญาตสิทธิ์เมื่อเดสก์ท็อปถาม"
SETUP_NO_MODEL = "ยังไม่มีโมเดลพร้อมใช้ · โหลดต่อ หรือเลือกนำเข้าโมเดลในหน้าโมเดล"
SETUP_MODEL_READY = "โมเดลพร้อมแล้ว · Meta+H เริ่ม/หยุดพูด · Meta+Shift+H สลับโหมด"
SETUP_DESKTOP_PENDING = "กำลังเตรียมปุ่มลัด/การวางข้อความ · หากระบบแสดงหน้าขอสิทธิ์ ให้กดอนุญาต"
SETUP_DESKTOP_READY = "ปุ่มลัดและการวางข้อความพร้อมแล้ว"
SETUP_MISSING_SHORTCUT = "ปุ่มลัดยังไม่ครบ"
SETUP_MISSING_PASTE = "ยังไม่ได้อนุญาตวางข้อความ"
SETUP_MISSING_SUFFIX = " · เปิดใช้ได้ในหน้าตั้งค่า"
BTN_RESUME_DOWNLOAD = "โหลดโมเดลต่อ"
BTN_STOP_DOWNLOAD = "หยุดดาวน์โหลด"
BTN_MANAGE_MODELS = "จัดการโมเดล"
BTN_PERMISSIONS = "ตั้งค่าสิทธิ์"
BTN_RECORD = "เริ่มพูด"
BTN_STOP = "หยุดพูด"
RECORD_TOOLTIP = "เริ่ม / หยุดพูด"
BTN_OPEN_AUDIO = "เปิดไฟล์เสียง"
BTN_CANCEL = "ยกเลิก"
LEVEL_ACCESSIBLE = "ระดับเสียงไมโครโฟน"
TRANSCRIPT_LABEL = "ข้อความของคุณ"
EDITOR_PLACEHOLDER = "เริ่มจากเสียงของคุณ…\n\nข้อความที่ถอดจะปรากฏที่นี่ แล้วแก้ไขได้ตามต้องการ"
EDITOR_ACCESSIBLE = "ข้อความที่ถอดเสียง แก้ไขได้"
BTN_PASTE = "วางในแอป"
BTN_COPY = "คัดลอก"
BTN_TRANSLATE = "แปลอังกฤษ"
BTN_RETRY = "ถอดใหม่"
METRICS_PLACEHOLDER = "{model} · เวลาและอุปกรณ์จะแสดงเมื่อถอดเสียงเสร็จ"
OPEN_AUDIO_TITLE = "เปิดไฟล์เสียง"
OPEN_AUDIO_FILTER = "ไฟล์เสียง (*.wav *.mp3 *.flac *.ogg *.m4a);;ทุกไฟล์ (*)"

# Models page
MODELS_TITLE = "โมเดลถอดเสียง"
MODELS_SUBTITLE = "เลือก ดาวน์โหลด หรือนำเข้าโมเดลของคุณ · ใช้งานในเครื่อง"
MODELS_TECHNICAL = "แสดงข้อมูลทางเทคนิค"
BTN_DOWNLOAD = "ดาวน์โหลด / ซ่อมไฟล์"
BTN_STOP_DOWNLOAD_SHORT = "หยุดโหลด"
BTN_USE_MODEL = "เลือกใช้"
BTN_REMOVE_MODEL = "ลบโมเดล"
BTN_IMPORT_MODEL = "นำเข้าโมเดลจากโฟลเดอร์…"
DOWNLOAD_HINT = "หยุดแล้วโหลดต่อได้ · ตรวจความสมบูรณ์ของไฟล์ก่อนเปิดใช้"
MODEL_READY = "พร้อมใช้ · {size}"
MODEL_NOT_DOWNLOADED = "ยังไม่ได้ดาวน์โหลด"
MODEL_SELECTED = " · เลือกอยู่"
MODEL_STORAGE_LOCAL = "นำเข้าจากโฟลเดอร์ · ใช้พื้นที่ {size:.2f} GB"
MODEL_STORAGE_DOWNLOAD = "ดาวน์โหลดประมาณ {size:.2f} GB"
MODEL_DESCRIPTION = "{storage} · หน่วยความจำประมาณ {memory} GB\nภาษา: {languages}\nสิทธิ์การใช้งาน: {license}"
MODEL_TECHNICAL = ("{repo}\nBackend: {backend} · Devices: {devices}\nFormat: {format}\nStatus: {status}\n"
                   "Revision: {revision}\nวินาทีประมวลผลต่อวินาทีเสียง: {rates}")
MODEL_NO_MEASUREMENTS = "ยังไม่มีผลวัด"
MODEL_EXTERNAL_REIMPORT = "โมเดลภายนอก: ใช้ปุ่มนำเข้าโมเดลจากโฟลเดอร์เพื่อนำเข้าอีกครั้ง"
MODEL_BUSY_REPAIR = "กำลังมีงานอยู่ · รอให้เสร็จหรือกดยกเลิกก่อนซ่อมโมเดลนี้"
MODEL_DOWNLOADING = ("กำลังดาวน์โหลด {name} ประมาณ {size:.2f} GB\n"
                     "เริ่มต้นครั้งแรก ใช้เวลาตามความเร็วอินเทอร์เน็ต · ภายหลังลบหรือเปลี่ยนโมเดลได้")
MODEL_IMPORT_BUSY = "รอให้งานและการดาวน์โหลดเสร็จก่อนนำเข้าโมเดล"
MODEL_IMPORT_DIALOG = "เลือกโฟลเดอร์ Qwen3-ASR หรือ Whisper OpenVINO / GGML Q5"
MODEL_IMPORTING = "กำลังตรวจและคัดลอกโมเดลเข้าพื้นที่แอป · ไฟล์ต้นฉบับจะเก็บไว้เหมือนเดิม"
MODEL_VERIFIED = "ตรวจไฟล์ครบ พร้อมใช้งาน"
MODEL_PROGRESS_IMPORT = "กำลังนำเข้า: "
MODEL_PROGRESS_DOWNLOAD = "กำลังดาวน์โหลด: "
MODEL_PROGRESS_SIZE = " · ตรวจแล้ว {done:.0f} / {total:.0f} MB"
MODEL_STOPPED = "หยุดแล้ว · กดโหลดโมเดลต่อได้ "
MODEL_IMPORTED = "นำเข้าแล้ว · เลือกโมเดลแล้วกดเลือกใช้ ไฟล์ต้นฉบับยังอยู่ครบ"
MODEL_IMPORT_CLEANUP_FAILED = "ล้างไฟล์นำเข้าชั่วคราวไม่สำเร็จ: {error}"
MODEL_DOWNLOAD_START_FAILED = "เริ่มตัวดาวน์โหลดไม่ได้ · กดดาวน์โหลดเพื่อลองใหม่"
MODEL_BUSY_SWITCH = "กำลังมีงานอยู่ · รอให้เสร็จหรือกดยกเลิกก่อนเปลี่ยนโมเดล"
MODEL_WAIT_DOWNLOAD = "รอให้ดาวน์โหลดโมเดลนี้เสร็จก่อน แล้วกดเลือกใช้"
MODEL_TRANSLATION_ONLY = "โมเดลนี้ใช้สำหรับปุ่มแปลอังกฤษและโหมด TH → ENG ไม่ต้องกดเลือกใช้"
MODEL_DOWNLOAD_FIRST = "ดาวน์โหลดโมเดลนี้ก่อน แล้วกดเลือกใช้"
MODEL_SELECT_SAVE_FAILED = "บันทึกการเลือกโมเดลไม่สำเร็จ: {error} · ตรวจพื้นที่ดิสก์แล้วลองใหม่"
MODEL_BUSY_REMOVE = "รอให้งานและการดาวน์โหลดเสร็จก่อนลบโมเดล"
MODEL_LEGACY = "โมเดลนี้เป็นของการติดตั้งรุ่นเก่า · แอปจะเก็บไฟล์ไว้ตามเดิม"
MODEL_REMOVE_TITLE = "ลบโมเดล"
MODEL_REMOVE_QUESTION = "ลบไฟล์ที่ดาวน์โหลดของโมเดลนี้หรือไม่? ดาวน์โหลดใหม่ได้ภายหลัง"

# Settings page
SETTINGS_TITLE = "ตั้งค่า"
SETTINGS_SUBTITLE = "ไมค์ ภาษา และปุ่มลัด · การเปลี่ยนแปลงมีผลกับงานถัดไปหลังกดบันทึก"
BTN_SAVE = "บันทึกการตั้งค่า"
BTN_ENABLE_SHORTCUT = "เปิดใช้ปุ่มลัด"
BTN_ENABLE_PASTE = "อนุญาตวางข้อความ"
LABEL_MICROPHONE = "ไมโครโฟน"
BTN_REFRESH_MICS = "ตรวจหาไมค์"
BTN_TEST_MIC = "ทดสอบไมค์ 5 วินาที"
PROFILE_CHOICES = (("Smart Mix · ปรับข้อความให้อ่านง่าย", "smart"), ("Raw · ถอดตามที่พูด", "raw"),
                   ("TH → ENG · พูดไทย แปลอังกฤษ", "th_to_eng"))
LABEL_PROFILE = "รูปแบบข้อความ"
LANGUAGE_CHOICES = (("อัตโนมัติ · ไทย + English", "auto"), ("ภาษาไทย", "Thai"), ("English", "English"))
LANGUAGE_AUTO_THAI = "อัตโนมัติ · ภาษาไทย"
LANGUAGE_AUTO_MIXED = "อัตโนมัติ · ไทย + English"
LANGUAGE_ENGLISH_OTHER_MODEL = "English · ต้องเลือกโมเดลอื่น"
LANGUAGE_ENGLISH = "English"
LABEL_LANGUAGE = "ภาษาที่พูด"
LANGUAGE_HINT = "Typhoon รองรับเสียงภาษาไทย · ถ้าพูดอังกฤษหรือผสมสองภาษา ให้เลือก Qwen ในหน้าโมเดล"
DEVICE_CHOICES = (("อัตโนมัติ · CPU แนะนำ", "auto"), ("CPU · แนะนำ", "cpu"), ("GPU · Beta", "gpu"), ("NPU · Beta", "npu"))
LABEL_DEVICE = "ประมวลผลด้วย"
PREFERENCE_CHOICES = (("ตอบสนองเร็ว", "speed"), ("ประหยัดพลังงาน · ต้องมีผลวัด", "power"))
LABEL_THREADS = "CPU threads"
PASTE_MODE_CHOICES = (("ตรวจและแก้ข้อความก่อนวาง", "review"), ("วางทันทีเมื่อถอดเสียงเสร็จ", "immediate"))
LABEL_PASTE_MODE = "เมื่อพูดจบ"
LABEL_HOTKEY = "ปุ่มลัดเริ่ม / หยุด"
SHORTCUT_CHECKING = "กำลังตรวจปุ่มลัด…"
SHORTCUT_SET_UP = "ตั้งค่าปุ่มลัด"
SHORTCUT_TRIGGER_READY = "{trigger} · พร้อมเริ่มและหยุดพูด"
SHORTCUT_NOT_ENABLED = "ยังไม่เปิดใช้ปุ่มลัด · กดเปิดใช้ปุ่มลัดด้านบน"
SHORTCUT_MODE_LINE = "\n{trigger} · สลับโหมด"
CHECK_HISTORY = "เก็บประวัติข้อความในเครื่อง"
CHECK_AUDIO_HISTORY = "เก็บประวัติเสียงในเครื่อง"
CHECK_VAD = "ตรวจช่วงพูดและตัดความเงียบต้น–ท้าย"
CHECK_REDUCED_TRANSPARENCY = "ลดความโปร่งใส เพิ่มความชัดของพื้นหลัง"
CHECK_POPUP = "แสดง Popup เล็กด้านซ้ายขณะพูด"
CHECK_SOUND = "เสียงแจ้งเริ่ม หยุด และวางข้อความ"
DICTIONARY_LABEL = "พจนานุกรมส่วนตัว · คำเดิม ตามด้วย Tab และคำที่ให้แทน"
DICTIONARY_ACCESSIBLE = "พจนานุกรมคำแทนที่ส่วนตัว"
CHECK_REMEMBER_DESKTOP = "จำสิทธิ์วางข้อความและปุ่มลัดที่ขอผ่านระบบ"
REMEMBER_DESKTOP_TOOLTIP = "เปิดก่อนอนุญาตปุ่มลัด/การวาง แล้วกดบันทึก · เดสก์ท็อปเป็นผู้ตัดสินว่าจะจำสิทธิ์ได้หรือไม่"
BTN_CLEAR_HISTORY = "ลบประวัติข้อความและเสียงที่บันทึก"
MIC_SYSTEM_DEFAULT = "ไมค์เริ่มต้นของระบบ"
MIC_DISCONNECTED = "ไมค์ที่เลือกไว้ถูกถอดออก · เลือกไมค์ที่มีอยู่"
NPU_ENABLED_TOOLTIP = "NPU ทดลอง: ทดสอบโมเดลนี้ก่อนและตรวจความแม่นยำ"
NPU_DISABLED_TOOLTIP = "โมเดลและ runtime ที่ติดตั้งยังไม่มี NPU ให้ใช้ · ดูหน้าตรวจสอบระบบ"
CLEAR_HISTORY_TITLE = "ลบประวัติ"
CLEAR_HISTORY_QUESTION = "ลบประวัติข้อความและเสียงทั้งหมดที่แอปบันทึกไว้หรือไม่?"

# Diagnostics page
DIAGNOSTICS_TITLE = "เครื่องของคุณ"
DIAGNOSTICS_SUBTITLE = "ตรวจไมค์ โมเดล และอุปกรณ์ที่ใช้ได้ พร้อมข้อมูลสำหรับแก้ปัญหา"
DIAGNOSTICS_ACCESSIBLE = "ข้อมูลอุปกรณ์สำหรับแก้ปัญหา"
BTN_REFRESH_DIAGNOSTICS = "ตรวจสอบใหม่"
BTN_COPY_REPORT = "คัดลอกรายงานปัญหา"
DIAG_NOT_INSTALLED = "ยังไม่ได้ติดตั้ง"
DIAG_NPU_NOTE = ("Patched AMD FastFlowLM ผ่านการทดสอบ ASR เบื้องต้นบน Ryzen AI 5 340 คุณภาพยังเป็นแบบทดลอง · "
                 "Intel NPU ยังต้องทดสอบกับฮาร์ดแวร์จริง")
DIAG_MICROPHONES = "ไมโครโฟน: {count}"
DIAG_MODEL_READY = "โมเดล: ดาวน์โหลดแล้ว · ระบบจะตรวจอีกครั้งเมื่อใช้งาน"
DIAG_MODEL_MISSING = "โมเดล: ยังไม่มี · เลือกและดาวน์โหลดในหน้าโมเดล"
DIAG_CPU = "CPU: ใช้ได้ · โหมดอัตโนมัติเริ่มด้วย CPU จนกว่าจะมีผลวัดความเร็วที่เทียบกันได้"
DIAG_NO_MICROPHONE = "ไม่พบไมโครโฟน · เสียบไมค์และอนุญาตให้แอปเข้าถึงไมโครโฟนในการตั้งค่าสิทธิ์ของระบบ"
DIAG_VULKAN = "GPU: เลือก Whisper Turbo Vulkan ในหน้าโมเดล แล้วเลือก GPU ในหน้าตั้งค่า · ผลลัพธ์จะบอกอุปกรณ์ที่ใช้จริง"
DIAG_AMD_NPU = "AMD NPU: พบ runtime และอุปกรณ์ · เลือกโมเดล AMD NPU และ NPU เอง คุณภาพเสียงยังเป็นแบบทดลอง"
DIAG_FLATPAK_NPU = ("NPU ใช้ไม่ได้ใน sandbox นี้ · CPU ใช้ได้ด้วยสิทธิ์มาตรฐาน "
                    "NPU แบบทดลองต้องมีไดรเวอร์ runtime และสิทธิ์เข้าถึงอุปกรณ์ที่เข้ากันได้บนเครื่องหลัก")
DIAG_NPU_INSTALL = "NPU: ติดตั้ง runtime และไดรเวอร์ของผู้ผลิตก่อนทดสอบ · การตรวจพบฮาร์ดแวร์อย่างเดียวยังใช้ถอดเสียงไม่ได้"
DIAG_SHORTCUT_PASTE = "ปุ่มลัดและการวาง: เปิดใช้แต่ละอย่างในหน้าตั้งค่า แล้วตอบหน้าขอสิทธิ์ของเดสก์ท็อป"

# Tray and menus
TRAY_IDLE = "PhimThaiMaiPen · พร้อมพิมพ์ด้วยเสียง"
TRAY_RECORDING = "PhimThaiMaiPen · กำลังฟัง…"
TRAY_PROCESSING = "PhimThaiMaiPen · กำลังประมวลผลเสียง…"
TRAY_PASTING = "PhimThaiMaiPen · กำลังวางข้อความ…"
MENU_APP = "แอป"
MENU_QUIT = "ออกจาก PhimThaiMaiPen"
MENU_CLEAR = "ล้างข้อความและเสียงชั่วคราว"
MENU_OPEN = "เปิด PhimThaiMaiPen"
MENU_TOGGLE = "เริ่ม / หยุดพูด"
MENU_CANCEL = "ยกเลิก"
CLOSING_WAIT_PASTE = "กำลังจบการวางข้อความ รอสักครู่แล้วแอปจะปิดให้"
CLOSING_WAIT_SHORTCUT = "กำลังตั้งปุ่มลัด รอสักครู่แล้วแอปจะปิดให้"


def job_message(text):
    """Translate a known English JobController/worker message to Thai; keep others."""
    value = str(text or "")
    for prefix, thai in JOB_STATUS.items():
        if value.startswith(prefix):
            return thai
    return value


def all_strings():
    """Every user-visible constant, flattened (used by tests)."""
    values = {}
    for name, value in globals().items():
        if not name.isupper():
            continue
        if isinstance(value, str):
            values[name] = value
        elif isinstance(value, dict):
            for key, item in value.items():
                values[f"{name}[{key}]"] = item
        elif isinstance(value, tuple):
            for index, item in enumerate(value):
                values[f"{name}[{index}]"] = item[0] if isinstance(item, tuple) else item
    return values
