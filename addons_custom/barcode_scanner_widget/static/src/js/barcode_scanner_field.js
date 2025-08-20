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

    async openScan() {
        try {
            if (typeof Html5Qrcode === "undefined" && typeof Quagga === "undefined") {
                this.notification.add(_t("Camera libraries missing"), { type: "danger" });
                return;
            }
            const devices = await Html5Qrcode.getCameras();
            const deviceId = devices?.[0]?.id || null;
            if (!deviceId) {
                this.notification.add(_t("Camera Not Found"), { type: "danger" });
                return;
            }
            this.state.deviceId = deviceId;
            this.startScanning();
        } catch (e) {
            this.notification.add(`${_t("Camera Not Found")}: ${e?.message || e}`, { type: "danger" });
        }
    }

    startScanning() {
        const el = this.webcamRef.el;
        if (!el) return;
        this.state.scanning = true;

        if (this.state.codeType === "qr" && typeof Html5Qrcode !== "undefined") {
            this._qr = new Html5Qrcode(el.id);
            this._qr
                .start(
                    this.state.deviceId,
                    { fps: 10, qrbox: 170 },
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
                            facingMode: "environment",
                            deviceId: this.state.deviceId,
                        },
                    },
                    decoder: { readers: [{ format: reader, config: {} }] },
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
