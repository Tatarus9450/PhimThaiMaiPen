# Hardware evidence

Recorded 2026-09-12 on the development host. Hardware discovery is not an ASR compatibility test.

## Status semantics

- **Detected:** an operating-system device or driver exists.
- **Runtime available:** the relevant runtime can enumerate the device. This does not prove that it can load a particular ASR model.
- **ASR verified:** the exact model revision, runtime, device and operating system have completed an audio transcription test with recorded output. Speed and accuracy require separate measurements.
- **Pending:** evidence is missing. Never display this as supported or select it automatically.

## Development host

| Item | Observed value |
| --- | --- |
| Operating system | Fedora 44 KDE, x86_64 |
| Kernel | `7.1.13-200.fc44.x86_64` |
| CPU | AMD Ryzen AI 5 340 with Radeon 840M, 12 logical CPUs |
| Memory reported by XRT | 13,726 MB |
| NPU device and driver | `/dev/accel/accel0`, `amdxdna` |
| XRT | `2.25.0` |
| XRT device | `RyzenAI-npu6`, `aie2p`, topology `6x8` |
| NPU firmware | `1.1.2.64` |
| NPU ASR | Stock FLM 1.0.5 truncated Thai; two-change proof completed four clips natively and inside KDE Platform 6.11; experimental quality |

Read-only commands used:

```bash
cat /etc/os-release
lscpu
ls -l /dev/accel /dev/dri
readlink -f /sys/class/accel/accel0/device/driver
rpm -qa | rg -i 'xrt|xdna|ryzen|openvino|onnx|npu'
rpm -ql xrt-base xrt-npu xrt_plugin-amdxdna
/opt/xilinx/xrt/bin/xrt-smi examine
```

Installed packages include `xrt-base`, `xrt-base-devel`, `xrt-npu` and `xrt_plugin-amdxdna`. XRT libraries are under `/opt/xilinx/xrt/lib64`; its executable is not on the observed default `PATH`. `xrt-smi examine` exited successfully and enumerated the NPU. This establishes **XRT device enumeration**, not availability of an ASR execution provider.

At this inventory, neither system Python nor the project's `.venv` had `openvino`, `openvino_genai`, `onnxruntime` or `ryzenai`. The project environment had `qwen_asr` and `torch`. Module presence was checked with `importlib.util.find_spec`; these observations may change after dependency installation.

## AMD NPU: working execution, experimental quality

[AMD's whisper.cpp README](https://github.com/amd/whisper.cpp#amd-ryzen-ai-support-for-npu), checked on the date above, documents NPU acceleration on Windows only, with Linux planned. Its flow uses `WHISPER_VITISAI=1`, FlexML runtime and matching GGML / `*-encoder-vitisai.rai` files. Only the encoder is offloaded through that flow.

[Ryzen AI Linux installation documentation](https://ryzenai.docs.amd.com/en/latest/linux.html) describes STX/KRK support for CNN, encoder NLP and selected LLM flows using Ubuntu packages. The Windows restriction above applies to AMD's whisper.cpp integration; it does not apply to every AMD NPU runtime.

The separate [ROCm/FastFlowLM Linux runtime](https://github.com/ROCm/FastFlowLM/blob/v1.0.5/docs/linux-getting-started.md) successfully executed ASR on this host. The isolated test used:

- [FLM 1.0.5 Linux portable archive](https://github.com/ROCm/FastFlowLM/releases/download/v1.0.5/fastflowlm_1.0.5_linux.tar.gz), SHA256 `dd797ccfda5e0f97e3b683c9b304bce7d0051f8e5d650b9eb001d01a83b19d2c`, 43,933,428 bytes
- [FastFlowLM/Whisper-V3-Turbo-NPU2](https://huggingface.co/FastFlowLM/Whisper-V3-Turbo-NPU2/tree/594eecd2d80b20cbb04ef0099162335d1dd1899a), revision `594eecd2d80b20cbb04ef0099162335d1dd1899a`
- `model.q4nx`, SHA256 `8fb97604bf5762ee26efa696cfc9eb70724110358c7b4ca628a7973bf8a16291`, 650,175,128 bytes, plus the revision's `config.json`, `tokenizer.json` and `tokenizer_config.json`
- Temporary runtime/model files under `/tmp/phimthai-npu-proof`; no sudo, kernel, firmware or driver changes

The [runtime license](https://github.com/ROCm/FastFlowLM/blob/v1.0.5/LICENSE_RUNTIME.txt) is MIT for orchestration/CLI. Its [release README](https://github.com/ROCm/FastFlowLM/tree/v1.0.5#-license) permits free use of binary NPU kernels, including commercial use, and requests FastFlowLM acknowledgment. The model card declares MIT. Binary-kernel source availability and the exact distribution/Flathub requirements still need separate packaging review; free use is not proof of a source-buildable package.

Reproduce after downloading and verifying the artifacts above:

```bash
# Runtime extracted into /tmp/phimthai-npu-proof/runtime
# Model files in /tmp/phimthai-npu-proof/models/Whisper-V3-Turbo-NPU2
env FLM_MODEL_PATH=/tmp/phimthai-npu-proof \
  XDG_CONFIG_HOME=/tmp/phimthai-npu-proof/config \
  /tmp/phimthai-npu-proof/runtime/flm validate --json

env FLM_MODEL_PATH=/tmp/phimthai-npu-proof \
  XDG_CONFIG_HOME=/tmp/phimthai-npu-proof/config \
  /tmp/phimthai-npu-proof/runtime/flm serve --asr 1 \
  --host 127.0.0.1 --port 52629 --cors 0

curl --fail -F model=whisper-v3 -F file=@/absolute/path/to/audio.wav \
  http://127.0.0.1:52629/v1/audio/transcriptions
```

`FLM_MODEL_PATH` is the parent of `models/` with this release's supplied model-list configuration. The JSON response has `model` and `text`. Use a free loopback port in an application and manage only the worker it owns. The portable build emitted a libcurl version-information warning but served all four requests successfully.

`flm validate --json` returned `ready: true`, firmware `1.1.2.64`, kernel `7.1.13`, and unlimited memlock. The serving process held `/dev/accel/accel0` open and mapped `libwhisper_npu.so` and `libxrt_driver_xdna.so.2.25.00`. Server logs recorded NPU locking during each request. This is device-use evidence; it does not measure the fraction of preprocessing or other work done on CPU.

Four FLEURS samples, dataset revision `70bb2e84b976b7e960aa89f1c648e09c59f894dd`, returned HTTP 200. Timings are sequential request wall time with the server already started, not paired CPU speedup measurements:

| Sample WAV | Audio seconds | Request seconds | Observed output quality |
| --- | --- | --- | --- |
| `10026868752543983818.wav` | 7.20 | 2.739 | Thai truncated: `สิ่งนี้เรียกว่าค่า pH ของสารเคมีคุณสามาร` |
| `10021525843523202225.wav` | 8.82 | 3.437 | Thai truncated and name/word errors |
| `1003119935936341070.wav` | 10.56 | 2.403 | Complete English sentence; reference `year` became `years` |
| `10052240106321793346.wav` | 8.76 | 2.449 | Complete English sentence; reference `word Sie` became `words say` |

Raw outputs and device evidence were saved to `/tmp/phimthai-npu-proof/smoke-results.json` and `device-evidence.json`. These temporary files are not shipped release artifacts.

After the chunk trials below, the restarted serving process reported `VmHWM: 521248 kB` (about 509 MiB peak resident memory) and `VmRSS: 283076 kB` through `/proc/<owned-pid>/status`. Accelerator allocations may not all be represented in process RSS; this is not a complete NPU memory measurement.

A follow-up split each Thai input using Qwen's `split_audio_into_chunks(wav, sr, max_chunk_sec=3.0, search_expand_sec=0.5)` and sent non-overlapping chunks sequentially. Normalization for the CER comparison was NFC, casefold, and removal of Unicode punctuation/whitespace:

| Thai sample | Whole-input CER | Chunked CER | Whole/chunked seconds |
| --- | --- | --- | --- |
| `10026868752543983818.wav` | 37/75 = 49.33% | 20/75 = 26.67% | 2.739 / 8.074 |
| `10021525843523202225.wav` | 64/127 = 50.39% | 70/127 = 55.12% | 3.437 / 9.723 |

The chunked output still omitted Thai and introduced Chinese or English hallucinations. The helper padded the second sample's final 0.10175-second tail to 0.5 seconds, adding 6,372 silent samples; it did not duplicate spoken samples. Thus 3-second chunking is **not an accepted fix**. Evidence is in `/tmp/phimthai-npu-proof/chunked-smoke-results.json`. FLM's source forces periodic timestamp sampling, but this test did not establish the cause of truncation.

Read-only source inspection found no supported request argument that corrects the truncation in FLM 1.0.5. The [ASR handler](https://github.com/ROCm/FastFlowLM/blob/v1.0.5/src/server/rest_handler.cpp#L1301) reads `model`, `file` and `stream`, then always calls `generate(e_transcribe, true, false, ...)`; it does not consume `language`, `response_format` or `max_tokens`. Unknown fields therefore must not be advertised as implemented controls.

The [decoder loop](https://github.com/ROCm/FastFlowLM/blob/v1.0.5/src/common/whisper/modeling_whisper.cpp#L185) allows 445 decoding steps, forces periodic timestamp sampling after a 16-step watchdog, and stops on EOS token 50257. This limit is not calculated from audio duration. The same source [selects a language token](https://github.com/ROCm/FastFlowLM/blob/v1.0.5/src/common/whisper/modeling_whisper.cpp#L148), but does not feed it to `decode_audio` before the transcribe token. The initial stock and 3-second chunk tests made no upstream source or binary-kernel changes.

A subsequent isolated hypothesis build added only `decode_audio(last_idx)` after language selection (plus its comment). Source commit `089e56d29416990e168abed43aff88fc0ad664f3` compiled successfully with GCC 16.2.1 and pinned tokenizer-cpp submodules. It loaded the exact portable release's NPU kernel libraries. The pH sample's Thai CER changed from 49.33% to 34.67%, but the other Thai sample regressed from 50.39% to 92.13%; English WER stayed 1/19 and 2/21. Thus **the prefix-only hypothesis failed as a fix and must not be shipped**. Patch, compiler environment, outputs and device evidence are saved under `/tmp/phimthai-npu-proof/` as `language-prefix.patch`, `build-environment.json`, `patched-prefix-results.json` and `patched-device-evidence.json`. Original portable binaries and kernel libraries remain unchanged.

A second proof build retained the prefix correction and replaced the forced 16-step timestamp branch with normal model sampling. No kernels changed. Whole-input results improved to 4/75 and 35/127 Thai character errors (combined 39/202 = 19.31%), with request times 3.179 and 4.269 seconds. Both Thai samples reached the end of the reference sentence, although transcription errors remained. English outputs and WER stayed unchanged. A separately rebuilt **unmodified** native control, using the same compiler and dependencies, reproduced the original portable outputs exactly on all four clips. This supports the two source changes as the reason for the observed improvement on these samples; it does not establish general accuracy, long-audio stability or a release recommendation.

The native handoff directory is `/tmp/phimthai-npu-proof/handoff`, with the unchanged portable launcher/kernel libraries, rebuilt `flm-real`, license/notice and `proof/` containing source commits, patch, toolchain, model hashes and results. The rebuilt binary SHA256 is `9a7ec4d45eeb94dd23fe8f0290fa376bc1cc3b361a4f53889afa7fd7077ef81c`. Source and all proof artifacts remain separate from the application. All proof servers were stopped after the controlled trials.

**Flatpak ABI blocker:** `readelf` shows the host-built executable needs `log10f@GLIBC_2.43`; installed KDE Platform/SDK 6.11 provide GLIBC 2.42. Its required GLIBCXX 3.4.32 fits the runtime's 3.4.34, but that does not resolve the libc mismatch. It also links host FFmpeg 62/60 and Boost 1.90 libraries. Rebuild the orchestration inside the target SDK and resolve its dependency closure before claiming Flatpak compatibility. See `proof/flatpak-abi-evidence.json`; copying this host binary into the Flatpak is not sufficient.

### SDK rebuild and isolated Flatpak NPU execution

The same two source changes subsequently built successfully inside `org.kde.Sdk//6.11`, using GCC 15.2.0, Rust 1.98.1, SDK FFmpeg 7/readline and Boost 1.90.0. The Rust SDK extension was installed per-user; no system driver or firmware changed. Boost source SHA256 is `49551aff3b22cbc5c5a9ed3dbc92f0e23ea50a0f7325b0d198b705e8ee3fc305` ([publisher metadata](https://archives.boost.io/release/1.90.0/source/boost_1_90_0.tar.bz2.json)). Local XRT headers came from `xrt-base-devel-2.25.0-1.x86_64`; copied-header hashes and source/submodule commits are recorded in the proof directory.

The SDK runtime is `.cache/npu-sdk-proof/runtime`, executable SHA256 `a2e1a750fddb851f66956723af971e91970e6d67b296a4987eefb055d0ffcda8`. Its maximum symbol requirements are GLIBC 2.39, GLIBCXX 3.4.32 and CXXABI 1.3.15; it has no RPATH. Hardware-path `ldd` inside KDE Platform found no missing libraries. The original launcher, XRT multiarch mirror, kernel libraries and xclbins remain intact. The SDK build adds its Boost 1.90 libraries and uses Platform FFmpeg/readline. Optional upstream XRT emulation libraries are not part of the observed ASR dependency path.

With one-invocation `--device=all`, this executable's `flm validate --json` returned `ready: true` inside KDE Platform 6.11, with empty stderr. All four complete FLEURS clips returned HTTP 200 and **byte-identical text to the native two-change proof**:

| Sample | SDK sandbox request seconds | Errors |
| --- | --- | --- |
| Thai pH | 3.183 | 4/75 CER |
| Thai named entity | 4.258 | 35/127 CER |
| English communication | 2.401 | 1/19 WER |
| English nouns | 2.391 | 2/21 WER |

The sandbox process held `/dev/accel/accel0` open and mapped the release's `libwhisper_npu.so` and `libxrt_driver_xdna.so.2.25.00`. `/proc/<owned-pid>/root/.flatpak-info` recorded Platform commit `3adaa41de78d95076617f743099ec3851b5ae4fcdadbaaa8b7df1412c705c56c`. Peak process RSS was 396,880 kB (about 388 MiB); this is not total accelerator memory. The owned test server was stopped after measurements. No persistent Flatpak permission override was added.

`runtime/proof/` contains build scripts/logs, hashes, validation, ABI/dependency output, raw transcriptions and device evidence. `.cache/npu-sdk-proof/BUILD-SDK.md` records reproduction, and `flatpak-module.json` is a minimal local module copying the runtime to `/app/libexec/fastflowlm`. This proves isolated runtime execution in the target sandbox, not application microphone/shortcut/paste behavior or a Flathub-ready package. A public source build must replace the local header input with pinned public sources and review all runtime dependencies and binary-kernel distribution terms.

### 100 sequential ASR jobs

The completed [stress report](stress-npu-100.json) contains 100 successful results, 100 unique delivered IDs, `backend=fastflowlm` / `device=npu` on every result, no reported failures, and one observed worker PID (136154). Each of the four FLEURS inputs was copied to a unique job WAV and submitted 25 times; each source produced exactly one distinct output string across all 25 repetitions. Three source outputs also match the earlier SDK proof after whitespace trimming; the pH clip differs only in Latin capitalization (`pH` here versus `PH` there). All four match after casefolding. This is 100 jobs over **four** inputs, not 100 independent utterances.

The first worker-reported `elapsed` was 6.169 seconds; the median for jobs 2–100 was 3.194 seconds. Per-source medians were 4.362 seconds (Thai named entity), 3.256 (Thai pH), 2.491 (English communication) and 2.501 (English nouns). `elapsed` starts after worker JSON parsing and includes VAD, model checks, backend setup/inference and postprocessing; it excludes Python worker startup, Qt dispatch, recording and paste. Backend `processing_time` includes server startup when needed and the HTTP request, so it is not pure NPU kernel time. These timings do not establish the end-to-end 30% target.

The runner reported its temporary directory removed after `jobs.cancel()` and cleanup. The recorded worker PID was absent when independently audited. The report does not contain final pending-queue state, FLM child PIDs or continuous process/memory measurements. Its `device=npu` field comes from a successful FastFlowLM backend response; per-job hardware tracing is absent, while the separate SDK test above records actual device access.

[`scripts/session-stress.py`](../scripts/session-stress.py) submits the next file only after the prior result. It tests sequential worker reuse and delivered-result association, **not concurrent queue pressure, live microphone capture, shortcuts, clipboard/paste delivery, cancellation during inference or crash/fallback recovery**. Exact source/report hashes, first/warm statistics and audit limits are in [stress-npu-analysis.json](evidence/stress-npu-analysis.json). The stress JSON alone does not identify its OS/sandbox or binary/model revision; do not use it to promote untested platform rows.

Mark stock FLM 1.0.5 **ASR execution verified; experimental; Thai truncation**. Mark the two-change native/SDK proof **experimental; four-sample completion improvement**. Keep both out of automatic recommendations until accuracy and stability regressions pass. Qwen3-ASR on AMD NPU and the complete microphone-to-editor/paste flow remain unverified by these ASR-only tests.

## Mixed Thai–English evaluation inputs

A separate four-clip challenge subset is available from the official [Typhoon TVSpeech dataset](https://huggingface.co/datasets/typhoon-ai/TVSpeech), pinned revision `b5cca17eb2933e96badabb96531545ed1f1bc318`. The publisher describes real public-video speech with manual transcriptions by native Thai speakers and a CC-BY license (version unspecified). Selected rows 90, 213, 305 and 405 contain English phrases/terms within Thai references, including “rule based / deal based”, “low tech / high tech”, “climate change” and podcast-platform names. Source-video titles and ThaiPublica attribution were resolved through YouTube oEmbed.

The four complete dataset WAVs total 3,078,320 bytes and 96.192 seconds, mono 16 kHz PCM16. They were fetched through Hugging Face viewer assets whose URL paths matched the pinned revision; the 431,630,957-byte Parquet file was not downloaded. No TTS, concatenation, cropping, resampling or reference rewriting was performed. This is publisher-described recorded human speech, not an independent certification that every utterance is spontaneous conversation. Selection is deliberate and small, so it cannot certify representative mixed-language accuracy.

The [subset manifest](evidence/tvspeech-mixed-subset.json) records exact manual references, per-WAV SHA256, unchanged segment IDs, original video attribution and the immutable full-Parquet URL/hash. Local WAVs, attribution and `fetch.py` are under `.cache/benchmark-mixed`. The fetcher obtains fresh signed URLs, rejects a different dataset revision/reference, and verifies size/hash. The [viewer API](https://huggingface.co/docs/dataset-viewer/rows) has no documented revision parameter; if its cache moves to a newer commit, the script fails rather than silently using different inputs. The pinned Parquet remains the explicit recovery source. No model accuracy result is asserted merely because these inputs are available.

Other surveyed candidates did not close this gate: `liva-ai/code-switching-asr` declares CC-BY-4.0 but its published language list lacks Thai; `gijs/sea_speech` appeared in search but its direct metadata fetch returned HTTP 401, so its audio/transcript/license could not be verified. Existing FLEURS pH and proper-name clips remain useful read-speech fixtures, not a dedicated conversational code-switch benchmark.

## AMD GPU: Vulkan runtime and eight-clip ASR proof

On 2026-09-12, a model-independent Vulkan probe built in KDE SDK 6.11 ran in KDE Platform 6.11 with invocation-only `--device=dri`. It enumerated **AMD Radeon 840M Graphics (RADV KRACKAN1)** as an integrated GPU, vendor `0x1002`, device `0x1114`, Mesa `26.1.6 (git-ffa422e53d)`, Vulkan API `1.4.354`. The raw Vulkan enumeration also listed duplicate ICD entries and CPU-only llvmpipe. This establishes sandbox hardware visibility, not successful ASR.

The isolated build candidate is [whisper.cpp v1.9.4](https://github.com/ggml-org/whisper.cpp/releases/tag/v1.9.4), commit `927cfce34f31707e17f2bff35c349632fb9e2c3a`, using its official Vulkan backend. Source archive SHA256: `41b664fee09e79176ac277b5237debec34f8d74af3c7d71f333f1ec67989ecde`. The SDK supplies Vulkan headers/loader and glslc; [SPIRV-Headers](https://github.com/KhronosGroup/SPIRV-Headers/tree/2a611a970fdbc41ac2e3e328802aed9985352dca) at immutable SDK 1.4.321.0 revision `2a611a970fdbc41ac2e3e328802aed9985352dca` supplies the missing build-only headers. Both project licenses are retained. No system driver or application code was changed.

The pinned multilingual model is [ggerganov/whisper.cpp](https://huggingface.co/ggerganov/whisper.cpp/tree/5359861c739e955e79d9a303bcbc70fb988958b1), revision `5359861c739e955e79d9a303bcbc70fb988958b1`, file `ggml-large-v3-turbo-q5_0.bin`, 574,041,195 bytes, SHA256 `394221709cd5ad1f40c46e6031ca61bce88931e6e088c188294c6d5a55ffa7e2`. Download and checksum verification passed; its model card declares MIT. An isolated eight-clip ASR proof now passed on the observed Radeon 840M, with the bounded quality results below.

The unmodified source built successfully in KDE SDK 6.11. The resulting CLI/server pass `--help` inside KDE Platform 6.11 from `/tmp`; all eight ELF objects resolve dependencies, with no RPATH/RUNPATH and maximum symbol versions GLIBC 2.38, GLIBCXX 3.4.32 and CXXABI 1.3.13. The linked ggml device probe reports one `Vulkan0` integrated GPU with the Radeon 840M description and a separate CPU entry. Its default selection removes duplicate raw entries and excludes llvmpipe. A process-local empty `GGML_VK_VISIBLE_DEVICES` control reports CPU only. The enumeration phase did not run a model; the subsequent ASR phase is recorded separately below.

[GPU ASR evidence](evidence/vulkan-asr.json): all four FLEURS and four full TVSpeech clips completed in KDE Platform 6.11 with `--device=dri --unshare=network`, two CPU threads, automatic language detection, and no Whisper translation. FFmpeg prepared full mono 16 kHz PCM16 WAVs without trimming/chunking. Logs record a 573.40 MB `Vulkan0` model buffer and successful GPU initialization; the owned server opened `/dev/dri/renderD128`, and deduplicated AMD DRM compute counters increased during every request, including a same-clip warm repeat. No GPU initialization failure or memory guard trigger occurred; the server stopped after the run.

Using the exact `scripts/benchmark.py` normalization, FLEURS Thai CER was **35/202 = 17.33%**, English WER **4/40 = 10%**, and TVSpeech mixed CER **282/1108 = 25.45%**. The dense low/high-tech clip omitted substantial reference text. These are small selected samples and do not establish parity with Qwen or broad conversational accuracy. The independently measured Qwen Thai baseline was better; this GPU backend remains an explicit experimental choice.

Fresh-server startup took 0.413 s; first request on the 8.82-second Thai clip took 5.192 s, and a same-clip warm repeat took 4.654 s with identical output. Page caches were not flushed and concurrent source compilation was active. Server peak RSS was 209,648 KiB (204.7 MiB), while driver resident allocation peaked separately at 828,716 KiB VRAM and 42,360 KiB GTT after deduplicating FDs by device/client ID. GPU memory is not included in the RSS figure; these counters are not a unique physical-memory sum on an integrated GPU. System MemAvailable remained at least 5,618,108 KiB. No idle-machine speed gain, energy result, microphone/paste test or complete-app acceptance follows from this proof.

Build inputs/logs, physical-device probe and source module recipe are under `.cache/vulkan-proof`. The generic x86_64 CPU helper disables native, SSE4.2, AVX, AVX2, BMI2, FMA and F16C specializations; this is not an old-CPU test. Shader compilation uses a serial glslc wrapper inside a two-job build to limit memory. Generated shaders are linked into the Vulkan backend, with runtime Vulkan libraries supplied by the Flatpak runtime rather than host library copies.

The first generic scalar CPU fallback is **not accepted for practical use**: a separate six-thread CPU-only CLI test on the 7.2-second FLEURS pH clip hit its 180-second limit without output. It accumulated 1,064.1 CPU-seconds, showing active work rather than an idle wait; the owned process was terminated and reaped. [Scalar failure evidence](evidence/vulkan-cpu-scalar.json) records CLI decoding defaults (five beams/best-of-five), so this is not a paired comparison with the server. The replacement dynamic CPU runtime now passes an isolated CPU/GPU smoke test below. The original scalar failure remains recorded; differing CLI/server decoding defaults prevent a paired percentage improvement claim.


The replacement SDK-built runtime separates a generic x64 CPU module and an AVX2/Haswell module. Its sole upstream source change is the parent-authored OSXSAVE/XGETBV scorer guard: check CPU AVX and OSXSAVE before XGETBV, then require XMM/YMM state bits `0x6`. Both scoring functions compile without AVX flags and with `-fno-lto`. On this host the scores are x64=1 and Haswell=64; logs and process maps confirm selection of `libggml-cpu-haswell.so`. A separate model-free probe with only the x64 module also passes on this same host. AVX512/AMX are disabled; neither the guard nor this probe certifies older CPU/OS/VM combinations. The [Intel optimization manual](https://cdrdv2-public.intel.com/821612/248966-Optimization-Reference-Manual-V1-050.pdf) describes the required OS state check in addition to CPUID.

[CPU dispatch evidence](evidence/vulkan-cpu-dispatch.json): in KDE Platform 6.11, the same full 7.2-second FLEURS pH clip passed twice with CPU-only `--nodevice=dri --no-gpu` and twice with Radeon 840M `--device=dri`, each with two threads and an unshared network namespace. First/warm request times were CPU **56.091/57.718 s**, GPU **4.839/4.263 s**; startup was 0.412/0.410 s respectively. All four outputs match with CER **4/75**. CPU has no DRM file descriptors; GPU logs, renderD128 access and increasing DRM compute counters establish actual Vulkan execution. Both owned servers were stopped and reaped. CPU peak RSS was 776,892 KiB; GPU RSS was 127,428 KiB plus separately recorded driver allocation. These are concurrent-build measurements with page caches retained.

All nine replacement ELF dependencies resolve inside Platform 6.11 without RPATH; maximum required symbol versions are GLIBC 2.38, GLIBCXX 3.4.32 and CXXABI 1.3.13. The runtime and two-module source recipe are under `.cache/vulkan-cpu-proof`; backend modules live beside executables in `bin`, core libraries in `lib`, and wrappers change cwd to their own `bin`. Model/audio/output arguments must be absolute. Of 1,959 pinned archive files, only the scorer source differs. This replacement has **one-clip smoke coverage**; the earlier eight-clip quality proof used the original runtime. Practical latency on older CPUs, broad quality, full-app fallback and release acceptance remain separate gates.


[Installed Flatpak worker proof](evidence/flatpak-vulkan-worker.json), app commit `efb38fd8d00b460e55028473efbec18ed8839f738f9585d0ca530c7c2afecc40`: the packaged `/app/lib/python3.13/site-packages/phimthai/worker.py` now completes one full 7.2-second FLEURS Thai job with six CPU threads on Vulkan and one GPU-requested job with DRI removed. The latter emits the explicit GPU-unavailable warning and uses the **same Whisper model on CPU**. Worker elapsed time was **4.387 s GPU / 23.300 s CPU**; backend request time was 3.831/22.750 s, excluding model startup. Both outputs match, with CER **4/75**. Each worker emits exactly one ready event and one result with its submitted ID, then exits cleanly after stdin EOF and reaps its single server.

The installed runtime binary matches the dispatch proof. GPU process maps, successful Vulkan0 allocation, renderD128 access and increasing AMD DRM compute counters establish physical execution. CPU process maps select Haswell, with no DRI nodes or DRM access. Both network namespaces expose only loopback and no external route. Peak combined worker/server RSS was 143,472 KiB on GPU and 809,232 KiB on CPU; GPU allocations are recorded separately. Page caches were retained and source builds were active. This passes the installed **worker and GPU-unavailable fallback** gates on this host; it does not add GUI, microphone, paste, cancellation, idle-worker, other-host or broad-accuracy coverage. The proof retains an initial harness mistake that inspected host-mounted sysfs for network interfaces; final cases use the namespace interface API.

## Intel NPU: documented integration, local test pending

[OpenVINO GenAI NPU documentation](https://docs.openvino.ai/2026/openvino-workflow-generative/inference-with-genai/inference-with-genai-on-npu.html) documents Whisper NPU support and FP16/INT8 exports. An integration candidate is a multilingual Whisper model, a compatible OpenVINO/GenAI pair and `openvino_genai.WhisperPipeline(model_dir, "NPU")`. Avoid English-only `.en` models for Thai support.

Ready-made multilingual model candidates, with immutable revisions:

- [OpenVINO/whisper-tiny-int8-ov](https://huggingface.co/OpenVINO/whisper-tiny-int8-ov/tree/a850762d97243dee30f46ca309720541af619ab0), revision `a850762d97243dee30f46ca309720541af619ab0`
- [OpenVINO/whisper-base-int8-ov](https://huggingface.co/OpenVINO/whisper-base-int8-ov/tree/0606293f0511136ada21755a265492f623a934b8), revision `0606293f0511136ada21755a265492f623a934b8`

Both converted model cards declare Apache-2.0 and list Thai and English. Preserve their notices and review upstream notices when packaging. Download the snapshot's `*.json`, `*.xml`, `*.bin` and tokenizer text files, including encoder, decoder, tokenizer and detokenizer artifacts. No remote Python model code is needed for the GenAI pipeline.

On 2026-09-12, PyPI metadata reported `openvino==2026.3.1`, `openvino-genai==2026.3.1.0`, and `openvino-tokenizers==2026.3.1.0`. OpenVINO and GenAI publish CPython 3.13 Linux x86_64 wheels with `manylinux_2_28`; tokenizers publishes a `py3-none-manylinux_2_28_x86_64` wheel. These packages declare Python >=3.10. This establishes artifact availability, not local Intel NPU validation. Sources: [OpenVINO](https://pypi.org/project/openvino/2026.3.1/), [GenAI](https://pypi.org/project/openvino-genai/2026.3.1.0/), [tokenizers](https://pypi.org/project/openvino-tokenizers/2026.3.1.0/).

Minimal evaluation recipe, not run on an Intel NPU in this session:

```bash
python3.13 -m venv /tmp/phimthai-openvino-proof
/tmp/phimthai-openvino-proof/bin/pip install \
  openvino==2026.3.1 openvino-genai==2026.3.1.0 \
  openvino-tokenizers==2026.3.1.0 huggingface_hub soundfile
```

```python
from huggingface_hub import snapshot_download
import openvino
import openvino_genai
import soundfile

path = snapshot_download(
    "OpenVINO/whisper-tiny-int8-ov",
    revision="a850762d97243dee30f46ca309720541af619ab0",
    allow_patterns=["*.json", "*.xml", "*.bin", "*.txt"],
)
device = "NPU"  # Set CPU explicitly for a separate CPU smoke test.
assert device in openvino.Core().available_devices
audio, rate = soundfile.read("known-mono-16khz.wav", dtype="float32")
assert rate == 16000 and audio.ndim == 1
pipe = openvino_genai.WhisperPipeline(path, device)
result = pipe.generate(audio.tolist())
print(result.texts)
```

Enumerate `openvino.Core().available_devices`, then load the exact exported model and transcribe a known mono 16 kHz recording. Enumeration alone cannot pass the ASR gate. Pin runtime versions and model revision when preparing release artifacts. No Intel NPU is available on this development host; Intel driver, model execution, accuracy, latency and Flatpak access remain pending.

## Selection and fallback acceptance

Automatic selection must use only validated model/backend/device combinations. Report the actual execution device, including any CPU work. A failed accelerator job may retry on CPU within the same session before output delivery; cancellation must suppress both retries and stale results. Neither a 30% speed improvement nor improved energy use has been established by this inventory.
