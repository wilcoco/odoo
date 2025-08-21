/** @odoo-module */

import { registry } from "@web/core/registry";
import { CharField } from "@web/views/fields/char/char_field";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { useRef, onWillUnmount, useState } from "@odoo/owl";

export class BarcodeScannerField extends CharField {
    setup() {
        super.setup();
        this.notification = useService("notification");
        this.state = useState({
            scanning: false,
            deviceId: null,
            codeType: "qr", // "qr" or "barcode"
            barcodeReader: "code_128_reader",
        });
        this.webcamRef = useRef("webcam");
        onWillUnmount(() => this.stopScanning());
    }

    // Ensure camera libraries are available; dynamically load if missing
    async ensureCameraLibs() {
        const loaders = [];
        if (typeof Html5Qrcode === "undefined") {
            loaders.push(this._loadScriptOnce("/barcode_scanner_widget/static/src/lib/html5-qrcode.min.js"));
        }
        if (typeof Quagga === "undefined") {
            loaders.push(this._loadScriptOnce("/barcode_scanner_widget/static/src/lib/quagga.min.js"));
        }
        if (loaders.length) {
            try {
                await Promise.all(loaders);
            } catch (e) {
                // If loading fails, keep default check handling below
                console.warn("Failed to dynamically load camera libs", e);
            }
        }
    }

    _loadScriptOnce(src) {
        return new Promise((resolve, reject) => {
            const existing = Array.from(document.getElementsByTagName("script")).find((s) => s.src && s.src.includes(src));
            if (existing) {
                if (existing.dataset.loaded === "ok") return resolve();
                existing.addEventListener("load", () => resolve());
                existing.addEventListener("error", () => reject(new Error("Failed to load " + src)));
                return;
            }
            const script = document.createElement("script");
            script.src = src;
            script.async = true;
            script.onload = () => {
                script.dataset.loaded = "ok";
                resolve();
            };
            script.onerror = () => reject(new Error("Failed to load " + src));
            document.head.appendChild(script);
        });
    }

    async _getDefaultCameraId() {
        const pickBack = (cams) => {
            if (!cams || !cams.length) return null;
            // Prefer labels indicating back/rear/environment
            const byLabel = cams.find((c) => {
                const l = (c.label || "").toLowerCase();
                return l.includes("back") || l.includes("rear") || l.includes("environment");
            });
            if (byLabel) return byLabel.id || byLabel.deviceId || null;
            // Mobile browsers often list the rear camera last
            const last = cams[cams.length - 1];
            return last?.id || last?.deviceId || null;
        };
        try {
            if (typeof Html5Qrcode !== "undefined" && Html5Qrcode.getCameras) {
                const devices = await Html5Qrcode.getCameras();
                const id = pickBack(devices);
                if (id) return id;
            }
        } catch (_) {}
        if (navigator.mediaDevices?.enumerateDevices) {
            const list = await navigator.mediaDevices.enumerateDevices();
            const cams = list.filter((d) => d.kind === "videoinput");
            const id = pickBack(cams);
            if (id) return id;
        }
        return null;
    }

    async _waitForViewportSize(el, attempts = 10, interval = 80) {
        for (let i = 0; i < attempts; i++) {
            const w = el.clientWidth || el.offsetWidth || 0;
            const h = el.clientHeight || el.offsetHeight || 0;
            if (w > 0 && h > 0) return { w, h };
            await new Promise((r) => setTimeout(r, interval));
        }
        return { w: el.clientWidth || 0, h: el.clientHeight || 0 };
    }

    async openScan() {
        try {
            await this.ensureCameraLibs();
            if (typeof Html5Qrcode === "undefined" && typeof Quagga === "undefined") {
                this.notification.add(_t("Camera libraries missing"), { type: "danger" });
                return;
            }
            const deviceId = await this._getDefaultCameraId();
            if (!deviceId) {
                // Fallback to facingMode if deviceId cannot be resolved
                this.state.deviceId = null;
                await this.startScanning();
                return;
            }
            this.state.deviceId = deviceId;
            await this.startScanning();
        } catch (e) {
            this.notification.add(`${_t("Camera Not Found")}: ${e?.message || e}`, { type: "danger" });
        }
    }

    async startScanning() {
        const el = this.webcamRef.el;
        if (!el) return;
        this.state.scanning = true;

        if (this.state.codeType === "qr" && typeof Html5Qrcode !== "undefined") {
            // Wait until viewport has a measurable size to avoid qrbox>width errors
            const { w, h } = await this._waitForViewportSize(el);
            const minSide = Math.min(w || 0, h || 0);
            const config = { fps: 10 };
            if (minSide >= 100) {
                const box = Math.max(50, Math.floor(minSide * 0.8));
                config.qrbox = box;
            }
            this._qr = new Html5Qrcode(el.id);
            this._qr
                .start(
                    this.state.deviceId || { facingMode: "environment" },
                    config,
                    (msg) => {
                        this.props.update?.(msg);
                        this.notification.add(`${_t("QR Code detected")}: ${msg}`, { type: "success" });
                        this.stopScanning();
                    },
                    () => {}
                )
                .catch((err) => {
                    this.notification.add(`${_t("Unable to start scanning")}: ${err}`, { type: "danger" });
                    this.stopScanning();
                });
        } else if (typeof Quagga !== "undefined") {
            const reader = this.state.barcodeReader || "code_128_reader";
            Quagga.init(
                {
                    inputStream: {
                        name: "Live",
                        type: "LiveStream",
                        target: el,
                        constraints: {
                            width: 300,
                            height: 250,
                            ...(this.state.deviceId
                                ? { deviceId: this.state.deviceId }
                                : { facingMode: "environment" }),
                        },
                    },
                    decoder: { readers: [reader] },
                },
                (err) => {
                    if (err) {
                        console.log(err);
                        this.notification.add(`${_t("Unable to start scanning")}: ${err}`, { type: "danger" });
                        this.state.scanning = false;
                        return;
                    }
                    Quagga.start();
                    this._quagga = true;
                }
            );
            this._onDetected = (result) => {
                const code = result?.codeResult?.code;
                if (!code) return;
                try {
                    Quagga.stop();
                } catch {}
                this._quagga = false;
                this.state.scanning = false;
                this.props.update?.(code);
                this.notification.add(`${_t("Barcode detected")}: ${code}`, { type: "success" });
            };
            Quagga.onDetected(this._onDetected);
        } else {
            this.notification.add(_t("No scanner available"), { type: "danger" });
            this.state.scanning = false;
        }
    }

    onInput(ev) {
        const val = ev.target?.value ?? "";
        this.props.update?.(val);
    }

    stopScanning() {
        if (this._qr) {
            this._qr
                .stop()
                .catch(() => {})
                .finally(() => {
                    this._qr = null;
                    this.state.scanning = false;
                });
        }
        if (this._quagga) {
            try {
                Quagga.offDetected(this._onDetected);
            } catch {}
            try {
                Quagga.stop();
            } catch {}
            this._quagga = false;
            this.state.scanning = false;
        }
    }
}

BarcodeScannerField.template = "barcode_scanner_widget.BarcodeScannerField";
BarcodeScannerField.components = { CharField };

// Register as a field descriptor (OWL fields registry expects an object with 'component')
registry.category("fields").add("barcode_scanner", {
    component: BarcodeScannerField,
    displayName: "Barcode Scanner",
    supportedTypes: ["char"],
});

