# Phim Thai Mai Pen

Linux Thai Voice Typing HotKey

<p align="center">
  <img src="https://github.com/user-attachments/assets/29660b40-78aa-4a22-9727-46f81606c7ef" alt="Phim Thai Mai Pen Banner" />
</p>

ระบบพิมพ์ด้วยเสียงบน Linux สำหรับพูดภาษาไทย, ไทยปนอังกฤษ, และแปลไทยเป็นอังกฤษก่อนพิมพ์ลงแอปที่กำลังใช้งานอยู่

Linux voice typing for Thai speech, Thai-English mixed speech, and Thai-to-English translation before inserting text into the app you are currently using.

ใช้ [Qwen3-ASR-0.6B](https://huggingface.co/Qwen/Qwen3-ASR-0.6B) เป็น backend หลัก รองรับไทยและอังกฤษ และรันงานถอดเสียงกับแปลภาษาในเครื่องของคุณเอง

It uses [Qwen3-ASR-0.6B](https://huggingface.co/Qwen/Qwen3-ASR-0.6B) as the default backend for Thai and English transcription and runs transcription plus translation locally on your machine.

---

## โปรแกรมนี้มีประโยชน์อะไร / Why Use It

1. เพิ่มระบบการพิมพ์ด้วยเสียงบน Linux ให้ฟีลใกล้เคียงกับที่หลายคนคุ้นจาก Windows Adds voice typing to Linux with a feel closer to what many people know from Windows.
2. เหมาะกับคนไทยสุด ๆ และพยายามให้ใช้งานได้กับแทบทุกหน้าต่างทุกโปรแกรมในเครื่องนี้ แต่อาจมีบัคหรือแอปบางตัวดื้อบ้าง Very Thai-focused and intended to work across almost any app window on your machine, although some bugs or stubborn apps are expected.
3. มีบัคแน่นอน เอาไว้ค่อยแก้ Bugs definitely exist. We can fix them later.

---

## ติดตั้ง / Install

```bash
git clone https://github.com/Tatarus9450/PhimThaiMaiPen.git
cd PhimThaiMaiPen
chmod +x install.sh
./install.sh
```

ตอนรัน `./install.sh` ให้ตอบเป็นตัวเลข:

When `./install.sh` starts, answer with a number:

- `1` ติดตั้งหรือซ่อมโปรแกรมนี้ - install or repair the program
- `2` ถอนการติดตั้ง - uninstall

ถ้าคุณเปลี่ยนจาก X11 ไป Wayland หรือเปลี่ยน desktop environment ภายหลัง ให้รัน `./install.sh` ใหม่อีกครั้ง

If you later switch between X11 and Wayland, or change desktop environments, run `./install.sh` again.

ถ้าต้องการตรวจระบบหลังติดตั้งเอง ให้รัน `python3 self_check.py`

If you want to run a manual health check after installation, run `python3 self_check.py`

---

## วิธีใช้งาน / How To Use

| Shortcut | Action |
| :--- | :--- |
| `Meta + H` | เริ่มหรือหยุดการอัดเสียง / Start or stop recording |
| `Meta + Shift + H` | เปลี่ยนโหมดการพิมพ์ / Change the dictation mode |
** ปุ่ม Meta คือปุ่มที่มีโลโก้ Windows ที่อยู่บนคีย์บอร์ดกันเกือบทุกคนเลยนะ หรือบางคนมีเขียนไว้แค่คําว่า WIN

วิธีใช้งาน:

Usage flow:

1. วางเคอร์เซอร์ในแอปที่ต้องการพิมพ์. Place your cursor in the target app.
2. ถ้าต้องการ เปลี่ยนโหมดด้วย `Meta + Shift + H`. If needed, change the mode with `Meta + Shift + H`.
3. กด `Meta + H` เพื่อเริ่มอัดเสียง. Press `Meta + H` to start recording.
4. พูดใส่ไมโครโฟน. Speak into your microphone.
5. กด `Meta + H` อีกครั้งเพื่อหยุดอัด. Press `Meta + H` again to stop recording.
6. ระบบจะถอดเสียงหรือแปลภาษา แล้วพิมพ์กลับเข้าแอปให้อัตโนมัติ. The app transcribes or translates your speech and inserts the text back into the target app.

---

## โหมดการใช้งาน / Modes

- `Smart Mix` ใช้สำหรับพูดไทยที่มีคำอังกฤษปน. For Thai speech with mixed English terms.
- `Raw` ใช้เมื่ออยากได้ข้อความแบบตรงที่สุด. For the most direct raw transcription.
- `TH to ENG` ใช้เมื่อพูดภาษาไทย แต่ต้องการผลลัพธ์เป็นภาษาอังกฤษ. For speaking Thai but getting English output.

ใน popup:

In the popup:

- `MIX` = `Smart Mix`
- `RAW` = `Raw`
- `TH>ENG` = `TH to ENG`

---

## หลักการทำงาน / How It Works

1. ผู้ใช้วางเคอร์เซอร์ไว้ในแอปที่ต้องการพิมพ์ แล้วกด `Meta + H` เพื่อเริ่มทำงาน. The user places the cursor in the target app and presses `Meta + H` to begin.
2. โปรแกรมรับคำสั่งจาก hotkey แล้วเริ่มอัดเสียงจากไมโครโฟนผ่าน `arecord`. The app receives the hotkey trigger and starts recording from the microphone through `arecord`.
3. ถ้าผู้ใช้กด `Meta + Shift + H` ก่อนหรือระหว่างใช้งาน โปรแกรมจะเปลี่ยนโหมดเป็น `Smart Mix`, `Raw`, หรือ `TH to ENG`. If the user presses `Meta + Shift + H` before or between runs, the app switches the active profile to `Smart Mix`, `Raw`, or `TH to ENG`.
4. เมื่อผู้ใช้กด `Meta + H` อีกครั้ง โปรแกรมจะหยุดอัดเสียงแล้วส่งไฟล์เสียงไปให้ local worker. When the user presses `Meta + H` again, the app stops recording and sends the audio file to the local worker.
5. worker จะเตรียมไฟล์เสียงให้อยู่ในรูปแบบที่เหมาะกับโมเดล แล้วส่งเข้า ASR backend เพื่อถอดเสียง. The worker normalizes the audio into the model-ready format and sends it to the ASR backend for transcription.
6. ถ้าอยู่ในโหมด `Smart Mix` ระบบจะจัดรูปข้อความและใช้ replacement rules เพิ่มเติม. If the active profile is `Smart Mix`, the app formats the text and applies replacement rules.
7. ถ้าอยู่ในโหมด `TH to ENG` ระบบจะถอดเสียงภาษาไทยก่อน แล้วแปลผลลัพธ์เป็นภาษาอังกฤษในเครื่อง. If the active profile is `TH to ENG`, the app first transcribes Thai speech and then translates the result to English locally.
8. เมื่อได้ข้อความสุดท้ายแล้ว โปรแกรมจะคัดลอกข้อความลง clipboard ก่อน แล้วพยายาม paste กลับเข้าแอปที่กำลังโฟกัสอยู่; ถ้า paste ไม่สำเร็จ ข้อความจะยังค้างอยู่ใน clipboard ให้ผู้ใช้ paste เอง. Once the final text is ready, the app copies it to the clipboard first and then tries to paste it back into the focused application; if the paste fails, the text remains in the clipboard for manual paste.

---

## หมายเหตุ / Quick Notes

- runtime ของการถอดเสียงและแปลภาษาเป็น local. Runtime transcription and translation are local.
- บน Wayland บางแอปอาจต้อง paste เองจาก clipboard ถ้า auto-paste ถูกบล็อก. On Wayland, some apps may require manual paste from the clipboard if auto-paste is blocked.
- ถ้า auto-paste สำเร็จ โปรแกรมจะคืนค่า clipboard เดิม; ถ้า auto-paste ไม่สำเร็จ ข้อความล่าสุดจะค้างอยู่ใน clipboard ให้ paste เอง. If auto-paste succeeds, the app restores the previous clipboard contents; if auto-paste fails, the latest text remains in the clipboard for manual paste.
- ถ้า hotkey ยังไม่ทำงานหลังติดตั้ง ให้ logout/login ใหม่ก่อน. If shortcuts do not work immediately after install, try logging out and back in first.

---

## self_check.py ใช้ทำอะไร ใช้ยังไง / What self_check.py Is For? How to Use?

`self_check.py` มีไว้เช็กแบบเร็ว ๆ ว่าโปรแกรมยังพร้อมใช้งานอยู่หรือไม่ เช่น dependency หลัก, worker, popup, การถอดเสียง, และการแปลภาษา โดยเอาไว้ตรวจสอบว่าโปรแกรมตัวนี้สามารถทำงานได้ถูกต้องกับเครื่องคอมพิวเตอร์ตอนนี้หรือไม่; หากมีข้อผิดพลาด คุณจะได้ตัดสินใจซ่อมโปรแกรมนี้ได้ทันที หรือถ้าคุณใจดีจะช่วยแจ้งปัญหาการใช้งานให้ผู้พัฒนาก็ได้

`self_check.py` is a quick health check to see whether the app is still ready to use on the current computer, including the main dependencies, worker, popup, transcription, and translation paths; if something is broken, you can decide to repair it right away, or report the issue to the developer if you feel generous.

วิธีใช้:

How to use:

```bash
python3 self_check.py
```

หรือถ้าอยู่ใน virtualenv:

Or if you are already inside the virtualenv:

```bash
./.venv/bin/python self_check.py
```

หมายเหตุ:

Notes:

- เหมาะกับการใช้หลังติดตั้ง หรือหลังแก้โค้ดบางส่วน Useful after installation or after making code changes.
- มันไม่ใช่การทดสอบไมโครโฟนจริงทุกครั้ง เพราะ smoke test (ใช้ไฟล์เสียงจำลอง) It is not a full live microphone test every time, because the main smoke test uses a generated audio sample.

---

## โมเดลถอดเสียง / ASR models

- ค่าเริ่มต้น `Qwen/Qwen3-ASR-0.6B` เหมาะกับ CPU และใช้หน่วยความจำน้อยกว่ารุ่น 1.7B แต่ความเร็วและความแม่นยำขึ้นกับเสียงและเครื่อง
- ตั้ง `TYPHOON_ASR_LANGUAGE="auto"` เพื่อให้ทั้ง `Raw` และ `Smart Mix` ตรวจจับภาษาอัตโนมัติ ส่วน `TH to ENG` ถอดเสียงแล้วแปลข้อความด้วยโมเดลแปลเดิม
- Audio is split near quiet boundaries around 10 seconds (up to about 15 seconds per chunk), with language detection per chunk. This helps when the speaker switches languages and keeps long transcripts within the generation budget. All chunk transcripts are combined.
- Mixed speech within a single chunk can still confuse language detection. Explicit `Thai` or `English` settings force the model's output language and may translate speech in another language; keep `auto` for bilingual dictation.
- เปลี่ยน `TYPHOON_MODEL` เป็น `Qwen/Qwen3-ASR-1.7B` ได้เมื่อมี RAM/GPU เพียงพอ รุ่นนี้ใช้ทรัพยากรมากกว่า
- The default 0.6B model runs locally on CPU (float32) or CUDA (float16). Download requires internet once; cached inference does not need an API key. Allow extra time for the first download. Model quality is not guaranteed to exceed Typhoon for every Thai recording.
- `TYPHOON_ASR_BACKEND="auto"` selects Qwen for model paths containing `qwen3-asr`; use `qwen` explicitly for a renamed local checkpoint. `TYPHOON_ASR_LANGUAGE` accepts `auto`, `Thai`, or `English` (Qwen only).
- หากต้องการกลับไป Typhoon ให้ติดตั้ง `.venv/bin/pip install typhoon-asr==0.1.1` แล้วตั้ง `TYPHOON_MODEL="scb10x/typhoon-asr-realtime"` และ `TYPHOON_ASR_BACKEND="auto"`
- หลังเปลี่ยน config ให้รัน `python3 typhoon_client.py --stop-service` โปรแกรมจะโหลดค่าล่าสุดเมื่อใช้งานครั้งถัดไป ชื่อไฟล์และตัวแปร `TYPHOON_*` คงไว้เพื่อรองรับสคริปต์เดิม

### ตรวจสอบหลังอัปเกรด / Upgrade verification

ทดสอบบนเครื่องนี้วันที่ 2026-09-11 ด้วย CPU Ryzen AI 5 340: unit tests 6 รายการ และ self-check 7 รายการผ่านทั้งหมด พร้อมทดสอบไฟล์เสียงไทย อังกฤษ คลิปต่อสองภาษา และการแปลไทยเป็นอังกฤษผ่าน worker จริง

ตัวอย่างเสียงมาจาก [Typhoon ASR](https://github.com/scb-10x/typhoon-asr/blob/main/examples/cv_test.wav) และ [Qwen3-ASR](https://qianwen-res.oss-cn-beijing.aliyuncs.com/Qwen3-ASR-Repo/asr_en.wav) โดยคลิปสองภาษาเป็นการต่อสองไฟล์ การตรวจนี้ยืนยันการทำงานเบื้องต้น ยังไม่ได้วัดความแม่นยำเทียบโมเดลเดิมหรือทดสอบเสียงพูดปนภาษาจริงจากไมโครโฟน

```bash
.venv/bin/python -m unittest -v test_asr_backend
python3 self_check.py
```

## License

MIT
