# PCB Inspector

A high-performance, desktop-based 2D Printed Circuit Board (PCB) inspection application built with **PySide6**, **OpenCV**, and hardware-accelerated (CUDA/GPU) image processing. The application supports full Master Template training, dual pass/fail thresholding, flexible hardware triggering over Ethernet, optional QR/Barcode/OCR-based serial number capture, and inspection logging — designed so any operator, regardless of technical background, can train, run, and maintain PCB inspection stations.

## Table of Contents

* Application Architecture
* Communication & Hardware Sync
* Core Features
* Configuration
* Installation
* Running the Application
* Typical Workflow
* Troubleshooting Notes

## Application Architecture

The application follows strict Object-Oriented Programming (OOP) patterns, with a clear separation between UI, business logic, and hardware I/O. This keeps the codebase modular, testable, and easy to extend.

### Project Structure

```
PCB_Inspector/
├── main.py                        
├── config.py                      
├── requirements.txt
├── assets/
│   ├── icon.png                   
│   └── splash.png                 
├── core/
│   ├── models.py                  # ComponentAnnotation, CodeRegionAnnotation, MasterTemplate
│   ├── app_settings.py            # Shared mutable runtime settings (paths, OCR config)
│   ├── template_manager.py        # Master Template JSON persistence
│   ├── file_naming.py             # CodeScanner (QR/Barcode/OCR) + OutputFileNamer
│   ├── inspection_logger.py       # CSV inspection event logger (start/stop)
│   └── image_utils.py             # Frame normalization (4-channel, mono, 16-bit, Bayer)
├── training/
│   ├── golden_image_builder.py    # Multi-image ingestion, alignment, denoising -> Golden Image
│   └── annotation_canvas.py       # Interactive draw/edit canvas (components + code regions)
├── inspection/
│   ├── inspection_engine.py       # Grayscale core engine, CUDA-aware, threshold + overlay logic
│   └── inspection_worker.py       # QRunnable wrapper for QThreadPool (GIL-free execution)
├── networking/
│   ├── outbound_trigger.py        # Mode 1: software-dominant outbound trigger controller
│   └── inbound_listener.py        # Mode 2: hardware-dominant inbound trigger listener (QThread)
├── camera/
│   └── camera_interface.py        # Abstract CameraInterface + OpenCVCamera implementation
└── ui/
    ├── main_window.py             # Tab orchestration, signal wiring, top-level state
    ├── training_widget.py         # Tab 1: Training / Master Registration
    ├── inspection_widget.py       # Tab 2: Live Inspection (results, logging controls)
    ├── live_capture_widget.py     # Tab 3: Live Capture (preview, manual/auto capture)
    ├── output_paths_widget.py     # Tab 4: Output Image Path (folders, golden image, OCR config)
    ├── hardware_panel.py          # Tab 5: Hardware Sync (Mode 1/2, batch testing, instructions)
    └── splash_screen.py           
```

### Layered Design

* **`core/`** — Pure data models and shared services with no UI dependencies (`ComponentAnnotation`, `CodeRegionAnnotation`, `MasterTemplate`, file naming, logging, image normalization). These are reused by both the Training and Inspection layers.
* **`training/`** — Everything needed to build a Golden Image baseline and annotate it interactively.
* **`inspection/`** — The comparison engine and its threaded execution wrapper. Fully decoupled from the UI; it accepts a `MasterTemplate` and a frame, and returns a structured `InspectionResult`.
* **`networking/` & `camera/`** — Hardware I/O abstractions. `CameraInterface` is an abstract base class so real vendor SDKs (Basler/FLIR/GigE Vision) can be swapped in without touching any other layer.
* **`ui/`** — PySide6 widgets, one per tab, each communicating with `MainWindow` exclusively through **Qt signals/slots** — no direct cross-widget coupling.

### Data Model

* **`ComponentAnnotation`** — a single inspectable region: name, position/size, shape (rectangle/circle), line thickness, label text size, and its own similarity acceptance threshold.
* **`CodeRegionAnnotation`** — a marked area used only to read a QR code, Barcode, or OCR serial number for output file naming. Never affects pass/fail. Each region has an `enabled` flag so it can be marked but optionally excluded from naming.
* **`MasterTemplate`** — the saved unit of training: Golden Image path, module-level similarity threshold, and the full lists of `ComponentAnnotation` and `CodeRegionAnnotation`. Persisted as JSON via `MasterTemplateManager`.

## Communication & Hardware Sync

The **Hardware Sync** tab supports two independent Ethernet-based trigger modes (TCP or UDP), plus offline batch testing and built-in setup instructions.

### Mode 1 — Outbound Trigger (Software Dominant)

* The application manages a configurable capture interval (in milliseconds).
* On every interval tick, `OutboundTriggerController` sends a `TRIGGER` packet to a configured Host/IP and Port over TCP or UDP, then fires a camera capture and runs it through the inspection pipeline.
* A **"Send Test Trigger Now"** button fires a single packet on demand, so operators can confirm PLC/camera connectivity before starting continuous triggering.
* A live status label reports Running/Stopped and the timestamp of the last trigger sent.

### Mode 2 — Inbound Trigger (Hardware Dominant)

* `InboundListenerThread` runs as a dedicated `QThread`, blocking on a TCP or UDP socket bound to a configurable host/port — this keeps the GUI fully responsive while waiting indefinitely for hardware signals.
* Any inbound signal from a PLC or physical sensor immediately triggers a camera capture and starts the inspection pipeline.
* A **"Send Simulated Signal (Self-Test)"** button lets operators simulate a PLC signal locally (loopback) to validate the listen → capture → inspect pipeline before wiring real hardware.
* A live status label reports Listening/Not Listening and the timestamp of the last signal received.

### Batch Testing Mode (Offline)

* Upload a single image or an entire folder of PCB images to validate Master Template logic and thresholds without any live camera or network connection.

### Built-In Setup Instructions

* A **"How to Sync Hardware (Instructions)"** button opens an in-app dialog explaining exact configuration steps for both modes, TCP-vs-UDP behavior, firewall/port considerations, and troubleshooting tips — so new users don't need external documentation to get connected.

## Core Features

### 1. Training Module & Master Registration

* Ingests reference images either one at a time or in a batch; there is no hard minimum — if fewer than 5 images are supplied, the Golden Image is still built, with a non-blocking notice recommending 5+ for best accuracy.
* `GoldenImageBuilder` aligns reference frames (ECC-based) and applies `fastNlMeansDenoisingColored` to synthesize a noise-reduced Golden Image baseline.
* Users can also **upload an existing Golden Image** directly (from the Output Image Path tab) instead of building a new one from reference photos.
* Interactive **Annotation Canvas** supports drawing both **rectangles and circles**, with adjustable line thickness and label text size set before drawing.
* Every drawn Component prompts for a unique name and its own acceptance threshold (%).
* **Edit Mode**: switching Mode to "Edit" reveals drag-to-resize corner handles on any shape; clicking a shape (or its entry in the component/code-region list) opens a dedicated editor panel (only one at a time, kept hidden otherwise to avoid UI clutter) to rename, reposition, resize, restyle, or delete it.
* **Code Regions** (optional): a separate annotation type (shown in orange) marking areas to be read as QR, Barcode, OCR, or Auto-detect — used purely for output file naming and never compared for pass/fail. Any number of regions can be marked; each has its own "use for file naming" toggle so operators can mark candidates without committing to naming behavior immediately.

### 2. Intelligent File Naming & Output Logic

* Two configurable output directories — **Pass Folder** and **Fail Folder** — set from the Output Image Path tab.
* Before saving, the app scans any **enabled** Code Regions for a QR code, Barcode, or OCR text.
* **Case A (Code found):** `[Code]_[YYYYMMDD_HHMMSS_mmm]_[Pass-or-Fail].jpg`
* **Case B (No code, or no enabled region, or nothing decoded):** `[YYYYMMDD_HHMMSS_mmm]_[Pass-or-Fail].jpg`
* During live inspection, each Code Region's decoded value and detected type are shown directly on the image overlay (e.g. `QR: SN-00231`, `Barcode: 84920011`, `OCR: LOT-4471`) and in the results list, so operators can immediately verify what was read — not just after the file is saved.

### 3. OCR Engine Flexibility (Tesseract / EasyOCR)

* The Output Image Path tab includes a **Tesseract executable path** field.
* If a valid Tesseract path is configured, OCR uses `pytesseract`.
* If no valid path is set (or Tesseract fails), the app **automatically falls back to EasyOCR** — a pure-Python OCR engine with no external binary dependency — so OCR-based serial number reading works out of the box for any user, with or without Tesseract installed.
* A live status indicator in both the Output Image Path tab and the Code Region editor shows which backend is currently active.

### 4. Execution Modes & Hardware Triggering

* Mode 1 (Outbound) and Mode 2 (Inbound) as described above, each independently configurable over TCP or UDP.
* **Manual Capture**: a dedicated "Capture Now" button on the Live Capture tab grabs a single frame on demand and runs it through inspection.
* **Auto Capture**: a configurable interval (ms) drives a local timer that automatically captures and inspects frames — independent of, and usable alongside, either network trigger mode.
* **Live Preview**: a continuously refreshed camera feed on the Live Capture tab, so operators can frame the PCB correctly before capturing.

`Note:` If you want integrate this applicaiton with PLC or Other Computer, reae [COMMUNICATION_ARCHITECTURE.md](./COMMUNICATION_ARCHITECTURE.md)

### 5. Core Inspection Engine & Performance

* Internally converts every frame to grayscale for fast comparison; the UI defaults to the original color view with a toggle to switch to the Algorithm (Monochrome) view — both views show identical pass/fail overlays and Code Region labels.
* `InspectionEngine` auto-detects CUDA (`cv2.cuda.getCudaEnabledDeviceCount()`) and offloads grayscale conversion to GPU when available, falling back to CPU otherwise.
* Frame normalization (`core/image_utils.py`) transparently handles 4-channel (BGRA/RGBA), single-channel (mono8), 16-bit, and raw Bayer camera outputs before they reach the comparison logic — so any camera/SDK output format is supported.
* Each inspection runs inside a `QRunnable` submitted to `QThreadPool`, using NumPy/OpenCV C-extensions that release the GIL — enabling true multi-core parallel execution without blocking the UI thread.

### 6. Thresholding & Visual Annotation

* **Dual-level thresholds**: an individual similarity percentage per Component, plus a separate Module-level (whole-image) similarity percentage.
* **Visual overlays**: passed components are enclosed in a green box/circle with their name and score; failed components are enclosed in red. Code Regions are always shown in orange with their decoded value.
* An image passes only if the module-level similarity meets its threshold **and** every individual component passes; any single component failure routes the image to the Fail Folder.

### 7. Inspection Logging

* Start/Stop Logging controls on the Live Inspection tab write every inspection event to a timestamped CSV file (`inspection_log_YYYYMMDD_HHMMSS.csv`).
* Each row captures the timestamp, saved filename, module similarity/result, and per-component name/similarity/result.
* The logging output folder is configured on the Output Image Path tab and can be changed at any time while logging is stopped.

### 8. Usability & Branding

* A **splash screen** displays at startup while the application initializes.
* A custom **application icon** is applied at the `QApplication` level, so the main window and all dialogs consistently carry the same branding.
* Edit panels for Components and Code Regions are hidden by default and only appear when a shape is explicitly selected, keeping the training screen uncluttered for non-technical operators.

## Configuration

All default paths and constants live in `config.py`:

| Setting | Purpose |
|---|---|
| `PASS_DIR` / `FAIL_DIR` | Default output folders for passed/failed inspection images |
| `GOLDEN_IMAGE_DIR` | Default folder offered when saving a new Golden Image |
| `LOGGING_DIR` | Default folder for CSV inspection logs |
| `CAMERA_DEVICE_INDEX` | OpenCV camera device index for the development/test camera |
| `TESSERACT_PATH` | Optional path to `tesseract.exe`; blank triggers automatic EasyOCR fallback |
| `ICON_PATH` / `SPLASH_PATH` | Branding assets shown at startup |
| `LIVE_PREVIEW_INTERVAL_MS` | Refresh rate for the Live Capture preview feed |

All of the above (except splash/icon) can also be changed at runtime from the **Output Image Path** tab without editing code, and are held in a shared `AppSettings` object referenced by every tab that needs them.

## Installation

```bash
pip install -r requirements.txt
```

`requirements.txt`:
```
PySide6>=6.6.0
opencv-contrib-python>=4.9.0
numpy>=1.26.0
pyzbar>=0.1.9
pytesseract>=0.3.10
easyocr>=1.7.0
```

**Notes:**
* `opencv-contrib-python` from pip is CPU-only. For true CUDA acceleration, build OpenCV from source with `-D WITH_CUDA=ON`. The engine automatically falls back to CPU if CUDA is unavailable.
* `pyzbar` requires the native `zbar` shared library on the OS (e.g. Visual C++ Redistributable 2013 x64 on Windows, or `libzbar0` on Linux).
* `pytesseract` requires the Tesseract OCR binary installed separately and its path configured in the Output Image Path tab — if skipped, EasyOCR is used automatically with no extra setup.
* EasyOCR downloads its recognition model on first use (one-time internet connection required).

## Running the Application

```bash
python main.py
```

This shows the splash screen, then opens the main window with five tabs: Training / Master Registration, Live Inspection, Live Capture, Output Image Path, and Hardware Sync.

## Typical Workflow

1. **Output Image Path tab** — set Pass/Fail folders, Golden Image folder, logging folder, and optionally a Tesseract path (or leave blank for EasyOCR).
2. **Training tab** — build a Golden Image from 5+ reference photos (or upload an existing one), draw Components with names and thresholds, optionally mark Code Regions for QR/Barcode/OCR, then save the Master Template (choosing where the Golden Image itself is stored).
3. **Hardware Sync tab** — configure Mode 1 or Mode 2 for live production, or use Batch Testing to validate the template offline first. Use the built-in instructions and test-signal buttons to confirm connectivity.
4. **Live Capture tab** — use Live Preview to frame the PCB, then Manual Capture or Auto Capture as needed.
5. **Live Inspection tab** — review Color/Algorithm views with pass/fail overlays and decoded Code Region values; start logging to record results to CSV.

## Troubleshooting Notes

* **`pyzbar` DLL errors on Windows** — usually resolved by installing the Visual C++ Redistributable 2013 (x64), or by using a Python 3.11/3.12 virtual environment instead of very new Python releases.
* **OCR not reading text** — verify the Tesseract path in the Output Image Path tab is a valid file; if left blank or invalid, EasyOCR is used automatically (no separate installation needed).
* **4-channel or unusual camera output** — handled transparently by `core/image_utils.py`; if a camera streams raw Bayer data, use `bayer_to_bgr()` explicitly in that camera's `CameraInterface` implementation with the correct Bayer pattern from its datasheet.
* **No response from Mode 1/2** — confirm the target device is reachable on the network, the correct protocol (TCP requires an already-running listener on the other end) is selected, and no firewall is blocking the configured port. Use the built-in test-trigger and simulated-signal buttons to isolate whether the issue is app-side or hardware-side.


